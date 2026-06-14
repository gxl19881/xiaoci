#include "wifi_board.h"
#include "audio/codecs/box_audio_codec.h"
#include "display/lcd_display.h"
#include "font_awesome_symbols.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "i2c_device.h"
// #include "iot/thing_manager.h"

#include <esp_log.h>
#include <driver/i2c_master.h>
#include <wifi_station.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <cstring> // 添加strcmp函数的声明
#include <lvgl.h>
#include "esp_lcd_touch_ft5x06.h"
#include <esp_lvgl_port.h>
#include "esp_lcd_st7796.h"
#include "aw9523.h"
#include "McpComplex.h"
#include "display.h"

#include <esp_timer.h>

#define TAG "QMSD-AD35"

LV_FONT_DECLARE(font_puhui_16_4);
LV_FONT_DECLARE(font_awesome_16_4);

static void scr_main_event_cb(lv_event_t *e)
{
    lv_event_code_t event = lv_event_get_code(e);
    // auto &board = Board::GetInstance();
    // auto display = board.GetDisplay();
    auto &app = Application::GetInstance();

    if (event == LV_EVENT_CLICKED)
    {
        ESP_LOGI(TAG, "Touch pressed event detected");
        app.ToggleChatState();
    }
}

// 在waveshare_amoled_1_8类之前添加新的显示类
class CustomLcdDisplay : public SpiLcdDisplay
{

private:
    lv_obj_t *time_label_ = nullptr;
    lv_style_t style_user;
    lv_style_t style_assistant;
    std::vector<lv_obj_t *> labelContainer; // 存储 label 指针的容器
    lv_anim_t anim[3];

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
    CustomLcdDisplay(esp_lcd_panel_io_handle_t io_handle,
                     esp_lcd_panel_handle_t panel_handle,
                     esp_lcd_touch_handle_t touch_handle,
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
                            .icon_font = &font_puhui_16_4,
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

    virtual void SetupUI()
    {
        DisplayLockGuard lock(this);

        ESP_LOGI(TAG, "Custom_SetupUI");
        auto screen = lv_disp_get_scr_act(lv_disp_get_default());
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        lv_obj_set_style_text_font(screen, &font_puhui_16_4, 0);
        lv_obj_set_style_text_color(screen, lv_color_white(), 0);
        

        /* Container */
        container_ = lv_obj_create(screen);
        lv_obj_set_size(container_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_flex_flow(container_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_all(container_, 0, 0);
        lv_obj_set_style_border_width(container_, 0, 0);
        lv_obj_set_style_pad_row(container_, 0, 0);
        lv_obj_add_flag(container_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(container_, scr_main_event_cb, LV_EVENT_CLICKED, NULL);

        /* Status bar */
        status_bar_ = lv_obj_create(container_);
        lv_obj_set_size(status_bar_, LV_HOR_RES, 48);
        lv_obj_set_style_radius(status_bar_, 0, 0);

        /* Status bar */
        lv_obj_set_style_pad_all(status_bar_, 0, 0);
        lv_obj_set_style_border_width(status_bar_, 0, 0);
        lv_obj_set_style_pad_column(status_bar_, 4, 0);
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(status_bar_, scr_main_event_cb, LV_EVENT_CLICKED, NULL);

        /* Content */
        content_ = lv_obj_create(container_);
        lv_obj_set_scrollbar_mode(content_, LV_SCROLLBAR_MODE_ACTIVE);
        lv_obj_set_style_radius(content_, 0, 0);
        lv_obj_set_width(content_, LV_HOR_RES);
        lv_obj_set_flex_grow(content_, 1);

        /* Content */
        lv_obj_set_flex_flow(content_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(content_, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_set_style_pad_all(content_, 0, 0);
        lv_obj_set_style_border_width(content_, 1, 0);

        network_label_ = lv_label_create(status_bar_);
        lv_label_set_text(network_label_, "");
        lv_obj_set_style_text_font(network_label_, &font_awesome_16_4, 0);
        lv_obj_align_to(network_label_, status_bar_, LV_ALIGN_LEFT_MID, 40, 0);

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

        emotion_label_ = lv_label_create(status_bar_);
        lv_obj_set_style_text_font(emotion_label_, &font_awesome_16_4, 0);
        lv_label_set_text(emotion_label_, FONT_AWESOME_AI_CHIP);
        lv_obj_align_to(emotion_label_, status_bar_, LV_ALIGN_RIGHT_MID, -40, -6);

        mute_label_ = lv_label_create(status_bar_);
        lv_label_set_text(mute_label_, "");
        lv_obj_set_style_text_font(mute_label_, &font_awesome_16_4, 0);

        // battery_label_ = lv_label_create(status_bar_);
        // lv_label_set_text(battery_label_, "");
        // lv_obj_set_style_text_font(battery_label_, &font_awesome_16_4, 0);
        // lv_obj_align_to(battery_label_, status_bar_, LV_ALIGN_RIGHT_MID, -40, 0);

        // 初始化聊天框的风格
        lv_style_init(&style_user);
        lv_style_set_radius(&style_user, 5);
        lv_style_set_bg_opa(&style_user, LV_OPA_COVER);
        lv_style_set_border_width(&style_user, 2);
        lv_style_set_border_color(&style_user, lv_color_hex(0));
        lv_style_set_pad_all(&style_user, 10);

        lv_style_set_text_color(&style_user, lv_color_hex(0xffffff));
        lv_style_set_bg_color(&style_user, lv_color_hex(0x00B050));

        lv_style_init(&style_assistant);
        lv_style_set_radius(&style_assistant, 5);
        lv_style_set_bg_opa(&style_assistant, LV_OPA_COVER);
        lv_style_set_border_width(&style_assistant, 2);
        lv_style_set_border_color(&style_assistant, lv_color_hex(0));
        lv_style_set_pad_all(&style_assistant, 10);

        lv_style_set_text_color(&style_assistant, lv_color_hex(0));
        // lv_style_set_bg_color(&style_assistant, lv_color_hex(0xE0E0E0));
        // lv_style_set_bg_color(&style_assistant, lv_color_hex(0xE0E0E0));
        lv_style_set_bg_color(&style_assistant, lv_color_hex(0xFFD1DC));

        DisplayLockGuard unlock(this);
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

        if (labelContainer.size() >= 10)
        {
            RemoveOldestLabel(); // 当 label 数量达到 10 时移除最早的
        }

        lv_obj_t *container = lv_obj_create(content_);
        lv_obj_set_scrollbar_mode(container, LV_SCROLLBAR_MODE_OFF);
        lv_obj_set_style_radius(container, 0, 0);
        lv_obj_set_style_border_width(container, 0, 0);
        lv_obj_set_width(container, LV_HOR_RES - 2);
        lv_obj_set_style_pad_all(container, 0, 0);

        lv_obj_t *label = lv_label_create(container);
        lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);

        if (strcmp(role, "user") == 0)
        {
            lv_obj_add_style(label, &style_user, 0);
            lv_obj_align(label, LV_ALIGN_RIGHT_MID, -2, 0);
        }
        else
        {
            lv_obj_add_style(label, &style_assistant, 0);
            lv_obj_align(label, LV_ALIGN_LEFT_MID, 2, 0);
        }
        lv_obj_set_style_text_font(label, &font_puhui_16_4, 0);
        lv_label_set_text(label, content);

        lv_obj_set_style_pad_all(label, 5, LV_PART_MAIN);

        lv_obj_update_layout(label);
        ESP_LOGI(TAG, "Label Width: %ld-%ld", lv_obj_get_width(label), (LV_HOR_RES - 2));
        if (lv_obj_get_width(label) >= (LV_HOR_RES - 2))
            lv_obj_set_width(label, (LV_HOR_RES - 2));
        lv_obj_scroll_to_view(container, LV_ANIM_ON);

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

        labelContainer.push_back(container); // 将新创建的 container 加入容器
    }
};

class QmsdAd35 : public WifiBoard
{
private:
    i2c_master_bus_handle_t i2c_bus_;
    Aw9523 *aw9523_;
    LcdDisplay *display_;
    Button boot_button_;
    esp_lcd_touch_handle_t touch_handle = nullptr;

    // 触摸事件回调函数


    void InitializeI2c()
    {
        // Initialize I2C peripheral
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = I2C_NUM_1,
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
    }

    void I2cDetect()
    {
        uint8_t address;
        printf("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\r\n");
        for (int i = 0; i < 128; i += 16)
        {
            printf("%02x: ", i);
            for (int j = 0; j < 16; j++)
            {
                fflush(stdout);
                address = i + j;
                esp_err_t ret = i2c_master_probe(i2c_bus_, address, pdMS_TO_TICKS(200));
                if (ret == ESP_OK)
                {
                    printf("%02x ", address);
                }
                else if (ret == ESP_ERR_TIMEOUT)
                {
                    printf("UU ");
                }
                else
                {
                    printf("-- ");
                }
            }
            printf("\r\n");
        }
    }

    void InitializeAw9523()
    {
        ESP_LOGI(TAG, "Init AW9523");
        aw9523_ = new Aw9523(i2c_bus_, 0x59);
        vTaskDelay(pdMS_TO_TICKS(50));

        // 1. 设置BOARD_RESET_PIN (P1.6)为GPIO模式，并进行复位操作
        // 修改引脚号提取方式
        uint8_t port_num = (BOARD_RESET_PIN >> 4);      // 获取端口号(0或1)
        uint8_t pin_num = (BOARD_RESET_PIN & 0x0F) % 8; // 确保引脚号在0-7范围内
        Aw9523Port port = port_num ? Aw9523Port::PORT_1 : Aw9523Port::PORT_0;

        ESP_LOGI(TAG, "Configuring reset pin: port=%d, pin=%d", port_num, pin_num);

        // 设置为GPIO模式并配置为输出
        aw9523_->SetPinFunction(port, pin_num, Aw9523PinMode::GPIO);
        aw9523_->SetPinMode(port, pin_num, Aw9523Mode::OUTPUT);

        // 复位操作
        aw9523_->SetPinLevel(port, pin_num, 0); // 低电平复位
        vTaskDelay(pdMS_TO_TICKS(10));
        aw9523_->SetPinLevel(port, pin_num, 1); // 高电平完成复位
        vTaskDelay(pdMS_TO_TICKS(10));

        // 2. 设置LED最大电流为37mA
        aw9523_->SetLedMaxCurrent(Aw9523Current::CURRENT_37MA);

        // 3. 配置LCD背光引脚为LED模式并设置亮度
        const uint8_t backlight_pins[] = {
            LCD_BL_0_PIN, LCD_BL_1_PIN, LCD_BL_2_PIN,
            LCD_BL_3_PIN, LCD_BL_4_PIN, LCD_BL_5_PIN};

        for (int i = 0; i < 6; i++)
        {
            uint8_t led_port_num = (backlight_pins[i] >> 4);
            uint8_t led_pin_num = (backlight_pins[i] & 0x0F) % 8; // 确保引脚号在0-7范围内
            Aw9523Port led_port = led_port_num ? Aw9523Port::PORT_1 : Aw9523Port::PORT_0;

            ESP_LOGI(TAG, "Configuring backlight pin %d: port=%d, pin=%d", i, led_port_num, led_pin_num);

            // 设置为LED模式
            aw9523_->SetPinFunction(led_port, led_pin_num, Aw9523PinMode::LED);

            // 设置LED亮度为50%
            aw9523_->SetLedDuty(led_port, led_pin_num, 128);
        }

        // 4. 配置功放控制引脚
        uint8_t pa_port_num = (PA_CTRL_PIN >> 4);
        uint8_t pa_pin_num = (PA_CTRL_PIN & 0x0F) % 8; // 确保引脚号在0-7范围内
        Aw9523Port pa_port = pa_port_num ? Aw9523Port::PORT_1 : Aw9523Port::PORT_0;

        ESP_LOGI(TAG, "Configuring PA control pin: port=%d, pin=%d", pa_port_num, pa_pin_num);

        // 设置为GPIO模式并输出高电平
        aw9523_->SetPinFunction(pa_port, pa_pin_num, Aw9523PinMode::GPIO);
        aw9523_->SetPinMode(pa_port, pa_pin_num, Aw9523Mode::OUTPUT);
        aw9523_->SetPinLevel(pa_port, pa_pin_num, 1);
    }

    void InitializeButtons()
    {
        boot_button_.OnClick([this]()
                             {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
                ResetWifiConfiguration();
            }
            app.ToggleChatState(); });
    }
#if 0
    void InitializeFt5x06Touch()
    {
        // esp_lcd_touch_handle_t tp= nullptr;
        
        const esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = EXAMPLE_PIN_NUM_TOUCH_RST,
            .int_gpio_num = EXAMPLE_PIN_NUM_TOUCH_INT,
            .levels = {
                .reset = 0,
                .interrupt = 0,
            },
            .flags = {
                .swap_xy = DISPLAY_SWAP_XY,
                .mirror_x = DISPLAY_MIRROR_X,
                .mirror_y = DISPLAY_MIRROR_Y,
            },
        };

        ESP_LOGI(TAG, "Initialize touch controller FT5x06");
        esp_lcd_panel_io_handle_t tp_io_handle = NULL;
        esp_lcd_panel_io_i2c_config_t tp_io_config;
        if (ESP_OK == i2c_master_probe(i2c_bus_, ESP_LCD_TOUCH_IO_I2C_FT5x06_ADDRESS, 100))
        {
            ESP_LOGE(TAG, "Touch found");
            I2cDetect();
            esp_lcd_panel_io_i2c_config_t config = ESP_LCD_TOUCH_IO_I2C_FT5x06_CONFIG();
            memcpy(&tp_io_config, &config, sizeof(config));
        }
        else
        {
            ESP_LOGE(TAG, "Touch not found");
        }

        tp_io_config.scl_speed_hz = 400 * 1000;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io_handle));
        ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_ft5x06(tp_io_handle, &tp_cfg, &touch_handle));

        ESP_LOGI(TAG, "bsp touch controller handle address: %p", touch_handle);

        assert(touch_handle);

        /* Add touch input (for selected screen) */
        const lvgl_port_touch_cfg_t touch_cfg = {
            .disp = lv_display_get_default(), 
            .handle = touch_handle,
        };

        lvgl_port_add_touch(&touch_cfg);
        ESP_LOGI(TAG, "Touch build successfully");

    }
#endif


