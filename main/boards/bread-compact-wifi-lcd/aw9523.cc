#include "aw9523.h"
#include <esp_log.h>
#include <string.h>
#include <stdexcept>  // 用于std::invalid_argument
#include <algorithm>  // 用于std::min

#define TAG "Aw9523"

// 寄存器地址定义
#define REG_INPUT_PORT0    0x00
#define REG_INPUT_PORT1    0x01
#define REG_OUTPUT_PORT0   0x02
#define REG_OUTPUT_PORT1   0x03
#define REG_CONFIG_PORT0   0x04
#define REG_CONFIG_PORT1   0x05
#define REG_INT_PORT0      0x06
#define REG_INT_PORT1      0x07
#define REG_IC_ID         0x10
#define REG_CTL           0x11
#define REG_LED_MODE_PORT0 0x12
#define REG_LED_MODE_PORT1 0x13
#define REG_DIM0          0x20
#define REG_DIM1          0x21
#define REG_DIM2          0x22
#define REG_DIM3          0x23
#define REG_SOFT_RESET    0x7F

Aw9523::Aw9523(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr) {
}

void Aw9523::CheckPinNumber(uint8_t pin_num) {
    if (pin_num > 7) {
        ESP_LOGE(TAG, "Invalid pin number: %d", pin_num);
        throw std::invalid_argument("Pin number must be 0-7");
    }
}


uint8_t Aw9523::GetPortRegister(Aw9523Port port, uint8_t reg0, uint8_t reg1) {
    return (port == Aw9523Port::PORT_0) ? reg0 : reg1;
}

uint8_t Aw9523::ReadLevel(Aw9523Port port) {
    uint8_t reg = GetPortRegister(port, REG_INPUT_PORT0, REG_INPUT_PORT1);
    return ReadReg(reg);
}

void Aw9523::SetLevel(Aw9523Port port, uint8_t value) {
    uint8_t reg = GetPortRegister(port, REG_OUTPUT_PORT0, REG_OUTPUT_PORT1);
    WriteReg(reg, value);
}

void Aw9523::SetPinLevel(Aw9523Port port, uint8_t pin_num, uint8_t value) {
    CheckPinNumber(pin_num);
    uint8_t reg = GetPortRegister(port, REG_OUTPUT_PORT0, REG_OUTPUT_PORT1);
    uint8_t current = ReadReg(reg);
    if (value) {
        current |= (1 << pin_num);
    } else {
        current &= ~(1 << pin_num);
    }
    WriteReg(reg, current);
}

void Aw9523::SetPortMode(Aw9523Port port, uint8_t mode) {
    uint8_t reg = GetPortRegister(port, REG_CONFIG_PORT0, REG_CONFIG_PORT1);
    WriteReg(reg, mode);
}

void Aw9523::SetPinMode(Aw9523Port port, uint8_t pin_num, Aw9523Mode mode) {
    CheckPinNumber(pin_num);
    uint8_t reg = GetPortRegister(port, REG_CONFIG_PORT0, REG_CONFIG_PORT1);
    uint8_t current = ReadReg(reg);
    if (mode == Aw9523Mode::INPUT) {
        current |= (1 << pin_num);
    } else {
        current &= ~(1 << pin_num);
    }
    WriteReg(reg, current);
}

void Aw9523::SetPort0PushPull(bool enable) {
    uint8_t value = ReadReg(REG_CTL);
    if (enable) {
        value |= (1 << 4);
    } else {
        value &= ~(1 << 4);
    }
    WriteReg(REG_CTL, value);
}

void Aw9523::SetLedMaxCurrent(Aw9523Current current) {
    uint8_t value = ReadReg(REG_CTL);
    value &= ~0x03;  // 清除低2位
    value |= static_cast<uint8_t>(current);
    WriteReg(REG_CTL, value);
}

void Aw9523::SetPortFunction(Aw9523Port port, uint8_t mode) {
    uint8_t reg = GetPortRegister(port, REG_LED_MODE_PORT0, REG_LED_MODE_PORT1);
    WriteReg(reg, mode);
}

void Aw9523::SetPinFunction(Aw9523Port port, uint8_t pin_num, Aw9523PinMode mode) {
    CheckPinNumber(pin_num);
    uint8_t reg = GetPortRegister(port, REG_LED_MODE_PORT0, REG_LED_MODE_PORT1);
    uint8_t current = ReadReg(reg);
    if (mode == Aw9523PinMode::GPIO) {
        current |= (1 << pin_num);
    } else {
        current &= ~(1 << pin_num);
    }
    WriteReg(reg, current);
}

uint8_t Aw9523::GetLedRegister(Aw9523Port port, uint8_t pin_num) {
    if (port == Aw9523Port::PORT_0) {
        return 0x24 + pin_num;
    } else {
        return 0x20 + pin_num + ((pin_num > 3) ? 0x08 : 0x00);
    }
}

void Aw9523::SetLedDuty(Aw9523Port port, uint8_t pin_num, uint8_t duty) {
    CheckPinNumber(pin_num);
    uint8_t reg = GetLedRegister(port, pin_num);
    WriteReg(reg, duty);
}

void Aw9523::SetMultiLedDuty(Aw9523Port port, uint8_t start_pin, uint8_t num_pins, uint8_t duty) {
    CheckPinNumber(start_pin + num_pins - 1);
    
    if (port == Aw9523Port::PORT_0) {
        // PORT0 的LED寄存器是连续的
        uint8_t reg = 0x24 + start_pin;
        for (uint8_t i = 0; i < num_pins; i++) {
            WriteReg(reg + i, duty);
        }
    } else {
        // PORT1 的LED寄存器分两段
        if (start_pin < 4) {
            uint8_t count = std::min<uint8_t>(4 - start_pin, num_pins);
            for (uint8_t i = 0; i < count; i++) {
                WriteReg(0x20 + start_pin + i, duty);
            }
            num_pins -= count;
            start_pin = 4;
        }
        if (num_pins > 0) {
            for (uint8_t i = 0; i < num_pins; i++) {
                WriteReg(0x28 + start_pin + i, duty);
            }
        }
    }
}

void Aw9523::SoftReset() {
    WriteReg(REG_SOFT_RESET, 0x00);
}