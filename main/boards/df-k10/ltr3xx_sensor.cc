// ltr3xx_sensor.cpp
#include "ltr3xx_sensor.h"
#include <string.h> // For memcpy
#include <esp_log.h>
#include <driver/i2c_master.h>
#define TAG "Ltr3xxSensor"



std::vector<uint16_t> ch1_samples;
std::vector<uint16_t> ch2_samples;
const size_t SAMPLE_BUFFER_SIZE = 10; // 例如，存储最近 10 个采样点

// ---------------------------------------------------------------------------
// 构造函数与析构函数
// ---------------------------------------------------------------------------

// 构造函数调用基类构造函数
Ltr3xxSensor::Ltr3xxSensor(i2c_master_bus_handle_t i2c_bus, uint8_t addr)
    : I2cDevice(i2c_bus, addr) {
    // 构造函数中不再需要创建和管理 i2c_device_，由基类完成
}

// 析构函数只需要处理派生类特有的资源
Ltr3xxSensor::~Ltr3xxSensor() {
    StopReading(); // 停止定时器
    // 基类析构函数会自动清理 i2c_device_
}

// ---------------------------------------------------------------------------
// 初始化与配置
// ---------------------------------------------------------------------------

esp_err_t Ltr3xxSensor::Initialize() {
    // 检查 I2C 设备是否已成功安装 (由基类构造函数完成)
    // 假设 i2c_device_ 是 protected 成员，可以直接访问
    if (!i2c_device_) {
        ESP_LOGE(TAG, "I2C device not initialized by base class.");
        return ESP_ERR_INVALID_STATE;
    }

    // 检查 Part ID 和 Manufacturer ID
    // 使用基类提供的 ReadReg 函数
    uint8_t part_id_val = ReadReg(LTR329_PART_ID);
    if (part_id_val != 0xA0) {
        ESP_LOGE(TAG, "Invalid Part ID. Expected 0xA0, got 0x%02X", part_id_val);
        return ESP_ERR_INVALID_VERSION;
    }

    uint8_t manu_id_val = ReadReg(LTR329_MANU_ID);
    if (manu_id_val != 0x05) {
        ESP_LOGE(TAG, "Invalid Manufacturer ID. Expected 0x05, got 0x%02X", manu_id_val);
        return ESP_ERR_INVALID_VERSION;
    }

    // 执行软复位
    if (!reset()) {
        ESP_LOGE(TAG, "Soft reset failed.");
        return ESP_FAIL;
    }

    // 使能传感器
    enable(true);
    if (!enabled()) {
        ESP_LOGE(TAG, "Failed to enable sensor.");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "LTR3xx sensor initialized successfully.");
    return ESP_OK;
}

esp_err_t Ltr3xxSensor::StartReading(uint32_t interval_ms) {
    if (read_timer_handle_) {
        return ESP_OK; // 已经在运行
    }

    esp_timer_create_args_t timer_args = {
        .callback = &Ltr3xxSensor::ReadTimerCallback,
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "ltr3xx_read_timer",
        .skip_unhandled_events = true
    };

    esp_err_t err = esp_timer_create(&timer_args, &read_timer_handle_);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create timer (err=0x%x)", err);
        return err;
    }

    err = esp_timer_start_periodic(read_timer_handle_, (uint64_t)interval_ms * 1000);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start timer (err=0x%x)", err);
        esp_timer_delete(read_timer_handle_);
        read_timer_handle_ = nullptr;
        return err;
    }

    ESP_LOGI(TAG, "Started periodic readings with interval %lu ms", interval_ms);
    return ESP_OK;
}

esp_err_t Ltr3xxSensor::StopReading() {
    if (!read_timer_handle_) {
        return ESP_OK; // 已停止
    }

    esp_timer_stop(read_timer_handle_);
    esp_timer_delete(read_timer_handle_);
    read_timer_handle_ = nullptr;

    ESP_LOGI(TAG, "Stopped periodic readings");
    return ESP_OK;
}

// ---------------------------------------------------------------------------
// 定时器回调与数据处理
// ---------------------------------------------------------------------------