    // 触摸任务实现

#if 1
    void InitializeTouch()
    {
        esp_lcd_touch_handle_t tp = nullptr;
        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = EXAMPLE_PIN_NUM_TOUCH_RST,
            .int_gpio_num = EXAMPLE_PIN_NUM_TOUCH_INT,
            .levels = {
                .reset = 0,
                .interrupt = 0,
            },
            .flags = {
                .swap_xy = DISPLAY_SWAP_XY,
                .mirror_x = DISPLAY_MIRROR_X,
                .mirror_y = DISPLAY_MIRROR_Y,
            },
            .user_data = this};
        esp_lcd_panel_io_handle_t tp_io_handle = NULL;
        esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_FT5x06_CONFIG();
        tp_io_config.scl_speed_hz = 400000;

        esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io_handle);
        esp_lcd_touch_new_i2c_ft5x06(tp_io_handle, &tp_cfg, &tp);
        assert(tp);

        /* Add touch input (for selected screen) */
        const lvgl_port_touch_cfg_t touch_cfg = {
            .disp = lv_display_get_default(),            
            .handle = tp,
        };

        lvgl_port_add_touch(&touch_cfg);

        // lv_indev_t *display_indev_ = lvgl_port_add_touch(&touch_cfg);
        // lv_indev_add_event_cb(display_indev_, touch_callback, LV_EVENT_VALUE_CHANGED, this);

        // // 创建触摸数据队列
        // touch_queue_ = xQueueCreate(10, sizeof(TouchPoint));

        // // 创建触摸任务
        // xTaskCreate(touch_task, "touch_task", 4096, this, 5, &touch_task_handle_);
    }
