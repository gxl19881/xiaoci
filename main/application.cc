#include "application.h"
#include "board.h"
#include "display.h"
#include "system_info.h"
#include "audio_codec.h"
#include "mqtt_protocol.h"
#include "websocket_protocol.h"
#include "font_awesome_symbols.h"
#include "assets/lang_config.h"
#include "mcp_server.h"
#include "settings.h"

#include <cstring>
#include <esp_log.h>
#include <cJSON.h>
#include <driver/gpio.h>
#include <arpa/inet.h>
#include <mbedtls/base64.h>
#include <esp_http_client.h>

#define TAG "Application"


static const char* const STATE_STRINGS[] = {
    "unknown",
    "starting",
    "configuring",
    "idle",
    "connecting",
    "listening",
    "speaking",
    "upgrading",
    "activating",
    "audio_testing",
    "fatal_error",
    "invalid_state"
};

Application::Application() {
    event_group_ = xEventGroupCreate();

#if CONFIG_USE_DEVICE_AEC && CONFIG_USE_SERVER_AEC
#error "CONFIG_USE_DEVICE_AEC and CONFIG_USE_SERVER_AEC cannot be enabled at the same time"
#elif CONFIG_USE_DEVICE_AEC
    aec_mode_ = kAecOnDeviceSide;
#elif CONFIG_USE_SERVER_AEC
    aec_mode_ = kAecOnServerSide;
#else
    aec_mode_ = kAecOff;
#endif

    esp_timer_create_args_t clock_timer_args = {
        .callback = [](void* arg) {
            Application* app = (Application*)arg;
            app->OnClockTimer();
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "clock_timer",
        .skip_unhandled_events = true
    };
    esp_timer_create(&clock_timer_args, &clock_timer_handle_);

    // 监听超时定时器：进入Listening后启动，用于在本地保证最长录音时长
    esp_timer_create_args_t listening_timer_args = {
        .callback = [](void* arg) {
            Application* app = (Application*)arg;
            app->OnListeningTimer();
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "listening_timer",
        .skip_unhandled_events = true
    };
    esp_timer_create(&listening_timer_args, &listening_timer_handle_);
}

Application::~Application() {
    if (clock_timer_handle_ != nullptr) {
        esp_timer_stop(clock_timer_handle_);
        esp_timer_delete(clock_timer_handle_);
    }
    if (listening_timer_handle_ != nullptr) {
        esp_timer_stop(listening_timer_handle_);
        esp_timer_delete(listening_timer_handle_);
    }
    vEventGroupDelete(event_group_);
}

void Application::MaybePromptStudentId() {
    if (awaiting_student_id_) return;
    awaiting_student_id_ = true;
    auto display = Board::GetInstance().GetDisplay();
    // 语音与屏幕提示（明确要求只报出数字）
    Alert("提示", "请只报出学号数字，比如：一八三零二", "neutral", Lang::Sounds::P3_POPUP);
    // 打开一次手动聆听，等待第一句 STT 作为学号
    Schedule([this]() {
        if (!protocol_) { awaiting_student_id_ = false; return; }
        if (!protocol_->IsAudioChannelOpened()) {
            SetDeviceState(kDeviceStateConnecting);
            if (!protocol_->OpenAudioChannel()) { awaiting_student_id_ = false; return; }
        }
        SetListeningMode(kListeningModeManualStop);
    });
}

void Application::CheckNewVersion(Ota& ota) {
    const int MAX_RETRY = 10;
    int retry_count = 0;
    int retry_delay = 10; // 初始重试延迟为10秒

    auto& board = Board::GetInstance();
    while (true) {
        SetDeviceState(kDeviceStateActivating);
        auto display = board.GetDisplay();
        display->SetStatus(Lang::Strings::CHECKING_NEW_VERSION);

        if (!ota.CheckVersion()) {
            retry_count++;
            if (retry_count >= MAX_RETRY) {
                ESP_LOGE(TAG, "Too many retries, exit version check");
                return;
            }

            char buffer[128];
            snprintf(buffer, sizeof(buffer), Lang::Strings::CHECK_NEW_VERSION_FAILED, retry_delay, ota.GetCheckVersionUrl().c_str());
            Alert(Lang::Strings::ERROR, buffer, "sad", Lang::Sounds::P3_EXCLAMATION);

            ESP_LOGW(TAG, "Check new version failed, retry in %d seconds (%d/%d)", retry_delay, retry_count, MAX_RETRY);
            for (int i = 0; i < retry_delay; i++) {
                vTaskDelay(pdMS_TO_TICKS(1000));
                if (device_state_ == kDeviceStateIdle) {
                    break;
                }
            }
            retry_delay *= 2; // 每次重试后延迟时间翻倍
            continue;
        }
        retry_count = 0;
        retry_delay = 10; // 重置重试延迟时间

        if (ota.HasNewVersion()) {
            Alert(Lang::Strings::OTA_UPGRADE, Lang::Strings::UPGRADING, "happy", Lang::Sounds::P3_UPGRADE);

            vTaskDelay(pdMS_TO_TICKS(3000));

            SetDeviceState(kDeviceStateUpgrading);
            
            display->SetIcon(FONT_AWESOME_DOWNLOAD);
            std::string message = std::string(Lang::Strings::NEW_VERSION) + ota.GetFirmwareVersion();
            display->SetChatMessage("system", message.c_str());

            board.SetPowerSaveMode(false);
            audio_service_.Stop();
            vTaskDelay(pdMS_TO_TICKS(1000));

            bool upgrade_success = ota.StartUpgrade([display](int progress, size_t speed) {
                std::thread([display, progress, speed]() {
                    char buffer[32];
                    snprintf(buffer, sizeof(buffer), "%d%% %uKB/s", progress, speed / 1024);
                    display->SetChatMessage("system", buffer);
                }).detach();
            });

            if (!upgrade_success) {
                // Upgrade failed, restart audio service and continue running
                ESP_LOGE(TAG, "Firmware upgrade failed, restarting audio service and continuing operation...");
                audio_service_.Start(); // Restart audio service
                board.SetPowerSaveMode(true); // Restore power save mode
                Alert(Lang::Strings::ERROR, Lang::Strings::UPGRADE_FAILED, "sad", Lang::Sounds::P3_EXCLAMATION);
                vTaskDelay(pdMS_TO_TICKS(3000));
                // Continue to normal operation (don't break, just fall through)
            } else {
                // Upgrade success, reboot immediately
                ESP_LOGI(TAG, "Firmware upgrade successful, rebooting...");
                display->SetChatMessage("system", "Upgrade successful, rebooting...");
                vTaskDelay(pdMS_TO_TICKS(1000)); // Brief pause to show message
                Reboot();
                return; // This line will never be reached after reboot
            }
        }

        // No new version, mark the current version as valid
        ota.MarkCurrentVersionValid();
        if (!ota.HasActivationCode() && !ota.HasActivationChallenge()) {
            xEventGroupSetBits(event_group_, MAIN_EVENT_CHECK_NEW_VERSION_DONE);
            // Exit the loop if done checking new version
            break;
        }

        display->SetStatus(Lang::Strings::ACTIVATION);
        // Activation code is shown to the user and waiting for the user to input
        if (ota.HasActivationCode()) {
            ShowActivationCode(ota.GetActivationCode(), ota.GetActivationMessage());
        }

        // This will block the loop until the activation is done or timeout
        for (int i = 0; i < 10; ++i) {
            ESP_LOGI(TAG, "Activating... %d/%d", i + 1, 10);
            esp_err_t err = ota.Activate();
            if (err == ESP_OK) {
                xEventGroupSetBits(event_group_, MAIN_EVENT_CHECK_NEW_VERSION_DONE);
                break;
            } else if (err == ESP_ERR_TIMEOUT) {
                vTaskDelay(pdMS_TO_TICKS(3000));
            } else {
                vTaskDelay(pdMS_TO_TICKS(10000));
            }
            if (device_state_ == kDeviceStateIdle) {
                break;
            }
        }
    }
}

void Application::ShowActivationCode(const std::string& code, const std::string& message) {
    struct digit_sound {
        char digit;
        const std::string_view& sound;
    };
    static const std::array<digit_sound, 10> digit_sounds{{
        digit_sound{'0', Lang::Sounds::P3_0},
        digit_sound{'1', Lang::Sounds::P3_1}, 
        digit_sound{'2', Lang::Sounds::P3_2},
        digit_sound{'3', Lang::Sounds::P3_3},
        digit_sound{'4', Lang::Sounds::P3_4},
        digit_sound{'5', Lang::Sounds::P3_5},
        digit_sound{'6', Lang::Sounds::P3_6},
        digit_sound{'7', Lang::Sounds::P3_7},
        digit_sound{'8', Lang::Sounds::P3_8},
        digit_sound{'9', Lang::Sounds::P3_9}
    }};

    // This sentence uses 9KB of SRAM, so we need to wait for it to finish
    Alert(Lang::Strings::ACTIVATION, message.c_str(), "happy", Lang::Sounds::P3_ACTIVATION);

    for (const auto& digit : code) {
        auto it = std::find_if(digit_sounds.begin(), digit_sounds.end(),
            [digit](const digit_sound& ds) { return ds.digit == digit; });
        if (it != digit_sounds.end()) {
            audio_service_.PlaySound(it->sound);
        }
    }
}

void Application::Alert(const char* status, const char* message, const char* emotion, const std::string_view& sound) {
    ESP_LOGW(TAG, "Alert %s: %s [%s]", status, message, emotion);
    auto display = Board::GetInstance().GetDisplay();
    display->SetStatus(status);
    display->SetEmotion(emotion);
    display->SetChatMessage("system", message);
    if (!sound.empty()) {
        audio_service_.PlaySound(sound);
    }
}

void Application::DismissAlert() {
    if (device_state_ == kDeviceStateIdle) {
        auto display = Board::GetInstance().GetDisplay();
        display->SetStatus(Lang::Strings::STANDBY);
        display->SetEmotion("neutral");
        display->SetChatMessage("system", "");
    }
}

void Application::ToggleChatState() {
    if (device_state_ == kDeviceStateActivating) {
        SetDeviceState(kDeviceStateIdle);
        return;
    } else if (device_state_ == kDeviceStateWifiConfiguring) {
        audio_service_.EnableAudioTesting(true);
        SetDeviceState(kDeviceStateAudioTesting);
        return;
    } else if (device_state_ == kDeviceStateAudioTesting) {
        audio_service_.EnableAudioTesting(false);
        SetDeviceState(kDeviceStateWifiConfiguring);
        return;
    }

    if (!protocol_) {
        ESP_LOGE(TAG, "Protocol not initialized");
        return;
    }

    if (device_state_ == kDeviceStateIdle) {
        Schedule([this]() {
            if (!protocol_->IsAudioChannelOpened()) {
                SetDeviceState(kDeviceStateConnecting);
                if (!protocol_->OpenAudioChannel()) {
                    return;
                }
            }

            // 默认使用“手动停止”模式，保证更长的录音时间（由本地定时器兜底限制上限）
            SetListeningMode(kListeningModeManualStop);
        });
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonNone);
        });
    } else if (device_state_ == kDeviceStateListening) {
        Schedule([this]() {
            protocol_->CloseAudioChannel();
        });
    }
}

