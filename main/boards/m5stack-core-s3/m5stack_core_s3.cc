#include "wifi_board.h"
#include "cores3_audio_codec.h"
#include "display/lcd_display.h"
#include "application.h"
#include "config.h"
#include "power_save_timer.h"
#include "i2c_device.h"
#include "axp2101.h"
#include <esp_log.h>
#include <driver/i2c_master.h>
#include <wifi_station.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_ili9341.h>
#include <esp_timer.h>
#include "esp32_camera.h"
#include "McpComplex.h"
#include "font_awesome_symbols.h"
#include <esp_lcd_touch_ft5x06.h>
#include <esp_lvgl_port.h>
#include "AudioPlayerUnit.h"
#define TAG "M5StackCoreS3Board"

LV_FONT_DECLARE(font_puhui_20_4);
LV_FONT_DECLARE(font_awesome_20_4);

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

static void play_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *btn = (lv_obj_t *)lv_event_get_target(e);
    lv_obj_t *label = lv_obj_get_child(btn, 0);

    if (code == LV_EVENT_CLICKED)
    {
        static bool is_playing = false;

        ESP_LOGI(TAG, "play_btn was clicked");   
        auto &board = Board::GetInstance();
        auto *player = board.GetAudioPlayer();

        if (is_playing)
        {
            lv_label_set_text(label, LV_SYMBOL_PLAY);
            player->pauseAudio();
            // 按钮释放后恢复蓝色
            lv_obj_set_style_bg_color(btn, lv_color_hex(0x2195f6), 0);
        }
        else
        {
            lv_label_set_text(label, LV_SYMBOL_PAUSE);
            player->playAudio();
            // 按钮释放后恢复蓝色
            lv_obj_set_style_bg_color(btn, lv_color_hex(0x2195f6), 0);
        }
        is_playing = !is_playing;
    }
    else if (code == LV_EVENT_PRESSED)
    {
        // 按钮按下时变为粉色
        lv_obj_set_style_bg_color(btn, lv_color_hex(0xFFC0CB), 0);
    }
}


static void prev_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *btn = (lv_obj_t *)lv_event_get_target(e);

    if (code == LV_EVENT_CLICKED)
    {
        ESP_LOGI(TAG, "prev_btn was clicked");   
        auto &board = Board::GetInstance();
        auto *player = board.GetAudioPlayer();
        player->previousAudio();
        // 按钮释放后恢复蓝色
        lv_obj_set_style_bg_color(btn, lv_color_hex(0x2195f6), 0);
    }
    else if (code == LV_EVENT_PRESSED)
    {
        // 按钮按下时变为粉色
        lv_obj_set_style_bg_color(btn, lv_color_hex(0xFFC0CB), 0);
    }
}


static void next_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    lv_obj_t *btn = (lv_obj_t *)lv_event_get_target(e);

    if (code == LV_EVENT_CLICKED)
    {
        ESP_LOGI(TAG, "next_btn was clicked");      
        auto &board = Board::GetInstance();
        auto *player = board.GetAudioPlayer();
        player->nextAudio();
        // 按钮释放后恢复蓝色
        lv_obj_set_style_bg_color(btn, lv_color_hex(0x2195f6), 0);
    }
    else if (code == LV_EVENT_PRESSED)
    {
        // 按钮按下时变为粉色
        lv_obj_set_style_bg_color(btn, lv_color_hex(0xFFC0CB), 0);
    }
}

