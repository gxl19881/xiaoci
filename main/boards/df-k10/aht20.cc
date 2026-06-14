#include "aht20.h"
#include <esp_log.h>
#include <driver/i2c_master.h>
#define TAG "Aht20Sensor"

// 命令定义 (根据 AHT20 数据手册)
#define AHT20_CMD_INIT        0xBE  // 初始化命令 (AHT20: 0xBE, 参数 0x08, 0x00)
#define AHT20_CMD_TRIGGER     0xAC  // 触发测量命令 (AHT20: 0xAC, 参数 0x33, 0x00)
#define AHT20_CMD_STATUS      0x71  // 状态查询命令 (AHT20: 0x71)
#define AHT20_CMD_SOFT_RESET  0xBA  // 软复位命令 (AHT20: 0xBA) - 备用

// 状态位定义 (根据 AHT20 数据手册)
#define AHT20_STATUS_BUSY     0x80  // 忙碌标志位 (Bit[7])
#define AHT20_STATUS_CALIB    0x08  // 校准标志位 (Bit[3])

// 构造函数实现
Aht20Sensor::Aht20Sensor(i2c_master_bus_handle_t i2c_bus, uint8_t addr)
    : I2cDevice(i2c_bus, addr) { // 初始化成员变量，包括回调函数
}

// 析构函数实现
Aht20Sensor::~Aht20Sensor() {
    StopReading();
}

esp_err_t Aht20Sensor::Initialize() {
    // AHT20 数据手册: 上电后要等待 40ms。
    vTaskDelay(pdMS_TO_TICKS(50)); 

    // AHT20 数据手册: 读取温湿度值之前，首先要看状态字的校准使能位 Bit[3] 是否为 1。
    // 如果不为 1，要发送 0xBE 命令 (初始化)，此命令参数有两个字节，第一个字节为 0x08，第二个字节为 0x00。
    
    // 检查校准状态
    uint8_t status = ReadReg(AHT20_CMD_STATUS); // 假设 ReadReg 发送命令并读取一个字节
    calibrated_ = (status & AHT20_STATUS_CALIB) != 0;

    if (!calibrated_) {
        ESP_LOGI(TAG, "AHT20 not calibrated, sending initialization command.");
        // AHT20 初始化命令: 0xBE, 参数 0x08, 0x00
        uint8_t init_cmd[3] = {AHT20_CMD_INIT, 0x08, 0x00}; // 更改为 3 个字节的命令
        // esp_err_t err = Transmit(init_cmd, 3); // 使用基类提供的 Transmit 方法
        esp_err_t err = i2c_master_transmit(i2c_device_, init_cmd, 3, 100);; // 使用基类提供的 Transmit 方法
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send initialization command (err=0x%x)", err);
            return err;
        }
        // AHT20 数据手册: 软复位需要 20ms。初始化可能需要更长时间。
        vTaskDelay(pdMS_TO_TICKS(100)); // 保持 100ms 以确保初始化完成。

        // 重新检查校准状态
        status = ReadReg(AHT20_CMD_STATUS);
        calibrated_ = (status & AHT20_STATUS_CALIB) != 0;
    }
    
    ESP_LOGI(TAG, "AHT20 initialized, calibrated: %s", calibrated_ ? "YES" : "NO");
    return ESP_OK;
}

esp_err_t Aht20Sensor::StartReading(float interval_ms) {
    if (reading_) {
        return ESP_OK; // 已经在读取中
    }
    
    // AHT20 数据手册: "注：在第一步的校准状态检验只需要上电时检查，在正常过程无需操作。"
    if (!calibrated_) {
        ESP_LOGE(TAG, "Sensor not calibrated, call Initialize() first");
        return ESP_ERR_INVALID_STATE;
    }
    
    esp_timer_create_args_t timer_args = {
        .callback = &Aht20Sensor::ReadTimerCallback, // 使用静态回调函数
        .arg = this, // 将 'this' 指针传递给回调函数
        .dispatch_method = ESP_TIMER_TASK,
        .name = "aht20_read_timer",
        .skip_unhandled_events = true
    };
    
    esp_err_t err = esp_timer_create(&timer_args, &read_timer_handle_);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create timer (err=0x%x)", err);
        return err;
    }
    
    err = esp_timer_start_periodic(read_timer_handle_, (uint64_t)(interval_ms * 1000));
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start timer (err=0x%x)", err);
        esp_timer_delete(read_timer_handle_);
        read_timer_handle_ = nullptr;
        return err;
    }
    
    reading_ = true;
    ESP_LOGI(TAG, "Started periodic readings with interval %.1f ms", interval_ms);
    return ESP_OK;
}