void Application::StartListening() {
    if (device_state_ == kDeviceStateActivating) {
        SetDeviceState(kDeviceStateIdle);
        return;
    } else if (device_state_ == kDeviceStateWifiConfiguring) {
        audio_service_.EnableAudioTesting(true);
        SetDeviceState(kDeviceStateAudioTesting);
        return;
    }

    if (!protocol_) {
        ESP_LOGE(TAG, "Protocol not initialized");
        return;
    }
    
    if (device_state_ == kDeviceStateIdle) {
        Schedule([this]() {
            if (!protocol_->IsAudioChannelOpened()) {
                SetDeviceState(kDeviceStateConnecting);
                if (!protocol_->OpenAudioChannel()) {
                    return;
                }
            }

            // PTT模式：使用“手动停止”，用户松手或到达上限后停止
            SetListeningMode(kListeningModeManualStop);
        });
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonNone);
            SetListeningMode(kListeningModeManualStop);
        });
    }
}

void Application::StopListening() {
    if (device_state_ == kDeviceStateAudioTesting) {
        audio_service_.EnableAudioTesting(false);
        SetDeviceState(kDeviceStateWifiConfiguring);
        return;
    }

    const std::array<int, 3> valid_states = {
        kDeviceStateListening,
        kDeviceStateSpeaking,
        kDeviceStateIdle,
    };
    // If not valid, do nothing
    if (std::find(valid_states.begin(), valid_states.end(), device_state_) == valid_states.end()) {
        return;
    }

    Schedule([this]() {
        if (device_state_ == kDeviceStateListening) {
            protocol_->SendStopListening();
            SetDeviceState(kDeviceStateIdle);
        }
    });
}

