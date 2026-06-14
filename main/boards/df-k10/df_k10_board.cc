#include "wifi_board.h"
#include "k10_audio_codec.h"
#include "display/lcd_display.h"
#include "esp_lcd_ili9341.h"
#include "led_control.h"
#include "font_awesome_symbols.h"
#include "application.h"
#include "button.h"
#include "config.h"
// #include "iot/thing_manager.h"
#include "esp32_camera.h"
#include "display.h"

#include "led/circular_strip.h"
#include "assets/lang_config.h"

#include <esp_log.h>
#include <esp_lcd_panel_vendor.h>
#include <driver/i2c_master.h>
#include <driver/spi_common.h>
#include <wifi_station.h>
#include "aht20.h"
#include "sc7a20h.h"
#include "ltr3xx_sensor.h"
#include "McpComplex.h"
// JPEG decoder (from esp_jpeg_simd component)
// Prefer the new esp_new_jpeg decoder API; include it explicitly to avoid picking the legacy SIMD header
#include "../../../managed_components/espressif__esp_new_jpeg/include/esp_jpeg_dec.h"
#include "esp_spiffs.h"
#include <stdio.h>
#include <sys/stat.h>
#include <errno.h>

// #include "pilot_bb.h"
#include "lvgl.h"
// #include <math.h>
#include "spectrum_visualizer.h"

#include "esp_io_expander_tca95xx_16bit.h"
#include "esp_timer.h"
#include <string.h>
#include "esp_rom_sys.h" // for esp_rom_delay_us

#define TAG "DF-K10"

LV_FONT_DECLARE(font_puhui_20_4);
LV_FONT_DECLARE(font_awesome_20_4);

LV_FONT_DECLARE(font_puhui_14_1);
LV_FONT_DECLARE(font_awesome_14_1);
LV_FONT_DECLARE(font_puhui_16_4);
LV_FONT_DECLARE(font_awesome_16_4);

void DrawRandomTriangles(lv_obj_t *parent)
{
    // 定义10种不同的颜色
    lv_color_t triangle_colors[10] = {
        lv_color_hex(0xFF6B6B), // 红色
        lv_color_hex(0x4ECDC4), // 青色
        lv_color_hex(0x45B7D1), // 蓝色
        lv_color_hex(0x96CEB4), // 绿色
        lv_color_hex(0xFECEA8), // 橙色
        lv_color_hex(0xDDA0DD), // 紫色
        lv_color_hex(0xF0E68C), // 黄色
        lv_color_hex(0xFFB6C1), // 粉色
        lv_color_hex(0x87CEEB), // 天蓝色
        lv_color_hex(0xDEB887)  // 米色
    };

    // 绘制10个随机位置的三角形
    for (int i = 0; i < 10; i++) {
        lv_obj_t *triangle = lv_obj_create(parent);
        
        // 设置三角形的样式
        static lv_style_t triangle_style[10];
        lv_style_init(&triangle_style[i]);
        lv_style_set_bg_opa(&triangle_style[i], LV_OPA_70);            // 设置透明度
        lv_style_set_bg_color(&triangle_style[i], triangle_colors[i]); // 设置不同的颜色
        lv_obj_add_style(triangle, &triangle_style[i], 0);
        
        // 移除边框和圆角
        lv_obj_set_style_border_width(triangle, 0, 0);
        lv_obj_set_style_radius(triangle, 0, 0);

        // 随机大小 (在屏幕高度的1/8到1/4之间)
        int size = LV_VER_RES / 8 + rand() % (LV_VER_RES / 8);

        // 随机位置 (确保三角形完全在屏幕内)
        int x = rand() % (LV_HOR_RES - size);
        int y = rand() % (LV_VER_RES - size);

        // 设置位置和大小
        lv_obj_set_size(triangle, size, size);
        lv_obj_set_pos(triangle, x, y);

        // 使用LVGL的clip_corner属性创建三角形效果
        lv_obj_set_style_clip_corner(triangle, true, 0);
        
        // 随机旋转角度
        int random_angle = rand() % 3600; // LVGL中角度以0.1度为单位
        lv_obj_set_style_transform_angle(triangle, random_angle, 0);
    }
}

struct ChatImageResource {
    lv_img_dsc_t dsc;
    void* data;
};

static void chat_image_delete_cb(lv_event_t * e) {
    ChatImageResource* res = (ChatImageResource*)lv_event_get_user_data(e);
    if (res) {
        if (res->data) {
            heap_caps_free(res->data);
        }
        heap_caps_free(res);
        ESP_LOGI("DF-K10", "Freed chat image resource");
    }
}

class CustomLcdDisplay : public SpiLcdDisplay
{

private:
    lv_obj_t *time_label_ = nullptr;
    lv_style_t style_user;
    lv_style_t style_assistant;
    std::vector<lv_obj_t *> labelContainer; // 存储 label 指针的容器
    lv_anim_t anim[4];
    lv_anim_t anim_m[3];
    lv_anim_t message_button_slide_anim_;      // 添加滑动动画
    lv_anim_t message_button_slide_hide_anim_; // 添加滑动隐藏动画
    // 实时摄像头预览相关
    lv_obj_t *live_preview_img_ = nullptr;        // 持续复用的 LVGL image 对象
    lv_img_dsc_t live_preview_dsc_{};             // 指向摄像头预览缓冲的描述符（不复制数据）
    bool live_preview_initialized_ = false;       // 是否已初始化描述符
    // 生成图片（非预览）临时展示对象与定时器：15 秒后自动移除
    lv_obj_t *transient_img_ = nullptr;
    esp_timer_handle_t transient_img_timer_ = nullptr;

    void RemoveOldestLabel()
    {
        if (!labelContainer.empty())
        {
            lv_obj_t *oldestLabel = labelContainer.front();
            labelContainer.erase(labelContainer.begin()); // 从容器中移除最早的 label 指针

            lv_obj_t *label = lv_obj_get_child(oldestLabel, 0);
            lv_obj_del(label);
            lv_obj_del(oldestLabel); // 删除 lvgl 对象
        }
    }

public:
    virtual void ShowImageFromBuffer(const void *data, size_t size);
    // 覆盖翻页/历史浏览接口，DF-K10 自定义样式独立实现
    virtual void ScrollHistoryPageUp() override;
    virtual void ScrollHistoryPageDown() override;
    virtual void ScrollToLatest() override;
    virtual void PauseAutoScrollMs(int ms) override;
    // SetPreviewImage 在类内已直接定义实现（实时预览覆盖）
    CustomLcdDisplay(esp_lcd_panel_io_handle_t io_handle,
                     esp_lcd_panel_handle_t panel_handle,
                     int width,
                     int height,
                     int offset_x,
                     int offset_y,
                     bool mirror_x,
                     bool mirror_y,
                     bool swap_xy)
        : SpiLcdDisplay(io_handle, panel_handle,
                        width, height, offset_x, offset_y, mirror_x, mirror_y, swap_xy,
                        {
                            .text_font = &font_puhui_16_4,
                            .emoji_font = font_emoji_32_init(),
                        })
    {
        // DisplayLockGuard lock(this);
        // lv_obj_set_style_pad_left(status_bar_, LV_HOR_RES * 0.1, 0);
        // lv_obj_set_style_pad_right(status_bar_, LV_HOR_RES * 0.1, 0);
        SetupUI();
    }
    static void set_width(void *var, int32_t v)
    {
        lv_obj_set_width((lv_obj_t *)var, v);
    }

    static void set_height(void *var, int32_t v)
    {
        lv_obj_set_height((lv_obj_t *)var, v);
    }
    void set_message_button_text(std::string text)
    {
        lv_label_set_text(message_button_label_, text.c_str());
    }