void Ltr3xxSensor::ReadTimerCallback(void* arg) {
    Ltr3xxSensor* sensor = static_cast<Ltr3xxSensor*>(arg);
    sensor->OnReadTimer();
}

// void Ltr3xxSensor::OnReadTimer2() {
//     uint16_t ch1_data, ch2_data;
//     if (newDataAvailable()) {
//         if (readBothChannels(ch1_data, ch2_data)) {
//             last_ch1_ = ch1_data;
//             last_ch2_ = ch2_data;
//             if (data_callback_) {
//                 data_callback_(last_ch1_, last_ch2_);
//             }
//         } else {
//             ESP_LOGW(TAG, "Data invalid after reading channels.");
//         }
//     } else {
//         // Optionally log if no new data is available, or just continue
//         // ESP_LOGD(TAG, "No new data available.");
//     }
// }


void Ltr3xxSensor::OnReadTimer() {
    uint16_t raw_ch1_data, raw_ch2_data;
    if (newDataAvailable()) {
        if (readBothChannels(raw_ch1_data, raw_ch2_data)) {
            // 存储原始数据
            last_ch1_ = raw_ch1_data;
            last_ch2_ = raw_ch2_data;

            // --- 平均值计算 ---
            // 添加到采样缓冲区
            ch1_samples.push_back(raw_ch1_data);
            ch2_samples.push_back(raw_ch2_data);

            // 保持缓冲区大小
            if (ch1_samples.size() > SAMPLE_BUFFER_SIZE) {
                ch1_samples.erase(ch1_samples.begin());
            }
            if (ch2_samples.size() > SAMPLE_BUFFER_SIZE) {
                ch2_samples.erase(ch2_samples.begin());
            }

            // 计算平均值
            uint16_t avg_ch1 = 0;
            if (!ch1_samples.empty()) {
                for (uint16_t sample : ch1_samples) {
                    avg_ch1 += sample;
                }
                avg_ch1 /= ch1_samples.size();
            }

            uint16_t avg_ch2 = 0;
            if (!ch2_samples.empty()) {
                for (uint16_t sample : ch2_samples) {
                    avg_ch2 += sample;
                }
                avg_ch2 /= ch2_samples.size();
            }

            // 通过回调传递平均值
            if (data_callback_) {
                data_callback_(avg_ch1, avg_ch2);
            }
            // --- 平均值计算结束 ---

        } else {
            ESP_LOGW(TAG, "Data invalid after reading channels.");
        }
    } else {
        // No new data, maybe do nothing or log
    }
}

// ---------------------------------------------------------------------------
// 传感器特有函数实现 (使用基类的 ReadReg/WriteReg)
// ---------------------------------------------------------------------------

bool Ltr3xxSensor::reset(void) {
    // LTR329_ALS_CTRL 寄存器 (0x80)
    // SW_RESET 位 (bit 1)
    uint8_t current_val = ReadReg(LTR329_ALS_CTRL);
    uint8_t new_val = current_val | (1 << 1); // 设置 SW_RESET 位
    WriteReg(LTR329_ALS_CTRL, new_val);
    
    vTaskDelay(pdMS_TO_TICKS(10)); // Delay for reset
    return true; // 假设操作成功
}

void Ltr3xxSensor::enable(bool en) {
    // LTR329_ALS_CTRL 寄存器 (0x80)
    // PWR_ON 位 (bit 0)
    uint8_t current_val = ReadReg(LTR329_ALS_CTRL);
    uint8_t new_val;
    if (en) {
        new_val = current_val | (1 << 0); // 设置 PWR_ON 位
    } else {
        new_val = current_val & ~(1 << 0); // 清除 PWR_ON 位
    }
    WriteReg(LTR329_ALS_CTRL, new_val);
}

bool Ltr3xxSensor::enabled(void) {
    // LTR329_ALS_CTRL 寄存器 (0x80)
    // PWR_ON 位 (bit 0)
    uint8_t val = ReadReg(LTR329_ALS_CTRL);
    return (val >> 0) & 1; // 读取 PWR_ON 位
}