void Application::Start() {
    auto& board = Board::GetInstance();
    SetDeviceState(kDeviceStateStarting);

    /* Setup the display */
    auto display = board.GetDisplay();

    /* Setup the audio service */
    auto codec = board.GetAudioCodec();
    audio_service_.Initialize(codec);
    audio_service_.Start();
    // 固件声明向服务器发送PCM而非Opus
    audio_service_.SetSendFormatPcm(true);

    AudioServiceCallbacks callbacks;
    callbacks.on_send_queue_available = [this]() {
        xEventGroupSetBits(event_group_, MAIN_EVENT_SEND_AUDIO);
    };
    callbacks.on_wake_word_detected = [this](const std::string& wake_word) {
        xEventGroupSetBits(event_group_, MAIN_EVENT_WAKE_WORD_DETECTED);
    };
    callbacks.on_vad_change = [this](bool speaking) {
        xEventGroupSetBits(event_group_, MAIN_EVENT_VAD_CHANGE);
    };
    audio_service_.SetCallbacks(callbacks);

    /* Start the clock timer to update the status bar */
    esp_timer_start_periodic(clock_timer_handle_, 1000000);

    /* Wait for the network to be ready */
    board.StartNetwork();

    // Update the status bar immediately to show the network state
    display->UpdateStatusBar(true);

    // Check for new firmware version or get the MQTT broker address
    Ota ota;
    CheckNewVersion(ota);

    // Initialize the protocol
    display->SetStatus(Lang::Strings::LOADING_PROTOCOL);

    // Add MCP common tools before initializing the protocol
    McpServer::GetInstance().AddCommonTools();

    if (ota.HasMqttConfig()) {
        protocol_ = std::make_unique<MqttProtocol>();
    } else if (ota.HasWebsocketConfig()) {
        protocol_ = std::make_unique<WebsocketProtocol>();
    } else {
        ESP_LOGW(TAG, "No protocol specified in the OTA config, using MQTT");
        protocol_ = std::make_unique<MqttProtocol>();
    }

    protocol_->OnNetworkError([this](const std::string& message) {
        last_error_message_ = message;
        xEventGroupSetBits(event_group_, MAIN_EVENT_ERROR);
    });
    protocol_->OnIncomingAudio([this](std::unique_ptr<AudioStreamPacket> packet) {
        if (device_state_ == kDeviceStateSpeaking) {
            audio_service_.PushPacketToDecodeQueue(std::move(packet));
        }
    });
    protocol_->OnAudioChannelOpened([this, codec, &board]() {
        board.SetPowerSaveMode(false);
        if (protocol_->server_sample_rate() != codec->output_sample_rate()) {
            ESP_LOGW(TAG, "Server sample rate %d does not match device output sample rate %d, resampling may cause distortion",
                protocol_->server_sample_rate(), codec->output_sample_rate());
        }
    });
    protocol_->OnAudioChannelClosed([this, &board]() {
        board.SetPowerSaveMode(true);
        Schedule([this]() {
            auto display = Board::GetInstance().GetDisplay();
            display->SetChatMessage("system", "");
            SetDeviceState(kDeviceStateIdle);
        });
    });
    protocol_->OnIncomingJson([this, display](const cJSON* root) {
        // Parse JSON data
        auto type = cJSON_GetObjectItem(root, "type");
        if (strcmp(type->valuestring, "tts") == 0) {
            // 等待学号阶段，忽略所有 TTS 下行，避免误进入 speaking/播放回复
            if (awaiting_student_id_) {
                return;
            }
            auto state = cJSON_GetObjectItem(root, "state");
            if (strcmp(state->valuestring, "start") == 0) {
                Schedule([this]() {
                    aborted_ = false;
                    if (device_state_ == kDeviceStateIdle || device_state_ == kDeviceStateListening) {
                        SetDeviceState(kDeviceStateSpeaking);
                    }
                });
            } else if (strcmp(state->valuestring, "stop") == 0) {
                Schedule([this]() {
                    if (device_state_ == kDeviceStateSpeaking) {
                        if (listening_mode_ == kListeningModeManualStop) {
                            SetDeviceState(kDeviceStateIdle);
                        } else {
                            SetDeviceState(kDeviceStateListening);
                        }
                    }
                });
            } else if (strcmp(state->valuestring, "sentence_start") == 0) {
                auto text = cJSON_GetObjectItem(root, "text");
                if (cJSON_IsString(text)) {
                    ESP_LOGI(TAG, "<< %s", text->valuestring);
                    Schedule([this, display, message = std::string(text->valuestring)]() {
                        display->SetChatMessage("assistant", message.c_str());
                    });
                }
            }
        } else if (strcmp(type->valuestring, "stt") == 0) {
            auto text = cJSON_GetObjectItem(root, "text");
            if (cJSON_IsString(text)) {
                ESP_LOGI(TAG, ">> %s", text->valuestring);
                // 学号阶段不把口述显示为聊天消息，避免造成对话错觉
                if (!awaiting_student_id_) {
                    Schedule([this, display, message = std::string(text->valuestring)]() {
                        display->SetChatMessage("user", message.c_str());
                    });
                }

                // 若正在等待学号，则用第一条识别文本作为学号，保存到 NVS，并提示保存成功
                if (awaiting_student_id_) {
                    // 规则提取：
                    // 1) 去掉空格/逗号/连字符/“号”字
                    // 2) 将中文数字“一二三四五六七八九零〇”替换成阿拉伯数字
                    // 3) 提取连续数字串（优先最长的一段）
                    auto raw = std::string(text->valuestring);
                    auto normalize = [](std::string s){
                        // 去噪字符
                        std::string out; out.reserve(s.size());
                        for (char ch : s) {
                            if (ch == ' ' || ch == ',' || ch == '，' || ch == '-' || ch == '—' || ch == '号') continue;
                            // 常见中文数字到半角
                            switch (ch) {
                                case '\xe4': // 可能是多字节中文，简化处理由下一个步骤覆盖
                                    out.push_back(ch); break;
                                default:
                                    out.push_back(ch); break;
                            }
                        }
                        // 简单替换中文数字（UTF-8下逐字处理较复杂，这里处理常见全角数字和中文汉字数字）
                        // 为简洁，这里按字面字符替换：
                        auto replace_all = [](std::string &str, const char* from, const char* to){
                            size_t pos = 0; size_t from_len = strlen(from); size_t to_len = strlen(to);
                            while ((pos = str.find(from, pos)) != std::string::npos) { str.replace(pos, from_len, to); pos += to_len; }
                        };
                        replace_all(out, "一", "1"); replace_all(out, "二", "2"); replace_all(out, "两", "2");
                        replace_all(out, "三", "3"); replace_all(out, "四", "4"); replace_all(out, "五", "5");
                        replace_all(out, "六", "6"); replace_all(out, "七", "7"); replace_all(out, "八", "8");
                        replace_all(out, "九", "9"); replace_all(out, "零", "0"); replace_all(out, "〇", "0");
                        // 全角数字
                        replace_all(out, "０", "0"); replace_all(out, "１", "1"); replace_all(out, "２", "2");
                        replace_all(out, "３", "3"); replace_all(out, "４", "4"); replace_all(out, "５", "5");
                        replace_all(out, "６", "6"); replace_all(out, "７", "7"); replace_all(out, "８", "8");
                        replace_all(out, "９", "9");
                        return out;
                    };
                    auto norm = normalize(raw);
                    // 提取最长数字串
                    std::string digits, best;
                    for (size_t i = 0; i < norm.size(); ++i) {
                        if (norm[i] >= '0' && norm[i] <= '9') { digits.push_back(norm[i]); }
                        else { if (digits.size() > best.size()) best.swap(digits); digits.clear(); }
                    }
                    if (digits.size() > best.size()) best = digits;

                    // 校验长度（可按项目需求调整），这里用 2-12 位，允许像“18”这样短学号
                    if (best.size() >= 2 && best.size() <= 12) {
                        student_id_ = best;
                        Settings nvs("app", true);
                        nvs.SetString("student_id", student_id_);
                        nvs.Commit();
                        // 屏幕常驻显示学号
                        Schedule([sid = student_id_]() {
                            auto display = Board::GetInstance().GetDisplay();
                            display->SetStudentId(sid.c_str());
                        });
                        char buf[96];
                        snprintf(buf, sizeof(buf), "学号已保存：%s", student_id_.c_str());
                        Schedule([display, msg = std::string(buf)](){ display->ShowNotification(msg.c_str(), 2000); });
                        // 结束本次聆听，并尽快通知服务器停止、关闭音频通道，避免进入对话流程
                        Schedule([this](){
                            if (protocol_) {
                                protocol_->SendStopListening();
                                protocol_->CloseAudioChannel();
                            }
                            SetDeviceState(kDeviceStateIdle);
                        });
                    } else {
                        // 未识别出合理学号：本地提示，并结束本次聆听，重新开启一次单句聆听，避免持续发送
                        Schedule([this](){
                            Alert("提示", "没有听清，请只报出学号数字，比如：一八三零二", "neutral", Lang::Sounds::P3_POPUP);
                            if (protocol_) {
                                protocol_->SendStopListening();
                            }
                            SetDeviceState(kDeviceStateIdle);
                        });
                        // 重新进入手动单句聆听（保持音频通道不关闭，减少抖动）
                        Schedule([this](){
                            if (protocol_) {
                                SetListeningMode(kListeningModeManualStop);
                            }
                        });
                    }
                }
            }
        } else if (strcmp(type->valuestring, "llm") == 0) {
            if (awaiting_student_id_) { return; }
            auto emotion = cJSON_GetObjectItem(root, "emotion");
            if (cJSON_IsString(emotion)) {
                Schedule([this, display, emotion_str = std::string(emotion->valuestring)]() {
                    display->SetEmotion(emotion_str.c_str());
                });
            }
        } else if (strcmp(type->valuestring, "mcp") == 0) {
            if (awaiting_student_id_) { return; }
            auto payload = cJSON_GetObjectItem(root, "payload");
            if (cJSON_IsObject(payload)) {
                McpServer::GetInstance().ParseMessage(payload);
            }
        } else if (strcmp(type->valuestring, "image_generation_status") == 0) {
            if (awaiting_student_id_) { return; }
            // { type: "image_generation_status", status: "started|progress|completed|failed", progress?: number, message?: string }
            cJSON* status = nullptr;
            cJSON* progress = nullptr;
            cJSON* msg = nullptr;

            // 优先检查 data 字段 (server 实现通常包装在 data 中)
            auto data_obj = cJSON_GetObjectItem(root, "data");
            if (cJSON_IsObject(data_obj)) {
                status = cJSON_GetObjectItem(data_obj, "status");
                progress = cJSON_GetObjectItem(data_obj, "progress");
                msg = cJSON_GetObjectItem(data_obj, "message");
            } else {
                status = cJSON_GetObjectItem(root, "status");
                progress = cJSON_GetObjectItem(root, "progress");
                msg = cJSON_GetObjectItem(root, "message");
            }

            if (cJSON_IsString(status) && strcmp(status->valuestring, "generating") == 0) {
                 // 优先显示服务器下发的动态消息（包含省略号动画），如果没有则使用本地默认格式
                 int p_val = (progress && cJSON_IsNumber(progress)) ? progress->valueint : 0;
                 std::string msg_str;
                 if (cJSON_IsString(msg) && strlen(msg->valuestring) > 0) {
                     msg_str = msg->valuestring;
                     // 如果消息里没有百分号且进度有效，可以补在这个字符串后面，或者直接信任服务器消息
                     // 这里选择直接显示服务器消息，以此支持服务器端的任意动画文本
                 } else {
                     char buf[32];
                     snprintf(buf, sizeof(buf), "正在绘图 %d%%", p_val);
                     msg_str = buf;
                 }

                 Schedule([this, display, m = msg_str]() {
                    display->SetChatMessage("system", m.c_str());
                 });
            } else if (cJSON_IsString(status) && strcmp(status->valuestring, "completed") == 0) {
                 // 绘图完成
                 // 这里不需要做太多，因为 connection.py 会通过 image_url 推送过来？如果不推送，至少界面要提示完成
                 Schedule([this, display]() {
                    display->SetChatMessage("system", "绘图完成，正在下载...");
                 });
            } else if (cJSON_IsString(msg)) {
                 Schedule([this, display, m = std::string(msg->valuestring)]() {
                    display->SetChatMessage("system", m.c_str());
                 });
            }
        } else if (strcmp(type->valuestring, "vision_result") == 0) {
            // [Added] 处理明确的 vision_result 信号，解决相机工具超时问题
            auto text = cJSON_GetObjectItem(root, "text");
            if (cJSON_IsString(text)) {
                ESP_LOGI(TAG, "Received vision_result signal, length=%d", (int)strlen(text->valuestring));
                auto camera = Board::GetInstance().GetCamera();
                if (camera) {
                    camera->SubmitResult(std::string(text->valuestring));
                }
            }
        } else if (strcmp(type->valuestring, "image_display") == 0 || strcmp(type->valuestring, "display_image") == 0) {
            if (awaiting_student_id_) { return; }
            // Tolerant parsing for multiple shapes
            auto encoding = cJSON_GetObjectItem(root, "encoding");
            auto data_str = cJSON_GetObjectItem(root, "data");
            auto data_url = cJSON_GetObjectItem(root, "data_url");
            auto url = cJSON_GetObjectItem(root, "url");
            auto image_url = cJSON_GetObjectItem(root, "image_url"); // object with { url: "..." }
            auto content = cJSON_GetObjectItem(root, "content");     // array items with type/image_url

            auto show_from_base64 = [this, display](const char* b64) {
                if (!b64 || !*b64) return;
                // Strip data URL prefix if present
                const char* p = strstr(b64, ";base64,");
                const unsigned char* input = (const unsigned char*)(p ? (p + 8) : b64);
                size_t input_len = strlen((const char*)input);
                size_t out_len = 0;
                int ret = mbedtls_base64_decode(nullptr, 0, &out_len, input, input_len);
                if ((ret == MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL || ret == 0) && out_len > 0) {
                    uint8_t* buf = (uint8_t*)heap_caps_malloc(out_len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
                    if (!buf) buf = (uint8_t*)heap_caps_malloc(out_len, MALLOC_CAP_8BIT);
                    if (buf) {
                        size_t actual = 0;
                        if (mbedtls_base64_decode(buf, out_len, &actual, input, input_len) == 0 && actual > 0) {
                            Schedule([this, display, buf, actual]() {
                                display->ShowImageFromBuffer(buf, actual);
                            });
                        } else {
                            heap_caps_free(buf);
                            Schedule([display]() { display->ShowMessageButton("图片解码失败", 3000); });
                        }
                    } else {
                        Schedule([display]() { display->ShowMessageButton("图片内存不足", 3000); });
                    }
                } else {
                    Schedule([display]() { display->ShowMessageButton("图片格式错误", 3000); });
                }
            };

            auto download_and_show = [this, display](const char* url_cstr) {
                if (!url_cstr) return;
                std::string url_s(url_cstr);
                Schedule([this, display, url = std::move(url_s)]() {
                    display->ShowMessageButton("图片下载中...", 1500);
                    esp_http_client_config_t cfg = {};
                    cfg.url = url.c_str();
                    cfg.timeout_ms = 15000;
                    esp_http_client_handle_t client = esp_http_client_init(&cfg);
                    if (!client) { display->ShowMessageButton("图片下载失败(初始化)", 3000); return; }
                    if (esp_http_client_open(client, 0) != ESP_OK) {
                        display->ShowMessageButton("图片下载失败(连接)", 3000);
                        esp_http_client_cleanup(client);
                        return;
                    }
                    int content_length = esp_http_client_fetch_headers(client);
                    if (content_length <= 0) content_length = 300*1024;
                    std::vector<uint8_t> data; data.reserve(std::min(content_length, 600*1024));
                    uint8_t tmp[2048]; int read_total = 0;
                    while (true) {
                        int r = esp_http_client_read(client, (char*)tmp, sizeof(tmp));
                        if (r <= 0) {
                            break;
                        }
                        data.insert(data.end(), tmp, tmp + r);
                        read_total += r;
                        if (read_total > 1024 * 1024) {
                            break;
                        }
                    }
                    esp_http_client_close(client); esp_http_client_cleanup(client);
                    if (!data.empty()) {
                        uint8_t* buf = (uint8_t*)heap_caps_malloc(data.size(), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
                        if (!buf) buf = (uint8_t*)heap_caps_malloc(data.size(), MALLOC_CAP_8BIT);
                        if (buf) { memcpy(buf, data.data(), data.size()); display->ShowImageFromBuffer(buf, data.size()); }
                        else { display->ShowMessageButton("图片内存不足", 3000); }
                    } else {
                        display->ShowMessageButton("图片为空", 3000);
                    }
                });
            };

            bool handled = false;
            // 1) explicit base64
            if (cJSON_IsString(encoding) && strcmp(encoding->valuestring, "base64") == 0 && cJSON_IsString(data_str)) {
                show_from_base64(data_str->valuestring); handled = true;
            }
            // 1.1) data is an object with nested fields (e.g. { image: <base64>, format: "base64" | encoding: "base64" | url | data_url | image_url })
            if (!handled && cJSON_IsObject(data_str)) {
                auto n_image = cJSON_GetObjectItem(data_str, "image");
                auto n_format = cJSON_GetObjectItem(data_str, "format");
                auto n_encoding = cJSON_GetObjectItem(data_str, "encoding");
                auto n_url = cJSON_GetObjectItem(data_str, "url");
                auto n_data_url = cJSON_GetObjectItem(data_str, "data_url");
                auto n_image_url = cJSON_GetObjectItem(data_str, "image_url");
                if (cJSON_IsString(n_image)) {
                    // Prefer explicit base64 hint but still try to decode if missing
                    if ((cJSON_IsString(n_format) && strcmp(n_format->valuestring, "base64") == 0) ||
                        (cJSON_IsString(n_encoding) && strcmp(n_encoding->valuestring, "base64") == 0) ||
                        true) {
                        show_from_base64(n_image->valuestring);
                        handled = true;
                    }
                } else if (cJSON_IsString(n_data_url)) {
                    show_from_base64(n_data_url->valuestring); handled = true;
                } else if (cJSON_IsString(n_url)) {
                    download_and_show(n_url->valuestring); handled = true;
                } else if (cJSON_IsObject(n_image_url)) {
                    auto u = cJSON_GetObjectItem(n_image_url, "url");
                    if (cJSON_IsString(u)) { download_and_show(u->valuestring); handled = true; }
                }
            }
            // 2) data_url field
            if (!handled && cJSON_IsString(data_url)) { show_from_base64(data_url->valuestring); handled = true; }
            // 3) plain data string (try detect data: prefix or assume base64)
            if (!handled && cJSON_IsString(data_str)) { show_from_base64(data_str->valuestring); handled = true; }
            // 4) direct url
            if (!handled && cJSON_IsString(url)) { download_and_show(url->valuestring); handled = true; }
            // 5) image_url object
            if (!handled && cJSON_IsObject(image_url)) {
                auto url2 = cJSON_GetObjectItem(image_url, "url");
                if (cJSON_IsString(url2)) { download_and_show(url2->valuestring); handled = true; }
            }
            // 6) content array (OpenAI style)
            if (!handled && cJSON_IsArray(content)) {
                cJSON* item = nullptr;
                cJSON_ArrayForEach(item, content) {
                    if (cJSON_IsObject(item)) {
                        auto itype = cJSON_GetObjectItem(item, "type");
                        if (cJSON_IsString(itype) && strcmp(itype->valuestring, "image") == 0) {
                            auto iurl = cJSON_GetObjectItem(item, "url");
                            auto idata = cJSON_GetObjectItem(item, "data");
                            auto iencoding = cJSON_GetObjectItem(item, "encoding");
                            auto iimage_url = cJSON_GetObjectItem(item, "image_url");
                            if (cJSON_IsString(iurl)) { download_and_show(iurl->valuestring); handled = true; break; }
                            if (cJSON_IsObject(iimage_url)) {
                                auto u = cJSON_GetObjectItem(iimage_url, "url");
                                if (cJSON_IsString(u)) { download_and_show(u->valuestring); handled = true; break; }
                            }
                            if (cJSON_IsString(iencoding) && strcmp(iencoding->valuestring, "base64") == 0 && cJSON_IsString(idata)) {
                                show_from_base64(idata->valuestring); handled = true; break; }
                            if (cJSON_IsString(idata)) { show_from_base64(idata->valuestring); handled = true; break; }
                        }
                    }
                }
            }

            if (!handled) {
                char* dump = cJSON_PrintUnformatted(root);
                ESP_LOGW(TAG, "Invalid image_display payload: %s", dump ? dump : "<null>");
                if (dump) cJSON_free(dump);
            }
        } else if (strcmp(type->valuestring, "system") == 0) {
            if (awaiting_student_id_) { return; }
            auto command = cJSON_GetObjectItem(root, "command");
            if (cJSON_IsString(command)) {
                ESP_LOGI(TAG, "System command: %s", command->valuestring);
                if (strcmp(command->valuestring, "reboot") == 0) {
                    // Do a reboot if user requests a OTA update
                    Schedule([this]() {
                        Reboot();
                    });
                } else {
                    ESP_LOGW(TAG, "Unknown system command: %s", command->valuestring);
                }
            }
        } else if (strcmp(type->valuestring, "alert") == 0) {
            auto status = cJSON_GetObjectItem(root, "status");
            auto message = cJSON_GetObjectItem(root, "message");
            auto emotion = cJSON_GetObjectItem(root, "emotion");
            if (cJSON_IsString(status) && cJSON_IsString(message) && cJSON_IsString(emotion)) {
                Alert(status->valuestring, message->valuestring, emotion->valuestring, Lang::Sounds::P3_VIBRATION);
            } else {
                ESP_LOGW(TAG, "Alert command requires status, message and emotion");
            }
#if CONFIG_RECEIVE_CUSTOM_MESSAGE
        } else if (strcmp(type->valuestring, "custom") == 0) {
            auto payload = cJSON_GetObjectItem(root, "payload");
            ESP_LOGI(TAG, "Received custom message: %s", cJSON_PrintUnformatted(root));
            if (cJSON_IsObject(payload)) {
                Schedule([this, display, payload_str = std::string(cJSON_PrintUnformatted(payload))]() {
                    display->SetChatMessage("system", payload_str.c_str());
                });
            } else {
                ESP_LOGW(TAG, "Invalid custom message format: missing payload");
            }
#endif
        } else {
            ESP_LOGW(TAG, "Unknown message type: %s", type->valuestring);
        }
    });
    bool protocol_started = protocol_->Start();

    SetDeviceState(kDeviceStateIdle);

    // 学号：每次启动强制采集一次，确保后续对话都绑定当次学号
    {
        Settings nvs("app", false);
        // 仍然读出现有值，但我们将以本次口述为准覆盖
        student_id_ = nvs.GetString("student_id", "");
    }
    // 若存在历史学号，先显示；随后仍清空并提示重新采集
    if (!student_id_.empty()) {
        display->SetStudentId(student_id_.c_str());
    } else {
        display->SetStudentId("");
    }
    // 清空当前会话中的学号并提示采集（本次会话以新口述为准）
    student_id_.clear();
    MaybePromptStudentId();

    has_server_time_ = ota.HasServerTime();
    if (protocol_started) {
        std::string message = std::string(Lang::Strings::VERSION) + ota.GetCurrentVersion();
        display->ShowNotification(message.c_str());
        display->SetChatMessage("system", "");
        // Play the success sound to indicate the device is ready
        audio_service_.PlaySound(Lang::Sounds::P3_SUCCESS);
    }

    // Print heap stats
    SystemInfo::PrintHeapStats();
}

void Application::OnClockTimer() {
    clock_ticks_++;

    auto display = Board::GetInstance().GetDisplay();
    display->UpdateStatusBar();

    // Print the debug info every 10 seconds
    if (clock_ticks_ % 10 == 0) {
        // SystemInfo::PrintTaskCpuUsage(pdMS_TO_TICKS(1000));
        // SystemInfo::PrintTaskList();
        SystemInfo::PrintHeapStats();
    }
}

// Add a async task to MainLoop
void Application::Schedule(std::function<void()> callback) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        main_tasks_.push_back(std::move(callback));
    }
    xEventGroupSetBits(event_group_, MAIN_EVENT_SCHEDULE);
}

