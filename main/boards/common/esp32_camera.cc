#include "esp32_camera.h"
#include "mcp_server.h"
#include "display.h"
#include "board.h"
#include "system_info.h"
#include "application.h"

#include <esp_log.h>
#include <esp_heap_caps.h>
#include <img_converters.h>
#include <cstring>
#include "mbedtls/md5.h"
#include <cJSON.h>
#include <thread>
#include <chrono>
#include <esp_timer.h>

#define TAG "Esp32Camera"

#include <atomic>
static std::atomic<bool> s_camera_busy(false);

#ifndef CONFIG_CAMERA_PREVIEW_TIMEOUT_MS
#define CONFIG_CAMERA_PREVIEW_TIMEOUT_MS 2500
#endif
#ifndef CONFIG_CAMERA_PREVIEW_FPS
#define CONFIG_CAMERA_PREVIEW_FPS 10
#endif

Esp32Camera::Esp32Camera(const camera_config_t& config) {
    // camera init
    esp_err_t err = esp_camera_init(&config); // 配置上面定义的参数
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed with error 0x%x", err);
        return;
    }

    sensor_t *s = esp_camera_sensor_get(); // 获取摄像头型号
    if (s->id.PID == GC0308_PID) {
        s->set_hmirror(s, 0);  // 这里控制摄像头镜像 写1镜像 写0不镜像
    }
    // 统一做一些温和的清晰度调优（若对应传感器不支持则跳过）
    if (s) {
        if (s->set_sharpness) s->set_sharpness(s, 2);     // 锐度略增，提升边缘清晰
        if (s->set_contrast)  s->set_contrast(s, 1);      // 对比度小幅提升
        if (s->set_saturation) s->set_saturation(s, 0);   // 饱和度保持中性
        if (s->set_brightness) s->set_brightness(s, 0);   // 亮度中性
        if (s->set_lenc)       s->set_lenc(s, 1);         // 启用镜头校正（如可用）
        // 若后续需要，可按设备情况逐步开放：s->set_denoise(s, 1) 等
    }

    // 初始化预览图片的内存
    memset(&preview_image_, 0, sizeof(preview_image_));
    preview_image_.header.magic = LV_IMAGE_HEADER_MAGIC;
    preview_image_.header.cf = LV_COLOR_FORMAT_RGB565;
    preview_image_.header.flags = LV_IMAGE_FLAGS_ALLOCATED | LV_IMAGE_FLAGS_MODIFIABLE;

    switch (config.frame_size) {
        case FRAMESIZE_SVGA:
            preview_image_.header.w = 800;
            preview_image_.header.h = 600;
            break;
        case FRAMESIZE_VGA:
            preview_image_.header.w = 640;
            preview_image_.header.h = 480;
            break;
        case FRAMESIZE_QVGA:
            preview_image_.header.w = 320;
            preview_image_.header.h = 240;
            break;
        case FRAMESIZE_128X128:
            preview_image_.header.w = 128;
            preview_image_.header.h = 128;
            break;
        case FRAMESIZE_240X240:
            preview_image_.header.w = 240;
            preview_image_.header.h = 240;
            break;
        default:
            ESP_LOGE(TAG, "Unsupported frame size: %d, image preview will not be shown", config.frame_size);
            preview_image_.data_size = 0;
            preview_image_.data = nullptr;
            return;
    }

    preview_image_.header.stride = preview_image_.header.w * 2;
    preview_image_.data_size = preview_image_.header.w * preview_image_.header.h * 2;
    preview_capacity_ = preview_image_.data_size;
    preview_image_.data = (uint8_t*)heap_caps_malloc(preview_capacity_, MALLOC_CAP_SPIRAM);
    if (!preview_image_.data) {
        preview_image_.data = (uint8_t*)heap_caps_malloc(preview_capacity_, MALLOC_CAP_8BIT);
    }
    if (!preview_image_.data) {
        ESP_LOGE(TAG, "Failed to allocate memory for preview image (%u bytes)", (unsigned)preview_capacity_);
        preview_capacity_ = 0;
        preview_image_.data_size = 0;
    }
}

Esp32Camera::~Esp32Camera() {
    if (fb_) {
        esp_camera_fb_return(fb_);
        fb_ = nullptr;
    }
    if (preview_image_.data) {
        heap_caps_free((void*)preview_image_.data);
        preview_image_.data = nullptr;
    }
    esp_camera_deinit();
}

void Esp32Camera::SetExplainUrl(const std::string& url, const std::string& token) {
    explain_url_ = url;
    explain_token_ = token;
}

bool Esp32Camera::Capture() {
    if (encoder_thread_.joinable()) {
        encoder_thread_.join();
    }

    int frames_to_get = 2;
    // Try to get a stable frame
    for (int i = 0; i < frames_to_get; i++) {
        if (fb_ != nullptr) {
            esp_camera_fb_return(fb_);
        }
        fb_ = esp_camera_fb_get();
        if (fb_ == nullptr) {
            ESP_LOGE(TAG, "Camera capture failed");
            return false;
        }
    }

    // 如果预览图片 buffer 为空，则跳过预览
    // 但仍返回 true，因为此时图像可以上传至服务器
    if (preview_image_.data_size == 0) {
        ESP_LOGW(TAG, "Skip preview because of unsupported frame size");
        return true;
    }
    if (preview_image_.data == nullptr) {
        ESP_LOGE(TAG, "Preview image data is not initialized");
        return true;
    }
    // 显示预览图片
    auto display = Board::GetInstance().GetDisplay();
    if (display != nullptr) {
        auto src = (uint16_t*)fb_->buf;
        auto dst = (uint16_t*)preview_image_.data;
        size_t pixel_count = fb_->len / 2;
        for (size_t i = 0; i < pixel_count; i++) {
            // 交换每个16位字内的字节
            dst[i] = __builtin_bswap16(src[i]);
        }
        display->SetPreviewImage(&preview_image_);
    }
    return true;
}

void Esp32Camera::EnsurePreviewBuffer(int w, int h) {
    size_t needed = (size_t)w * h * 2;
    if (needed <= preview_capacity_ && preview_image_.data) {
        preview_image_.header.w = w;
        preview_image_.header.h = h;
        preview_image_.header.stride = w * 2;
        preview_image_.data_size = needed;
        return;
    }
    if (preview_image_.data) {
        heap_caps_free((void*)preview_image_.data);
        preview_image_.data = nullptr;
    }
    preview_image_.data = (uint8_t*)heap_caps_malloc(needed, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!preview_image_.data) preview_image_.data = (uint8_t*)heap_caps_malloc(needed, MALLOC_CAP_8BIT);
    if (!preview_image_.data) {
        ESP_LOGE(TAG, "Reallocate preview buffer failed (%u bytes)", (unsigned)needed);
        preview_capacity_ = 0;
        preview_image_.data_size = 0;
        return;
    }
    preview_capacity_ = needed;
    preview_image_.header.w = w;
    preview_image_.header.h = h;
    preview_image_.header.stride = w * 2;
    preview_image_.data_size = needed;
}

bool Esp32Camera::SetFrameSize(framesize_t fs) {
    sensor_t *s = esp_camera_sensor_get();
    if (!s) return false;
    if (s->status.framesize == fs) return true;
    int r = s->set_framesize(s, fs);
    if (r != 0) {
        ESP_LOGE(TAG, "set_framesize failed: %d", r);
        return false;
    }
    // 根据 framesize 更新预览 buffer 尺寸
    int w=0,h=0;
    switch (fs) {
        case FRAMESIZE_VGA: w=640;h=480; break;
        case FRAMESIZE_QVGA: w=320;h=240; break;
        case FRAMESIZE_QQVGA: w=160;h=120; break;
        #ifdef FRAMESIZE_QQVGA2
        case FRAMESIZE_QQVGA2: w=128;h=160; break;
        #endif
        default: w=320;h=240; break;
    }
    EnsurePreviewBuffer(w,h);
    return true;
}

