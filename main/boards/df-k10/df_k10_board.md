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
// #include "pilot_bb.h"

#include "esp_io_expander_tca95xx_16bit.h"

#define TAG "DF-K10"

LV_FONT_DECLARE(font_puhui_20_4);
LV_FONT_DECLARE(font_awesome_20_4);
LV_FONT_DECLARE(font_puhui_14_1);
LV_FONT_DECLARE(font_awesome_14_1);

class CustomLcdDisplay : public SpiLcdDisplay
{
private:
    lv_obj_t *text_box_container;
    lv_obj_t *lightSensor_label_;
    lv_obj_t *temp_hum_data_label_;
    lv_obj_t *sdcard_label_;
    bool is_visible_ = false; // 记录显示状态

    void CreateTextBox()
    {
        DisplayLockGuard lock(this);

        // 创建文本框区域容器，改为纵向布局
        auto screen1 = lv_screen_active();
        lv_obj_set_style_text_font(screen1, fonts_.text_font, 0);
        lv_obj_set_style_text_color(screen1, current_theme_.text, 0);
        lv_obj_set_style_bg_color(screen1, current_theme_.background, 0);

        text_box_container = lv_obj_create(screen1);
        lv_obj_set_size(text_box_container, width_, height_ * 0.25); // 增加容器高度以容纳三行
        lv_obj_align(text_box_container, LV_ALIGN_BOTTOM_MID, 0, -5);
        lv_obj_set_style_bg_color(text_box_container, current_theme_.chat_background, 0);
        lv_obj_set_style_border_width(text_box_container, 1, 0);
        lv_obj_set_style_border_color(text_box_container, current_theme_.border, 0);
        lv_obj_set_style_radius(text_box_container, 8, 0);
        lv_obj_set_flex_flow(text_box_container, LV_FLEX_FLOW_COLUMN); // 改为纵向布局
        lv_obj_set_style_pad_all(text_box_container, 5, 0);
        lv_obj_set_scrollbar_mode(text_box_container, LV_SCROLLBAR_MODE_OFF);
        // lv_obj_add_flag(text_box_container, LV_OBJ_FLAG_HIDDEN);

        // 创建温湿度数据显示标签 - 第一行
        temp_hum_data_label_ = lv_label_create(text_box_container);
        lv_label_set_text(temp_hum_data_label_, "--.--°C --.--%");
        // lv_obj_set_style_text_color(temp_hum_data_label_, current_theme_.text, 0);
        lv_obj_set_style_text_color(temp_hum_data_label_, LV_COLOR_MAKE(0xFF, 0x00, 0x00), 0);
        lv_obj_set_style_text_font(temp_hum_data_label_, &font_puhui_14_1, 0);
        lv_obj_set_width(temp_hum_data_label_, width_ * 0.9);         // 占满容器宽度
        lv_obj_align(temp_hum_data_label_, LV_ALIGN_TOP_LEFT, 10, 5); // 顶部左侧

        // 创建加速度数据显示标签 - 第二行
        lightSensor_label_ = lv_label_create(text_box_container);
        lv_label_set_text(lightSensor_label_, "0.00 0.00 0.00");
        lv_obj_set_style_text_color(lightSensor_label_, current_theme_.text, 0);
        lv_obj_set_style_text_font(lightSensor_label_, &font_puhui_14_1, 0);
        lv_obj_set_width(lightSensor_label_, width_ * 0.9);         // 占满容器宽度
        lv_obj_align(lightSensor_label_, LV_ALIGN_TOP_LEFT, 10, 5); // 顶部左侧，由布局自动排列

        // 创建SD卡状态显示标签 - 第三行
        sdcard_label_ = lv_label_create(text_box_container);
        lv_label_set_text(sdcard_label_, "等待检测SD卡");
        lv_obj_set_style_text_color(sdcard_label_, current_theme_.text, 0);
        lv_obj_set_style_text_font(sdcard_label_, &font_puhui_14_1, 0);
        lv_obj_set_width(sdcard_label_, width_ * 0.9);         // 占满容器宽度
        lv_obj_align(sdcard_label_, LV_ALIGN_TOP_LEFT, 10, 5); // 顶部左侧，由布局自动排列

        // 为容器设置内边距，使三行之间有间隔
        lv_obj_set_style_pad_row(text_box_container, 1, 0); // 行间距
    }

public:
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
                            .text_font = &font_puhui_20_4,
                            .icon_font = &font_awesome_20_4,
                            .emoji_font = font_emoji_64_init(),
                        })
    {
        DisplayLockGuard lock(this);

        // 在父类UI初始化后添加文本框
        if (container_ != nullptr)
        {
            CreateTextBox();
        }
    }

    // 更新加速度显示
    // void SetAccelerationText(const char* text) {
    //     DisplayLockGuard lock(this);
    //     if (accel_label_ != nullptr) {
    //         lv_label_set_text(accel_label_, text);
    //     }
    // }

    // 更新温湿度显示
    void SetAht20SensoryText(float temp, float hum)
    {
        DisplayLockGuard lock(this);
        if (temp_hum_data_label_ != nullptr)
        {
            char buffer[60];
            sprintf(buffer, "温度:%.2f°C,湿度:%.2f%%", temp, hum);

            lv_label_set_text(temp_hum_data_label_, buffer);
        }
    }
    void SetLightSensorText(uint16_t vis, uint16_t red)
    {
        DisplayLockGuard lock(this);
        if (temp_hum_data_label_ != nullptr)
        {
            char buffer[60];
            sprintf(buffer, "可见光:%d,红外光:%d", vis, red);

            lv_label_set_text(lightSensor_label_, buffer);
        }
    }

    // 更新sd卡显示
    // void SetSDcardText(const char* text) {
    //     DisplayLockGuard lock(this);
    //     if (sdcard_label_ != nullptr) {
    //         lv_label_set_text(sdcard_label_, text);
    //     }
    // }

    // 显示传感器信息
    void Show()
    {
        DisplayLockGuard lock(this);
        lv_obj_clear_flag(text_box_container, LV_OBJ_FLAG_HIDDEN);
        is_visible_ = true;
    }

    // 隐藏传感器信息
    void Hide()
    {
        DisplayLockGuard lock(this);
        lv_obj_add_flag(text_box_container, LV_OBJ_FLAG_HIDDEN);
        is_visible_ = false;
    }

    // 查询显示状态
    bool IsVisible() const
    {
        return is_visible_;
    }
};

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
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
                self->ResetWifiConfiguration();
            }
            app.ToggleChatState(); }, this);
        iot_button_register_cb(btn_a, BUTTON_LONG_PRESS_START, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto self = static_cast<Df_K10Board*>(usr_data);
            auto codec = self->GetAudioCodec();
            auto volume = codec->output_volume() - 10;
            if (volume < 0) {
                volume = 0;
            }
            codec->SetOutputVolume(volume);
            self->GetDisplay()->ShowNotification(Lang::Strings::VOLUME + std::to_string(volume)); }, this);

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
        iot_button_register_cb(btn_b, BUTTON_SINGLE_CLICK, nullptr, [](void *button_handle, void *usr_data)
                               {
            auto self = static_cast<Df_K10Board*>(usr_data);
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
                self->ResetWifiConfiguration();
            }
            app.ToggleChatState(); }, this);
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
        
        boot_button_.OnDoubleClick([this]()
                                   {
                                       if (custom_display_->IsVisible())
                                       {
                                           custom_display_->Hide();
                                           ESP_LOGI(TAG, "隐藏传感器信息");
                                       }
                                       else
                                       {
                                           custom_display_->Show();
                                           ESP_LOGI(TAG, "显示传感器信息");
                                       }
                                   });
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
                                                  UpdateAht20SensorDisplay(temperature_, humidity_);
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
                                                    UpdateLightSensorDisplay(visible, IR);
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
            custom_display_->SetAht20SensoryText(temp, hum);
        }
    }
    void UpdateLightSensorDisplay(uint16_t visible, uint16_t IR)
    {
        if (custom_display_)
        {
            custom_display_->SetLightSensorText(visible , IR);
        }
    }

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
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

        camera_ = new Esp32Camera(config);
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

// #if CONFIG_IOT_PROTOCOL_XIAOZHI
//         auto &thing_manager = iot::ThingManager::GetInstance();
//         thing_manager.AddThing(iot::CreateThing("Speaker"));
// #endif
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
            return std::to_string(temp) + "C, " + std::to_string(hum) + "%";
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
            return "可见光数值为：" + std::to_string(visible_) + "LUX, 红外线为：" + std::to_string(IR_);
        }
        return "Sensor not available";
    }
};
DECLARE_BOARD(Df_K10Board);

Df_K10Board *Df_K10Board::instance_ = nullptr;
