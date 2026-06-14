以下是完整的代码修改，包括头文件和实现文件：

头文件修改 (display.h)
```cpp


#pragma once

#include <string>
#include <chrono>
#include "esp_log.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "lvgl.h"

class Display {
public:
    Display();
    ~Display();

    // 显示消息按钮
    void ShowMessageButton(const char* text, int duration_ms);
    void ShowMessageButton(std::string text, int duration_ms);

private:
    // 消息按钮相关
    lv_obj_t* message_button_container_;  // 按钮容器
    lv_obj_t* message_button_label_;     // 按钮上的文本标签
    esp_timer_handle_t message_button_timer_;
    lv_anim_t message_button_show_anim_;
    lv_anim_t message_button_hide_anim_;

    // 其他现有成员变量和方法...
};
实现文件修改 (display.cc)
cpp


#include <esp_log.h>
#include <esp_err.h>
#include <string>
#include <cstdlib>
#include <cstring>

#include "display.h"
#include "board.h"
#include "application.h"
#include "font_awesome_symbols.h"
#include "audio_codec.h"
#include "settings.h"
#include "assets/lang_config.h"

#define TAG "Display"

Display::Display() {
    // 初始化消息按钮相关成员变量
    message_button_container_ = nullptr;
    message_button_label_ = nullptr;
    message_button_timer_ = nullptr;

    // 创建消息按钮容器
    message_button_container_ = lv_btn_create(lv_scr_act());
    lv_obj_set_size(message_button_container_, LV_SIZE_CONTENT, LV_SIZE_CONTENT);  // 自适应大小
    lv_obj_align(message_button_container_, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_add_flag(message_button_container_, LV_OBJ_FLAG_HIDDEN);

    // 设置玻璃态效果
    lv_obj_set_style_bg_opa(message_button_container_, LV_OPA_70, 0);  // 半透明背景
    lv_obj_set_style_bg_color(message_button_container_, lv_color_hex(0x888888), 0);  // 灰色背景
    lv_obj_set_style_border_width(message_button_container_, 0, 0);  // 无边框
    lv_obj_set_style_shadow_width(message_button_container_, 20, 0);  // 添加阴影
    lv_obj_set_style_shadow_opa(message_button_container_, LV_OPA_50, 0);  // 半透明阴影
    lv_obj_set_style_shadow_color(message_button_container_, lv_color_hex(0x000000), 0);  // 黑色阴影
    lv_obj_set_style_radius(message_button_container_, 10, 0);  // 圆角

    // 创建消息按钮标签
    message_button_label_ = lv_label_create(message_button_container_);
    lv_obj_set_style_text_color(message_button_label_, lv_color_hex(0xFFFFFF), 0);  // 白色文字
    lv_obj_set_style_text_font(message_button_label_, &lv_font_montserrat_24, 0);  // 设置字体大小
    lv_obj_align(message_button_label_, LV_ALIGN_CENTER, 0, 0);  // 文字居中

    // 初始化显示动画
    lv_anim_init(&message_button_show_anim_);
    message_button_show_anim_.var = message_button_container_;
    message_button_show_anim_.exec_cb = (lv_anim_exec_xcb_t)lv_obj_set_y;
    message_button_show_anim_.path_cb = &lv_anim_path_ease_out;
    message_button_show_anim_.ready_cb = nullptr;
    message_button_show_anim_.time = 300;  // 动画持续时间300ms

    // 初始化隐藏动画
    lv_anim_init(&message_button_hide_anim_);
    message_button_hide_anim_.var = message_button_container_;
    message_button_hide_anim_.exec_cb = (lv_anim_exec_xcb_t)lv_obj_set_y;
    message_button_hide_anim_.path_cb = &lv_anim_path_ease_in;
    message_button_hide_anim_.ready_cb = nullptr;
    message_button_hide_anim_.time = 300;  // 动画持续时间300ms

    // 创建消息按钮定时器
    esp_timer_create_args_t message_button_timer_args = {
        .callback = [](void *arg) {
            Display *display = static_cast<Display*>(arg);
            DisplayLockGuard lock(display);
            
            // 启动隐藏动画
            lv_anim_start(&display->message_button_hide_anim_);
            
            // 在动画结束后隐藏按钮容器
            lv_timer_t *timer = lv_timer_create([](lv_timer_t *t) {
                Display *disp = static_cast<Display*>(t->user_data);
                lv_obj_add_flag(disp->message_button_container_, LV_OBJ_FLAG_HIDDEN);
                lv_timer_del(t);
            }, display->message_button_hide_anim_.time, display);
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "message_button_timer",
        .skip_unhandled_events = false,
    };
    ESP_ERROR_CHECK(esp_timer_create(&message_button_timer_args, &message_button_timer_));

    // 创建一个电源管理锁
    auto ret = esp_pm_lock_create(ESP_PM_APB_FREQ_MAX, 0, "display_update", &pm_lock_);
    if (ret == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "Power management not supported");
    } else {
        ESP_ERROR_CHECK(ret);
    }
}

Display::~Display() {
    // 清理消息按钮相关资源
    if (message_button_timer_ != nullptr) {
        esp_timer_stop(message_button_timer_);
        esp_timer_delete(message_button_timer_);
    }

    if (message_button_container_ != nullptr) {
        lv_obj_del(message_button_container_);
    }

    if (notification_timer_ != nullptr) {
        esp_timer_stop(notification_timer_);
        esp_timer_delete(notification_timer_);
    }

    if (network_label_ != nullptr) {
        lv_obj_del(network_label_);
        lv_obj_del(notification_label_);
        lv_obj_del(status_label_);
        lv_obj_del(mute_label_);
        lv_obj_del(battery_label_);
        lv_obj_del(emotion_label_);
    }
    if( low_battery_popup_ != nullptr ) {
        lv_obj_del(low_battery_popup_);
    }
    if (pm_lock_ != nullptr) {
        esp_pm_lock_delete(pm_lock_);
    }
}

void Display::ShowMessageButton(const char* text, int duration_ms) {
    DisplayLockGuard lock(this);
    if (message_button_container_ == nullptr || message_button_label_ == nullptr) {
        return;
    }
    
    // 设置消息按钮文本
    lv_label_set_text(message_button_label_, text);
    
    // 获取屏幕高度
    lv_coord_t screen_height = lv_disp_get_ver_res(NULL);
    lv_coord_t container_height = lv_obj_get_height(message_button_container_);
    
    // 设置初始位置（屏幕外底部）
    lv_obj_set_y(message_button_container_, screen_height);
    lv_obj_clear_flag(message_button_container_, LV_OBJ_FLAG_HIDDEN);
    
    // 设置显示动画的起始和结束值
    message_button_show_anim_.start_value = screen_height;
    message_button_show_anim_.end_value = screen_height - container_height - 20;  // 留出20像素的边距
    
    // 启动显示动画
    lv_anim_start(&message_button_show_anim_);
    
    // 停止之前的定时器
    esp_timer_stop(message_button_timer_);
    
    // 设置隐藏动画
    message_button_hide_anim_.start_value = screen_height - container_height - 20;
    message_button_hide_anim_.end_value = screen_height;
    
    // 启动定时器，在指定时间后触发隐藏动画
    ESP_ERROR_CHECK(esp_timer_start_once(message_button_timer_, duration_ms * 1000));
}

void Display::ShowMessageButton(std::string text, int duration_ms) {
    // 直接调用const char*版本的重载函数
    ShowMessageButton(text.c_str(), duration_ms);
}

// 其他现有方法保持不变...
这些修改实现了：

创建了一个具有玻璃态效果的消息按钮容器
在容器上添加了自适应大小的文本标签
实现了从底部弹出和退出的动画效果
添加了定时自动消失功能
提供了两个重载版本的ShowMessageButton方法
保持了资源的正确管理
使用示例：

cpp


display.ShowMessageButton("Hello World", 3000);  // 使用const char*版本
std::string message = "Hello World";
display.ShowMessageButton(message, 3000);  // 使用std::string版本