bool Esp32Camera::PreviewAndWaitConfirm(int timeout_ms, int fps) {
    if (preview_active_) {
         ESP_LOGW(TAG, "Force releasing stuck preview state (entered new Preview)");
         preview_active_ = false;
    }
    
    // 检查全局忙标志（防止多线程并发访问相机）
    // 增加至5秒 (50 * 100ms) 的等待重试机制，满足"立即释放并在5秒内重新打开"的需求
    bool acquired = false;
    for (int i = 0; i < 50; i++) {
        bool expected = false;
        if (s_camera_busy.compare_exchange_strong(expected, true)) {
            acquired = true;
            break;
        }
        if (i == 0) {
             ESP_LOGW(TAG, "Camera is busy, waiting (up to 5s)...");
             auto display = Board::GetInstance().GetDisplay();
             if (display) display->ShowNotification("相机忙，请稍候...", 1000);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
        
        // 尝试主动清理标志（如果看起来是死锁）
        if (i == 20 && preview_active_) {
            preview_active_ = false; // 再次尝试清理
        }
    }
    
    if (!acquired) {
        ESP_LOGE(TAG, "Camera busy timeout (5s), force releasing lock and retrying once");
        s_camera_busy = false; // 强行释放锁（自我修复）
        bool expected = false;
        if (!s_camera_busy.compare_exchange_strong(expected, true)) {
             ESP_LOGE(TAG, "Camera still busy after force release!");
             return false;
        }
        // 成功获取锁
        ESP_LOGI(TAG, "Camera lock acquired after force release");
    }

    sensor_t *s = esp_camera_sensor_get();
    if (!s) {
        s_camera_busy = false;
        return false;
    }
    // 保持原始分辨率（例如 VGA 640x480），避免驱动在动态切换分辨率时出现 FB-SIZE mismatch

    // 保持原始分辨率（例如 640x480），在软件侧下采样到 <=320x240 进行预览，避免驱动 FB-SIZE mismatch

    // 暂停 AFE/语音采集处理，避免预览期间 CPU 与内存争用、导致 AFE(FEED) 环形缓冲溢出
    auto *board = &Board::GetInstance();
    ESP_LOGI(TAG, "Attempt to pause audio AFE for preview");
    {
        // 停止语音处理与唤醒词检测，同时关闭输入
        auto &app = Application::GetInstance();
        auto &as = app.GetAudioService();
        as.EnableWakeWordDetection(false);
        as.EnableVoiceProcessing(false);
        if (board && board->GetAudioCodec()) {
            board->GetAudioCodec()->EnableInput(false);
        }
    }

    // 若上一次拍照后释放了预览缓冲，则此处按需重新分配一个较小的 QVGA 预览缓冲
    if (preview_image_.data_size == 0 || !preview_image_.data) {
        EnsurePreviewBuffer(320, 240);
        if (preview_image_.data_size == 0 || !preview_image_.data) {
            ESP_LOGW(TAG, "No preview buffer (alloc failed), skip preview interactive");
            s_camera_busy = false;
            return true; // 不阻塞，直接按已确认处理
        }
        ESP_LOGI(TAG, "Preview buffer re-allocated: %dx%d", preview_image_.header.w, preview_image_.header.h);
    }

    preview_active_ = true;
    preview_confirmed_ = false;
    preview_canceled_ = false;

    auto display = Board::GetInstance().GetDisplay();
    ESP_LOGI(TAG, "Preview start (manual mode=%s, timeout_ms=%d)", timeout_ms<=0?"yes":"no", timeout_ms);
    if (display) {
        // 瞬时提示 + 持续底部提示
        display->ShowNotification("进入预览", 800);
        display->ShowMessageButton("按A拍照  按B取消", 60000); // 给一个较长的显示时间，结束时手动隐藏
    }

    int interval_ms = 1000 / (fps <=0 ? 8 : fps);
    int elapsed = 0;
    // FPS 统计
    int frame_counter = 0;
    int last_fps_log_ms = 0;
    while (true) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) {
            ESP_LOGE(TAG, "Preview frame get failed");
            preview_canceled_ = true;
            break;
        }
        // 保持摄像头工作在原始分辨率（例如 640x480），在软件侧按需下采样到 <=320x240 进行预览
        int fb_w = fb->width;
        int fb_h = fb->height;
        int factor_x = fb_w / 320; if (factor_x < 1) factor_x = 1;
        int factor_y = fb_h / 240; if (factor_y < 1) factor_y = 1;
        int factor = factor_x < factor_y ? factor_x : factor_y;
        if (factor > 4) factor = 4; // 限制最大下采样因子，避免过小
        int out_w = fb_w / factor;
        int out_h = fb_h / factor;
        if (out_w < 1) {
            out_w = 1;
        }
        if (out_h < 1) {
            out_h = 1;
        }
        EnsurePreviewBuffer(out_w, out_h);

        auto src = (const uint16_t*)fb->buf;
        auto dst = (uint16_t*)preview_image_.data;
        // 行列步进为 factor，实现近邻采样
        for (int y = 0; y < out_h; ++y) {
            int sy = y * factor;
            const uint16_t* row_src = src + (size_t)sy * fb_w;
            uint16_t* row_dst = dst + (size_t)y * out_w;
            for (int x = 0; x < out_w; ++x) {
                int sx = x * factor;
                row_dst[x] = __builtin_bswap16(row_src[sx]);
            }
        }
        preview_image_.header.w = out_w;
        preview_image_.header.h = out_h;
        preview_image_.header.stride = out_w * 2;
        preview_image_.data_size = (size_t)out_w * out_h * 2;
        if (display) display->SetPreviewImage(&preview_image_);
        esp_camera_fb_return(fb);
        frame_counter++;

        if (preview_canceled_) {
            preview_active_ = false;
            if (display) {
                display->HideMessageButton();
                // 隐藏预览叠层，恢复正常界面
                display->SetPreviewImage(nullptr);
            }
            ESP_LOGI(TAG, "Preview canceled by user (elapsed=%dms)", elapsed);
            // 用户取消拍照：此时恢复音频
            {
                auto &app = Application::GetInstance();
                auto &as = app.GetAudioService();
                as.EnableVoiceProcessing(true);
                as.EnableWakeWordDetection(true);
                if (board && board->GetAudioCodec()) {
                    board->GetAudioCodec()->EnableInput(true);
                }
            }
            s_camera_busy = false;
            return false;
        }
        if (preview_confirmed_) {
            break; // 进入最终拍照
        }
            if (timeout_ms > 0 && elapsed >= timeout_ms) {
                ESP_LOGI(TAG, "Preview auto confirm by timeout");
                break; // 正常自动确认
            }
            // 强制最大超时 60s，防止用户未操作导致死锁
            if (timeout_ms <= 0 && elapsed >= 60000) {
                ESP_LOGW(TAG, "Preview force cancel by max timeout (60s)");
                preview_canceled_ = true;
                break;
            }
            if (timeout_ms <= 0) {
                // 不自动确认：仅等待 A/B
            }
        vTaskDelay(pdMS_TO_TICKS(interval_ms));
        elapsed += interval_ms;
        // 每秒输出一次 FPS
        if (elapsed - last_fps_log_ms >= 1000) {
            int fps_now = frame_counter * 1000 / (elapsed - last_fps_log_ms);
            ESP_LOGI(TAG, "Preview FPS=%d frames=%d elapsed=%dms heap_free=%d", fps_now, frame_counter, elapsed, (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
            frame_counter = 0;
            last_fps_log_ms = elapsed;
        }
    }

    preview_active_ = false;
    if (display) {
        display->HideMessageButton();
        // 预览完成/确认，隐藏预览叠层
        display->SetPreviewImage(nullptr);
        // 将图片添加到聊天记录
        display->AddChatImage(&preview_image_);
    }
    // 释放预览缓冲，腾出内部/PSRAM 空间供后续 JPEG 编码与网络发送使用
    if (preview_image_.data) {
        heap_caps_free((void*)preview_image_.data);
        preview_image_.data = nullptr;
        preview_image_.data_size = 0;
        preview_capacity_ = 0;
        ESP_LOGI(TAG, "Preview buffer released after confirm");
    }
    // 保持音频暂停到 Explain() 结束，再集中恢复（避免边上传边采集造成争用）
    ESP_LOGI(TAG, "Preview confirmed by user (elapsed=%dms)", elapsed);

    s_camera_busy = false;
    return true; // 确认
}
bool Esp32Camera::SetHMirror(bool enabled) {
    sensor_t *s = esp_camera_sensor_get();
    if (s == nullptr) {
        ESP_LOGE(TAG, "Failed to get camera sensor");
        return false;
    }
    
    esp_err_t err = s->set_hmirror(s, enabled);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to set horizontal mirror: %d", err);
        return false;
    }
    
    ESP_LOGI(TAG, "Camera horizontal mirror set to: %s", enabled ? "enabled" : "disabled");
    return true;
}