void Ltr3xxSensor::setGain(ltr329_gain_t gain) {
    // LTR329_GAIN 寄存器 (0x82)
    // GAIN 位 (bits 0-2)
    uint8_t current_val = ReadReg(LTR329_ALS_CTRL);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    uint8_t new_val = (current_val & ~(mask << 0)) | ((gain & mask) << 0); // 清除旧增益位，设置新增益位
    WriteReg(gain, new_val);
}

ltr329_gain_t Ltr3xxSensor::getGain() {
    // LTR329_GAIN 寄存器 (0x82)
    // GAIN 位 (bits 0-2)
    uint8_t val = ReadReg(LTR329_ALS_CTRL);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    return (ltr329_gain_t)((val >> 0) & mask); // 读取并提取增益位
}

void Ltr3xxSensor::setIntegrationTime(ltr329_integrationtime_t inttime) {
    // LTR329_ALS_CTRL 寄存器 (0x80)
    // INT_TIME 位 (bits 3-5)
    uint8_t current_val = ReadReg(LTR329_ALS_CTRL);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    uint8_t new_val = (current_val & ~(mask << 3)) | ((inttime & mask) << 3); // 清除旧积分时间位，设置新积分时间位
    WriteReg(LTR329_ALS_CTRL, new_val);
}

ltr329_integrationtime_t Ltr3xxSensor::getIntegrationTime() {
    // LTR329_ALS_CTRL 寄存器 (0x80)
    // INT_TIME 位 (bits 3-5)
    uint8_t val = ReadReg(LTR329_ALS_CTRL);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    return (ltr329_integrationtime_t)((val >> 3) & mask); // 读取并提取积分时间位
}

void Ltr3xxSensor::setMeasurementRate(ltr329_measurerate_t rate) {
    // LTR329_MEAS_RATE 寄存器 (0x81)
    // MEAS_RATE 位 (bits 0-2)
    uint8_t current_val = ReadReg(LTR329_MEAS_RATE);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    uint8_t new_val = (current_val & ~(mask << 0)) | ((rate & mask) << 0); // 清除旧测量速率位，设置新测量速率位
    WriteReg(LTR329_MEAS_RATE, new_val);
}

ltr329_measurerate_t Ltr3xxSensor::getMeasurementRate() {
    // LTR329_MEAS_RATE 寄存器 (0x81)
    // MEAS_RATE 位 (bits 0-2)
    uint8_t val = ReadReg(LTR329_MEAS_RATE);
    uint8_t mask = (1 << 3) - 1; // Mask for 3 bits
    return (ltr329_measurerate_t)((val >> 0) & mask); // 读取并提取测量速率位
}

bool Ltr3xxSensor::newDataAvailable() {
    // LTR329_STATUS 寄存器 (0x87)
    // DATA_READY 位 (bit 2)
    uint8_t status_val = ReadReg(LTR329_STATUS);
    return (status_val >> 2) & 1; // 检查 DATA_READY 位
}

bool Ltr3xxSensor::readBothChannels(uint16_t &ch1, uint16_t &ch2) {
    uint8_t data_buffer[4]; // CH1_MSB, CH1_LSB, CH2_MSB, CH2_LSB
    // 使用基类提供的 ReadRegs 函数从 LTR329_CH1DATA 开始读取 4 个字节
    ReadRegs(LTR329_CH1DATA, data_buffer, 4);

    ch1 = (data_buffer[1] << 8) | data_buffer[0]; // CH1 = CH1_MSB | CH1_LSB
    ch2 = (data_buffer[3] << 8) | data_buffer[2]; // CH2 = CH2_MSB | CH2_LSB

    // Check Data Invalid bit (bit 7)
    uint8_t status_val = ReadReg(LTR329_STATUS);
    bool data_invalid = (status_val >> 7) & 1;
    return !data_invalid; // 返回数据是否有效 (DATA_INVALID 为 0 时有效)
}

// --- LTR303 特有功能实现 ---
// 这些函数也直接调用基类提供的 I2C 读写方法