#endif 
    void InitializeSt7796uDisplay()
    {
        ESP_LOGI(TAG, "Initialize Intel 8080 bus");

        // 声明必要的句柄变量
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t lcd_panel = nullptr;

        // 配置I80总线
        esp_lcd_i80_bus_handle_t i80_bus = NULL;
        esp_lcd_i80_bus_config_t bus_config = {
            .dc_gpio_num = PIN_NUM_LCD_DC,
            .wr_gpio_num = PIN_NUM_LCD_WR,
            .clk_src = LCD_CLK_SRC_DEFAULT,
            .data_gpio_nums = {
                PIN_NUM_LCD_DATA0,
                PIN_NUM_LCD_DATA1,
                PIN_NUM_LCD_DATA2,
                PIN_NUM_LCD_DATA3,
                PIN_NUM_LCD_DATA4,
                PIN_NUM_LCD_DATA5,
                PIN_NUM_LCD_DATA6,
                PIN_NUM_LCD_DATA7,
            },
            .bus_width = 8,
            .max_transfer_bytes = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t),
            .psram_trans_align = 64,
            .sram_trans_align = 4,
        };
        ESP_ERROR_CHECK(esp_lcd_new_i80_bus(&bus_config, &i80_bus));

        ESP_LOGI(TAG, "Installing panel IO");
        esp_lcd_panel_io_i80_config_t io_config = {
            .cs_gpio_num = PIN_NUM_LCD_CS,
            .pclk_hz = (10 * 1000 * 1000),
            .trans_queue_depth = 10,
            .on_color_trans_done = nullptr,
            .user_ctx = nullptr,
            .lcd_cmd_bits = 8,
            .lcd_param_bits = 8,
            .dc_levels = {
                .dc_idle_level = 0,
                .dc_cmd_level = 0,
                .dc_dummy_level = 0,
                .dc_data_level = 1,
            },
            .flags = {
                .swap_color_bytes = 0,
            },
        };

        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i80(i80_bus, &io_config, &panel_io));

        ESP_LOGI(TAG, "Install ST7796 panel driver");
        const esp_lcd_panel_dev_config_t panel_config = {
            .reset_gpio_num = PIN_NUM_LCD_RST,
#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 0, 0)
            .color_space = ESP_LCD_COLOR_SPACE_BGR,
#else
            .rgb_endian = LCD_RGB_ENDIAN_BGR,
#endif
            .bits_per_pixel = LCD_BIT_PER_PIXEL,
        };

        ESP_ERROR_CHECK(esp_lcd_new_panel_st7796(panel_io, &panel_config, &lcd_panel));

        ESP_ERROR_CHECK(esp_lcd_panel_reset(lcd_panel));

        ESP_ERROR_CHECK(esp_lcd_panel_init(lcd_panel));