//------------------------------------------------------------------------

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
        // lv_obj_add_flag(container_, LV_OBJ_FLAG_CLICKABLE);
        // lv_obj_add_event_cb(container_, scr_main_event_cb, LV_EVENT_CLICKED, NULL);

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
        lv_style_set_bg_color(&style_assistant, lv_color_hex(0xFFD1DC));
        //----------------------------------------------------------------------------
        /* Control buttons container */
       
        lv_obj_t *button_container = lv_obj_create(container_);
        lv_obj_set_size(button_container, LV_HOR_RES, 60);
        lv_obj_set_style_pad_all(button_container, 0, 0);
        lv_obj_set_style_border_width(button_container, 0, 0);
        lv_obj_set_style_bg_color(button_container, lv_color_white(), 0);
        lv_obj_align(button_container, LV_ALIGN_BOTTOM_MID, 0, 0);

        /* Previous button */
        lv_obj_t *prev_btn = lv_btn_create(button_container);
        lv_obj_set_size(prev_btn, 80, 50);
        lv_obj_align(prev_btn, LV_ALIGN_LEFT_MID, 10, 0);
        lv_obj_set_style_bg_color(prev_btn, lv_color_hex(0x2195f6), 0);
        lv_obj_t *prev_label = lv_label_create(prev_btn);
        lv_obj_set_style_text_font(prev_label, &font_awesome_20_4, 0);
        lv_label_set_text(prev_label, LV_SYMBOL_PREV);
        lv_obj_center(prev_label);

        /* Play/Pause button */
        lv_obj_t *play_btn = lv_btn_create(button_container);
        lv_obj_set_size(play_btn, 80, 50);
        lv_obj_align(play_btn, LV_ALIGN_CENTER, 0, 0);
        lv_obj_set_style_bg_color(play_btn, lv_color_hex(0x2195f6), 0);
        lv_obj_t *play_label = lv_label_create(play_btn);
        lv_obj_set_style_text_font(play_label, &font_awesome_20_4, 0);
        lv_label_set_text(play_label, LV_SYMBOL_PLAY);
        // lv_label_set_text(play_label, "\uf04a");
        lv_obj_center(play_label);

        /* Next button */
        lv_obj_t *next_btn = lv_btn_create(button_container);
        lv_obj_set_size(next_btn, 80, 50);
        lv_obj_align(next_btn, LV_ALIGN_RIGHT_MID, -10, 0);
        lv_obj_set_style_bg_color(next_btn, lv_color_hex(0x2195f6), 0);
        lv_obj_t *next_label = lv_label_create(next_btn);
        lv_obj_set_style_text_font(next_label, &font_awesome_20_4, 0);
        lv_label_set_text(next_label, LV_SYMBOL_NEXT);
        lv_obj_center(next_label);

        lv_obj_add_event_cb(prev_btn, prev_btn_event_cb, LV_EVENT_ALL, NULL);
        lv_obj_add_event_cb(play_btn, play_btn_event_cb, LV_EVENT_ALL, NULL);
        lv_obj_add_event_cb(next_btn, next_btn_event_cb, LV_EVENT_ALL, NULL);

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
   

        DisplayLockGuard lock(this);

        if (labelContainer.size() >= 3)
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

class Pmic : public Axp2101
{
public:
    // Power Init
    Pmic(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : Axp2101(i2c_bus, addr)
    {
        uint8_t data = ReadReg(0x90);
        data |= 0b10110100;
        WriteReg(0x90, data);
        WriteReg(0x99, (0b11110 - 5));
        WriteReg(0x97, (0b11110 - 2));
        WriteReg(0x69, 0b00110101);
        WriteReg(0x30, 0b111111);
        WriteReg(0x90, 0xBF);
        WriteReg(0x94, 33 - 5);
        WriteReg(0x95, 33 - 5);
    }

    void SetBrightness(uint8_t brightness)
    {
        brightness = ((brightness + 641) >> 5);
        WriteReg(0x99, brightness);
    }
};

class CustomBacklight : public Backlight
{
public:
    CustomBacklight(Pmic *pmic) : pmic_(pmic) {}