esp_err_t Aht20Sensor::StopReading() {
    if (!reading_) {
        return ESP_OK; // 已经停止
    }
    
    if (read_timer_handle_) {
        esp_timer_stop(read_timer_handle_);
        esp_timer_delete(read_timer_handle_);
        read_timer_handle_ = nullptr;
    }
    
    reading_ = false;
    ESP_LOGI(TAG, "Stopped periodic readings");
    return ESP_OK;
}

// 静态定时器回调函数实现
void Aht20Sensor::ReadTimerCallback(void* arg) {
    Aht20Sensor* sensor = static_cast<Aht20Sensor*>(arg); // 将 void* 转换为 Aht20Sensor 指针
    sensor->OnReadTimer(); // 调用实例的 OnReadTimer 方法
}

// 定时器触发的读取操作实现
void Aht20Sensor::OnReadTimer() {
    float temperature, humidity;
    esp_err_t err = TriggerMeasurement();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to trigger measurement (err=0x%x)", err);
        return;
    }
    
    // AHT20 数据手册: "等待 75ms 待测量完成"
    vTaskDelay(pdMS_TO_TICKS(75)); // 更改延迟时间为 75ms
    
    err = ReadMeasurement(&temperature, &humidity);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to read measurement (err=0x%x)", err);
    }
    
    // 更新存储的最新数据
    if (err == ESP_OK) {
        last_temperature_ = temperature;
        last_humidity_ = humidity;
    }
    
    // 使用实例成员的回调函数
    if (err == ESP_OK && data_callback_) {
        data_callback_(temperature, humidity);
    }
}

esp_err_t Aht20Sensor::TriggerMeasurement() {
    // AHT20 数据手册: "直接发送 0xAC 命令(触发测量)，此命令参数有两个字节，第一个字节为 0x33，第二个字节为 0x00。"
    uint8_t measure_cmd[3] = {AHT20_CMD_TRIGGER, 0x33, 0x00};
    // return Transmit(measure_cmd, 3);
    return i2c_master_transmit(i2c_device_, measure_cmd, 3, 100);
}

esp_err_t Aht20Sensor::ReadMeasurement(float* temperature, float* humidity) {
    // AHT20 数据手册: "然后可以读取六个字节(发 0X71 即可以读取)。"
    // 通常是读取 7 个字节：1 个状态字节 + 6 个数据/CRC 字节。
    uint8_t buffer[7];
    // esp_err_t err = ReadRegs(AHT20_CMD_STATUS, buffer, 7);
    // if (err != ESP_OK) {
    //     ESP_LOGE(TAG, "Failed to read raw data (err=0x%x)", err);
    //     return err;
    // }
   ReadRegs(AHT20_CMD_STATUS, buffer, 7);

    
    // 检查状态 (Bit 7: 忙碌指示)
    // AHT20 数据手册: "若状态比特位[Bit7]为 0 代表数据可正常读取, 为 1 时传感器为忙状态"
    if (buffer[0] & AHT20_STATUS_BUSY) {
        ESP_LOGW(TAG, "Sensor is still busy after 75ms delay.");
        return ESP_ERR_TIMEOUT;
    }
    
    // 解析湿度数据 (20 位原始数据)
    // AHT20 数据手册: RH = SRH / 2^20 * 100%
    // 数据格式: Status | RH2 | RH1 | RH0 & T2 | T1 | T0 | CRC
    uint32_t hum_raw = ((uint32_t)buffer[1] << 12) | 
                       ((uint32_t)buffer[2] << 4) | 
                       ((buffer[3] & 0xF0) >> 4); // 提取 buffer[3] 的高 4 位
    *humidity = (float)hum_raw * 100.0f / 0x100000; // 0x100000 等于 2^20
    
    // 解析温度数据 (20 位原始数据)
    // AHT20 数据手册: T = ST / 2^20 * 200 - 50
    uint32_t temp_raw = ((uint32_t)(buffer[3] & 0x0F) << 16) | // 提取 buffer[3] 的低 4 位
                        ((uint32_t)buffer[4] << 8) | 
                         (uint32_t)buffer[5];
    *temperature = (float)temp_raw * 200.0f / 0x100000 - 50.0f; // 0x100000 等于 2^20
    
    ESP_LOGD(TAG, "Raw values: temp=0x%06lX, hum=0x%06lX", temp_raw, hum_raw);
    ESP_LOGI(TAG, "Temperature: %.2f°C, Humidity: %.2f%%", *temperature, *humidity);
    
    return ESP_OK;
}
