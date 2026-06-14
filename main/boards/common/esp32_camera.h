#ifndef ESP32_CAMERA_H
#define ESP32_CAMERA_H

#include <esp_camera.h>
#include <lvgl.h>
#include <thread>
#include <memory>
#include <vector>
#include <string>
#include <mutex>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include "camera.h"

struct JpegChunk {
    uint8_t* data;
    size_t len;
};

class Esp32Camera : public Camera {
private:
    camera_fb_t* fb_ = nullptr;
    lv_img_dsc_t preview_image_;
    std::string explain_url_;
    std::string explain_token_;
    std::thread encoder_thread_;
    // 预览交互状态
    volatile bool preview_active_ = false;
    volatile bool preview_confirmed_ = false;
    volatile bool preview_canceled_ = false;
    size_t preview_capacity_ = 0; // 已分配 buffer 容量（字节）

    // 多图缓存
    std::vector<camera_fb_t*> cached_fbs_;

    void EnsurePreviewBuffer(int w, int h);
    bool SetFrameSize(framesize_t fs);
    std::string UploadJpegChunks(const std::vector<JpegChunk>& chunks, const std::string& question);

public:
    Esp32Camera(const camera_config_t& config);
    ~Esp32Camera();

    virtual void SetExplainUrl(const std::string& url, const std::string& token);
    virtual bool Capture();
    // 翻转控制函数
    virtual bool SetHMirror(bool enabled) override;
    virtual bool SetVFlip(bool enabled) override;
    virtual std::string Explain(const std::string& question);

    // 多图缓存与合并分析
    virtual bool CacheCurrentFrame() override;
    virtual void ClearCachedPhotos() override;
    virtual std::string ExplainCached(const std::string& question) override;

    // 预览 + 按键确认/取消
    // timeout_ms：超时自动确认（>0），fps：预览刷新帧率（建议 8~12）
    bool PreviewAndWaitConfirm(int timeout_ms, int fps);
    bool IsPreviewActive() const { return preview_active_; }
    void RequestPreviewConfirm() { if (preview_active_) preview_confirmed_ = true; }
    void RequestPreviewCancel() { if (preview_active_) preview_canceled_ = true; }

    virtual void ForceResetStatus() override;

    // External result injection (thread-safe)
    virtual void SubmitResult(const std::string& result) override;

private:
    std::mutex result_mutex_;
    std::string pending_result_;
    volatile bool has_pending_result_ = false;
};

#endif // ESP32_CAMERA_H