    void SetBrightnessImpl(uint8_t brightness) override
    {
        pmic_->SetBrightness(target_brightness_);
        brightness_ = target_brightness_;
    }

private:
    Pmic *pmic_;
};

class Aw9523 : public I2cDevice
{
public:
    // Exanpd IO Init
    Aw9523(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr)
    {
        WriteReg(0x02, 0b00000111); // P0
        WriteReg(0x03, 0b10001111); // P1
        WriteReg(0x04, 0b00011000); // CONFIG_P0
        WriteReg(0x05, 0b00001100); // CONFIG_P1
        WriteReg(0x11, 0b00010000); // GCR P0 port is Push-Pull mode.
        WriteReg(0x12, 0b11111111); // LEDMODE_P0
        WriteReg(0x13, 0b11111111); // LEDMODE_P1
    }

    void ResetAw88298()
    {
        ESP_LOGI(TAG, "Reset AW88298");
        WriteReg(0x02, 0b00000011);
        vTaskDelay(pdMS_TO_TICKS(10));
        WriteReg(0x02, 0b00000111);
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    void ResetIli9342()
    {
        ESP_LOGI(TAG, "Reset IlI9342");
        WriteReg(0x03, 0b10000001);
        vTaskDelay(pdMS_TO_TICKS(20));
        WriteReg(0x03, 0b10000011);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
};

class M5StackCoreS3Board : public WifiBoard
{
private:
    i2c_master_bus_handle_t i2c_bus_;
    Pmic *pmic_;
    Aw9523 *aw9523_;
    LcdDisplay *display_;
    Esp32Camera *camera_;
   
    PowerSaveTimer *power_save_timer_;
    AudioPlayerUnit *audio_player_;

    void InitializeAudioPlayer()
    {
        audio_player_ = new AudioPlayerUnit(UART_NUM_1, AUDIO_PLAYER_TX_PIN, AUDIO_PLAYER_RX_PIN);
        if (audio_player_->begin())
        {
            ESP_LOGI(TAG, "Audio Player Unit initialized successfully");
            audio_player_->playAudio();
        }
        else
        {
            ESP_LOGE(TAG, "Failed to initialize Audio Player Unit");
        }
    }

    void InitializePowerSaveTimer()
    {
        power_save_timer_ = new PowerSaveTimer(-1, 300, 600);
        power_save_timer_->OnEnterSleepMode([this]()
                                            {
            ESP_LOGI(TAG, "Enabling sleep mode");
            auto display = GetDisplay();
            display->SetChatMessage("system", "");
            display->SetEmotion("sleepy");
            GetBacklight()->SetBrightness(10); });
        power_save_timer_->OnExitSleepMode([this]()
                                           {
            auto display = GetDisplay();
            display->SetChatMessage("system", "");
            display->SetEmotion("neutral");
            GetBacklight()->RestoreBrightness(); });
        power_save_timer_->OnShutdownRequest([this]()
                                             { pmic_->PowerOff(); });
        power_save_timer_->SetEnabled(true);
    }

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

    void InitializeAxp2101()
    {
        ESP_LOGI(TAG, "Init AXP2101");
        pmic_ = new Pmic(i2c_bus_, 0x34);
    }

    void InitializeAw9523()
    {
        ESP_LOGI(TAG, "Init AW9523");
        aw9523_ = new Aw9523(i2c_bus_, 0x58);
        vTaskDelay(pdMS_TO_TICKS(50));
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

    void InitializeIli9342Display()
    {
        ESP_LOGI(TAG, "Init IlI9342");

        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        ESP_LOGD(TAG, "Install panel IO");
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = GPIO_NUM_3;
        io_config.dc_gpio_num = GPIO_NUM_35;
        io_config.spi_mode = 2;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &panel_io));

        ESP_LOGD(TAG, "Install LCD driver");
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR;
        panel_config.bits_per_pixel = 16;
        ESP_ERROR_CHECK(esp_lcd_new_panel_ili9341(panel_io, &panel_config, &panel));

        esp_lcd_panel_reset(panel);
        aw9523_->ResetIli9342();

        esp_lcd_panel_init(panel);
        esp_lcd_panel_invert_color(panel, true);
        esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);

        //         display_ = new SpiLcdDisplay(panel_io, panel,
        //                                     DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY,
        //                                     {
        //                                         .text_font = &font_puhui_20_4,
        //                                         .icon_font = &font_awesome_20_4,
        // #if CONFIG_USE_WECHAT_MESSAGE_STYLE
        //                                         .emoji_font = font_emoji_32_init(),
        // #else
        //                                         .emoji_font = font_emoji_64_init(),
        // #endif
        //                                     });

        display_ = new CustomLcdDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y,
                                        DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }

    void InitializeTouch()
    {
        esp_lcd_touch_handle_t tp;
        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = GPIO_NUM_NC, // Shared with LCD reset
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
    }

    void InitializeCamera()
    {
        // Open camera power
        camera_config_t config = {};
        config.pin_d0 = CAMERA_PIN_D0;
        config.pin_d1 = CAMERA_PIN_D1;
        config.pin_d2 = CAMERA_PIN_D2;
        config.pin_d3 = CAMERA_PIN_D3;
        config.pin_d4 = CAMERA_PIN_D4;
        config.pin_d5 = CAMERA_PIN_D5;
        config.pin_d6 = CAMERA_PIN_D6;
        config.pin_d7 = CAMERA_PIN_D7;
        config.pin_xclk = CAMERA_PIN_XCLK;
        config.pin_pclk = CAMERA_PIN_PCLK;
        config.pin_vsync = CAMERA_PIN_VSYNC;
        config.pin_href = CAMERA_PIN_HREF;
        config.pin_sccb_sda = CAMERA_PIN_SIOD;
        config.pin_sccb_scl = CAMERA_PIN_SIOC;
        config.sccb_i2c_port = 1;
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size = FRAMESIZE_QVGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        camera_ = new Esp32Camera(config);
    }

    // 物联网初始化，添加对 AI 可见设备
    void InitializeIot()
    {

        new McpComplex();
    }

public:
    M5StackCoreS3Board()
    {
        InitializePowerSaveTimer();
        InitializeI2c();
        InitializeAxp2101();
        InitializeAw9523();
        I2cDetect();
        InitializeSpi();
        InitializeIli9342Display();
        InitializeCamera();
        InitializeIot();
        InitializeTouch();
        // InitializeFt6336TouchPad();
        GetBacklight()->RestoreBrightness();
        InitializeAudioPlayer();
    }

    virtual AudioCodec *GetAudioCodec() override
    {
        static CoreS3AudioCodec audio_codec(i2c_bus_,
                                            AUDIO_INPUT_SAMPLE_RATE,
                                            AUDIO_OUTPUT_SAMPLE_RATE,
                                            AUDIO_I2S_GPIO_MCLK,
                                            AUDIO_I2S_GPIO_BCLK,
                                            AUDIO_I2S_GPIO_WS,
                                            AUDIO_I2S_GPIO_DOUT,
                                            AUDIO_I2S_GPIO_DIN,
                                            AUDIO_CODEC_AW88298_ADDR,
                                            AUDIO_CODEC_ES7210_ADDR,
                                            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Display *GetDisplay() override
    {
        return display_;
    }

    virtual Camera *GetCamera() override
    {
        return camera_;
    }
    virtual AudioPlayerUnit *GetAudioPlayer() override
    {
        return audio_player_;
    }

    virtual bool GetBatteryLevel(int &level, bool &charging, bool &discharging) override
    {
        static bool last_discharging = false;
        charging = pmic_->IsCharging();
        discharging = pmic_->IsDischarging();
        if (discharging != last_discharging)
        {
            power_save_timer_->SetEnabled(discharging);
            last_discharging = discharging;
        }

        level = pmic_->GetBatteryLevel();
        return true;
    }

    virtual void SetPowerSaveMode(bool enabled) override
    {
        if (!enabled)
        {
            power_save_timer_->WakeUp();
        }
        WifiBoard::SetPowerSaveMode(enabled);
    }

    virtual Backlight *GetBacklight() override
    {
        static CustomBacklight backlight(pmic_);
        return &backlight;
    }
};

DECLARE_BOARD(M5StackCoreS3Board);