    virtual void SetupUI()
    {
        DisplayLockGuard lock(this);

        ESP_LOGI(TAG, "Custom_SetupUI");

        auto screen = lv_disp_get_scr_act(lv_disp_get_default());
        lv_obj_set_style_text_font(screen, &font_puhui_16_4, 0);
        // lv_obj_set_style_text_color(screen, lv_color_white(), 0);

        /* Container */
        container_ = lv_obj_create(screen);
        lv_obj_set_size(container_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_flex_flow(container_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_all(container_, 0, 0);
        lv_obj_set_style_border_width(container_, 0, 0);
        lv_obj_set_style_pad_row(container_, 0, 0);

        /* Status bar */
        status_bar_ = lv_obj_create(container_);
        lv_obj_set_size(status_bar_, LV_HOR_RES, 48);
        lv_obj_set_style_radius(status_bar_, 0, 0);

        /* Status bar */
        lv_obj_set_style_pad_all(status_bar_, 0, 0);
        lv_obj_set_style_border_width(status_bar_, 0, 0);
        lv_obj_set_style_pad_column(status_bar_, 4, 0);

        /* Content */
        content_ = lv_obj_create(container_);
    lv_obj_set_scrollbar_mode(content_, LV_SCROLLBAR_MODE_ACTIVE);
    // 显式启用纵向滚动，避免在某些布局下滚动方向未开启导致无法翻页
    lv_obj_set_scroll_dir(content_, LV_DIR_VER);
        lv_obj_set_style_radius(content_, 0, 0);
        lv_obj_set_width(content_, LV_HOR_RES);
        lv_obj_set_flex_grow(content_, 1);
        // DrawRandomTriangles(content_);

        /* Content */
        lv_obj_set_flex_flow(content_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(content_, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_set_style_pad_all(content_, 0, 0);
        lv_obj_set_style_border_width(content_, 0, 0);

        // 历史浏览自动恢复定时器（与通用实现保持一致）
        if (autoscroll_resume_timer_ == nullptr) {
            esp_timer_create_args_t targs = {};
            targs.callback = [](void* arg){
                // 通过派生类指针访问受保护成员，符合 C++ 受保护访问规则
                auto self = static_cast<CustomLcdDisplay*>(arg);
                self->autoscroll_paused_ = false;
            };
            targs.arg = this;
            targs.dispatch_method = ESP_TIMER_TASK;
            targs.name = "autoscroll_resume";
            esp_timer_create(&targs, &autoscroll_resume_timer_);
        }

        network_label_ = lv_label_create(status_bar_);
        lv_label_set_text(network_label_, "");
        lv_obj_set_style_text_font(network_label_, &font_awesome_16_4, 0);
        lv_obj_align_to(network_label_, status_bar_, LV_ALIGN_LEFT_MID, 20, 0);
        lv_obj_add_flag(network_label_, LV_OBJ_FLAG_HIDDEN);

        // lv_obj_t* wave_ = create_spectrum(status_bar_);
        lv_obj_t *wave_ = SpectrumVisualizer::create(status_bar_);
        lv_obj_align(wave_, LV_ALIGN_LEFT_MID, -10, 0);

        notification_label_ = lv_label_create(status_bar_);
        lv_obj_set_flex_grow(notification_label_, 1);
        lv_obj_set_style_text_align(notification_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_text(notification_label_, "通知");
        lv_obj_add_flag(notification_label_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_center(notification_label_);

        status_label_ = lv_label_create(status_bar_);
        lv_obj_set_flex_grow(status_label_, 1);
        lv_label_set_text(status_label_, "正在初始化");
        lv_obj_set_style_text_align(status_label_, LV_TEXT_ALIGN_CENTER, 0);
        // lv_obj_set_style_text_color(status_label_, lv_color_make(0, 255, 0), 0);
        lv_obj_center(status_label_);

    // 学号常驻标签（右侧小号文字，过长截断）
    student_id_label_ = lv_label_create(status_bar_);
    lv_obj_set_style_text_font(student_id_label_, &font_puhui_14_1, 0);
    lv_label_set_long_mode(student_id_label_, LV_LABEL_LONG_CLIP);
    lv_obj_set_width(student_id_label_, 90);
    lv_label_set_text(student_id_label_, "");
    // 先隐藏，等待 SetStudentId() 赋值时再显示
    lv_obj_add_flag(student_id_label_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_align_to(student_id_label_, status_bar_, LV_ALIGN_RIGHT_MID, -6, 10);

        emotion_label_ = lv_label_create(status_bar_);
        lv_obj_set_style_text_font(emotion_label_, &font_awesome_16_4, 0);
        lv_label_set_text(emotion_label_, FONT_AWESOME_AI_CHIP);
        lv_obj_align_to(emotion_label_, status_bar_, LV_ALIGN_RIGHT_MID, -20, -6);

        mute_label_ = lv_label_create(status_bar_);
        lv_label_set_text(mute_label_, "");
        lv_obj_set_style_text_font(mute_label_, &font_awesome_16_4, 0);

    // 学号标签：放在状态栏右下角，较小字号，过长自动省略
    student_id_label_ = lv_label_create(status_bar_);
    lv_obj_set_style_text_font(student_id_label_, &font_puhui_14_1, 0);
    lv_label_set_long_mode(student_id_label_, LV_LABEL_LONG_CLIP);
    lv_obj_set_width(student_id_label_, LV_HOR_RES / 3); // 右侧预留 1/3 宽度
    lv_obj_align_to(student_id_label_, status_bar_, LV_ALIGN_RIGHT_MID, -6, 10);
    lv_label_set_text(student_id_label_, "");
    lv_obj_add_flag(student_id_label_, LV_OBJ_FLAG_HIDDEN);

        // battery_label_ = lv_label_create(status_bar_);
        // lv_label_set_text(battery_label_, "");
        // lv_obj_set_style_text_font(battery_label_, &font_awesome_16_4, 0);
        // lv_obj_align_to(battery_label_, status_bar_, LV_ALIGN_RIGHT_MID, -40, 0);

        // 初始化聊天框的风格
        // lv_style_init(&style_user);
        // lv_style_set_radius(&style_user, 5);
        // lv_style_set_bg_opa(&style_user, LV_OPA_COVER);
        // lv_style_set_border_width(&style_user, 2);
        // lv_style_set_border_color(&style_user, lv_color_hex(0));
        // lv_style_set_pad_all(&style_user, 10);

        // lv_style_set_text_color(&style_user, lv_color_hex(0xffffff));
        // lv_style_set_bg_color(&style_user, lv_color_hex(0x00B050));

        // lv_style_init(&style_assistant);
        // lv_style_set_radius(&style_assistant, 5);
        // lv_style_set_bg_opa(&style_assistant, LV_OPA_COVER);
        // lv_style_set_border_width(&style_assistant, 2);
        // lv_style_set_border_color(&style_assistant, lv_color_hex(0));
        // lv_style_set_pad_all(&style_assistant, 10);
        //---------------------------------------------------------------
        // 初始化聊天框的风格
        lv_style_init(&style_user);
        lv_style_set_radius(&style_user, 3);         // 增加圆角半径
        lv_style_set_bg_opa(&style_user, LV_OPA_90); // 增加不透明度
        lv_style_set_border_width(&style_user, 0);   // 移除边框
        lv_style_set_pad_all(&style_user, 10);
        lv_style_set_text_color(&style_user, lv_color_hex(0xffffff));
        lv_style_set_bg_color(&style_user, lv_color_hex(0x00B050)); // 绿色背景
        // lv_style_set_bg_grad_color(&style_user, lv_color_hex(0x00B050)); // 更深的蓝色
        // lv_style_set_bg_grad_dir(&style_user, LV_GRAD_DIR_HOR);          // 垂直渐变

        // 添加阴影效果
        lv_style_set_shadow_width(&style_user, 10);
        lv_style_set_shadow_opa(&style_user, LV_OPA_50);
        lv_style_set_shadow_color(&style_user, lv_color_hex(0x000000));
        lv_style_set_shadow_ofs_x(&style_user, -2);
        lv_style_set_shadow_ofs_y(&style_user, 2);

        lv_style_init(&style_assistant);
        lv_style_set_radius(&style_assistant, 3);         // 增加圆角半径
        lv_style_set_bg_opa(&style_assistant, LV_OPA_90); // 增加不透明度
        lv_style_set_border_width(&style_assistant, 0);   // 移除边框
        lv_style_set_pad_all(&style_assistant, 10);
        lv_style_set_text_color(&style_assistant, lv_color_hex(0x000000));
        lv_style_set_bg_color(&style_assistant, lv_color_hex(0xFFD1DC)); // 粉色背景

        // 添加阴影效果
        lv_style_set_shadow_width(&style_assistant, 10);
        lv_style_set_shadow_opa(&style_assistant, LV_OPA_50);
        lv_style_set_shadow_color(&style_assistant, lv_color_hex(0x000000));
        lv_style_set_shadow_ofs_x(&style_assistant, 2);
        lv_style_set_shadow_ofs_y(&style_assistant, 2);
        //---------------------------------------------------------------
        // lv_style_set_text_color(&style_assistant, lv_color_hex(0));
        // lv_style_set_bg_color(&style_assistant, lv_color_hex(0xE0E0E0));
        // lv_style_set_bg_color(&style_assistant, lv_color_hex(0xE0E0E0));
        // lv_style_set_bg_color(&style_assistant, lv_color_hex(0xFFD1DC));

        // 创建消息按钮容器
        message_button_container_ = lv_btn_create(lv_scr_act());
        lv_obj_set_size(message_button_container_, LV_SIZE_CONTENT, LV_SIZE_CONTENT); // 自适应大小
        // lv_obj_align(message_button_container_, LV_ALIGN_BOTTOM_MID, 0, -5);
        lv_obj_align(message_button_container_, LV_ALIGN_TOP_MID, 0, 50);
        lv_obj_add_flag(message_button_container_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(message_button_container_, LV_OBJ_FLAG_FLOATING); // 添加浮动标志

        // 设置玻璃态效果
        lv_obj_set_style_bg_opa(message_button_container_, LV_OPA_80, 0);                    // 半透明背景
        lv_obj_set_style_bg_color(message_button_container_, lv_color_hex(0x87CEEB), 0);     // 灰色背景
        lv_obj_set_style_border_width(message_button_container_, 0, 0);                      // 无边框
        lv_obj_set_style_shadow_width(message_button_container_, 20, 0);                     // 添加阴影
        lv_obj_set_style_shadow_opa(message_button_container_, LV_OPA_50, 0);                // 半透明阴影
        lv_obj_set_style_shadow_color(message_button_container_, lv_color_hex(0x000000), 0); // 黑色阴影
        lv_obj_set_style_radius(message_button_container_, 5, 0);                            // 圆角

        // 创建消息按钮标签
        message_button_label_ = lv_label_create(message_button_container_);
        lv_obj_set_style_text_color(message_button_label_, lv_color_hex(0x000000), 0); // 白色文字
        lv_obj_set_style_text_font(message_button_label_, &font_puhui_20_4, 0);        // 设置字体大小
        lv_label_set_text(message_button_label_, "数据更新中");
        lv_obj_align(message_button_label_, LV_ALIGN_CENTER, 0, 0); // 文字居中

        // 初始化显示动画
        lv_anim_init(&message_button_show_anim_);
        message_button_show_anim_.var = message_button_container_;
        message_button_show_anim_.exec_cb = (lv_anim_exec_xcb_t)lv_obj_set_style_opa;
        message_button_show_anim_.path_cb = &lv_anim_path_ease_out;
        message_button_show_anim_.start_cb = nullptr;
        message_button_show_anim_.act_time = 500;                                    // 动画持续时间300ms
        lv_anim_set_values(&message_button_show_anim_, LV_OPA_TRANSP, LV_OPA_COVER); // 从透明到不透明

        // 初始化隐藏动画
        lv_anim_init(&message_button_hide_anim_);
        message_button_hide_anim_.var = message_button_container_;
        message_button_hide_anim_.exec_cb = (lv_anim_exec_xcb_t)lv_obj_set_style_opa;
        message_button_hide_anim_.path_cb = &lv_anim_path_ease_in;
        message_button_hide_anim_.start_cb = nullptr;
        message_button_hide_anim_.act_time = 500;                                    // 动画持续时间300ms
        lv_anim_set_values(&message_button_hide_anim_, LV_OPA_COVER, LV_OPA_TRANSP); // 从不透明到透明

        // 初始化显示动画2 - 位移
        // lv_anim_init(&message_button_slide_anim_);
        // message_button_slide_anim_.var = message_button_container_;
        // message_button_slide_anim_.exec_cb = (lv_anim_exec_xcb_t)lv_obj_set_y;
        // message_button_slide_anim_.path_cb = &lv_anim_path_overshoot; // 使用过冲效果
        // message_button_slide_anim_.start_cb = nullptr;
        // message_button_slide_anim_.act_time = 500; // 稍微延长动画时间以更好地展示过冲效果

        lv_anim_init(&message_button_slide_anim_);
        lv_anim_set_var(&message_button_slide_anim_, message_button_container_);
        lv_anim_set_early_apply(&message_button_slide_anim_, true);
        lv_anim_set_path_cb(&message_button_slide_anim_, lv_anim_path_overshoot);
        lv_anim_set_time(&message_button_slide_anim_, 500);
        lv_anim_set_values(&message_button_slide_anim_, 0, lv_obj_get_height(message_button_label_));
        lv_anim_set_exec_cb(&message_button_slide_anim_, (lv_anim_exec_xcb_t)set_height);
        // lv_anim_start(&anim[2]);

        // 生成图片自动隐藏定时器
        if (transient_img_timer_ == nullptr) {
            esp_timer_create_args_t targs = {};
            targs.callback = [](void* arg){
                auto self = static_cast<CustomLcdDisplay*>(arg);
                DisplayLockGuard guard(self);
                if (self->transient_img_) {
                    lv_obj_del(self->transient_img_);
                    self->transient_img_ = nullptr;
                }
            };
            targs.arg = this;
            targs.dispatch_method = ESP_TIMER_TASK;
            targs.name = "gen_img_hide";
            esp_timer_create(&targs, &transient_img_timer_);
        }

        DisplayLockGuard unlock(this);
    }

    virtual void SetPreviewImage(const lv_img_dsc_t *image) override
    {
        DisplayLockGuard lock(this);
        static uint32_t last_log_ms = 0; // 限频日志
        static uint32_t call_count = 0;
        call_count++;
        uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000ULL);
        if (image == nullptr || image->data == nullptr) {
            // 隐藏
            if (live_preview_img_) {
                lv_obj_add_flag(live_preview_img_, LV_OBJ_FLAG_HIDDEN);
            }
            if (now_ms - last_log_ms > 500) {
                ESP_LOGI(TAG, "PreviewImage hide call=%lu", (unsigned long)call_count);
                last_log_ms = now_ms;
            }
            return;
        }

        if (!live_preview_img_) {
            // 创建一个悬浮在最上层的 image 对象（不放入 chat 内容流）
            live_preview_img_ = lv_image_create(lv_scr_act());
            lv_obj_add_flag(live_preview_img_, LV_OBJ_FLAG_FLOATING);
            // 半透明背景遮罩（可选）
            // lv_obj_set_style_bg_opa(live_preview_img_, LV_OPA_50, 0);
        }

        // 使用传入的描述符（零拷贝）: 需要构造一个临时描述符指向同一 data
        live_preview_dsc_.header = image->header;
        live_preview_dsc_.data_size = image->data_size;
        live_preview_dsc_.data = image->data; // 不复制，摄像头循环里会不断覆盖

        lv_image_set_src(live_preview_img_, &live_preview_dsc_);

        // 计算缩放：让预览尽量占宽度 90%（保持比例）
        lv_coord_t target_w = LV_HOR_RES * 90 / 100;
        if (live_preview_dsc_.header.w > 0) {
            uint32_t zoom = (uint32_t)target_w * 256 / live_preview_dsc_.header.w;
            if (zoom > 256) zoom = 256; // 不放大超过 1:1
            if (zoom == 0) zoom = 1;
            lv_image_set_scale(live_preview_img_, zoom);
        }

        // 居中放置（在上方留出状态栏 48px）
        lv_obj_align(live_preview_img_, LV_ALIGN_TOP_MID, 0, 52);
        lv_obj_clear_flag(live_preview_img_, LV_OBJ_FLAG_HIDDEN);
        // 确保在最顶层
        lv_obj_move_foreground(live_preview_img_);
        // 强制重绘
        lv_obj_invalidate(live_preview_img_);

        if (now_ms - last_log_ms > 500) {
            ESP_LOGI(TAG, "PreviewImage show call=%lu w=%d h=%d data=%p zoomed=%d%% heap_free=%u", (unsigned long)call_count,
                     (int)live_preview_dsc_.header.w, (int)live_preview_dsc_.header.h, live_preview_dsc_.data,
                     (int)(live_preview_img_ ? (int)lv_image_get_scale(live_preview_img_)*100/256 : -1),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
            last_log_ms = now_ms;
        }
    }

    virtual void SetChatMessage(const char *role, const char *content) override
    {
        ESP_LOGI(TAG, "SET CHAT MESSAGE");
        if (content != nullptr && *content == '\0')
            return;

        std::stringstream ss;
        ss << "role: " << role << ", content: " << content << std::endl;
        std::string logMessage = ss.str();

        // auto& board = static_cast<waveshare_amoled_1_8&>(Board::GetInstance());
        // auto sdcard = board.GetSdcard();
        // sdcard->Write("/sdcard/log.txt", logMessage.c_str());

        DisplayLockGuard lock(this);

        // 动态检查内存，如果不足则清理旧消息
        size_t min_free_internal = 1536;
        if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < min_free_internal) {
             while (!labelContainer.empty() && heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < min_free_internal) {
                RemoveOldestLabel();
            }
        }

        // 限制历史记录数量，防止内存溢出
        // 降低上限到 2，配合动态内存检查
        while (labelContainer.size() >= 20)
        {
            RemoveOldestLabel();
        }

        // [Anti-Flooding] 如果上一条由于是系统状态消息（如"正在生成..."），尝试原地更新
        if (strcmp(role, "system") == 0 && !labelContainer.empty()) {
            lv_obj_t* last_container = labelContainer.back();
            if (last_container != nullptr && lv_obj_get_child_cnt(last_container) > 0) {
                lv_obj_t* last_label = lv_obj_get_child(last_container, 0);
                if (last_label != nullptr) {
                    const char* last_text = lv_label_get_text(last_label);
                    if (last_text && content) {
                        bool last_generating = (strstr(last_text, "正在生成") != nullptr || strstr(last_text, "绘图") != nullptr || strstr(last_text, "正在识别") != nullptr);
                        bool curr_generating = (strstr(content, "正在生成") != nullptr || strstr(content, "绘图") != nullptr || strstr(content, "正在识别") != nullptr);
                        
                        // 如果两者都是生成状态消息，则视为同一事件流，原地刷新
                        if (last_generating && curr_generating) {
                            lv_label_set_text(last_label, content);
                            
                            // 关键修复：重置宽度为自动计算，否则之前的固定宽度会导致新文本被截断或不显示
                            lv_obj_set_width(last_label, LV_SIZE_CONTENT);
                            
                            // 强制更新布局以获取新尺寸
                            lv_obj_update_layout(last_label);
                            
                            // 检查最大宽度限制
                            if (lv_obj_get_width(last_label) >= (LV_HOR_RES - 2)) {
                                lv_obj_set_width(last_label, (LV_HOR_RES - 2));
                            }
                            
                            // 保持居中样式
                            lv_obj_set_style_text_align(last_label, LV_TEXT_ALIGN_CENTER, 0); 
                            
                            // 强制重绘
                            lv_obj_invalidate(last_label);
                            
                            // 避免后续新建逻辑
                            ESP_LOGI(TAG, "Update existing bubble text: %s", content);
                            return;
                        }
                    }
                }
            }
        }

        lv_obj_t *container = lv_obj_create(content_);
        lv_obj_set_scrollbar_mode(container, LV_SCROLLBAR_MODE_OFF);
        lv_obj_set_style_radius(container, 0, 0);
        lv_obj_set_style_border_width(container, 0, 0);
        // lv_obj_set_width(container, LV_SIZE_CONTENT);
        lv_obj_set_width(container, LV_HOR_RES);
        lv_obj_set_style_pad_all(container, 0, 0);
        // DrawRandomTriangles(container);

        lv_obj_t *label = lv_label_create(container);
        lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
        lv_label_set_text(label, content);
        if (strcmp(role, "user") == 0)
        {
            lv_obj_add_style(label, &style_user, 0);
            lv_obj_align(label, LV_ALIGN_RIGHT_MID, -2, 0);
            lv_obj_align(container, LV_ALIGN_RIGHT_MID, 0, 0);
        }
        else if (strcmp(role, "system") == 0)
        {
            lv_obj_add_style(label, &style_assistant, 0);
            lv_obj_align(label, LV_ALIGN_CENTER, 0, 0);
        }
        else
        {
            lv_obj_add_style(label, &style_assistant, 0);
            lv_obj_align(label, LV_ALIGN_LEFT_MID, 2, 0);
            // lv_obj_align(container, LV_ALIGN_LEFT_MID, 0, 0);
        }
        
        // [Font Logic] Check for generating messages to apply smaller font
        // Using 14pt font as 12pt is not currently declared/available
        bool is_generating_msg = (strcmp(role, "system") == 0 && (strstr(content, "正在生成") != nullptr || strstr(content, "绘图") != nullptr || strstr(content, "正在识别") != nullptr));

        if (is_generating_msg || (strcmp(role, "system") == 0 && (strcmp(content, "图片正在生成中，请耐心等待……") == 0 || strcmp(content, "照片正在识别中，请耐心等待……") == 0))) {
            lv_obj_set_style_text_font(label, &font_puhui_14_1, 0);
            lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
        } else {
            lv_obj_set_style_text_font(label, &font_puhui_16_4, 0);
        }

        lv_obj_set_style_pad_all(label, 5, LV_PART_MAIN);

        lv_obj_update_layout(label);
        ESP_LOGI(TAG, "Label Width: %ld-%ld", lv_obj_get_width(label), (LV_HOR_RES - 2));
        if (lv_obj_get_width(label) >= (LV_HOR_RES - 2))
            lv_obj_set_width(label, (LV_HOR_RES - 2));
        // 仅当未暂停自动滚动时，自动滚动到底部以显示新消息
        if (!autoscroll_paused_) {
            lv_obj_scroll_to_view(container, LV_ANIM_ON);
        }

        for (size_t i = 0; i < 2; i++)
        {
            lv_anim_init(&anim[i]);
            lv_anim_set_var(&anim[i], label);
            lv_anim_set_early_apply(&anim[i], false);
            lv_anim_set_path_cb(&anim[i], lv_anim_path_overshoot);
            lv_anim_set_time(&anim[i], 300);
            lv_anim_set_delay(&anim[i], 200);
        }
        lv_anim_set_values(&anim[0], 0, lv_obj_get_width(label));
        lv_anim_set_exec_cb(&anim[0], (lv_anim_exec_xcb_t)set_width);
        lv_anim_start(&anim[0]);

        lv_anim_set_values(&anim[1], 0, lv_obj_get_height(label));
        lv_anim_set_exec_cb(&anim[1], (lv_anim_exec_xcb_t)set_height);
        lv_anim_start(&anim[1]);

        lv_obj_set_width(label, 0);
        lv_obj_set_height(label, 0);

        lv_anim_init(&anim[2]);
        lv_anim_set_var(&anim[2], container);
        lv_anim_set_early_apply(&anim[2], true);
        lv_anim_set_path_cb(&anim[2], lv_anim_path_overshoot);
        lv_anim_set_time(&anim[2], 200);
        lv_anim_set_values(&anim[2], 0, lv_obj_get_height(label));
        lv_anim_set_exec_cb(&anim[2], (lv_anim_exec_xcb_t)set_height);
        lv_anim_start(&anim[2]);

        // lv_anim_init(&anim[3]);
        // lv_anim_set_var(&anim[3], container);
        // lv_anim_set_early_apply(&anim[3], true);
        // lv_anim_set_path_cb(&anim[3], lv_anim_path_overshoot);
        // lv_anim_set_time(&anim[3], 200);
        // lv_anim_set_values(&anim[3], 0, lv_obj_get_width(label));

        // lv_anim_set_exec_cb(&anim[3], (lv_anim_exec_xcb_t)set_width);

        // lv_anim_start(&anim[3]);

        labelContainer.push_back(container); // 将新创建的 container 加入容器
    }

    virtual void AddChatImage(const lv_img_dsc_t* image) override
    {
        DisplayLockGuard lock(this);
        if (image == nullptr || image->data == nullptr) return;

        // 检查内部 RAM 是否充足，如果不足则不添加图片，优先保证系统稳定性
        // 降低阈值到 1.5KB，因为当前系统常态剩余 ~2KB，6KB 阈值会导致图片无法显示
        size_t min_free_internal = 1536;
        if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < min_free_internal) {
            ESP_LOGW(TAG, "Low internal RAM (%d), skipping chat image to prevent crash", 
                     (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
            // 尝试清理一些旧消息看看能不能腾出空间
            while (!labelContainer.empty() && heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < min_free_internal) {
                RemoveOldestLabel();
            }
            // 再次检查，如果还是不够，就放弃
            if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < min_free_internal) {
                return;
            }
        }

        while (labelContainer.size() >= 20) { // 统一历史记录上限到 20
            RemoveOldestLabel();
        }

        // Allocate resource
        ChatImageResource* res = (ChatImageResource*)heap_caps_malloc(sizeof(ChatImageResource), MALLOC_CAP_SPIRAM);
        if (!res) return;

        size_t data_size = image->data_size;
        res->data = heap_caps_malloc(data_size, MALLOC_CAP_SPIRAM);
        if (!res->data) {
            heap_caps_free(res);
            return;
        }
        memcpy(res->data, image->data, data_size);
        memcpy(&res->dsc, image, sizeof(lv_img_dsc_t));
        res->dsc.data = (const uint8_t*)res->data;

        // Create container
        lv_obj_t *container = lv_obj_create(content_);
        lv_obj_set_scrollbar_mode(container, LV_SCROLLBAR_MODE_OFF);
        lv_obj_set_style_radius(container, 0, 0);
        lv_obj_set_style_border_width(container, 0, 0);
        lv_obj_set_width(container, LV_HOR_RES);
        lv_obj_set_style_pad_all(container, 10, 0);
        lv_obj_set_flex_flow(container, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(container, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        // Create image object
        lv_obj_t *img = lv_image_create(container);
        lv_image_set_src(img, &res->dsc);
        
        if (res->dsc.header.w > 0) {
            int target_w = 200;
            int zoom = target_w * 256 / res->dsc.header.w;
            lv_image_set_scale(img, zoom);
        }
        
        lv_obj_set_style_radius(img, 5, 0);
        lv_obj_set_style_clip_corner(img, true, 0);

        // Add delete callback
        lv_obj_add_event_cb(img, chat_image_delete_cb, LV_EVENT_DELETE, res);

        labelContainer.push_back(container);
        
        if (!autoscroll_paused_) {
            lv_obj_scroll_to_view(container, LV_ANIM_ON);
        }
    }

    virtual void ShowMessageButton(const char *text, int duration_ms) override
    {
        DisplayLockGuard lock(this);
        if (message_button_container_ == nullptr || message_button_label_ == nullptr)
        {
            return;
        }

        lv_label_set_text(message_button_label_, text);

        // 设置初始透明度为0
        lv_obj_set_style_opa(message_button_container_, LV_OPA_TRANSP, 0);
        lv_obj_clear_flag(message_button_container_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(message_button_container_);

        // for (size_t i = 0; i < 2; i++)
        // {
        //     lv_anim_init(&anim_m[i]);
        //     lv_anim_set_var(&anim_m[i], message_button_label_);
        //     lv_anim_set_early_apply(&anim[i], false);
        //     lv_anim_set_path_cb(&anim_m[i], lv_anim_path_overshoot);
        //     lv_anim_set_time(&anim_m[i], 300);
        //     lv_anim_set_delay(&anim_m[i], 200);
        // }
        // lv_anim_set_values(&anim_m[0], 0, lv_obj_get_width(message_button_label_));
        // lv_anim_set_exec_cb(&anim_m[0], (lv_anim_exec_xcb_t)set_width);
        // lv_anim_start(&anim_m[0]);

        // lv_anim_set_values(&anim_m[1], 0, lv_obj_get_height(message_button_label_));
        // lv_anim_set_exec_cb(&anim_m[1], (lv_anim_exec_xcb_t)set_height);
        // lv_anim_start(&anim_m[1]);

        // lv_anim_init(&anim_m[2]);
        // lv_anim_set_var(&anim_m[2], message_button_container_);
        // lv_anim_set_early_apply(&anim_m[2], true);
        // lv_anim_set_path_cb(&anim_m[2], lv_anim_path_overshoot);
        // lv_anim_set_time(&anim_m[2], 200);
        // lv_anim_set_values(&anim_m[2], 0, lv_obj_get_height(message_button_label_));
        // lv_anim_set_exec_cb(&anim_m[2], (lv_anim_exec_xcb_t)set_height);
        // lv_anim_start(&anim_m[2]);

        //  for (size_t i = 0; i < 2; i++)
        // {
        //     lv_anim_init(&anim_m[i]);
        //     lv_anim_set_var(&anim_m[i], message_button_container_);
        //     lv_anim_set_early_apply(&anim[i], false);
        //     lv_anim_set_path_cb(&anim_m[i], lv_anim_path_overshoot);
        //     lv_anim_set_time(&anim_m[i], 300);
        //     lv_anim_set_delay(&anim_m[i], 200);
        // }
        // lv_anim_set_values(&anim_m[0], 0, lv_obj_get_width(message_button_label_));
        // lv_anim_set_exec_cb(&anim_m[0], (lv_anim_exec_xcb_t)set_width);
        // lv_anim_start(&anim_m[0]);

        // lv_anim_set_values(&anim_m[1], 0, lv_obj_get_height(message_button_label_));
        // lv_anim_set_exec_cb(&anim_m[1], (lv_anim_exec_xcb_t)set_height);
        // lv_anim_start(&anim_m[1]);
        // 启动显示动画（参数已在初始化时设置）
        lv_anim_start(&message_button_show_anim_);
        // 停止之前的定时器
        esp_timer_stop(message_button_timer_);

        // 启动定时器，在指定时间后触发隐藏动画
        ESP_ERROR_CHECK(esp_timer_start_once(message_button_timer_, duration_ms * 1000));
    }
};

void CustomLcdDisplay::ShowImageFromBuffer(const void *data, size_t size)
{
    DisplayLockGuard lock(this);

    // 直接使用输入数据进行解码，不再写入 SPIFFS
    // 使用 esp_new_jpeg 解码为 RGB565
    jpeg_dec_config_t cfg = {};
    cfg.output_type = JPEG_PIXEL_FORMAT_RGB565_LE; 
    cfg.scale.width = 0;
    cfg.scale.height = 0;
    cfg.clipper.width = 0;
    cfg.clipper.height = 0;
    cfg.rotate = JPEG_ROTATE_0D;
    cfg.block_enable = false;
    
    jpeg_dec_handle_t handle = nullptr;
    jpeg_error_t jret = jpeg_dec_open(&cfg, &handle);
    if (jret != JPEG_ERR_OK || handle == nullptr)
    {
        ESP_LOGE(TAG, "jpeg_dec_open failed: %d", (int)jret);
        ShowMessageButton("图片解码初始化失败", 3000);
        return;
    }

    jpeg_dec_io_t *io = (jpeg_dec_io_t *)calloc(1, sizeof(jpeg_dec_io_t));
    jpeg_dec_header_info_t *info = (jpeg_dec_header_info_t *)calloc(1, sizeof(jpeg_dec_header_info_t));
    if (!io || !info)
    {
        if (io) free(io);
        if (info) free(info);
        jpeg_dec_close(handle);
        ShowMessageButton("图片内存不足", 3000);
        return;
    }

    io->inbuf = (uint8_t *)data;
    io->inbuf_len = (int)size;
    
    int ret = jpeg_dec_parse_header(handle, io, info);
    if (ret != JPEG_ERR_OK || info->width <= 0 || info->height <= 0)
    {
        ESP_LOGE(TAG, "jpeg header parse failed: %d", ret);
        free(info);
        free(io);
        jpeg_dec_close(handle);
        ShowMessageButton("图片格式不支持", 3000);
        return;
    }

    ESP_LOGI(TAG, "JPEG header ok: %dx%d", info->width, info->height);

    int out_size = 0;
    ret = jpeg_dec_get_outbuf_len(handle, &out_size);
    if (ret != JPEG_ERR_OK || out_size <= 0)
    {
        free(info);
        free(io);
        jpeg_dec_close(handle);
        ShowMessageButton("图片尺寸获取失败", 3000);
        return;
    }
    
    uint8_t *out_buf = (uint8_t *)heap_caps_aligned_alloc(16, (size_t)out_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!out_buf)
        out_buf = (uint8_t *)heap_caps_aligned_alloc(16, (size_t)out_size, MALLOC_CAP_8BIT);
    if (!out_buf)
    {
        free(info);
        free(io);
        jpeg_dec_close(handle);
        ShowMessageButton("图片内存不足", 3000);
        return;
    }

    io->outbuf = out_buf;
    int consumed = io->inbuf_len - io->inbuf_remain;
    io->inbuf = ((uint8_t *)data) + consumed;
    io->inbuf_len = io->inbuf_remain;

    ret = jpeg_dec_process(handle, io);
    if (ret != JPEG_ERR_OK)
    {
        ESP_LOGE(TAG, "jpeg decode failed: %d", ret);
        heap_caps_free(out_buf);
        free(info);
        free(io);
        jpeg_dec_close(handle);
        ShowMessageButton("图片解码失败", 3000);
        return;
    }

    // 构造 LVGL 图像描述符
    lv_img_dsc_t *img_dsc = (lv_img_dsc_t *)heap_caps_malloc(sizeof(lv_img_dsc_t), MALLOC_CAP_8BIT);
    if (!img_dsc)
    {
        heap_caps_free(out_buf);
        free(info);
        free(io);
        jpeg_dec_close(handle);
        ShowMessageButton("图片内存不足", 3000);
        return;
    }
    memset(img_dsc, 0, sizeof(*img_dsc));
    img_dsc->header.w = info->width;
    img_dsc->header.h = info->height;
    img_dsc->header.cf = LV_COLOR_FORMAT_RGB565;
    img_dsc->data_size = (size_t)out_size;
    img_dsc->data = out_buf;

    // 提前释放 JPEG 解码资源，释放 Internal RAM，防止 AddChatImage 误判内存不足而清空历史
    free(info);
    free(io);
    jpeg_dec_close(handle);

    // 将图片添加到聊天记录中
    AddChatImage(img_dsc);

    // 清理内存 (AddChatImage 会复制数据)
    heap_caps_free(out_buf);
    heap_caps_free(img_dsc);
}

// ----------------------- 历史浏览与翻页实现 -----------------------
void CustomLcdDisplay::PauseAutoScrollMs(int ms) {
    autoscroll_paused_ = true;
    if (autoscroll_resume_timer_) {
        esp_timer_stop(autoscroll_resume_timer_);
        esp_timer_start_once(autoscroll_resume_timer_, (uint64_t)ms * 1000ULL);
    }
}

void CustomLcdDisplay::ScrollHistoryPageUp() {
    DisplayLockGuard lock(this);
    if (!content_) return;
    // 使用内容区域高度的 70% 作为翻页步长
    lv_coord_t dy = (lv_coord_t)(lv_obj_get_height(content_) * 7 / 10);
    // 实测在当前布局中，正向 Y 滚动反而显示更早的内容，因此这里使用正向
    lv_obj_scroll_by(content_, 0, dy, LV_ANIM_ON);
    PauseAutoScrollMs(8000);
}

void CustomLcdDisplay::ScrollHistoryPageDown() {
    DisplayLockGuard lock(this);
    if (!content_) return;
    lv_coord_t dy = (lv_coord_t)(lv_obj_get_height(content_) * 7 / 10);
    // 与 PageUp 相反方向
    lv_obj_scroll_by(content_, 0, -dy, LV_ANIM_ON);
    PauseAutoScrollMs(8000);
}

void CustomLcdDisplay::ScrollToLatest() {
    DisplayLockGuard lock(this);
    if (!content_) return;
    uint32_t child_count = lv_obj_get_child_cnt(content_);
    if (child_count > 0) {
        lv_obj_t* last = lv_obj_get_child(content_, child_count - 1);
        if (last) {
            lv_obj_scroll_to_view_recursive(last, LV_ANIM_ON);
        }
    }
    autoscroll_paused_ = false;
}

class Df_K10Board : public WifiBoard
{
private:
    i2c_master_bus_handle_t i2c_bus_;
    esp_io_expander_handle_t io_expander;
    LcdDisplay *display_;
    CustomLcdDisplay *custom_display_;
    Button boot_button_;
    button_handle_t btn_a;
    button_handle_t btn_b;
    Esp32Camera *camera_;

    button_driver_t *btn_a_driver_ = nullptr;
    button_driver_t *btn_b_driver_ = nullptr;

    CircularStrip *led_strip_;
    Aht20Sensor *aht20_sensor_;
    Sc7a20hSensor *sc7a20h_sensor_;
    Ltr3xxSensor *ltr303_sensor_;
    float temperature_ = 0.0f;
    float humidity_ = 0.0f;
    uint16_t visible_ = 0;
    uint16_t IR_ = 0;
    // Copilot *g_copilot_instance = nullptr;

    static Df_K10Board *instance_;

    // 内置测试图片缓冲（用于开机自测显示）
    uint8_t* embedded_jpg_buf_ = nullptr;
    size_t embedded_jpg_size_ = 0;
    // A 键按住说话（Push-To-Talk）状态标记
    bool a_push_to_talk_active_ = false;

    void InitializeI2c()
    {
        // Initialize I2C peripheral
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = (i2c_port_t)1,
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {
                .enable_internal_pullup = 1,
            },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));

        // I2C 总线恢复：若上电时总线被拉低（busy），尝试通过 GPIO 对 SCL 发送 9 个脉冲释放从设备
        // 仅在检测为 busy 时执行，防止影响正常时序
        {
            // 尝试使用驱动层查询 busy 标志
            bool bus_busy = false;
            // 部分 HAL 无法直接判忙，使用一个快速探测事务；若失败则判为 busy
            i2c_master_dev_handle_t tmp_dev = nullptr;
            i2c_device_config_t dev_cfg = {
                .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                .device_address = 0x00, // 任意地址进行空探测
                .scl_speed_hz = 100000,
            };
            if (i2c_master_bus_add_device(i2c_bus_, &dev_cfg, &tmp_dev) == ESP_OK) {
                const uint8_t dummy = 0x00;
                esp_err_t tr = i2c_master_transmit(tmp_dev, &dummy, 0, 10); // 0 字节快速事务
                if (tr != ESP_OK) bus_busy = true;
                i2c_master_bus_rm_device(tmp_dev);
            } else {
                bus_busy = true;
            }

            if (bus_busy) {
                ESP_LOGW(TAG, "I2C bus seems busy at init, try recovering by toggling SCL");
                // 暂时释放总线，切 GPIO 控制 SCL
                gpio_config_t io_conf = {
                    .pin_bit_mask = 1ULL << AUDIO_CODEC_I2C_SCL_PIN,
                    .mode = GPIO_MODE_OUTPUT,
                    .pull_up_en = GPIO_PULLUP_ENABLE,
                    .pull_down_en = GPIO_PULLDOWN_DISABLE,
                    .intr_type = GPIO_INTR_DISABLE,
                };
                gpio_config(&io_conf);
                gpio_set_level((gpio_num_t)AUDIO_CODEC_I2C_SCL_PIN, 1);
                // 发送 9 个脉冲
                for (int i = 0; i < 9; ++i) {
                    gpio_set_level((gpio_num_t)AUDIO_CODEC_I2C_SCL_PIN, 0);
                    esp_rom_delay_us(5);
                    gpio_set_level((gpio_num_t)AUDIO_CODEC_I2C_SCL_PIN, 1);
                    esp_rom_delay_us(5);
                }
                // 恢复 I2C 驱动接管（重新初始化总线）
                i2c_del_master_bus(i2c_bus_);
                ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));
                ESP_LOGW(TAG, "I2C bus recovery done and bus re-initialized");
            }
        }
    }

    void InitializeSpi()
    {
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = GPIO_NUM_21;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = GPIO_NUM_12;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    esp_err_t IoExpanderSetLevel(uint16_t pin_mask, uint8_t level)
    {
        return esp_io_expander_set_level(io_expander, pin_mask, level);
    }

    uint8_t IoExpanderGetLevel(uint16_t pin_mask)
    {
        uint32_t pin_val = 0;
        esp_io_expander_get_level(io_expander, DRV_IO_EXP_INPUT_MASK, &pin_val);
        pin_mask &= DRV_IO_EXP_INPUT_MASK;
        return (uint8_t)((pin_val & pin_mask) ? 1 : 0);
    }

    void InitializeIoExpander()
    {
        esp_io_expander_new_i2c_tca95xx_16bit(
            i2c_bus_, ESP_IO_EXPANDER_I2C_TCA9555_ADDRESS_000, &io_expander);

        esp_err_t ret;
        ret = esp_io_expander_print_state(io_expander);
        if (ret != ESP_OK)
        {
            ESP_LOGE(TAG, "Print state failed: %s", esp_err_to_name(ret));
        }
        ret = esp_io_expander_set_dir(io_expander, IO_EXPANDER_PIN_NUM_0,
                                      IO_EXPANDER_OUTPUT);
        if (ret != ESP_OK)
        {
            ESP_LOGE(TAG, "Set direction failed: %s", esp_err_to_name(ret));
        }
        ret = esp_io_expander_set_level(io_expander, 0, 1);
        if (ret != ESP_OK)
        {
            ESP_LOGE(TAG, "Set level failed: %s", esp_err_to_name(ret));
        }
        ret = esp_io_expander_set_dir(
            io_expander, DRV_IO_EXP_INPUT_MASK,
            IO_EXPANDER_INPUT);
        if (ret != ESP_OK)
        {
            ESP_LOGE(TAG, "Set direction failed: %s", esp_err_to_name(ret));
        }
    }
    void InitializeButtons()
    {
        instance_ = this;

        // Button A
        button_config_t btn_a_config = {
            .long_press_time = 1000,
            .short_press_time = 0};
        btn_a_driver_ = (button_driver_t *)calloc(1, sizeof(button_driver_t));
        btn_a_driver_->enable_power_save = false;
        btn_a_driver_->get_key_level = [](button_driver_t *button_driver) -> uint8_t
        {
            return !instance_->IoExpanderGetLevel(IO_EXPANDER_PIN_NUM_2);
        };
        ESP_ERROR_CHECK(iot_button_create(&btn_a_config, btn_a_driver_, &btn_a));
        iot_button_register_cb(btn_a, BUTTON_SINGLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto self = static_cast<Df_K10Board*>(usr_data);
            // 若处于预览交互：A 确认
            auto cam = static_cast<Esp32Camera*>(self->GetCamera());
            if (cam && cam->IsPreviewActive()) {
                ESP_LOGI(TAG, "Button A pressed (preview active) -> confirm");
                cam->RequestPreviewConfirm();
                return; }
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
                self->ResetWifiConfiguration();
            }
            app.ToggleChatState(); }, this);
        // A 键长按：按住说话（连接并开始聆听）
        iot_button_register_cb(btn_a, BUTTON_LONG_PRESS_START, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto &app = Application::GetInstance();
            ESP_LOGI(TAG, "PTT(A): LONG_PRESS_START -> StartListening");
            app.StartListening();
            auto self = static_cast<Df_K10Board*>(usr_data);
            self->a_push_to_talk_active_ = true; }, this);
        // A 键抬起：若处于按住说话，则停止聆听并待命
        iot_button_register_cb(btn_a, BUTTON_PRESS_UP, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto self = static_cast<Df_K10Board*>(usr_data);
            if (self->a_push_to_talk_active_) {
                auto &app = Application::GetInstance();
                ESP_LOGI(TAG, "PTT(A): PRESS_UP -> StopListening");
                app.StopListening();
                self->a_push_to_talk_active_ = false;
            } }, this);

        // Button B
        button_config_t btn_b_config = {
            .long_press_time = 1000,
            .short_press_time = 0};
        btn_b_driver_ = (button_driver_t *)calloc(1, sizeof(button_driver_t));
        btn_b_driver_->enable_power_save = false;
        btn_b_driver_->get_key_level = [](button_driver_t *button_driver) -> uint8_t
        {
            return !instance_->IoExpanderGetLevel(IO_EXPANDER_PIN_NUM_12);
        };
        ESP_ERROR_CHECK(iot_button_create(&btn_b_config, btn_b_driver_, &btn_b));
        // iot_button_register_cb(btn_b, BUTTON_SINGLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
        //                        {
        //     auto self = static_cast<Df_K10Board*>(usr_data);
        //     auto& app = Application::GetInstance();
        //     if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
        //         self->ResetWifiConfiguration();
        //     }
        //     app.ToggleChatState(); }, this);

    iot_button_register_cb(btn_b, BUTTON_SINGLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
                   {
        auto board = static_cast<Df_K10Board*>(usr_data);
    // 若处于预览交互：B 取消
    auto cam = static_cast<Esp32Camera*>(board->GetCamera());
    if (cam && cam->IsPreviewActive()) { ESP_LOGI(TAG, "Button B pressed (preview active) -> cancel"); cam->RequestPreviewCancel(); return; }
        // 历史浏览：单击 B 向上翻页
        board->GetDisplay()->ScrollHistoryPageUp();
        board->GetDisplay()->ShowMessageButton("上一页 (历史浏览中)", 1200); }, this);

        iot_button_register_cb(btn_b, BUTTON_DOUBLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto board = static_cast<Df_K10Board*>(usr_data);
            // 历史浏览：双击 B 向下翻页
            board->GetDisplay()->ScrollHistoryPageDown();
            board->GetDisplay()->ShowMessageButton("下一页 (历史浏览中)", 1200); }, this);

        // iot_button_register_cb(btn_b, BUTTON_SINGLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
        //                        {
        //                            auto self = static_cast<Df_K10Board *>(usr_data);
        //                            auto &app = Application::GetInstance();
        //                            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected())
        //                            {
        //                                self->ResetWifiConfiguration();
        //                            }

        //                            if (app.GetDeviceState() == kDeviceStateListening)
        //                            {
        //                                auto proto_ = &app.GetProtocol();
        //                                proto_->SendWakeWordDetected("随便给我说一句话"); // 仅在聆听状态下触发，只发送文字问题，小智会根据问题做出响应
        //                            }
        //                            else
        //                            {
        //                                // app.ToggleChatState();
        //                                app.WakeWordInvoke("随便给我说一句话");
        //                            } }, this);
        iot_button_register_cb(btn_b, BUTTON_LONG_PRESS_START, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto self = static_cast<Df_K10Board*>(usr_data);
            auto codec = self->GetAudioCodec();
            auto volume = codec->output_volume() + 10;
            if (volume > 100) {
                volume = 100;
            }
            codec->SetOutputVolume(volume);
            self->GetDisplay()->ShowNotification(Lang::Strings::VOLUME + std::to_string(volume)); }, this);
    }

    void InitializeAht20Sensor()
    {
        // 初始化传感器
        aht20_sensor_ = new Aht20Sensor(i2c_bus_);
        esp_err_t err = aht20_sensor_->Initialize();
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "Failed to initialize AHT20 sensor (err=0x%x)", err);
            return;
        }