// The Main Event Loop controls the chat state and websocket connection
// If other tasks need to access the websocket or chat state,
// they should use Schedule to call this function
void Application::MainEventLoop() {
    // Raise the priority of the main event loop to avoid being interrupted by background tasks (which has priority 2)
    vTaskPrioritySet(NULL, 3);

    while (true) {
        auto bits = xEventGroupWaitBits(event_group_, MAIN_EVENT_SCHEDULE |
            MAIN_EVENT_SEND_AUDIO |
            MAIN_EVENT_WAKE_WORD_DETECTED |
            MAIN_EVENT_VAD_CHANGE |
            MAIN_EVENT_ERROR, pdTRUE, pdFALSE, portMAX_DELAY);
        if (bits & MAIN_EVENT_ERROR) {
            SetDeviceState(kDeviceStateIdle);
            Alert(Lang::Strings::ERROR, last_error_message_.c_str(), "sad", Lang::Sounds::P3_EXCLAMATION);
        }

        if (bits & MAIN_EVENT_SEND_AUDIO) {
            while (auto packet = audio_service_.PopPacketFromSendQueue()) {
                if (!protocol_->SendAudio(std::move(packet))) {
                    break;
                }
            }
        }

        if (bits & MAIN_EVENT_WAKE_WORD_DETECTED) {
            OnWakeWordDetected();
        }

        if (bits & MAIN_EVENT_VAD_CHANGE) {
            if (device_state_ == kDeviceStateListening) {
                auto led = Board::GetInstance().GetLed();
                led->OnStateChanged();
            }
        }

        if (bits & MAIN_EVENT_SCHEDULE) {
            std::unique_lock<std::mutex> lock(mutex_);
            auto tasks = std::move(main_tasks_);
            lock.unlock();
            for (auto& task : tasks) {
                task();
            }
        }
    }
}

