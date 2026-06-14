#ifndef __AW9523_H__
#define __AW9523_H__

#include "i2c_device.h"

// 枚举定义
enum class Aw9523Port {
    PORT_0,
    PORT_1
};

enum class Aw9523Mode {
    OUTPUT,
    INPUT
};

enum class Aw9523PinMode {
    LED,
    GPIO
};

enum class Aw9523Current {
    CURRENT_37MA = 0x00,
    CURRENT_27_25MA,
    CURRENT_18_5MA,
    CURRENT_9_25MA
};

class Aw9523 : public I2cDevice {
public:
    Aw9523(i2c_master_bus_handle_t i2c_bus, uint8_t addr = 0x5B);
    
    // 基本GPIO操作
    uint8_t ReadLevel(Aw9523Port port);
    void SetLevel(Aw9523Port port, uint8_t value);
    void SetPinLevel(Aw9523Port port, uint8_t pin_num, uint8_t value);
    
    // 输入输出模式设置
    void SetPortMode(Aw9523Port port, uint8_t mode);
    void SetPinMode(Aw9523Port port, uint8_t pin_num, Aw9523Mode mode);
    
    // LED相关功能
    void SetPort0PushPull(bool enable);
    void SetLedMaxCurrent(Aw9523Current current);
    void SetPortFunction(Aw9523Port port, uint8_t mode);
    void SetPinFunction(Aw9523Port port, uint8_t pin_num, Aw9523PinMode mode);
    void SetLedDuty(Aw9523Port port, uint8_t pin_num, uint8_t duty);
    void SetMultiLedDuty(Aw9523Port port, uint8_t start_pin, uint8_t num_pins, uint8_t duty);
    
    // 系统控制
    void SoftReset();

private:
    void CheckPinNumber(uint8_t pin_num);
    uint8_t GetPortRegister(Aw9523Port port, uint8_t reg0, uint8_t reg1);
    uint8_t GetLedRegister(Aw9523Port port, uint8_t pin_num);
};

#endif // __AW9523_H__