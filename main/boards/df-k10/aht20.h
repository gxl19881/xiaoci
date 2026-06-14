#ifndef AHT20_SENSOR_H
#define AHT20_SENSOR_H

#include <esp_err.h>
#include <driver/i2c_master.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_timer.h>
#include <functional> // 包含 functional 头文件

// 定义 AHT20 的 I2C 地址
#define AHT20_DEFAULT_I2C_ADDR 0x38

// 假设的 I2C 设备基类头文件
// 如果您没有这个文件，需要将 I2cDevice 的功能集成到 Aht20Sensor 类中
// 或者根据您的实际 I2C 驱动框架进行调整。
#include "i2c_device.h" 

/**
 * @brief AHT20 温湿度传感器驱动类
 */
class Aht20Sensor : public I2cDevice {
private:
    bool reading_ = false;                  // 标志位，指示是否正在进行周期性读取
    bool calibrated_ = false;               // 标志位，指示传感器是否已校准
    esp_timer_handle_t read_timer_handle_ = nullptr; // 定时器句柄

    // 存储最新的温度和湿度数据
    float last_temperature_ = 0.0f;
    float last_humidity_ = 0.0f;

    // 定时器触发的实际读取操作
    void OnReadTimer();

    // 触发测量命令
    esp_err_t TriggerMeasurement();
    // 读取并解析测量数据
    esp_err_t ReadMeasurement(float* temperature, float* humidity);

public:
    // 使用 std::function 定义回调函数类型
    using Aht20SensorCallback = std::function<void(float temp, float hum)>;
    
private:
    // 实例成员用于存储回调函数
    Aht20SensorCallback data_callback_= nullptr;

public:
    /**
     * @brief 构造函数
     * @param i2c_bus I2C总线句柄
     * @param addr AHT20的I2C地址 (通常为0x38)
     * @param callback 可选的回调函数，用于传递测量结果
     */
    Aht20Sensor(i2c_master_bus_handle_t i2c_bus, uint8_t addr = AHT20_DEFAULT_I2C_ADDR);

    /**
     * @brief 析构函数
     */
    ~Aht20Sensor();

    /**
     * @brief 初始化 AHT20 传感器
     *        包括发送初始化命令和检查校准状态。
     * @return ESP_OK on success, or an error code
     */
    esp_err_t Initialize();

    /**
     * @brief 开始周期性读取温湿度数据
     * @param interval_ms 读取间隔时间 (毫秒)
     * @return ESP_OK on success, or an error code
     */
    esp_err_t StartReading(float interval_ms);

    /**
     * @brief 停止周期性读取温湿度数据
     * @return ESP_OK on success, or an error code
     */
    esp_err_t StopReading();
    
    /**
     * @brief 获取最新的温度和湿度数据
     * @param temperature 指向存储温度值的float指针
     * @param humidity 指向存储湿度值的float指针
     */
    void GetLastMeasurement(float* temperature, float* humidity) const {
        *temperature = last_temperature_;
        *humidity = last_humidity_;
    }

    /**
     * @brief 检查传感器是否已校准
     * @return 如果已校准返回true，否则返回false
     */
    bool IsCalibrated() const { return calibrated_; }

    /**
     * @brief 检查传感器是否正在进行周期性读取
     * @return 如果正在读取返回true，否则返回false
     */
    bool IsReading() const { return reading_; }
    
    /**
     * @brief 设置温湿度数据回调函数
     * @param callback 指向回调函数的 std::function 对象
     */
    void SetAht20SensorCallback(Aht20SensorCallback callback) {
        data_callback_ = callback;
    }

private:
    // 静态回调函数，用于 esp_timer，它会调用实例的 OnReadTimer 方法
    static void ReadTimerCallback(void* arg);
};

#endif // AHT20_SENSOR_H