bool Esp32Camera::SetVFlip(bool enabled) {
    sensor_t *s = esp_camera_sensor_get();
    if (s == nullptr) {
        ESP_LOGE(TAG, "Failed to get camera sensor");
        return false;
    }
    
    esp_err_t err = s->set_vflip(s, enabled);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to set vertical flip: %d", err);
        return false;
    }
    
    ESP_LOGI(TAG, "Camera vertical flip set to: %s", enabled ? "enabled" : "disabled");
    return true;
}

std::string Esp32Camera::UploadJpegChunks(const std::vector<JpegChunk>& jpeg_chunks, const std::string& question) {
    // 使用 application/octet-stream 上传原始 JPEG 字节；问题通过 URL 查询参数传递
    // 为确保中文兼容，这里对 question 做 URL 编码
    auto url_encode = [](const std::string &s) -> std::string {
        static const char *hex = "0123456789ABCDEF";
        std::string out; out.reserve(s.size()*3);
        for (unsigned char c : s) {
            bool safe = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c=='-' || c=='_' || c=='.' || c=='~';
            if (safe) { out.push_back((char)c); }
            else { out.push_back('%'); out.push_back(hex[(c>>4)&0xF]); out.push_back(hex[c&0xF]); }
        }
        return out;
    };
    std::string url_with_q = explain_url_;
    if (!question.empty()) {
        url_with_q += (url_with_q.find('?') == std::string::npos ? "?" : "&");
        url_with_q += "question=" + url_encode(question);
    }

    // 计算总长度
    size_t body_len = 0; for (const auto &c : jpeg_chunks) body_len += c.len;
    
    // 准备并打开 HTTP 连接
    auto network = Board::GetInstance().GetNetwork();
    auto http = network->CreateHttp(3);
    http->SetTimeout(120000);
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    if (!Application::GetInstance().GetStudentId().empty()) {
        http->SetHeader("Student-Id", Application::GetInstance().GetStudentId().c_str());
    }
    if (!explain_token_.empty()) {
        http->SetHeader("Authorization", "Bearer " + explain_token_);
    }
    http->SetHeader("Content-Type", "application/octet-stream");
    http->SetHeader("Accept-Charset", "utf-8");
    http->SetHeader("Accept", "application/json, text/plain, */*");
    http->SetHeader("Expect", "");
    
    char cl_buf[32]; snprintf(cl_buf, sizeof(cl_buf), "%u", (unsigned)body_len);
    http->SetHeader("Content-Length", cl_buf);

    if (!http->Open("POST", url_with_q)) {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        return "{\"success\": false, \"message\": \"Network error\"}";
    }

    // 发送数据
    for (const auto &c : jpeg_chunks) {
        if (c.data && c.len) {
            if (http->Write(reinterpret_cast<const char*>(c.data), c.len) < 0) {
                ESP_LOGE(TAG, "Failed to write JPEG data");
                return "{\"success\": false, \"message\": \"Network write error\"}";
            }
        }
    }

    // 获取响应
    int status_code = http->GetStatusCode();
    std::string response;
    char buffer[512];
    int ret;
    while ((ret = http->Read(buffer, sizeof(buffer))) > 0) {
        response.append(buffer, ret);
    }
    http->Close();

    // Handle Async 202 accepted response
    if (status_code == 202) {
        ESP_LOGI(TAG, "Async processing accepted (202), start polling result...");
        cJSON* root = cJSON_Parse(response.c_str());
        if (!root) {
            ESP_LOGE(TAG, "Failed to parse 202 response");
            return "{\"success\": false, \"message\": \"Server 202 error\"}";
        }
        cJSON* url_item = cJSON_GetObjectItem(root, "result_url");
        std::string result_url = "";
        if (cJSON_IsString(url_item) && url_item->valuestring) {
            result_url = url_item->valuestring;
        }
        cJSON_Delete(root);

        if (result_url.empty()) {
            ESP_LOGE(TAG, "No result_url in 202 response");
            return "{\"success\": false, \"message\": \"Async url missing\"}";
        }

        // Poll url for result
        int64_t start_ms = esp_timer_get_time() / 1000;
        int max_wait = 300000; // Default timeout 300s
        int poll_interval = 1000;

        while (true) {
            int64_t now_ms = esp_timer_get_time() / 1000;
            if (now_ms - start_ms > max_wait) {
                ESP_LOGE(TAG, "Polling timeout");
                return "{\"success\": false, \"message\": \"Polling timeout\"}";
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(poll_interval));

            auto& board = Board::GetInstance();
            auto network = board.GetNetwork();
            if (!network) {
                 ESP_LOGE(TAG, "Network not available for polling");
                 return "{\"success\": false, \"message\": \"Network error\"}";
            }
            auto poll_http = network->CreateHttp(3);
            poll_http->SetHeader("Accept", "application/json");
            poll_http->SetHeader("Accept-Charset", "utf-8"); // Ensure charset matches server

            if (!poll_http->Open("GET", result_url)) {
                ESP_LOGW(TAG, "Poll connection failed, retrying...");
                continue;
            }

            int p_status = poll_http->GetStatusCode();
            std::string p_resp;
            char p_buf[512];
            int p_ret;
            while ((p_ret = poll_http->Read(p_buf, sizeof(p_buf))) > 0) {
                p_resp.append(p_buf, p_ret);
            }
            poll_http->Close();

            if (p_status == 200) {
                // Check if pending
                if (p_resp.find("\"status\":\"pending\"") != std::string::npos || 
                    p_resp.find("\"status\": \"pending\"") != std::string::npos) {
                    continue; // Still pending
                }
                // Done
                return p_resp;
            } else if (p_status == 202) {
                continue; // Still processing
            } else if (p_status >= 400) {
                ESP_LOGE(TAG, "Poll error status: %d", p_status);
                // Don't quit immediately on temporary 500s? No, assume failure.
                return "{\"success\": false, \"message\": \"Poll failed: " + std::to_string(p_status) + "\"}";
            }
        }
    }

    if (status_code != 200) {
        ESP_LOGE(TAG, "HTTP error: %d, response: %s", status_code, response.c_str());
        return "{\"success\": false, \"message\": \"Server error: " + std::to_string(status_code) + "\"}";
    }
    return response;
}