void Application::OnWakeWordDetected() {
    if (!protocol_) {
        return;
    }

    if (device_state_ == kDeviceStateIdle) {
        audio_service_.EncodeWakeWord();

        if (!protocol_->IsAudioChannelOpened()) {
            SetDeviceState(kDeviceStateConnecting);
            if (!protocol_->OpenAudioChannel()) {
                audio_service_.EnableWakeWordDetection(true);
                return;
            }
        }

        auto wake_word = audio_service_.GetLastWakeWord();
        ESP_LOGI(TAG, "Wake word detected: %s", wake_word.c_str());
#if CONFIG_USE_AFE_WAKE_WORD || CONFIG_USE_CUSTOM_WAKE_WORD
        // Encode and send the wake word data to the server
        while (auto packet = audio_service_.PopWakeWordPacket()) {
            protocol_->SendAudio(std::move(packet));
        }
        // Set the chat state to wake word detected
        protocol_->SendWakeWordDetected(wake_word);
    // 唤醒词进入聆听也统一改为“手动停止”，避免自动停导致的录音过短
    SetListeningMode(kListeningModeManualStop);
#else
    SetListeningMode(kListeningModeManualStop);
        // Play the pop up sound to indicate the wake word is detected
        audio_service_.PlaySound(Lang::Sounds::P3_POPUP);
#endif
    } else if (device_state_ == kDeviceStateSpeaking) {
        AbortSpeaking(kAbortReasonWakeWordDetected);
    } else if (device_state_ == kDeviceStateActivating) {
        SetDeviceState(kDeviceStateIdle);
    }
}

