#ifndef LTR3XX_SENSOR_H
#define LTR3XX_SENSOR_H

#include <esp_err.h>
#include <driver/i2c_master.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <functional>


#include "i2c_device.h" 

// ---------------------------------------------------------------------------
// Adafruit LTR329/LTR303 库中的常量定义 (保持不变)
// ---------------------------------------------------------------------------

// I2C 地址
#define LTR329_I2CADDR_DEFAULT 0x29 ///< I2C address
#define LTR329_PART_ID 0x86         ///< Part id/revision register
#define LTR329_MANU_ID 0x87         ///< Manufacturer ID register
#define LTR329_ALS_CTRL 0x80        ///< ALS control register
#define LTR329_STATUS 0x8C          ///< Status register
#define LTR329_CH1DATA 0x88         ///< Data for channel 1 (read all 4 bytes!)
#define LTR329_MEAS_RATE 0x85       ///< Integration time and data rate

// These registers on LTR-303 only!
#define LTR303_REG_INTERRUPT 0x8F ///< Register to enable/configure int output
#define LTR303_REG_THRESHHIGH_LSB 0x97 ///< ALS 'high' threshold limit
#define LTR303_REG_THRESHLOW_LSB 0x99  ///< ALS 'low' threshold limit
#define LTR303_REG_INTPERSIST 0x9E ///< Register for setting the IRQ persistance

/*!    @brief  Sensor gain for ALS  */
typedef enum {
  LTR3XX_GAIN_1 = 0,
  LTR3XX_GAIN_2 = 1,
  LTR3XX_GAIN_4 = 2,
  LTR3XX_GAIN_8 = 3,
  // 4 & 5 unused!
  LTR3XX_GAIN_48 = 6,
  LTR3XX_GAIN_96 = 7,
} ltr329_gain_t;

/*!    @brief Integration times, in milliseconds */
typedef enum {
  LTR3XX_INTEGTIME_100,
  LTR3XX_INTEGTIME_50,
  LTR3XX_INTEGTIME_200,
  LTR3XX_INTEGTIME_400,
  LTR3XX_INTEGTIME_150,
  LTR3XX_INTEGTIME_250,
  LTR3XX_INTEGTIME_300,
  LTR3XX_INTEGTIME_350,
} ltr329_integrationtime_t;

/*!    @brief Measurement rates, in milliseconds */
typedef enum {
  LTR3XX_MEASRATE_50,
  LTR3XX_MEASRATE_100,
  LTR3XX_MEASRATE_200,
  LTR3XX_MEASRATE_500,
  LTR3XX_MEASRATE_1000,
  LTR3XX_MEASRATE_2000,
} ltr329_measurerate_t;

// ---------------------------------------------------------------------------
// ESP-IDF 驱动类定义
// ---------------------------------------------------------------------------

// 定义光照传感器数据回调函数类型
using Ltr3xxDataCallback = std::function<void(uint16_t ch1, uint16_t ch2)>;

/**
 * @brief LTR329/LTR303 光照传感器驱动类
 */
class Ltr3xxSensor : public I2cDevice { // 直接继承 I2cDevice
public:
    Ltr3xxSensor(i2c_master_bus_handle_t i2c_bus, uint8_t addr);
    ~Ltr3xxSensor(); // 使用 override 关键字

    esp_err_t Initialize();
    esp_err_t StartReading(uint32_t interval_ms);
    esp_err_t StopReading();

    // 传感器配置和状态获取
    void setGain(ltr329_gain_t gain);
    ltr329_gain_t getGain();
    void setIntegrationTime(ltr329_integrationtime_t inttime);
    ltr329_integrationtime_t getIntegrationTime();
    void setMeasurementRate(ltr329_measurerate_t rate);
    ltr329_measurerate_t getMeasurementRate();

    // 数据读取
    bool newDataAvailable();
    bool readBothChannels(uint16_t &ch1, uint16_t &ch2);

    // LTR303 特有功能
    void enableInterrupt(bool en);
    void setInterruptPolarity(bool pol);
    void setLowThreshold(uint16_t value);
    uint16_t getLowThreshold(void);
    void setHighThreshold(uint16_t value);
    uint16_t getHighThreshold(void);
    void setIntPersistance(uint8_t counts);
    uint8_t getIntPersistance(void);
    void SetLtr3xxSensorCallback(Ltr3xxDataCallback callback) {
        data_callback_ = callback;
    }

    //     /**
    //  * @brief 获取最新的可见光和红外线数据
    //  * @param visible 指向存储可见光值的int16_t指针
    //  * @param IR 指向存储红外值的int16_t指针
    //  */
    // void GetLastMeasurement(int16_t* visible, int16_t* IR) const {
    //     *visible = last_ch1_;
    //     *IR = last_ch2_;
    // }

private:
    Ltr3xxDataCallback data_callback_;
    esp_timer_handle_t read_timer_handle_ = nullptr;
    uint16_t last_ch1_ = 0;
    uint16_t last_ch2_ = 0;

    // 内部辅助函数
    bool reset(void);
    void enable(bool en);
    bool enabled(void);

    // 定时器回调
    static void ReadTimerCallback(void* arg);
    void OnReadTimer();
};

#endif // LTR3XX_SENSOR_H

// 您希望 Ltr3xxSensor 类也像您提供的 Aw9523 示例一样，直接继承 I2cDevice，并在构造函数中调用基类的构造函数，而不需要在 Ltr3xxSensor 内部显式地创建和管理 i2c_device_config_t 和 i2c_master_dev_handle_t。

// 将 I2C 设备句柄的创建和管理委托给基类 I2cDevice 来完成，使 Ltr3xxSensor 类直接继承 I2cDevice，并利用其提供的 I2C 读写方法。