bool Esp32Camera::CacheCurrentFrame() {
    bool expected = false;
    if (!s_camera_busy.compare_exchange_strong(expected, true)) {
        ESP_LOGW(TAG, "Camera is busy (CacheCurrentFrame)");
        return false;
    }

    sensor_t *sensor = esp_camera_sensor_get();
    framesize_t original_fs = FRAMESIZE_VGA;
    if (sensor) {
        original_fs = (framesize_t)sensor->status.framesize;
        if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
        
        // 强制使用 VGA
        if (sensor->set_framesize) {
            sensor->set_framesize(sensor, FRAMESIZE_VGA);
            for (int i = 0; i < 2; ++i) {
                camera_fb_t* tmp = esp_camera_fb_get();
                if (tmp) esp_camera_fb_return(tmp);
            }
        }
        fb_ = esp_camera_fb_get();
    } else {
        fb_ = esp_camera_fb_get();
    }

    if (!fb_) {
        if (sensor) sensor->set_framesize(sensor, original_fs);
        s_camera_busy = false;
        return false;
    }

    // 1. Compress raw frame to JPEG immediately to save memory
    // Use moderate quality (80)
    uint8_t* jpg_buf = NULL;
    size_t jpg_len = 0;
    bool converted = frame2jpg(fb_, 80, &jpg_buf, &jpg_len);
    
    // Free raw frame immediately
    esp_camera_fb_return(fb_); fb_ = nullptr;
    if (sensor) sensor->set_framesize(sensor, original_fs);

    if (!converted || !jpg_buf) {
        ESP_LOGE(TAG, "JPEG compression failed");
        s_camera_busy = false;
        return false;
    }
    
    ESP_LOGI(TAG, "Compressed frame: len=%u", (unsigned)jpg_len);

    // 2. Store JPEG in cache list
    camera_fb_t* jpeg_fb = (camera_fb_t*)malloc(sizeof(camera_fb_t));
    if (!jpeg_fb) {
        free(jpg_buf);
        s_camera_busy = false;
        return false;
    }
    // Note: frame2jpg allocates using standard malloc/calloc (usually internal or whatever fits)
    // We keep it as is. In ClearCachedPhotos we need to use free() for this buf instead of heap_caps_free 
    // if it was allocated by frame2jpg? 
    // frame2jpg implementation usually uses calloc.
    // However, my ClearCachedPhotos uses heap_caps_free.
    // It's safer to move it to a known heap type or ensure free compatibility.
    // For ESP32, free() handles all heaps, heap_caps_free as well?
    // Let's migrate to SPIRAM explicitly to be safe and consistent with ClearCachedPhotos usage.
    
    uint8_t* spiram_buf = (uint8_t*)heap_caps_malloc(jpg_len, MALLOC_CAP_SPIRAM);
    if (spiram_buf) {
        memcpy(spiram_buf, jpg_buf, jpg_len);
        free(jpg_buf);
        jpeg_fb->buf = spiram_buf;
    } else {
        // Fallback to original buffer if SPIRAM fail
        jpeg_fb->buf = jpg_buf;
    }
    
    jpeg_fb->len = jpg_len;
    jpeg_fb->width = 0; // Meaningless for JPEG stream container
    jpeg_fb->height = 0;
    jpeg_fb->format = PIXFORMAT_JPEG;

    // Limit cache size
    if (cached_fbs_.size() >= 10) { // Can store more JPEGs now
        ESP_LOGW(TAG, "Cache full (max 10), popping oldest frame");
        camera_fb_t* old = cached_fbs_.front();
        cached_fbs_.erase(cached_fbs_.begin());
        if (old->buf) heap_caps_free(old->buf); // We ensure buf is from heap_caps_malloc or compatible
        free(old);
    }

    cached_fbs_.push_back(jpeg_fb);
    ESP_LOGI(TAG, "Cached JPEG frame %d: len=%u", cached_fbs_.size(), jpeg_fb->len);

    // Restore audio
    auto &app = Application::GetInstance();
    auto &as = app.GetAudioService();
    as.EnableVoiceProcessing(true);
    as.EnableWakeWordDetection(true);
    if (Board::GetInstance().GetAudioCodec()) {
        Board::GetInstance().GetAudioCodec()->EnableInput(true);
    }

    s_camera_busy = false;
    return true;
}

void Esp32Camera::ClearCachedPhotos() {
    for (auto fb : cached_fbs_) {
        if (fb->buf) heap_caps_free(fb->buf);
        free(fb);
    }
    cached_fbs_.clear();
    ESP_LOGI(TAG, "Cleared cached photos");
}

std::string Esp32Camera::ExplainCached(const std::string& question) {
    if (cached_fbs_.empty()) {
        return "{\"success\": false, \"message\": \"No cached photos\"}";
    }

    bool expected = false;
    if (!s_camera_busy.compare_exchange_strong(expected, true)) {
        return "{\"success\": false, \"message\": \"Camera is busy\"}";
    }

    size_t total_len = 0;
    for (auto fb : cached_fbs_) {
        total_len += fb->len;
    }
    
    // Allocate buffer for all JPEGs concatenated
    uint8_t* big_buf = (uint8_t*)heap_caps_malloc(total_len, MALLOC_CAP_SPIRAM);
    if (!big_buf) {
        s_camera_busy = false;
        return "{\"success\": false, \"message\": \"Not enough memory to concat photos\"}";
    }

    size_t offset = 0;
    for (auto fb : cached_fbs_) {
        memcpy(big_buf + offset, fb->buf, fb->len);
        offset += fb->len;
    }

    ESP_LOGI(TAG, "Concatenated %d JPEGs, total len=%u", cached_fbs_.size(), (unsigned)total_len);

    // Prepare chunks for upload
    std::vector<JpegChunk> jpeg_chunks;
    jpeg_chunks.push_back({big_buf, total_len});

    std::string result = UploadJpegChunks(jpeg_chunks, question);
    
    heap_caps_free(big_buf);
    ClearCachedPhotos();
    s_camera_busy = false;
    return result;
}

/**
 * @brief 将摄像头捕获的图像发送到远程服务器进行AI分析和解释
 * 
 * 该函数将当前摄像头缓冲区中的图像编码为JPEG格式，并通过HTTP POST请求
 * 以multipart/form-data的形式发送到指定的解释服务器。服务器将根据提供的
 * 问题对图像进行AI分析并返回结果。
 * 
 * 实现特点：
 * - 使用独立线程编码JPEG，与主线程分离
 * - 采用分块传输编码(chunked transfer encoding)优化内存使用
 * - 通过队列机制实现编码线程和发送线程的数据同步
 * - 支持设备ID、客户端ID和认证令牌的HTTP头部配置
 * 
 * @param question 要向AI提出的关于图像的问题，将作为表单字段发送
 * @return std::string 服务器返回的JSON格式响应字符串
 *         成功时包含AI分析结果，失败时包含错误信息
 *         格式示例：{"success": true, "result": "分析结果"}
 *                  {"success": false, "message": "错误信息"}
 * 
 * @note 调用此函数前必须先调用SetExplainUrl()设置服务器URL
 * @note 函数会等待之前的编码线程完成后再开始新的处理
 * @warning 如果摄像头缓冲区为空或网络连接失败，将返回错误信息
 */