void Ltr3xxSensor::enableInterrupt(bool en) {
    // LTR303 的 INT_CFG 寄存器 (0x83)
    // Bit 1: INT_EN (Interrupt Enable)
    uint8_t current_val = ReadReg(LTR303_REG_INTERRUPT);
    uint8_t new_val;
    if (en) {
        new_val = current_val | (1 << 1); // 设置 INT_EN 位
    } else {
        new_val = current_val & ~(1 << 1); // 清除 INT_EN 位
    }
    WriteReg(LTR303_REG_INTERRUPT, new_val);
}

void Ltr3xxSensor::setInterruptPolarity(bool pol) {
    // LTR303 的 INT_CFG 寄存器 (0x83)
    // Bit 2: INT_POL (Interrupt Polarity) 0=Active Low, 1=Active High
    uint8_t current_val = ReadReg(LTR303_REG_INTERRUPT);
    uint8_t new_val;
    if (pol) {
        new_val = current_val | (1 << 2); // 设置 INT_POL 位
    } else {
        new_val = current_val & ~(1 << 2); // 清除 INT_POL 位
    }
    WriteReg(LTR303_REG_INTERRUPT, new_val);
}

void Ltr3xxSensor::setLowThreshold(uint16_t value) {
    // LTR303 的 THRESHLOW 寄存器 (0x84, 0x85) - 16 bits, LSB first
    uint8_t data[3] = {LTR303_REG_THRESHLOW_LSB,(uint8_t)(value & 0xFF), (uint8_t)(value >> 8)};
    // 使用基类提供的 WriteReg 函数，分两次写 LSB 和 MSB
    // WriteReg(LTR303_REG_THRESHLOW_LSB, data[0]);
    // WriteReg(LTR303_REG_THRESHLOW_LSB, data[1]);
    esp_err_t err = i2c_master_transmit(i2c_device_, data, 3, 100);; // 使用基类提供的 Transmit 方法
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send  command (err=0x%x)", err);
            
        }
}

uint16_t Ltr3xxSensor::getLowThreshold(void) {
    uint8_t data[2];
    // 使用基类提供的 ReadRegs 函数读取 LSB 和 MSB
    ReadRegs(LTR303_REG_THRESHLOW_LSB, data, 2);
    return (data[1] << 8) | data[0]; // 组合成 16 位值 (MSB | LSB)
}

void Ltr3xxSensor::setHighThreshold(uint16_t value) {
    // LTR303 的 THRESHHIGH 寄存器 (0x86, 0x87) - 16 bits, LSB first
    uint8_t data[3] = {LTR303_REG_THRESHHIGH_LSB,(uint8_t)(value & 0xFF), (uint8_t)(value >> 8)};
    // WriteReg(LTR303_REG_THRESHLOW_LSB, data[0]);
    // WriteReg(LTR303_REG_THRESHHIGH_MSB, data[1]);
    esp_err_t err = i2c_master_transmit(i2c_device_, data, 3, 100);; // 使用基类提供的 Transmit 方法
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send  command (err=0x%x)", err);
            
        }
    
}

uint16_t Ltr3xxSensor::getHighThreshold(void) {
    uint8_t data[2];
    ReadRegs(LTR303_REG_THRESHLOW_LSB, data, 2);
    return (data[1] << 8) | data[0]; // 组合成 16 位值 (MSB | LSB)
}

void Ltr3xxSensor::setIntPersistance(uint8_t counts) {
    // LTR303 的 INTPERSIST 寄存器 (0x87)
    // Bits 0-3: INT_PERSIST (Persistence count)
    // Value is counts - 1
    uint8_t val = (counts > 0 && counts <= 16) ? (counts - 1) : 0; // 限制在有效范围内
    
    uint8_t current_val = ReadReg(LTR303_REG_INTPERSIST);
    uint8_t mask = (1 << 4) - 1; // Mask for 4 bits
    uint8_t new_val = (current_val & ~(mask << 0)) | ((val & mask) << 0); // 清除旧持久性计数位，设置新值
    WriteReg(LTR303_REG_INTPERSIST, new_val);
}

uint8_t Ltr3xxSensor::getIntPersistance(void) {
    uint8_t val = ReadReg(LTR303_REG_INTPERSIST);
    uint8_t mask = (1 << 4) - 1; // Mask for 4 bits
    return ((val >> 0) & mask) + 1; // 读取并提取持久性计数，加 1 还原为实际计数
}
