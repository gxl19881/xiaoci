#include "wifi_board.h"
#include "codecs/box_audio_codec.h"
#include "application.h"
#include "display/lcd_display.h"
#include "font_awesome_symbols.h"
// #include "display/no_display.h"
#include "button.h"

#include "esp_lcd_panel_ops.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_ldo_regulator.h"

#include "esp_lcd_jd9365_10_1.h"
#include "config.h"

#include <wifi_station.h>
#include <esp_log.h>
#include <driver/i2c_master.h>
#include <esp_lvgl_port.h>
#include "esp_lcd_touch_gt911.h"
#define TAG "WaveshareEsp32p4xc"

LV_FONT_DECLARE(font_puhui_30_4);
LV_FONT_DECLARE(font_awesome_30_4);

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

class CustomMipiDisplay : public MipiLcdDisplay
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

    // CustomMipiDisplay(io, disp_panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
    //                   DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY,
    //                   {
    //                       .text_font = &font_puhui_30_4,
    //                       .icon_font = &font_awesome_30_4,
    //                       .emoji_font = font_emoji_64_init(),
    //                   });

public:
    virtual void ShowImageFromBuffer(const void *data, size_t size);
    CustomMipiDisplay(esp_lcd_panel_io_handle_t io_handle,
                      esp_lcd_panel_handle_t panel_handle,
                      //   esp_lcd_touch_handle_t touch_handle,
                      int width,
                      int height,
                      int offset_x,
                      int offset_y,
                      bool mirror_x,
                      bool mirror_y,
                      bool swap_xy)
        : MipiLcdDisplay(io_handle, panel_handle,
                         width, height, offset_x, offset_y, mirror_x, mirror_y, swap_xy,
                         {
                             .text_font = &font_puhui_30_4,
                             .icon_font = &font_awesome_30_4,
                             .emoji_font = font_emoji_64_init(),
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
        lv_obj_set_style_text_font(screen, &font_puhui_30_4, 0);
        lv_obj_set_style_text_color(screen, lv_color_white(), 0);

        /* Container */
        container_ = lv_obj_create(screen);
        // lv_obj_set_size(container_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_size(container_, 600, 600);
        lv_obj_center(container_);

        lv_obj_set_flex_flow(container_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_all(container_, 0, 0);
        lv_obj_set_style_border_width(container_, 0, 0);
        lv_obj_set_style_pad_row(container_, 0, 0);
        lv_obj_add_flag(container_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(container_, scr_main_event_cb, LV_EVENT_CLICKED, NULL);

        /* Status bar */
        status_bar_ = lv_obj_create(container_);
        lv_obj_set_size(status_bar_, 600, 85);
        lv_obj_set_style_radius(status_bar_, 0, 0);
        lv_obj_set_style_bg_opa(status_bar_, LV_OPA_10, 0);

        /* Status bar */
        lv_obj_set_style_pad_all(status_bar_, 0, 0);
        lv_obj_set_style_border_width(status_bar_, 0, 0);
        lv_obj_set_style_pad_column(status_bar_, 4, 0);

        /* Content */
        content_ = lv_obj_create(container_);
        lv_obj_set_scrollbar_mode(content_, LV_SCROLLBAR_MODE_ACTIVE);
        lv_obj_set_style_radius(content_, 0, 0);
        lv_obj_set_width(content_, 600);
        lv_obj_set_flex_grow(content_, 1);

        /* Content */
        lv_obj_set_flex_flow(content_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(content_, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_set_style_pad_all(content_, 0, 0);
        lv_obj_set_style_border_width(content_, 1, 0);

        network_label_ = lv_label_create(status_bar_);
        lv_label_set_text(network_label_, "");
        lv_obj_set_style_text_font(network_label_, &font_awesome_30_4, 0);
        lv_obj_align_to(network_label_, status_bar_, LV_ALIGN_LEFT_MID, 40, 0);

        notification_label_ = lv_label_create(status_bar_);
        lv_obj_set_flex_grow(notification_label_, 1);
        lv_obj_set_style_text_align(notification_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_text(notification_label_, "通知");
        lv_obj_add_flag(notification_label_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_center(notification_label_);

        // status_label_ = lv_label_create(status_bar_);
        // lv_obj_set_flex_grow(status_label_, 1);
        // lv_label_set_text(status_label_, "正在初始化");
        // lv_obj_set_style_text_align(status_label_, LV_TEXT_ALIGN_CENTER, 0);
        // // lv_obj_set_style_text_color(status_label_, lv_color_make(0, 255, 0), 0);
        // lv_obj_center(status_label_);

        emotion_label_ = lv_label_create(status_bar_);
        lv_obj_set_style_text_font(emotion_label_, &font_awesome_30_4, 0);
        lv_label_set_text(emotion_label_, FONT_AWESOME_AI_CHIP);
        lv_obj_align_to(emotion_label_, status_bar_, LV_ALIGN_RIGHT_MID, -40, -6);

        mute_label_ = lv_label_create(status_bar_);
        lv_label_set_text(mute_label_, "");
        lv_obj_set_style_text_font(mute_label_, &font_awesome_30_4, 0);

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

        // lv_style_set_text_color(&style_user, lv_color_hex(0xffffff));
        // lv_style_set_bg_color(&style_user, lv_color_hex(0x00B050));

        lv_style_set_bg_color(&style_user, lv_color_hex(0x00B050));


        lv_style_init(&style_assistant);
        lv_style_set_radius(&style_assistant, 5);
        lv_style_set_bg_opa(&style_assistant, LV_OPA_COVER);
        lv_style_set_border_width(&style_assistant, 2);
        lv_style_set_border_color(&style_assistant, lv_color_hex(0));
        lv_style_set_pad_all(&style_assistant, 10);

        lv_style_set_text_color(&style_assistant, lv_color_hex(0));
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
        lv_obj_set_width(container, 600 - 4);
        lv_obj_set_style_pad_all(container, 0, 0);

        lv_obj_t *label = lv_label_create(container);
        lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);

        if (strcmp(role, "user") == 0)
        {
            lv_obj_add_style(label, &style_user, 0);
            lv_obj_align(label, LV_ALIGN_RIGHT_MID, -4, 0);
        }
        else
        {
            lv_obj_add_style(label, &style_assistant, 0);
            lv_obj_align(label, LV_ALIGN_LEFT_MID, 4, 0);
        }
        lv_obj_set_style_text_font(label, &font_puhui_30_4, 0);
        lv_label_set_text(label, content);

        lv_obj_set_style_pad_all(label, 5, LV_PART_MAIN);

        lv_obj_update_layout(label);
        ESP_LOGI(TAG, "Label Width: %ld-%ld", lv_obj_get_width(label), (600 - 2));
        if (lv_obj_get_width(label) >= (600 - 4))
            lv_obj_set_width(label, (600 - 4));
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

void CustomMipiDisplay::ShowImageFromBuffer(const void *data, size_t size)
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

class WaveshareEsp32p4xc : public WifiBoard
{
private:
    i2c_master_bus_handle_t i2c_bus_;
    Button boot_button_;
    LcdDisplay *display_;
    CustomMipiDisplay *displayMipi_;

    void InitializeCodecI2c()
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

    static esp_err_t bsp_enable_dsi_phy_power(void)
    {
#if MIPI_DSI_PHY_PWR_LDO_CHAN > 0
        // Turn on the power for MIPI DSI PHY, so it can go from "No Power" state to "Shutdown" state
        static esp_ldo_channel_handle_t phy_pwr_chan = NULL;
        esp_ldo_channel_config_t ldo_cfg = {
            .chan_id = MIPI_DSI_PHY_PWR_LDO_CHAN,
            .voltage_mv = MIPI_DSI_PHY_PWR_LDO_VOLTAGE_MV,
        };
        esp_ldo_acquire_channel(&ldo_cfg, &phy_pwr_chan);
        ESP_LOGI(TAG, "MIPI DSI PHY Powered on");
#endif // BSP_MIPI_DSI_PHY_PWR_LDO_CHAN > 0

        return ESP_OK;
    }

    void InitializeLCD()
    {
        bsp_enable_dsi_phy_power();
        esp_lcd_panel_io_handle_t io = NULL;
        esp_lcd_panel_handle_t disp_panel = NULL;

        esp_lcd_dsi_bus_handle_t mipi_dsi_bus = NULL;
        esp_lcd_dsi_bus_config_t bus_config = JD9365_PANEL_BUS_DSI_2CH_CONFIG();
        esp_lcd_new_dsi_bus(&bus_config, &mipi_dsi_bus);

        ESP_LOGI(TAG, "Install MIPI DSI LCD control panel");
        // we use DBI interface to send LCD commands and parameters
        esp_lcd_dbi_io_config_t dbi_config = JD9365_PANEL_IO_DBI_CONFIG();
        esp_lcd_new_panel_io_dbi(mipi_dsi_bus, &dbi_config, &io);

        esp_lcd_dpi_panel_config_t dpi_config = {
            .dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
            .dpi_clock_freq_mhz = 46,
            .pixel_format = LCD_COLOR_PIXEL_FORMAT_RGB565,
            .num_fbs = 1,
            .video_timing = {
                .h_size = DISPLAY_WIDTH,
                .v_size = DISPLAY_HEIGHT,
                .hsync_pulse_width = 20,
                .hsync_back_porch = 20,
                .hsync_front_porch = 40,
                .vsync_pulse_width = 4,
                .vsync_back_porch = 12,
                .vsync_front_porch = 24,
            },
            .flags = {
                .use_dma2d = true,
            },
        };
        jd9365_vendor_config_t vendor_config = {
            .init_cmds = lcd_init_cmds,
            .init_cmds_size = sizeof(lcd_init_cmds) / sizeof(lcd_init_cmds[0]),
            .mipi_config = {
                .dsi_bus = mipi_dsi_bus,
                .dpi_config = &dpi_config,
                .lane_num = 2,
            },
            .flags = {
                .use_mipi_interface = 1,
            },
        };

        const esp_lcd_panel_dev_config_t lcd_dev_config = {
            .reset_gpio_num = PIN_NUM_LCD_RST,
            .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
            .bits_per_pixel = 16,
            .vendor_config = &vendor_config,
        };
        esp_lcd_new_panel_jd9365(io, &lcd_dev_config, &disp_panel);
        esp_lcd_panel_reset(disp_panel);
        esp_lcd_panel_init(disp_panel);

        // display_ = new MipiLcdDisplay(io, disp_panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
        //                                DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY,
        //                                {
        //                                    .text_font = &font_puhui_30_4,
        //                                    .icon_font = &font_awesome_30_4,
        //                                    .emoji_font = font_emoji_64_init(),
        //                                });
        displayMipi_ = new CustomMipiDisplay(io, disp_panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                             DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }
    void InitializeTouch()
    {
        esp_lcd_touch_handle_t tp;
        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = GPIO_NUM_23,
            .int_gpio_num = GPIO_NUM_NC,
            .levels = {
                .reset = 0,
                .interrupt = 0,
            },
            .flags = {
                .swap_xy = 0,
                .mirror_x = 0,
                .mirror_y = 0,
            },
        };
        esp_lcd_panel_io_handle_t tp_io_handle = NULL;
        esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
        tp_io_config.scl_speed_hz = 400 * 1000;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io_handle));
        ESP_LOGI(TAG, "Initialize touch controller");
        ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_gt911(tp_io_handle, &tp_cfg, &tp));
        const lvgl_port_touch_cfg_t touch_cfg = {
            .disp = lv_display_get_default(),
            .handle = tp,
        };
        lvgl_port_add_touch(&touch_cfg);
        ESP_LOGI(TAG, "Touch panel initialized successfully");
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

public:
    WaveshareEsp32p4xc() : boot_button_(BOOT_BUTTON_GPIO)
    {
        InitializeCodecI2c();
        InitializeLCD();
        InitializeTouch();
        InitializeButtons();
        GetBacklight()->RestoreBrightness();
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
        return displayMipi_;
    }

    virtual Backlight *GetBacklight() override
    {
        static PwmBacklight backlight(DISPLAY_BACKLIGHT_PIN, DISPLAY_BACKLIGHT_OUTPUT_INVERT);
        return &backlight;
    }
};

DECLARE_BOARD(WaveshareEsp32p4xc);
