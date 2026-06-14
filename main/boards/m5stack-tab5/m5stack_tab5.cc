#include "wifi_board.h"
#include "tab5_audio_codec.h"
#include "display/lcd_display.h"
#include "esp_lcd_ili9881c.h"
#include "font_awesome_symbols.h"
#include "font_emoji.h"
#include "application.h"
#include "button.h"
#include "config.h"

#include <esp_log.h>
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_ops.h"
#include "esp_ldo_regulator.h"
#include <esp_lcd_panel_vendor.h>
#include <driver/i2c_master.h>
#include <driver/spi_common.h>
#include <wifi_station.h>
#include "i2c_device.h"
#include "esp_lcd_touch_gt911.h"
#include <cstring>

#include <esp_lvgl_port.h>
#include "font_awesome_symbols.h"
#include "McpComplex.h"

#define TAG "M5StackTab5Board"

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
        lv_obj_set_size(container_, LV_HOR_RES, LV_VER_RES);
        lv_obj_center(container_);

        lv_obj_set_flex_flow(container_, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_all(container_, 0, 0);
        lv_obj_set_style_border_width(container_, 0, 0);
        lv_obj_set_style_pad_row(container_, 0, 0);
        lv_obj_add_flag(container_, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(container_, scr_main_event_cb, LV_EVENT_CLICKED, NULL);

        /* Status bar */
        status_bar_ = lv_obj_create(container_);
        lv_obj_set_size(status_bar_, LV_HOR_RES, 85);
        lv_obj_set_style_radius(status_bar_, 0, 0);
        lv_obj_set_style_bg_opa(status_bar_, LV_OPA_10, 0);

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
        lv_obj_set_style_text_font(network_label_, &font_awesome_30_4, 0);
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

        if (labelContainer.size() >= 20)
        {
            RemoveOldestLabel(); // 当 label 数量达到 10 时移除最早的
        }

        lv_obj_t *container = lv_obj_create(content_);
        lv_obj_set_scrollbar_mode(container, LV_SCROLLBAR_MODE_OFF);
        lv_obj_set_style_radius(container, 0, 0);
        lv_obj_set_style_border_width(container, 0, 0);
        lv_obj_set_width(container, LV_HOR_RES - 4);
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
        ESP_LOGI(TAG, "Label Width: %ld-%ld", lv_obj_get_width(label), (LV_HOR_RES - 2));
        if (lv_obj_get_width(label) >= (LV_HOR_RES - 4))
            lv_obj_set_width(label, (LV_HOR_RES - 4));
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

#define AUDIO_CODEC_ES8388_ADDR ES8388_CODEC_DEFAULT_ADDR
#define LCD_MIPI_DSI_PHY_PWR_LDO_CHAN 3 // LDO_VO3 is connected to VDD_MIPI_DPHY
#define LCD_MIPI_DSI_PHY_PWR_LDO_VOLTAGE_MV 2500

// PI4IO registers
#define PI4IO_REG_CHIP_RESET 0x01
#define PI4IO_REG_IO_DIR 0x03
#define PI4IO_REG_OUT_SET 0x05
#define PI4IO_REG_OUT_H_IM 0x07
#define PI4IO_REG_IN_DEF_STA 0x09
#define PI4IO_REG_PULL_EN 0x0B
#define PI4IO_REG_PULL_SEL 0x0D
#define PI4IO_REG_IN_STA 0x0F
#define PI4IO_REG_INT_MASK 0x11
#define PI4IO_REG_IRQ_STA 0x13

class Pi4ioe1 : public I2cDevice
{
public:
    Pi4ioe1(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr)
    {
        WriteReg(PI4IO_REG_CHIP_RESET, 0xFF);
        uint8_t data = ReadReg(PI4IO_REG_CHIP_RESET);
        WriteReg(PI4IO_REG_IO_DIR, 0b01111111);     // 0: input 1: output
        WriteReg(PI4IO_REG_OUT_H_IM, 0b00000000);   // 使用到的引脚关闭 High-Impedance
        WriteReg(PI4IO_REG_PULL_SEL, 0b01111111);   // pull up/down select, 0 down, 1 up
        WriteReg(PI4IO_REG_PULL_EN, 0b01111111);    // pull up/down enable, 0 disable, 1 enable
        WriteReg(PI4IO_REG_IN_DEF_STA, 0b10000000); // P1, P7 默认高电平
        WriteReg(PI4IO_REG_INT_MASK, 0b01111111);   // P7 中断使能 0 enable, 1 disable
        WriteReg(PI4IO_REG_OUT_SET, 0b01110110);    // Output Port Register P1(SPK_EN), P2(EXT5V_EN), P4(LCD_RST), P5(TP_RST), P6(CAM)RST 输出高电平
    }
};

class Pi4ioe2 : public I2cDevice
{
public:
    Pi4ioe2(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr)
    {
        WriteReg(PI4IO_REG_CHIP_RESET, 0xFF);
        uint8_t data = ReadReg(PI4IO_REG_CHIP_RESET);
        WriteReg(PI4IO_REG_IO_DIR, 0b10111001);     // 0: input 1: output
        WriteReg(PI4IO_REG_OUT_H_IM, 0b00000110);   // 使用到的引脚关闭 High-Impedance
        WriteReg(PI4IO_REG_PULL_SEL, 0b10111001);   // pull up/down select, 0 down, 1 up
        WriteReg(PI4IO_REG_PULL_EN, 0b11111001);    // pull up/down enable, 0 disable, 1 enable
        WriteReg(PI4IO_REG_IN_DEF_STA, 0b01000000); // P6 默认高电平
        WriteReg(PI4IO_REG_INT_MASK, 0b10111111);   // P6 中断使能 0 enable, 1 disable
        WriteReg(PI4IO_REG_OUT_SET, 0b10001001);    // Output Port Register P0(WLAN_PWR_EN), P3(USB5V_EN), P7(CHG_EN) 输出高电平
    }
};

class M5StackTab5Board : public WifiBoard
{
private:
    i2c_master_bus_handle_t i2c_bus_;
    Button boot_button_;
    LcdDisplay *display_;
    Pi4ioe1 *pi4ioe1_;
    Pi4ioe2 *pi4ioe2_;
    esp_lcd_touch_handle_t touch_ = nullptr;

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

    void InitializePi4ioe()
    {
        ESP_LOGI(TAG, "Init I/O Exapander PI4IOE");
        pi4ioe1_ = new Pi4ioe1(i2c_bus_, 0x43);
        pi4ioe2_ = new Pi4ioe2(i2c_bus_, 0x44);
    }

    void InitializeButtons()
    {
        boot_button_.OnClick([this]()
                             {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting && !WifiStation::GetInstance().IsConnected()) {
                // ResetWifiConfiguration();
            }
            app.ToggleChatState(); });
    }
#if 0
    void InitializeGt911TouchPad() {
        ESP_LOGI(TAG, "Init GT911");
 
        /* Initialize Touch Panel */
        ESP_LOGI(TAG, "Initialize touch IO (I2C)");
        const esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = GPIO_NUM_NC, 
            .int_gpio_num = TOUCH_INT_GPIO, 
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
        tp_io_config.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP; // 更改 GT911 地址 
        tp_io_config.scl_speed_hz = 100000;
        esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io_handle);
        esp_lcd_touch_new_i2c_gt911(tp_io_handle, &tp_cfg, &touch_);

         lvgl_port_add_touch(&touch_cfg);
        ESP_LOGI(TAG, "Touch panel initialized successfully");

        // 检测不到触摸？待更换设备测试
        // /* read data test */ 
        // for (uint8_t i = 0; i < 50; i++) {
        //     esp_lcd_touch_read_data(touch_);
        //     if (touch_->data.points > 0) {
        //         printf("\ntouch: %d, %d\n", touch_->data.coords[0].x, touch_->data.coords[0].y);
        //     }
        //     vTaskDelay(pdMS_TO_TICKS(100));
        // }
    }
#endif
    void InitializeTouch()
    {
        esp_lcd_touch_handle_t tp;
        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = GPIO_NUM_NC,
            .int_gpio_num = TOUCH_INT_GPIO,
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
        tp_io_config.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP; // 更改 GT911 地址
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

    void InitializeSpi()
    {
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = GPIO_NUM_37;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = GPIO_NUM_36;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    void InitializeIli9881cDisplay()
    {
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        ESP_LOGI(TAG, "Turn on the power for MIPI DSI PHY");
        esp_ldo_channel_handle_t ldo_mipi_phy = NULL;
        esp_ldo_channel_config_t ldo_mipi_phy_config = {
            .chan_id = LCD_MIPI_DSI_PHY_PWR_LDO_CHAN,
            .voltage_mv = LCD_MIPI_DSI_PHY_PWR_LDO_VOLTAGE_MV,
        };
        ESP_ERROR_CHECK(esp_ldo_acquire_channel(&ldo_mipi_phy_config, &ldo_mipi_phy));

        ESP_LOGI(TAG, "Install MIPI DSI LCD control panel");
        esp_lcd_dsi_bus_handle_t mipi_dsi_bus;
        esp_lcd_dsi_bus_config_t bus_config = {
            .bus_id = 0,
            .num_data_lanes = 2,
            .phy_clk_src = MIPI_DSI_PHY_CLK_SRC_DEFAULT,
            .lane_bit_rate_mbps = 900, // 900MHz
        };
        ESP_ERROR_CHECK(esp_lcd_new_dsi_bus(&bus_config, &mipi_dsi_bus));

        ESP_LOGI(TAG, "Install panel IO");
        esp_lcd_dbi_io_config_t dbi_config = {
            .virtual_channel = 0,
            .lcd_cmd_bits = 8,
            .lcd_param_bits = 8,
        };
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_dbi(mipi_dsi_bus, &dbi_config, &panel_io));

        ESP_LOGI(TAG, "Install LCD driver of ili9881c");
        esp_lcd_dpi_panel_config_t dpi_config = {.virtual_channel = 0,
                                                 .dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
                                                 .dpi_clock_freq_mhz = 60,
                                                 .pixel_format = LCD_COLOR_PIXEL_FORMAT_RGB565,
                                                 .num_fbs = 2,
                                                 .video_timing =
                                                     {
                                                         .h_size = DISPLAY_WIDTH,
                                                         .v_size = DISPLAY_HEIGHT,
                                                         .hsync_pulse_width = 40,
                                                         .hsync_back_porch = 140,
                                                         .hsync_front_porch = 40,
                                                         .vsync_pulse_width = 4,
                                                         .vsync_back_porch = 20,
                                                         .vsync_front_porch = 20,
                                                     },
                                                 .flags = {
                                                     .use_dma2d = false,
                                                 }};

        ili9881c_vendor_config_t vendor_config = {
            .init_cmds = tab5_lcd_ili9881c_specific_init_code_default,
            .init_cmds_size = sizeof(tab5_lcd_ili9881c_specific_init_code_default) /
                              sizeof(tab5_lcd_ili9881c_specific_init_code_default[0]),
            .mipi_config =
                {
                    .dsi_bus = mipi_dsi_bus,
                    .dpi_config = &dpi_config,
                    .lane_num = 2,
                },
        };

        esp_lcd_panel_dev_config_t lcd_dev_config = {};
        lcd_dev_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
        lcd_dev_config.reset_gpio_num = -1;
        lcd_dev_config.bits_per_pixel = 16;
        lcd_dev_config.vendor_config = &vendor_config;

        ESP_ERROR_CHECK(esp_lcd_new_panel_ili9881c(panel_io, &lcd_dev_config, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        // ESP_ERROR_CHECK(esp_lcd_panel_mirror(disp_panel, false, true));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

        // display_ = new MipiLcdDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X,
        //                               DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY,
        //                               {
        //                                   .text_font = &font_puhui_30_4,
        //                                   .icon_font = &font_awesome_30_4,
        //                                   .emoji_font = font_emoji_64_init(),
        //                               });
        display_ = new CustomMipiDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                             DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }
    void InitializeIot()
    {
        // auto &thing_manager = iot::ThingManager::GetInstance();
        // thing_manager.AddThing(iot::CreateThing("Speaker"));
        // thing_manager.AddThing(iot::CreateThing("Backlight"));
        // thing_manager.AddThing(iot::CreateThing("Lamp"));
        new McpComplex();
    }
public:
    M5StackTab5Board() : boot_button_(BOOT_BUTTON_GPIO)
    {
        InitializeI2c();
        I2cDetect();
        InitializePi4ioe();
        // InitializeGt911TouchPad();

        InitializeIli9881cDisplay();
        InitializeTouch();
        InitializeButtons();
        GetBacklight()->RestoreBrightness();
        // new McpComplex();

        InitializeIot();
    }

    virtual AudioCodec *GetAudioCodec() override
    {
        static Tab5AudioCodec audio_codec(i2c_bus_,
                                          AUDIO_INPUT_SAMPLE_RATE,
                                          AUDIO_OUTPUT_SAMPLE_RATE,
                                          AUDIO_I2S_GPIO_MCLK,
                                          AUDIO_I2S_GPIO_BCLK,
                                          AUDIO_I2S_GPIO_WS,
                                          AUDIO_I2S_GPIO_DOUT,
                                          AUDIO_I2S_GPIO_DIN,
                                          AUDIO_CODEC_PA_PIN,
                                          AUDIO_CODEC_ES8388_ADDR,
                                          AUDIO_CODEC_ES7210_ADDR,
                                          AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Display *GetDisplay() override
    {
        return display_;
    }

    virtual Backlight *GetBacklight() override
    {
        static PwmBacklight backlight(DISPLAY_BACKLIGHT_PIN, DISPLAY_BACKLIGHT_OUTPUT_INVERT);
        return &backlight;
    }
};

DECLARE_BOARD(M5StackTab5Board);