void Application::AbortSpeaking(AbortReason reason) {
    ESP_LOGI(TAG, "Abort speaking");
    aborted_ = true;
    protocol_->SendAbortSpeaking(reason);
}

void Application::SetListeningMode(ListeningMode mode) {
    listening_mode_ = mode;
    SetDeviceState(kDeviceStateListening);
}

void Application::SetDeviceState(DeviceState state) {
    if (device_state_ == state) {
        return;
    }
    
    clock_ticks_ = 0;
    auto previous_state = device_state_;
    device_state_ = state;
    ESP_LOGI(TAG, "STATE: %s", STATE_STRINGS[device_state_]);

    // Send the state change event
    DeviceStateEventManager::GetInstance().PostStateChangeEvent(previous_state, state);

    auto& board = Board::GetInstance();
    auto display = board.GetDisplay();
    auto led = board.GetLed();
    led->OnStateChanged();
    
    // 当从idle状态变成其他任何状态时，停止音乐播放
    if (previous_state == kDeviceStateIdle && state != kDeviceStateIdle) {
        auto music = board.GetMusic();
        if (music) {
            ESP_LOGI(TAG, "Stopping music streaming due to state change: %s -> %s", 
                    STATE_STRINGS[previous_state], STATE_STRINGS[state]);
            music->StopStreaming();
        }
    }
    
    switch (state) {
        case kDeviceStateUnknown:
        case kDeviceStateIdle:
            display->SetStatus(Lang::Strings::STANDBY);
            display->SetEmotion("neutral");
            // 若已获得学号，则结束等待学号阶段
            if (awaiting_student_id_ && !student_id_.empty()) {
                awaiting_student_id_ = false;
            }
            audio_service_.EnableVoiceProcessing(false);
            audio_service_.EnableWakeWordDetection(true);
            // 离开聆听：停止监听上限定时器
            if (listening_timer_handle_) {
                esp_timer_stop(listening_timer_handle_);
            }
            break;
        case kDeviceStateConnecting:
            display->SetStatus(Lang::Strings::CONNECTING);
            display->SetEmotion("neutral");
            display->SetChatMessage("system", "");
            break;
        case kDeviceStateListening:
            display->SetStatus(Lang::Strings::LISTENING);
            display->SetEmotion("neutral");

            // Make sure the audio processor is running
            if (!audio_service_.IsAudioProcessorRunning()) {
                // 始终发送 StartListening 以获取 STT；下行在等待学号阶段已被屏蔽
                protocol_->SendStartListening(listening_mode_);
                audio_service_.EnableVoiceProcessing(true);
                audio_service_.EnableWakeWordDetection(false);
            }
            // 进入聆听：为手动/自动停模式启动兜底时长，避免“录音太短”
            if (listening_mode_ != kListeningModeRealtime && listening_timer_handle_) {
                esp_timer_stop(listening_timer_handle_);
                esp_timer_start_once(listening_timer_handle_, (uint64_t)listening_timeout_ms_ * 1000);
            }
            break;
        case kDeviceStateSpeaking:
            display->SetStatus(Lang::Strings::SPEAKING);

            if (listening_mode_ != kListeningModeRealtime) {
                audio_service_.EnableVoiceProcessing(false);
                // Only AFE wake word can be detected in speaking mode
#if CONFIG_USE_AFE_WAKE_WORD
                audio_service_.EnableWakeWordDetection(true);
#else
                audio_service_.EnableWakeWordDetection(false);
#endif
            }
            audio_service_.ResetDecoder();
            // 离开聆听：停止监听上限定时器
            if (listening_timer_handle_) {
                esp_timer_stop(listening_timer_handle_);
            }
            break;
        default:
            // Do nothing
            break;
    }
}