        // 设置温湿度数据回调
        aht20_sensor_->SetAht20SensorCallback([this](float temp, float hum)
                                              {
                                                  // UpdateAht20SensorDisplay(temp, hum);

                                                  temperature_ = temp;
                                                  humidity_ = hum;
                                                  //   UpdateAht20SensorDisplay(temperature_, humidity_);
                                                  //  ESP_LOGE(TAG, "Temperature: %.2f C, Humidity: %.2f %%", temp, hum);
                                              });

        // 启动周期性读取（每秒一次）
        err = aht20_sensor_->StartReading(3000);
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "Failed to start periodic readings (err=0x%x)", err);
        }
    }

    void InitializeLtr303Sensor()
    {
        // 初始化光照传感器（假设设备地址为0x23）
        ltr303_sensor_ = new Ltr3xxSensor(i2c_bus_, LTR329_I2CADDR_DEFAULT);

        esp_err_t err = ltr303_sensor_->Initialize();
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "Failed to initialize LTR303 sensor (err=0x%x)", err);
            return;
        }

        // 配置传感器参数
        ltr303_sensor_->setGain(LTR3XX_GAIN_4);
        ltr303_sensor_->setIntegrationTime(LTR3XX_INTEGTIME_50);
        ltr303_sensor_->setMeasurementRate(LTR3XX_MEASRATE_50);
        ltr303_sensor_->SetLtr3xxSensorCallback([this](uint16_t visible, uint16_t IR)
                                                {
                                                    // UpdateAht20SensorDisplay(temp, hum);
                                                    visible_ = visible;
                                                    IR_ = IR;
                                                    // UpdateLightSensorDisplay(visible, IR);
                                                    // ESP_LOGE(TAG, "visible: %d, reds: %d", visl_, reds_);
                                                });

        // 启动周期性读取（3秒间隔）
        err = ltr303_sensor_->StartReading(100);
        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "Failed to start periodic readings (err=0x%x)", err);
        }
    }
    void UpdateAht20SensorDisplay(float temp, float hum)
    {
        if (custom_display_)
        {

            char text[64];
            snprintf(text, sizeof(text), "温度:%.1f°C 湿度:%.1f%%", temp, hum);
            custom_display_->set_message_button_text(text);
        }
    }
    // void UpdateLightSensorDisplay(uint16_t visible, uint16_t IR)
    // {
    //     if (custom_display_)
    //     {
    //         custom_display_->SetLightSensorText(visible , IR);
    //     }
    // }

    void InitializeCamera()
    {
        camera_config_t config = {};
        config.ledc_channel = LEDC_CHANNEL_2; // LEDC通道选择  用于生成XCLK时钟 但是S3不用
        config.ledc_timer = LEDC_TIMER_2;     // LEDC timer选择  用于生成XCLK时钟 但是S3不用
        config.pin_d0 = CAMERA_PIN_D2;
        config.pin_d1 = CAMERA_PIN_D3;
        config.pin_d2 = CAMERA_PIN_D4;
        config.pin_d3 = CAMERA_PIN_D5;
        config.pin_d4 = CAMERA_PIN_D6;
        config.pin_d5 = CAMERA_PIN_D7;
        config.pin_d6 = CAMERA_PIN_D8;
        config.pin_d7 = CAMERA_PIN_D9;
        config.pin_xclk = CAMERA_PIN_XCLK;
        config.pin_pclk = CAMERA_PIN_PCLK;
        config.pin_vsync = CAMERA_PIN_VSYNC;
        config.pin_href = CAMERA_PIN_HREF;
        config.pin_sccb_sda = -1; // 这里如果写-1 表示使用已经初始化的I2C接口
        config.pin_sccb_scl = CAMERA_PIN_SIOC;
        config.sccb_i2c_port = 1; //  这里如果写1 默认使用I2C1
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
    // GC2145 不支持硬件 JPEG，改用 RGB565（由软件JPEG编码）
    config.pixel_format = PIXFORMAT_RGB565;
    // 与驱动期望保持一致：使用 VGA(640x480)，避免出现 FB-SIZE mismatch（SVGA 在本模组上不稳定）
    config.frame_size = FRAMESIZE_VGA;    // 640x480
    // JPEG 质量参数仅在 JPEG 模式生效，此处保留默认
    config.jpeg_quality = 18;
    // 降低内存峰值：使用单缓冲
    config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
    // 在仅有单缓冲的情况下，采用 WHEN_EMPTY 避免帧覆盖，降低峰值压力
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

        camera_ = new Esp32Camera(config);

        // 进一步微调传感器参数，增强清晰度与对比度（不同模组可按需再调）
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
            // 分辨率、质量（JPEG 模式下生效）
            if (s->set_framesize && s->status.framesize != FRAMESIZE_VGA) { s->set_framesize(s, FRAMESIZE_VGA); }
            if (s->set_quality)   { s->set_quality(s, 18); }   // 数值越小质量越高(1~63)

            // 观感增强：适度提亮、提对比和锐度，抑制噪点
            if (s->set_brightness) { s->set_brightness(s, 1); }   // -2 ~ 2
            if (s->set_contrast)   { s->set_contrast(s, 1); }     // -2 ~ 2
            if (s->set_sharpness)  { s->set_sharpness(s, 2); }    // -2 ~ 2（部分驱动支持）
            if (s->set_saturation) { s->set_saturation(s, 0); }   // -2 ~ 2

            // 自动增益/曝光/白平衡，适应室内光
            if (s->set_gain_ctrl)     { s->set_gain_ctrl(s, 1); }
            if (s->set_exposure_ctrl) { s->set_exposure_ctrl(s, 1); }
            if (s->set_awb_gain)      { s->set_awb_gain(s, 1); }
            if (s->set_whitebal)      { s->set_whitebal(s, 1); }

            // 降噪/镜像翻转（按模组装配需求调整）
            // 关闭强降噪以避免文字边缘被抹平造成“糊”的观感
            if (s->set_denoise)   { s->set_denoise(s, 0); }
            if (s->set_hmirror)   { s->set_hmirror(s, 0); }
            if (s->set_vflip)     { s->set_vflip(s, 0); }
        }
    }

    void InitializeIli9341Display()
    {
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        // 液晶屏控制IO初始化
        ESP_LOGD(TAG, "Install panel IO");
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = GPIO_NUM_14;
        io_config.dc_gpio_num = GPIO_NUM_13;
        io_config.spi_mode = 0;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &panel_io));

        // 初始化液晶屏驱动芯片
        ESP_LOGD(TAG, "Install LCD driver");
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.bits_per_pixel = 16;
        panel_config.color_space = ESP_LCD_COLOR_SPACE_BGR;

        ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(panel_io, &panel_config, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, DISPLAY_BACKLIGHT_OUTPUT_INVERT));
        ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

        custom_display_ = new CustomLcdDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y,
                                               DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
        display_ = custom_display_;