std::string Esp32Camera::Explain(const std::string& question) {
    // 检查全局忙标志
    bool expected = false;
    if (!s_camera_busy.compare_exchange_strong(expected, true)) {
        return "{\"success\": false, \"message\": \"Camera is busy\"}";
    }

    if (explain_url_.empty()) {
        s_camera_busy = false;
        return "{\"success\": false, \"message\": \"Image explain URL or token is not set\"}";
    }

    ESP_LOGI(TAG, "Explain start question_utf8_len=%u fb=%p size=%dx%d len=%u heap_free=%d", (unsigned)question.size(), fb_, fb_?fb_->width:0, fb_?fb_->height:0, fb_?fb_->len:0, (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));

    // 拍照时使用稳定分辨率（优先 VGA；在内存较充足时可尝试 SVGA），拍完后还原
    sensor_t *sensor = esp_camera_sensor_get();
    framesize_t original_fs = FRAMESIZE_VGA;
    bool fs_changed = false;
    if (sensor) {
        original_fs = (framesize_t)sensor->status.framesize;
        // 释放旧帧，避免切换分辨率前持有 FB
        if (fb_) {
            esp_camera_fb_return(fb_);
            fb_ = nullptr;
        }
        auto try_capture = [&](framesize_t fs) -> camera_fb_t* {
            if (!sensor->set_framesize) return nullptr;
            int r = sensor->set_framesize(sensor, fs);
            if (r != 0) return nullptr;
            // 丢弃两帧用于稳定
            for (int i = 0; i < 2; ++i) {
                camera_fb_t* tmp = esp_camera_fb_get();
                if (tmp) esp_camera_fb_return(tmp);
            }
            // 实际取一帧
            return esp_camera_fb_get();
        };
        // 在内部RAM较低时直接选择 VGA，避免 FB-OVF；否则可尝试 SVGA 再回退到 VGA
        size_t free_internal = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
        framesize_t desired_fs = (free_internal > 12000 ? FRAMESIZE_SVGA : FRAMESIZE_VGA);
        camera_fb_t* shot = try_capture(desired_fs);
        if (!shot) {
            desired_fs = FRAMESIZE_VGA;
            shot = try_capture(desired_fs);
        }
        if (shot) {
            fb_ = shot; fs_changed = (original_fs != desired_fs);
            ESP_LOGI(TAG, "Explain capture framesize %s %ux%u", desired_fs==FRAMESIZE_SVGA?"SVGA":"VGA", fb_->width, fb_->height);
        }
    }

    // 同步 JPEG 编码：避免创建线程与队列导致的额外内存分配失败（"Not enough space"）
    // 直接将回调分片累积到 vector；质量降低到 75 以进一步减小大小
    // 动态决定 JPEG 质量：内存越低压缩越激进
    size_t free_before_encode = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    int jpeg_quality = (free_before_encode < 9000 ? 65 : 75);
    std::vector<JpegChunk> jpeg_chunks; jpeg_chunks.reserve(24);
    size_t total_sent = 0; size_t log_next = 8192;
    bool encode_ok = frame2jpg_cb(fb_, jpeg_quality, [](void* arg, size_t, const void* data, size_t len) -> unsigned int {
        auto *vec = reinterpret_cast<std::vector<JpegChunk>*>(arg);
        if (!data || len == 0) return 0;
        uint8_t* buf = (uint8_t*)heap_caps_aligned_alloc(16, len, MALLOC_CAP_SPIRAM);
        if (!buf) buf = (uint8_t*)heap_caps_aligned_alloc(16, len, MALLOC_CAP_8BIT);
        if (!buf) return 0; // 放弃该分片（极端内存不足）
        memcpy(buf, data, len);
        vec->push_back({buf, len});
        return len;
    }, &jpeg_chunks);
    for (auto &c : jpeg_chunks) { total_sent += c.len; if (total_sent >= log_next) { ESP_LOGI(TAG, "Explain JPEG progress sent=%uB", (unsigned)total_sent); log_next += 8192; } }
    ESP_LOGI(TAG, "Explain JPEG encode done total=%uB (sync, quality=%d, free_before=%u)", (unsigned)total_sent, jpeg_quality, (unsigned)free_before_encode);
    if (!encode_ok || jpeg_chunks.empty()) {
        if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
        auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true);
        if (Board::GetInstance().GetAudioCodec()) {
            Board::GetInstance().GetAudioCodec()->EnableInput(true);
        }
        s_camera_busy = false;
        return "{\"success\": false, \"message\": \"JPEG encode failed\"}";
    }

    // 使用 application/octet-stream 上传原始 JPEG 字节；问题通过 URL 查询参数传递
    // 为确保中文兼容，这里对 question 做 URL 编码
    auto url_encode = [](const std::string &s) -> std::string {
        static const char *hex = "0123456789ABCDEF";
        std::string out; out.reserve(s.size()*3);
        for (unsigned char c : s) {
            bool safe = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c=='-' || c=='_' || c=='.' || c=='~';
            if (safe) { out.push_back((char)c); }
            else { out.push_back('%'); out.push_back(hex[(c>>4)&0xF]); out.push_back(hex[c&0xF]); }
        }
        return out;
    };
    std::string url_with_q = explain_url_;
    if (!question.empty()) {
        url_with_q += (url_with_q.find('?') == std::string::npos ? "?" : "&");
        url_with_q += "question=" + url_encode(question);
    }
    // 收集 JPEG 分片至内存，计算 Content-Length
    // 之前 total_sent 已统计

    // 计算总长度
    size_t body_len = 0; for (const auto &c : jpeg_chunks) body_len += c.len;
    // 将分片拼成连续内存，避免网络写入时的分片错序/边界问题（降低条纹伪影风险）
    if (body_len > 0) {
        uint8_t* joined = (uint8_t*)heap_caps_aligned_alloc(16, body_len, MALLOC_CAP_SPIRAM);
        if (!joined) joined = (uint8_t*)heap_caps_aligned_alloc(16, body_len, MALLOC_CAP_8BIT);
        if (joined) {
            size_t off = 0;
            for (auto &c : jpeg_chunks) {
                if (c.data && c.len) { memcpy(joined + off, c.data, c.len); off += c.len; }
                if (c.data) heap_caps_free(c.data);
            }
            jpeg_chunks.clear();
            JpegChunk whole{joined, body_len};
            jpeg_chunks.push_back(whole);
        }
    }

    // 简化：不做 SOI/EOI 扫描与裁剪，直接发送编码输出
    size_t send_total_len = body_len;

    // 准备并打开 HTTP 连接（此时已知 Content-Length）：
    auto network = Board::GetInstance().GetNetwork();
    auto http = network->CreateHttp(3);
    // 缩短总超时时间，避免平台 120s 总超时；服务器侧一般 3-8s 内返回
    // 设定为 180s，防止网络卡死导致长时间无法进行下一次操作
    http->SetTimeout(180000);
    // 配置HTTP头（包含 Content-Length，避免服务器等待未知长度导致不返回响应头）
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    if (!Application::GetInstance().GetStudentId().empty()) {
        http->SetHeader("Student-Id", Application::GetInstance().GetStudentId().c_str());
    }
    if (!explain_token_.empty()) {
        http->SetHeader("Authorization", "Bearer " + explain_token_);
    }
    http->SetHeader("Content-Type", "application/octet-stream");
    http->SetHeader("Accept-Charset", "utf-8");
    http->SetHeader("Accept", "application/json, text/plain, */*");
    // 显式禁用 100-continue 握手，避免某些代理/服务端等待导致的阻塞
    http->SetHeader("Expect", "");
    // 明确长度，发送完整 JPEG 输出（不追加额外 EOI）
    uint32_t content_len = (uint32_t)send_total_len;
    char cl_buf[32]; snprintf(cl_buf, sizeof(cl_buf), "%u", (unsigned)content_len);
    http->SetHeader("Content-Length", cl_buf);
    // 不再设置 JPEG 裁剪诊断头
    // 计算即将发送的 JPEG 有效负载的 MD5，便于与服务器日志比对
    // 为避免重复扫描，这里直接按同样的裁剪区间计算
    {
        uint8_t md5_bin[16] = {0};
        char md5_hex[33] = {0};
        // 使用 mbedtls 增量计算，兼容内存追加 EOI 的情形
    mbedtls_md5_context ctx; mbedtls_md5_init(&ctx);
    mbedtls_md5_starts(&ctx);
        for (auto &c : jpeg_chunks) {
            if (c.data && c.len) mbedtls_md5_update(&ctx, c.data, c.len);
        }
    mbedtls_md5_finish(&ctx, md5_bin);
        mbedtls_md5_free(&ctx);
        static const char *hex = "0123456789abcdef";
        for (int i = 0; i < 16; ++i) { md5_hex[i*2] = hex[(md5_bin[i] >> 4) & 0xF]; md5_hex[i*2+1] = hex[md5_bin[i] & 0xF]; }
        http->SetHeader("X-JPEG-MD5", md5_hex);
        http->SetHeader("X-JPEG-CL", cl_buf);
    }
    // 避免长连接导致某些代理延迟关闭
    http->SetHeader("Connection", "close");

    // 使用异步模式：通过查询参数 async=1 + 头 X-Async: 1 双重指示，确保服务端进入快速应答路径
    http->SetHeader("X-Async", "1");
    // 请求服务端按竖图 600x800 输出：portrait=1 + target=600x800，并保持异步
    // 恢复为原始尺寸上传，仅保留异步参数
    std::string final_url = url_with_q + (url_with_q.find('?')==std::string::npos?"?":"&") + "async=1";
    // 提取基准 origin（scheme://host:port），用于后续将服务端返回的内部 result_url 重写为外部可达地址
    auto extract_origin = [](const std::string& u) -> std::string {
        size_t p = u.find("://"); if (p == std::string::npos) return ""; p += 3;
        size_t s = u.find('/', p); if (s == std::string::npos) return u; return u.substr(0, s);
    };
    auto rewrite_to_base = [](const std::string& abs, const std::string& base) -> std::string {
        if (base.empty()) return abs;
        size_t p = abs.find("://"); if (p == std::string::npos) return abs; p += 3;
        size_t s = abs.find('/', p); if (s == std::string::npos) return abs; // 无路径
        std::string path = abs.substr(s);
        return base + path;
    };
    std::string base_origin = extract_origin(final_url);
    if (!http->Open("POST", final_url)) {
        ESP_LOGE(TAG, "Failed to connect to explain URL");
        // 释放缓存的 JPEG 内存
        for (auto &c : jpeg_chunks) { if (c.data) heap_caps_free(c.data); }
        // 恢复屏幕显示并释放相机帧
        auto display = Board::GetInstance().GetDisplay();
        if (display) display->SetPreviewImage(nullptr);
        if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
        if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
        // 恢复音频
        {
            auto &app = Application::GetInstance();
            auto &as = app.GetAudioService();
            as.EnableVoiceProcessing(true);
            as.EnableWakeWordDetection(true);
            if (Board::GetInstance().GetAudioCodec()) {
                Board::GetInstance().GetAudioCodec()->EnableInput(true);
            }
        }
        s_camera_busy = false;
        return "{\"success\": false, \"message\": \"Failed to connect to explain URL\"}";
    }
    ESP_LOGI(TAG, "Explain HTTP open ok (octet-stream,len=%u) url=%s", (unsigned)body_len, final_url.c_str());

    // 顺序写入 JPEG 字节（非 chunked），跳过 SOI 之前的异常字节，并在需要时补齐 EOI
    // 发送完整编码输出，不追加 EOI
    size_t written_total = 0;
    for (auto &c : jpeg_chunks) {
        if (c.data && c.len) {
            http->Write((const char*)c.data, c.len);
            written_total += c.len;
            heap_caps_free(c.data);
        }
    }
    // 明确结束请求体，触发底层 flush/FIN（某些实现需要显式 0 字节写入来结束发送）
    http->Write(nullptr, 0);
    ESP_LOGI(TAG, "Explain JPEG write bytes=%u (sync)", (unsigned)written_total);
    // 注：不再执行 0 字节写入以避免个别服务端/代理在 Connection: close 场景下的解析歧义
    ESP_LOGI(TAG, "Explain JPEG all sent total=%uB, waiting for response headers", (unsigned)body_len);

    // 仅当状态码 >= 300 时才认为需要降级重试；200/202 都属于正常快速返回
    if (http->GetStatusCode() >= 300) {
        int code = http->GetStatusCode();
        ESP_LOGW(TAG, "Upload got status=%d, will consider VGA fallback once", code);
        // 如果第一次尝试是 SVGA，则降级到 VGA 重试一次
        bool used_svga = (fb_ && fb_->width >= 800 && fb_->height >= 600);
    if (used_svga && sensor && sensor->set_framesize) {
            ESP_LOGW(TAG, "Retrying upload with VGA (fallback)");
            // 释放旧帧
            if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
            // 切换到 VGA 并取新帧
            sensor->set_framesize(sensor, FRAMESIZE_VGA);
            // 丢弃一帧稳定
            camera_fb_t* tmp = esp_camera_fb_get();
            if (tmp) esp_camera_fb_return(tmp);
            fb_ = esp_camera_fb_get();
            if (!fb_) {
                ESP_LOGE(TAG, "Retry capture VGA failed");
            } else {
                // 重新编码与上传（同步调用回调，避免线程/队列带来的内存压力）
                std::vector<JpegChunk> r_chunks; r_chunks.reserve(16);
                size_t r_total = 0;
                bool ok2 = frame2jpg_cb(fb_, 80, [](void* arg, size_t, const void* data, size_t len) -> unsigned int {
                    auto* vec = reinterpret_cast<std::vector<JpegChunk>*>(arg);
                    if (!data || len == 0) return 0;
                    uint8_t* buf = (uint8_t*)heap_caps_aligned_alloc(16, len, MALLOC_CAP_SPIRAM);
                    if (!buf) buf = (uint8_t*)heap_caps_aligned_alloc(16, len, MALLOC_CAP_8BIT);
                    if (!buf) return 0;
                    memcpy(buf, data, len);
                    vec->push_back({buf, len});
                    return len;
                }, &r_chunks);
                if (!ok2 || r_chunks.empty()) {
                    ESP_LOGE(TAG, "Retry VGA encode failed");
                } else {
                    for (auto &c : r_chunks) r_total += c.len;
                    // 拼接为连续内存
                    uint8_t* joined = (uint8_t*)heap_caps_aligned_alloc(16, r_total, MALLOC_CAP_SPIRAM);
                    if (!joined) joined = (uint8_t*)heap_caps_aligned_alloc(16, r_total, MALLOC_CAP_8BIT);
                    if (joined) {
                        size_t off = 0; for (auto &c : r_chunks) { memcpy(joined + off, c.data, c.len); off += c.len; heap_caps_free(c.data); }
                        // 直接发送
                        auto network2 = Board::GetInstance().GetNetwork();
                        auto http2 = network2->CreateHttp(3);
                        http2->SetTimeout(120000);
                        http2->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
                        http2->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
                        if (!Application::GetInstance().GetStudentId().empty()) http2->SetHeader("Student-Id", Application::GetInstance().GetStudentId().c_str());
                        if (!explain_token_.empty()) http2->SetHeader("Authorization", std::string("Bearer ")+explain_token_);
                        http2->SetHeader("Content-Type", "application/octet-stream");
                        http2->SetHeader("Accept-Charset", "utf-8");
                        http2->SetHeader("Accept", "application/json, text/plain, */*");
                        http2->SetHeader("Expect", "");
                        http2->SetHeader("Connection", "close");
                        // 与主路径保持一致，使用异步快速返回
                        http2->SetHeader("X-Async", "1");
                        char clb[32]; snprintf(clb, sizeof(clb), "%u", (unsigned)r_total); http2->SetHeader("Content-Length", clb);
                        // 追加异步与目标方向/尺寸参数
                        // 回退路径也保持与主路径一致，仅 async=1
                        std::string final_url2 = url_with_q + (url_with_q.find('?')==std::string::npos?"?":"&") + "async=1";
                        if (!http2->Open("POST", final_url2)) {
                            ESP_LOGE(TAG, "Retry open failed");
                        } else {
                            http2->Write((const char*)joined, r_total);
                            http2->Write(nullptr, 0);
                            int sc2 = http2->GetStatusCode();
                            std::string result2 = http2->ReadAll();
                            http2->Close();
                            if (sc2 == 200 || sc2 == 202) {
                                bool try_poll2 = false; std::string poll_url2;
                                cJSON *json2 = cJSON_Parse(result2.c_str());
                                if (json2) {
                                    const cJSON *accepted2 = cJSON_GetObjectItem(json2, "accepted");
                                    const cJSON *result_url2 = cJSON_GetObjectItem(json2, "result_url");
                                    if (cJSON_IsTrue(accepted2) && cJSON_IsString(result_url2) && result_url2->valuestring) {
                                        try_poll2 = true; poll_url2 = result_url2->valuestring;
                                        // 将返回的内部地址重写为外部可达的 origin
                                        std::string base_origin2 = extract_origin(final_url2);
                                        if (!base_origin2.empty() && poll_url2.rfind("http", 0) == 0) {
                                            std::string rewritten2 = rewrite_to_base(poll_url2, base_origin2);
                                            if (rewritten2 != poll_url2) {
                                                ESP_LOGW(TAG, "Rewrite poll_url(retry) to base origin: %s -> %s", poll_url2.c_str(), rewritten2.c_str());
                                                poll_url2 = rewritten2;
                                            }
                                        }
                                    }
                                    const cJSON *success2 = cJSON_GetObjectItem(json2, "success");
                                    const cJSON *response2 = cJSON_GetObjectItem(json2, "response");
                                    if (!try_poll2 && cJSON_IsTrue(success2) && cJSON_IsString(response2)) {
                                        cJSON_Delete(json2);
                                        // 直接成功，统一清理并返回
                                        auto display = Board::GetInstance().GetDisplay(); if (display) display->SetPreviewImage(nullptr);
                                        if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
                                        if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
                                        auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(false); as.EnableWakeWordDetection(false); vTaskDelay(20); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true); if (Board::GetInstance().GetAudioCodec()) Board::GetInstance().GetAudioCodec()->EnableInput(true);
                                        size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
                                        ESP_LOGI(TAG, "Explain image size=%dx%d (retry VGA), compressed size=%d, remain stack size=%d, question=%s\n%s", fb_?fb_->width:0, fb_?fb_->height:0, (int)r_total, (int)remain_stack_size, question.c_str(), result2.c_str());
                                        heap_caps_free(joined);
                                        s_camera_busy = false;
                                        return result2;
                                    }
                                    cJSON_Delete(json2);
                                }
                                if (try_poll2 && !poll_url2.empty()) {
                                    ESP_LOGI(TAG, "Explain polling (retry) %s", poll_url2.c_str());
                                    const int total_wait_ms2 = 120000; const int interval_ms2 = 1000; int waited2 = 0;
                                    while (waited2 < total_wait_ms2) {
                                        auto net3 = Board::GetInstance().GetNetwork(); auto http3 = net3->CreateHttp(2);
                                        http3->SetTimeout(10000);
                                        http3->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
                                        http3->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
                                        if (!Application::GetInstance().GetStudentId().empty()) http3->SetHeader("Student-Id", Application::GetInstance().GetStudentId().c_str());
                                        if (!explain_token_.empty()) http3->SetHeader("Authorization", std::string("Bearer ")+explain_token_);
                                        http3->SetHeader("Accept", "application/json, text/plain, */*");
                                        if (http3->Open("GET", poll_url2)) {
                                            int sc3 = http3->GetStatusCode();
                                            std::string body3 = http3->ReadAll();
                                            http3->Close();
                                            ESP_LOGD(TAG, "Explain poll(retry) status=%d", sc3);
                                            cJSON *j3 = cJSON_Parse(body3.c_str());
                                            if (j3) {
                                                const cJSON *status3 = cJSON_GetObjectItem(j3, "status");
                                                const cJSON *success3 = cJSON_GetObjectItem(j3, "success");
                                                const cJSON *response3 = cJSON_GetObjectItem(j3, "response");
                                                if (cJSON_IsString(status3) && status3->valuestring && strcmp(status3->valuestring, "pending")==0) {
                                                    cJSON_Delete(j3);
                                                } else if (cJSON_IsTrue(success3) && cJSON_IsString(response3)) {
                                                    // 统一清理并返回
                                                    auto display = Board::GetInstance().GetDisplay(); if (display) display->SetPreviewImage(nullptr);
                                                    if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
                                                    if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
                                                    auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(false); as.EnableWakeWordDetection(false); vTaskDelay(20); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true); if (Board::GetInstance().GetAudioCodec()) Board::GetInstance().GetAudioCodec()->EnableInput(true);
                                                    size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
                                                    ESP_LOGI(TAG, "Explain image size=%dx%d (retry VGA), compressed size=%d, remain stack size=%d, question=%s\n%s", fb_?fb_->width:0, fb_?fb_->height:0, (int)r_total, (int)remain_stack_size, question.c_str(), body3.c_str());
                                                    heap_caps_free(joined);
                                                    cJSON_Delete(j3);
                                                    s_camera_busy = false;
                                                    return body3;
                                                } else if (cJSON_IsFalse(success3)) {
                                                    auto display = Board::GetInstance().GetDisplay(); if (display) display->SetPreviewImage(nullptr);
                                                    if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
                                                    if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
                                                    auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(false); as.EnableWakeWordDetection(false); vTaskDelay(20); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true); if (Board::GetInstance().GetAudioCodec()) Board::GetInstance().GetAudioCodec()->EnableInput(true);
                                                    size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
                                                    ESP_LOGI(TAG, "Explain image size=%dx%d (retry VGA), compressed size=%d, remain stack size=%d, question=%s\n%s", fb_?fb_->width:0, fb_?fb_->height:0, (int)r_total, (int)remain_stack_size, question.c_str(), body3.c_str());
                                                    heap_caps_free(joined);
                                                    cJSON_Delete(j3);
                                                    s_camera_busy = false;
                                                    return body3;
                                                } else {
                                                    cJSON_Delete(j3);
                                                }
                                            }
                                        }
                                        vTaskDelay(pdMS_TO_TICKS(interval_ms2));
                                        waited2 += interval_ms2;
                                    }
                                    // 轮询超时，走统一清理并返回初始响应体
                                    auto display = Board::GetInstance().GetDisplay(); if (display) display->SetPreviewImage(nullptr);
                                    if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
                                    if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
                                    auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(false); as.EnableWakeWordDetection(false); vTaskDelay(20); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true); if (Board::GetInstance().GetAudioCodec()) Board::GetInstance().GetAudioCodec()->EnableInput(true);
                                    size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
                                    ESP_LOGI(TAG, "Explain image size=%dx%d (retry VGA), compressed size=%d, remain stack size=%d, question=%s\n%s", fb_?fb_->width:0, fb_?fb_->height:0, (int)r_total, (int)remain_stack_size, question.c_str(), result2.c_str());
                                    heap_caps_free(joined);
                                    s_camera_busy = false;
                                    return result2;
                                } else {
                                    // 无需轮询，直接按成功处理
                                    auto display = Board::GetInstance().GetDisplay(); if (display) display->SetPreviewImage(nullptr);
                                    if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
                                    if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
                                    auto &app = Application::GetInstance(); auto &as = app.GetAudioService(); as.EnableVoiceProcessing(false); as.EnableWakeWordDetection(false); vTaskDelay(20); as.EnableVoiceProcessing(true); as.EnableWakeWordDetection(true); if (Board::GetInstance().GetAudioCodec()) Board::GetInstance().GetAudioCodec()->EnableInput(true);
                                    size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
                                    ESP_LOGI(TAG, "Explain image size=%dx%d (retry VGA), compressed size=%d, remain stack size=%d, question=%s\n%s", fb_?fb_->width:0, fb_?fb_->height:0, (int)r_total, (int)remain_stack_size, question.c_str(), result2.c_str());
                                    heap_caps_free(joined);
                                    s_camera_busy = false;
                                    return result2;
                                }
                            } else {
                                ESP_LOGE(TAG, "Retry VGA upload failed: %d", sc2);
                            }
                        }
                        heap_caps_free(joined);
                    } else {
                        for (auto &c : r_chunks) { if (c.data) heap_caps_free(c.data); }
                    }
                }
            }
        }
        // 上传失败也要恢复屏幕与相机资源（最终失败）
        auto display = Board::GetInstance().GetDisplay();
        if (display) display->SetPreviewImage(nullptr);
        if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
        if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
        // 恢复音频
        {
            auto &app = Application::GetInstance();
            auto &as = app.GetAudioService();
            as.EnableVoiceProcessing(true);
            as.EnableWakeWordDetection(true);
            if (Board::GetInstance().GetAudioCodec()) {
                Board::GetInstance().GetAudioCodec()->EnableInput(true);
            }
        }
        s_camera_busy = false;
        return "{\"success\": false, \"message\": \"Failed to upload photo\"}";
    }
    int http_code = http->GetStatusCode();
    ESP_LOGI(TAG, "Explain HTTP status=%d reading response", http_code);

    std::string result = http->ReadAll();
    http->Close();

    // 统一的成功返回：先做清理与恢复，再打印日志并返回结果
    auto do_success_return = [&](void) -> std::string {
        // 上传成功后恢复屏幕显示，释放相机帧，避免预览叠层遮挡或内存泄漏
        {
            auto display = Board::GetInstance().GetDisplay();
            if (display) display->SetPreviewImage(nullptr);
            if (fb_) { esp_camera_fb_return(fb_); fb_ = nullptr; }
            if (sensor && fs_changed) sensor->set_framesize(sensor, original_fs);
        }

        // 上传完成后恢复音频，并强制重启音频处理器，彻底复位AFE状态，防止ringbuffer溢出
        {
            auto &app = Application::GetInstance();
            auto &as = app.GetAudioService();
            as.EnableVoiceProcessing(false);
            as.EnableWakeWordDetection(false);
            vTaskDelay(20); // 确保AFE任务彻底停下
            as.EnableVoiceProcessing(true);
            as.EnableWakeWordDetection(true);
            if (Board::GetInstance().GetAudioCodec()) {
                Board::GetInstance().GetAudioCodec()->EnableInput(true);
            }
        }

        // 栈余量与最终日志
        size_t remain_stack_size = uxTaskGetStackHighWaterMark(nullptr);
        ESP_LOGI(TAG, "Explain image size=%dx%d, compressed size=%d, remain stack size=%d, question=%s\n%s",
            fb_?fb_->width:0, fb_?fb_->height:0, total_sent, (int)remain_stack_size, question.c_str(), result.c_str());
        s_camera_busy = false;
        return result;
    };

    // 支持异步返回：202 或 200+accepted=true
    bool try_poll = false; std::string poll_url;
    if (http_code == 202 || http_code == 200) {
        cJSON *json = cJSON_Parse(result.c_str());
        if (json) {
            const cJSON *accepted = cJSON_GetObjectItem(json, "accepted");
            const cJSON *result_url = cJSON_GetObjectItem(json, "result_url");
            if (cJSON_IsTrue(accepted) && cJSON_IsString(result_url) && result_url->valuestring) {
                try_poll = true; poll_url = result_url->valuestring;
                // 若返回的是容器内网地址（如 172.18.*），将其重写到与请求相同的 origin 上
                if (!base_origin.empty() && poll_url.rfind("http", 0) == 0) {
                    size_t pos_path = poll_url.find('/' , poll_url.find("://") + 3);
                    if (pos_path != std::string::npos) {
                        std::string rewritten = rewrite_to_base(poll_url, base_origin);
                        if (rewritten != poll_url) {
                            ESP_LOGW(TAG, "Rewrite poll_url to base origin: %s -> %s", poll_url.c_str(), rewritten.c_str());
                            poll_url = rewritten;
                        }
                    }
                }
            }
            const cJSON *success = cJSON_GetObjectItem(json, "success");
            const cJSON *response = cJSON_GetObjectItem(json, "response");
            if (!try_poll && cJSON_IsTrue(success) && cJSON_IsString(response)) {
                // 已有直接结果，直接返回
                cJSON_Delete(json);
                return do_success_return();
            }
            cJSON_Delete(json);
        }
    }

    if (try_poll && !poll_url.empty()) {
        ESP_LOGI(TAG, "Explain polling %s", poll_url.c_str());
        // Polling max 120s
        const int total_wait_ms = 120000;
        // Interval reduced to 200ms to catch injected results faster
        const int interval_ms = 200; 
        int waited = 0;
        
        // Reuse HTTP client
        auto net2 = Board::GetInstance().GetNetwork();
        auto http2 = net2->CreateHttp(2);
        
        while (waited < total_wait_ms) {
            // Check for injected result logic
            if (has_pending_result_) {
                std::string res_injected;
                {
                    std::lock_guard<std::mutex> lock(result_mutex_);
                    res_injected = pending_result_;
                    has_pending_result_ = false;
                    pending_result_.clear();
                }
                ESP_LOGI(TAG, "Early return with injected result: %s", res_injected.c_str());
                if (http2) http2->Close();
                
                // Construct fake success response
                cJSON* root = cJSON_CreateObject();
                cJSON_AddBoolToObject(root, "success", true);
                cJSON_AddStringToObject(root, "response", res_injected.c_str());
                char* json_str = cJSON_PrintUnformatted(root);
                result = std::string(json_str);
                cJSON_free(json_str);
                cJSON_Delete(root);
                
                return do_success_return();
            }

            if (!http2) {
                // If creation failed, try to recreate
                http2 = net2->CreateHttp(2);
                if (!http2) {
                    ESP_LOGE(TAG, "Failed to create HTTP client for polling");
                    vTaskDelay(pdMS_TO_TICKS(interval_ms));
                    waited += interval_ms;
                    continue;
                }
            }

            // Reduced timeout to 3s to allow faster interruption
            http2->SetTimeout(3000);
            http2->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
            http2->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
            if (!Application::GetInstance().GetStudentId().empty()) http2->SetHeader("Student-Id", Application::GetInstance().GetStudentId().c_str());
            if (!explain_token_.empty()) http2->SetHeader("Authorization", std::string("Bearer ")+explain_token_);
            http2->SetHeader("Accept", "application/json, text/plain, */*");
            
            // Log iteration to debug stuck loop
            ESP_LOGD(TAG, "Explain loop polling... (waited %d ms)", waited);

            if (http2->Open("GET", poll_url)) {
                int sc = http2->GetStatusCode();
                std::string body = http2->ReadAll();
                http2->Close();
                ESP_LOGD(TAG, "Explain poll status=%d", sc);
                cJSON *j = cJSON_Parse(body.c_str());
                if (j) {
                    const cJSON *status = cJSON_GetObjectItem(j, "status");
                    const cJSON *success = cJSON_GetObjectItem(j, "success");
                    const cJSON *response = cJSON_GetObjectItem(j, "response");
                    if (cJSON_IsString(status) && status->valuestring && strcmp(status->valuestring, "pending")==0) {
                        cJSON_Delete(j);
                    } else if (cJSON_IsTrue(success) && cJSON_IsString(response)) {
                        result = body; cJSON_Delete(j);
                        return do_success_return();
                    } else if (cJSON_IsFalse(success)) {
                        // 任务失败，直接返回该错误
                        result = body; cJSON_Delete(j);
                        return do_success_return();
                    } else {
                        cJSON_Delete(j);
                    }
                }
            } else {
                // Open 失败，可能是内存不足或网络问题
                ESP_LOGW(TAG, "Explain poll open failed");
                // 尝试释放并重建，以防状态异常
                http2.reset(); 
            }
            vTaskDelay(pdMS_TO_TICKS(interval_ms));
            waited += interval_ms;
        }
        // 轮询超时：返回原始接收体（包含 task_id），由上层决定提示
    }
    // 非立即/轮询成功路径：做统一清理并返回（通常是超时或没有 accepted）
    return do_success_return();
}

