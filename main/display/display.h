#ifndef DISPLAY_H
#define DISPLAY_H

#include <lvgl.h>
#include <esp_timer.h>
#include <esp_log.h>
#include <esp_pm.h>

#include <string>
#include <chrono>

struct DisplayFonts {
    const lv_font_t* text_font = nullptr;
    const lv_font_t* icon_font = nullptr;
    const lv_font_t* emoji_font = nullptr;
};

class Display {
public:
    Display();
    virtual ~Display();

    virtual void SetStatus(const char* status);
    virtual void ShowNotification(const char* notification, int duration_ms = 3000);
    virtual void ShowNotification(const std::string &notification, int duration_ms = 3000);
    virtual void SetEmotion(const char* emotion);
    virtual void SetChatMessage(const char* role, const char* content);
    virtual void SetMusicInfo(const char* song_name);
    virtual void SetIcon(const char* icon);
    virtual void SetPreviewImage(const lv_img_dsc_t* image);
    // Add an image to the chat history
    virtual void AddChatImage(const lv_img_dsc_t* image) {}
    // Show encoded image from a memory buffer (e.g. JPEG/GIF/PNG in RAM)
    // Default implementation is no-op; boards with LCD can override.
    // The buffer must remain valid while the image is displayed.
    virtual void ShowImageFromBuffer(const void* data, size_t size) {}
    virtual void SetTheme(const std::string& theme_name);
    virtual std::string GetTheme() { return current_theme_name_; }
    virtual void UpdateStatusBar(bool update_all = false);
    virtual void SetPowerSaveMode(bool on);

    // 在状态栏常驻显示学号，例如："学号: 18302"；传入空字符串则清空
    virtual void SetStudentId(const char* student_id);

    inline int width() const { return width_; }
    inline int height() const { return height_; }
    virtual    void ShowMessageButton(const char* text, int duration_ms);
    virtual void ShowMessageButton(std::string text, int duration_ms);
    // 新增：隐藏消息按钮（用于摄像头预览结束时清理提示）
    virtual void HideMessageButton();

    // 历史浏览/翻页：在聊天区域中向上/向下翻页，或回到最新消息
    // 默认空实现，由具体显示类（如 LcdDisplay）覆盖
    virtual void ScrollHistoryPageUp() {}
    virtual void ScrollHistoryPageDown() {}
    virtual void ScrollToLatest() {}
    // 暂停/恢复自动滚动（收到新消息时是否自动滚动到底部）
    virtual void PauseAutoScrollMs(int ms) {}
 
protected:
    int width_ = 0;
    int height_ = 0;
    
    esp_pm_lock_handle_t pm_lock_ = nullptr;
    lv_display_t *display_ = nullptr;

    lv_obj_t *emotion_label_ = nullptr;
    lv_obj_t *network_label_ = nullptr;
    lv_obj_t *status_label_ = nullptr;
    lv_obj_t *notification_label_ = nullptr;
    lv_obj_t *mute_label_ = nullptr;
    lv_obj_t *battery_label_ = nullptr;
    lv_obj_t *student_id_label_ = nullptr; // 新增：学号常驻标签
    lv_obj_t* chat_message_label_ = nullptr;
    lv_obj_t* low_battery_popup_ = nullptr;
    lv_obj_t* low_battery_label_ = nullptr;
    
    const char* battery_icon_ = nullptr;
    const char* network_icon_ = nullptr;
    bool muted_ = false;
    std::string current_theme_name_;

    std::chrono::system_clock::time_point last_status_update_time_;
    esp_timer_handle_t notification_timer_ = nullptr;

    friend class DisplayLockGuard;
    virtual bool Lock(int timeout_ms = 0) = 0;
    virtual void Unlock() = 0;

        // 消息按钮相关
    lv_obj_t* message_button_container_;  // 按钮容器
    lv_obj_t* message_button_label_;     // 按钮上的文本标签
    esp_timer_handle_t message_button_timer_;
    lv_anim_t message_button_show_anim_;
    lv_anim_t message_button_hide_anim_;

    // 历史浏览状态
    bool autoscroll_paused_ = false;
    esp_timer_handle_t autoscroll_resume_timer_ = nullptr;
};


class DisplayLockGuard {
public:
    DisplayLockGuard(Display *display) : display_(display) {
        if (!display_->Lock(30000)) {
            ESP_LOGE("Display", "Failed to lock display");
        }
    }
    ~DisplayLockGuard() {
        display_->Unlock();
    }

private:
    Display *display_;
};

class NoDisplay : public Display {
private:
    virtual bool Lock(int timeout_ms = 0) override {
        return true;
    }
    virtual void Unlock() override {}
};

#endif