#if CONFIG_BOARD_TYPE_DF_K10
        // （已禁用）原本此处会在开机 1 秒后显示内置测试图片，用于验证显示链路。
        // 如果需要重新启用，请恢复被移除的嵌入 JPG 代码块并在 CMakeLists.txt 中确保 EMBED_FILES。
#endif
    }

    // 物联网初始化，添加对 AI 可见设备
    void InitializeIot()
    {
        led_strip_ = new CircularStrip(BUILTIN_LED_GPIO, 3);
        new LedStripControl(led_strip_);
        new McpComplex();

        // const char *my_device_id = "esp32_device_007";
        // const char *my_peer_id = "esp32_device_007"; // 通常与 device_id 相同

        // g_copilot_instance = new Copilot(my_device_id, my_peer_id);
        // if (!g_copilot_instance)
        // {
        //     ESP_LOGE(TAG, "Failed to create Copilot instance!");
        //     return;
        // }

        // esp_err_t init_result = g_copilot_instance->Initialize();
        // if (init_result == ESP_OK)
        // {
        //     ESP_LOGI(TAG, "Copilot instance initialized successfully.");

        // }
    }

public:
    Df_K10Board() : boot_button_(BOOT_BUTTON_GPIO)
    {
        InitializeI2c();
        InitializeIoExpander();
        InitializeSpi();
        InitializeIli9341Display();
        InitializeButtons();
        InitializeAht20Sensor();
        InitializeLtr303Sensor();
        InitializeIot();
        InitializeCamera();
    }

    virtual Led *GetLed() override
    {
        return led_strip_;
    }

    virtual AudioCodec *GetAudioCodec() override
    {
        static K10AudioCodec audio_codec(
            i2c_bus_,
            AUDIO_INPUT_SAMPLE_RATE,
            AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK,
            AUDIO_I2S_GPIO_WS,
            AUDIO_I2S_GPIO_DOUT,
            AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN,
            AUDIO_CODEC_ES8311_ADDR,
            AUDIO_CODEC_ES7210_ADDR,
            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Camera *GetCamera() override
    {
        return camera_;
    }

    virtual Display *GetDisplay() override
    {
        return display_;
    }

    std::string get_temp_humid_sensor() override
    {
        if (aht20_sensor_)
        {
            float temp, hum;
            aht20_sensor_->GetLastMeasurement(&temp, &hum);
            char text[64];
            snprintf(text, sizeof(text), "温度:%.1f°C湿度:%.1f%%", temp, hum);
            return std::string(text);
        }
        return "Sensor not available";
    }
    std::string get_als_sensor() override
    {
        if (ltr303_sensor_)
        {
            // uint16_t visible, IR;
            // ltr303_sensor_->readBothChannels(visible, IR);
            // return "可见光数值为："+ std::to_string(visible) + "LUX, 红外线为：" + std::to_string(IR);
            char text[32];
            snprintf(text, sizeof(text), "光照:%dlux", visible_);
            return std::string(text);
        }
        return "Sensor not available";
    }
};
DECLARE_BOARD(Df_K10Board);

Df_K10Board *Df_K10Board::instance_ = nullptr;