#if ESP_IDF_VERSION < ESP_IDF_VERSION_VAL(5, 0, 0)
        ESP_ERROR_CHECK(esp_lcd_panel_disp_off(lcd_panel, false));
#else
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(lcd_panel, true));
#endif

        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(lcd_panel, true));

        display_ = new CustomLcdDisplay(panel_io, lcd_panel, touch_handle,
                                        DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }

    // 物联网初始化，添加对 AI 可见设备
    void InitializeIot()
    {
        //     auto &thing_manager = iot::ThingManager::GetInstance();
        //     thing_manager.AddThing(iot::CreateThing("Speaker"));
        // thing_manager.AddThing(iot::CreateThing("Backlight"));
        // thing_manager.AddThing(iot::CreateThing("Lamp"));
        new McpComplex();
    }

public:
    QmsdAd35() : boot_button_(GPIO_NUM_0)
    {
        InitializeI2c();
        I2cDetect();
        InitializeAw9523();

        InitializeSt7796uDisplay();
        // InitializeFt5x06Touch();
        InitializeTouch();
        InitializeButtons();
        InitializeIot();
    }

    virtual AudioCodec *GetAudioCodec() override
    {
        static BoxAudioCodec audio_codec(
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

    virtual Display *GetDisplay() override
    {
        return display_;
    }
};

void CustomLcdDisplay::ShowImageFromBuffer(const void *data, size_t size)
{
    DisplayLockGuard lock(this);

    // 清理旧图片（如有）
    static lv_obj_t *last_img = nullptr;
    if (last_img)
    {
        lv_obj_del(last_img);
        last_img = nullptr;
    }

    // 创建 LVGL 图片对象
    last_img = lv_img_create(lv_scr_act());
    lv_img_set_src(last_img, data); // LVGL 8.x/9.x 支持 JPEG/GIF 内存图片
    lv_obj_center(last_img);
}

DECLARE_BOARD(QmsdAd35);