void Application::OnListeningTimer() {
    // 超时兜底：若仍处于Listening，则主动发送停止并回到Idle
    if (device_state_ == kDeviceStateListening) {
        ESP_LOGI(TAG, "Listening timeout reached (%d ms), stopping...", listening_timeout_ms_);
        if (protocol_) {
            protocol_->SendStopListening();
        }
        SetDeviceState(kDeviceStateIdle);
    }
}

void Application::Reboot() {
    ESP_LOGI(TAG, "Rebooting...");
    esp_restart();
}

void Application::WakeWordInvoke(const std::string& wake_word) {
    if (device_state_ == kDeviceStateIdle) {
        ToggleChatState();
        Schedule([this, wake_word]() {
            if (protocol_) {
                protocol_->SendWakeWordDetected(wake_word); 
            }
        }); 
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonNone);
        });
    } else if (device_state_ == kDeviceStateListening) {   
        Schedule([this]() {
            if (protocol_) {
                protocol_->CloseAudioChannel();
            }
        });
    }
}

bool Application::CanEnterSleepMode() {
    if (device_state_ != kDeviceStateIdle) {
        return false;
    }

    if (protocol_ && protocol_->IsAudioChannelOpened()) {
        return false;
    }

    if (!audio_service_.IsIdle()) {
        return false;
    }

    // Now it is safe to enter sleep mode
    return true;
}

