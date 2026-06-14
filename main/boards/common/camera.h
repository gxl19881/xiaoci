#ifndef CAMERA_H
#define CAMERA_H

#include <string>

class Camera {
public:
    virtual void SetExplainUrl(const std::string& url, const std::string& token) = 0;
    virtual bool Capture() = 0;
    virtual bool SetHMirror(bool enabled) = 0;
    virtual bool SetVFlip(bool enabled) = 0;
    virtual std::string Explain(const std::string& question) = 0;

    // 预览交互接口（默认实现为空操作，保持向后兼容）
    // timeout_ms: 超时毫秒；fps: 预览帧率
    // 默认直接返回 true 表示“已确认”，这样旧派生类不需要修改
    virtual bool PreviewAndWaitConfirm(int /*timeout_ms*/, int /*fps*/) { return true; }
    virtual bool IsPreviewActive() const { return false; }
    virtual void RequestPreviewConfirm() {}
    virtual void RequestPreviewCancel() {}

    // 强制重置状态，用于在“A tool is already running”时强制释放忙碌状态
    virtual void ForceResetStatus() {}

    // 多图缓存与合并分析接口
    virtual bool CacheCurrentFrame() { return false; }
    virtual void ClearCachedPhotos() {}
    virtual std::string ExplainCached(const std::string& question) { return "{\"success\": false, \"message\": \"Not implemented\"}"; }

    // External result injection (e.g. from WebSocket)
    virtual void SubmitResult(const std::string& result) {}
};

#endif // CAMERA_H