void Esp32Camera::ForceResetStatus() {
    ESP_LOGW(TAG, "Force resetting camera status and clearing cache");
    
    // Clear pending result
    {
        std::lock_guard<std::mutex> lock(result_mutex_);
        has_pending_result_ = false;
        pending_result_.clear();
    }

    // 强制复位 busy 标志
    s_camera_busy = false;
    
    // 清理缓存
    ClearCachedPhotos();
    
    // 如果有残留的 FB，释放
    if (fb_) {
        esp_camera_fb_return(fb_);
        fb_ = nullptr;
    }
    
    // 如果正在预览，强制取消
    if (preview_active_) {
        preview_canceled_ = true;
        // 等待一小会儿让预览循环感知
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        preview_active_ = false;
        preview_canceled_ = false;
    }

    // 释放预览 buffer
    if (preview_image_.data) {
        heap_caps_free((void*)preview_image_.data);
        preview_image_.data = nullptr;
        preview_image_.data_size = 0;
        preview_capacity_ = 0;
    }
    
    // 重置预览交互标志
    preview_confirmed_ = false;

    // [Added] 注意：不应该清除 explain_url_ 和 explain_token_，因为这是系统启动时下发的配置，
    // 清除会导致后续所有视觉请求报错 "URL or token not set"。
    // 这里明确注释保留它们。
}

void Esp32Camera::SubmitResult(const std::string& result) {
    std::lock_guard<std::mutex> lock(result_mutex_);
    pending_result_ = result;
    has_pending_result_ = true;
    ESP_LOGI(TAG, "Result submitted externally, length=%d", (int)result.length());
}