void Application::SendMcpMessage(const std::string& payload) {
    Schedule([this, payload]() {
        if (protocol_) {
            protocol_->SendMcpMessage(payload);
        }
    });
}

void Application::SetAecMode(AecMode mode) {
    aec_mode_ = mode;
    Schedule([this]() {
        auto& board = Board::GetInstance();
        auto display = board.GetDisplay();
        switch (aec_mode_) {
        case kAecOff:
            audio_service_.EnableDeviceAec(false);
            display->ShowNotification(Lang::Strings::RTC_MODE_OFF);
            break;
        case kAecOnServerSide:
            audio_service_.EnableDeviceAec(false);
            display->ShowNotification(Lang::Strings::RTC_MODE_ON);
            break;
        case kAecOnDeviceSide:
            audio_service_.EnableDeviceAec(true);
            display->ShowNotification(Lang::Strings::RTC_MODE_ON);
            break;
        }

        // If the AEC mode is changed, close the audio channel
        if (protocol_ && protocol_->IsAudioChannelOpened()) {
            protocol_->CloseAudioChannel();
        }
    });
}

// 新增：接收外部音频数据（如音乐播放）
void Application::AddAudioData(AudioStreamPacket&& packet) {
    auto codec = Board::GetInstance().GetAudioCodec();
    if (device_state_ == kDeviceStateIdle && codec->output_enabled()) {
        // packet.payload包含的是原始PCM数据（int16_t）
        if (packet.payload.size() >= 2) {
            size_t num_samples = packet.payload.size() / sizeof(int16_t);
            std::vector<int16_t> pcm_data(num_samples);
            memcpy(pcm_data.data(), packet.payload.data(), packet.payload.size());
            
            // 检查采样率是否匹配，如果不匹配则进行简单重采样
            if (packet.sample_rate != codec->output_sample_rate()) {
                // ESP_LOGI(TAG, "Resampling music audio from %d to %d Hz", 
                //         packet.sample_rate, codec->output_sample_rate());
                
                // 验证采样率参数
                if (packet.sample_rate <= 0 || codec->output_sample_rate() <= 0) {
                    ESP_LOGE(TAG, "Invalid sample rates: %d -> %d", 
                            packet.sample_rate, codec->output_sample_rate());
                    return;
                }
                
                std::vector<int16_t> resampled;
                
                if (packet.sample_rate > codec->output_sample_rate()) {
                    ESP_LOGI(TAG, "音乐播放：将采样率从 %d Hz 切换到 %d Hz", 
                        codec->output_sample_rate(), packet.sample_rate);

                    // 尝试动态切换采样率
                    if (codec->SetOutputSampleRate(packet.sample_rate)) {
                        ESP_LOGI(TAG, "成功切换到音乐播放采样率: %d Hz", packet.sample_rate);
                    } else {
                        ESP_LOGW(TAG, "无法切换采样率，继续使用当前采样率: %d Hz", codec->output_sample_rate());
                    }
                } else {
                    // 上采样：线性插值
                    float upsample_ratio = codec->output_sample_rate() / static_cast<float>(packet.sample_rate);
                    size_t expected_size = static_cast<size_t>(pcm_data.size() * upsample_ratio + 0.5f);
                    resampled.reserve(expected_size);
                    
                    for (size_t i = 0; i < pcm_data.size(); ++i) {
                        // 添加原始样本
                        resampled.push_back(pcm_data[i]);
                        
                        // 计算需要插值的样本数
                        int interpolation_count = static_cast<int>(upsample_ratio) - 1;
                        if (interpolation_count > 0 && i + 1 < pcm_data.size()) {
                            int16_t current = pcm_data[i];
                            int16_t next = pcm_data[i + 1];
                            for (int j = 1; j <= interpolation_count; ++j) {
                                float t = static_cast<float>(j) / (interpolation_count + 1);
                                int16_t interpolated = static_cast<int16_t>(current + (next - current) * t);
                                resampled.push_back(interpolated);
                            }
                        } else if (interpolation_count > 0) {
                            // 最后一个样本，直接重复
                            for (int j = 1; j <= interpolation_count; ++j) {
                                resampled.push_back(pcm_data[i]);
                            }
                        }
                    }
                    
                    ESP_LOGI(TAG, "Upsampled %d -> %d samples (ratio: %.2f)", 
                            pcm_data.size(), resampled.size(), upsample_ratio);
                }
                
                pcm_data = std::move(resampled);
            }
            
            // 确保音频输出已启用
            if (!codec->output_enabled()) {
                codec->EnableOutput(true);
            }
            
            // 发送PCM数据到音频编解码器
            codec->OutputData(pcm_data);
            
            audio_service_.UpdateOutputTimestamp();
        }
    }
}

void Application::PlaySound(const std::string_view& sound) {
    audio_service_.PlaySound(sound);
}