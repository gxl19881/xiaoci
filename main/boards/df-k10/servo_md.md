
```c

我来为您扩展舵机控制器库，支持4个舵机引脚的控制。这个库将允许您同时控制4个舵机，每个舵机可以是180度或360度类型。

1. 头文件 (ServoController.h)
cpp
 

#ifndef SERVO_CONTROLLER_H
#define SERVO_CONTROLLER_H

#include <Arduino.h>
#include <Wire.h>

// 舵机类型定义
enum ServoType {
    SERVO_180_DEG,  // 180度舵机
    SERVO_360_DEG   // 360度舵机
};

// I2C命令定义
enum I2CCommand {
    CMD_SET_ANGLE = 0x01,       // 设置舵机角度
    CMD_GET_ANGLE = 0x02,       // 获取舵机角度
    CMD_SET_SPEED = 0x03,       // 设置舵机速度
    CMD_GET_STATUS = 0x04,      // 获取舵机状态
    CMD_SET_TYPE = 0x05,        // 设置舵机类型
    CMD_GET_TYPE = 0x06,        // 获取舵机类型
    CMD_SET_PWM = 0x07,         // 直接设置PWM值
    CMD_GET_PWM = 0x08,         // 获取当前PWM值
    CMD_ROTATE_CONTINUOUS = 0x09,// 360度舵机连续旋转
    CMD_SET_SERVO_SELECT = 0x0A,// 选择舵机
    CMD_GET_SERVO_SELECT = 0x0B // 获取当前选择的舵机
};

// 舵机状态结构体
struct ServoStatus {
    uint16_t current_angle;     // 当前角度(0-180度)或速度(0-100%)
    uint16_t target_angle;      // 目标角度或速度
    uint8_t  is_moving;         // 是否正在移动
    uint8_t  speed;             // 移动速度(1-10)
    uint8_t  type;              // 舵机类型
    uint16_t pwm_value;         // 当前PWM值
};

// 舵机引脚定义
enum ServoPin {
    SERVO_PIN_1 = 0,
    SERVO_PIN_2 = 1,
    SERVO_PIN_3 = 2,
    SERVO_PIN_4 = 3,
    SERVO_PIN_ALL = 0xFF        // 所有舵机
};

class ServoController {
public:
    // 构造函数
    ServoController(uint8_t i2cAddress = 0x30);
    
    // 初始化
    void begin();
    
    // 舵机选择
    void selectServo(ServoPin pin);       // 选择要控制的舵机
    ServoPin getSelectedServo();          // 获取当前选择的舵机
    
    // 设置舵机类型
    void setServoType(ServoType type);    // 设置当前选择的舵机类型
    void setServoType(ServoPin pin, ServoType type);  // 设置指定舵机的类型
    ServoType getServoType();             // 获取当前选择的舵机类型
    ServoType getServoType(ServoPin pin); // 获取指定舵机的类型
    
    // 180度舵机控制
    void setAngle(uint16_t angle);        // 设置当前选择的舵机角度
    void setAngle(ServoPin pin, uint16_t angle);  // 设置指定舵机角度
    uint16_t getAngle();                  // 获取当前选择的舵机角度
    uint16_t getAngle(ServoPin pin);      // 获取指定舵机角度
    
    // 360度舵机控制
    void setSpeed(uint8_t speed);         // 设置当前选择的舵机速度
    void setSpeed(ServoPin pin, uint8_t speed);  // 设置指定舵机速度
    void rotate(int8_t speed);            // 旋转当前选择的舵机
    void rotate(ServoPin pin, int8_t speed);     // 旋转指定舵机
    void stop();                          // 停止当前选择的舵机
    void stop(ServoPin pin);              // 停止指定舵机
    void stopAll();                       // 停止所有舵机
    
    // 通用控制
    void setMoveSpeed(uint8_t speed);     // 设置当前选择的舵机移动速度
    void setMoveSpeed(ServoPin pin, uint8_t speed);  // 设置指定舵机移动速度
    uint8_t getMoveSpeed();               // 获取当前选择的舵机移动速度
    uint8_t getMoveSpeed(ServoPin pin);   // 获取指定舵机移动速度
    
    // 直接PWM控制
    void setPWM(uint16_t pwm);            // 设置当前选择的舵机PWM值
    void setPWM(ServoPin pin, uint16_t pwm);       // 设置指定舵机PWM值
    uint16_t getPWM();                    // 获取当前选择的舵机PWM值
    uint16_t getPWM(ServoPin pin);        // 获取指定舵机PWM值
    
    // 状态查询
    ServoStatus getStatus();              // 获取当前选择的舵机状态
    ServoStatus getStatus(ServoPin pin);  // 获取指定舵机状态
    
    // 高级控制
    void moveTo(uint16_t angle, uint8_t speed = 5);  // 移动当前选择的舵机到指定角度
    void moveTo(ServoPin pin, uint16_t angle, uint8_t speed = 5);  // 移动指定舵机到指定角度
    bool isMoving();                      // 检查当前选择的舵机是否正在移动
    bool isMoving(ServoPin pin);          // 检查指定舵机是否正在移动
    bool isAnyMoving();                   // 检查是否有任何舵机正在移动
    void waitUntilStopped();              // 等待当前选择的舵机停止移动
    void waitUntilStopped(ServoPin pin);  // 等待指定舵机停止移动
    void waitUntilAllStopped();           // 等待所有舵机停止移动
    
    // 批量操作
    void setAllAngles(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4);
    void setAllTypes(ServoType type1, ServoType type2, ServoType type3, ServoType type4);
    void setAllSpeeds(uint8_t speed1, uint8_t speed2, uint8_t speed3, uint8_t speed4);
    void moveToAll(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4, uint8_t speed = 5);
    
private:
    uint8_t _i2cAddress;         // I2C从机地址
    ServoPin _selectedServo;     // 当前选择的舵机
    
    // 私有辅助函数
    bool sendCommand(I2CCommand cmd, const uint8_t* data, uint8_t len);
    bool readData(I2CCommand cmd, uint8_t* buffer, uint8_t len);
    uint16_t readUInt16();
    bool writeUInt16(uint16_t value);
};

#endif // SERVO_CONTROLLER_H
2. 实现文件 (ServoController.cpp)
cpp
 

#include "ServoController.h"

// 构造函数
ServoController::ServoController(uint8_t i2cAddress) : _i2cAddress(i2cAddress), _selectedServo(SERVO_PIN_1) {
}

// 初始化
void ServoController::begin() {
    Wire.begin();
    
    // 初始选择第一个舵机
    selectServo(SERVO_PIN_1);
    
    // 初始化所有舵机为180度舵机
    setAllTypes(SERVO_180_DEG, SERVO_180_DEG, SERVO_180_DEG, SERVO_180_DEG);
    
    // 初始停止所有舵机
    stopAll();
    
    // 初始位置设为90度
    setAllAngles(90, 90, 90, 90);
}

// 舵机选择
void ServoController::selectServo(ServoPin pin) {
    _selectedServo = pin;
    uint8_t data[] = { (uint8_t)pin };
    sendCommand(CMD_SET_SERVO_SELECT, data, 1);
}

ServoPin ServoController::getSelectedServo() {
    uint8_t buffer[1];
    if (readData(CMD_GET_SERVO_SELECT, buffer, 1)) {
        _selectedServo = (ServoPin)buffer[0];
    }
    return _selectedServo;
}

// 设置舵机类型
void ServoController::setServoType(ServoType type) {
    setServoType(_selectedServo, type);
}

void ServoController::setServoType(ServoPin pin, ServoType type) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    uint8_t data[] = { (uint8_t)type };
    sendCommand(CMD_SET_TYPE, data, 1);
}

ServoType ServoController::getServoType() {
    return getServoType(_selectedServo);
}

ServoType ServoController::getServoType(ServoPin pin) {
    if (pin != _selectedServo) {
        ServoPin original = _selectedServo;
        selectServo(pin);
        uint8_t buffer[1];
        ServoType type = SERVO_180_DEG;
        if (readData(CMD_GET_TYPE, buffer, 1)) {
            type = (ServoType)buffer[0];
        }
        selectServo(original);
        return type;
    } else {
        uint8_t buffer[1];
        if (readData(CMD_GET_TYPE, buffer, 1)) {
            return (ServoType)buffer[0];
        }
        return SERVO_180_DEG;
    }
}

// 180度舵机控制
void ServoController::setAngle(uint16_t angle) {
    setAngle(_selectedServo, angle);
}

void ServoController::setAngle(ServoPin pin, uint16_t angle) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制角度范围
    if (angle > 180) angle = 180;
    
    uint8_t data[] = { (uint8_t)(angle >> 8), (uint8_t)(angle & 0xFF) };
    sendCommand(CMD_SET_ANGLE, data, 2);
}

uint16_t ServoController::getAngle() {
    return getAngle(_selectedServo);
}

uint16_t ServoController::getAngle(ServoPin pin) {
    if (pin != _selectedServo) {
        ServoPin original = _selectedServo;
        selectServo(pin);
        uint8_t buffer[2];
        uint16_t angle = 0;
        if (readData(CMD_GET_ANGLE, buffer, 2)) {
            angle = (buffer[0] << 8) | buffer[1];
        }
        selectServo(original);
        return angle;
    } else {
        uint8_t buffer[2];
        if (readData(CMD_GET_ANGLE, buffer, 2)) {
            return (buffer[0] << 8) | buffer[1];
        }
        return 0;
    }
}

// 360度舵机控制
void ServoController::setSpeed(uint8_t speed) {
    setSpeed(_selectedServo, speed);
}

void ServoController::setSpeed(ServoPin pin, uint8_t speed) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制速度范围
    if (speed > 100) speed = 100;
    
    uint8_t data[] = { speed };
    sendCommand(CMD_ROTATE_CONTINUOUS, data, 1);
}

void ServoController::rotate(int8_t speed) {
    rotate(_selectedServo, speed);
}

void ServoController::rotate(ServoPin pin, int8_t speed) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制速度范围
    if (speed > 100) speed = 100;
    if (speed < -100) speed = -100;
    
    uint8_t data[] = { (uint8_t)speed };
    sendCommand(CMD_ROTATE_CONTINUOUS, data, 1);
}

void ServoController::stop() {
    stop(_selectedServo);
}

void ServoController::stop(ServoPin pin) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    rotate(0);
}

void ServoController::stopAll() {
    for (int i = 0; i < 4; i++) {
        stop((ServoPin)i);
    }
}

// 设置移动速度
void ServoController::setMoveSpeed(uint8_t speed) {
    setMoveSpeed(_selectedServo, speed);
}

void ServoController::setMoveSpeed(ServoPin pin, uint8_t speed) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制速度范围
    if (speed > 10) speed = 10;
    if (speed < 1) speed = 1;
    
    uint8_t data[] = { speed };
    sendCommand(CMD_SET_SPEED, data, 1);
}

uint8_t ServoController::getMoveSpeed() {
    return getMoveSpeed(_selectedServo);
}

uint8_t ServoController::getMoveSpeed(ServoPin pin) {
    if (pin != _selectedServo) {
        ServoPin original = _selectedServo;
        selectServo(pin);
        uint8_t buffer[1];
        uint8_t speed = 5;
        if (readData(CMD_GET_SPEED, buffer, 1)) {
            speed = buffer[0];
        }
        selectServo(original);
        return speed;
    } else {
        uint8_t buffer[1];
        if (readData(CMD_GET_SPEED, buffer, 1)) {
            return buffer[0];
        }
        return 5;  // 默认速度
    }
}

// 直接设置PWM值
void ServoController::setPWM(uint16_t pwm) {
    setPWM(_selectedServo, pwm);
}

void ServoController::setPWM(ServoPin pin, uint16_t pwm) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制PWM范围
    if (pwm < 1000) pwm = 1000;
    if (pwm > 2000) pwm = 2000;
    
    uint8_t data[] = { (uint8_t)(pwm >> 8), (uint8_t)(pwm & 0xFF) };
    sendCommand(CMD_SET_PWM, data, 2);
}

uint16_t ServoController::getPWM() {
    return getPWM(_selectedServo);
}

uint16_t ServoController::getPWM(ServoPin pin) {
    if (pin != _selectedServo) {
        ServoPin original = _selectedServo;
        selectServo(pin);
        uint8_t buffer[2];
        uint16_t pwm = 1500;
        if (readData(CMD_GET_PWM, buffer, 2)) {
            pwm = (buffer[0] << 8) | buffer[1];
        }
        selectServo(original);
        return pwm;
    } else {
        uint8_t buffer[2];
        if (readData(CMD_GET_PWM, buffer, 2)) {
            return (buffer[0] << 8) | buffer[1];
        }
        return 1500;  // 默认中间值
    }
}

// 获取完整状态
ServoStatus ServoController::getStatus() {
    return getStatus(_selectedServo);
}

ServoStatus ServoController::getStatus(ServoPin pin) {
    ServoStatus status = {0};
    
    if (pin != _selectedServo) {
        ServoPin original = _selectedServo;
        selectServo(pin);
        
        uint8_t buffer[9];
        if (readData(CMD_GET_STATUS, buffer, 9)) {
            status.current_angle = (buffer[0] << 8) | buffer[1];
            status.target_angle = (buffer[2] << 8) | buffer[3];
            status.is_moving = buffer[4];
            status.speed = buffer[5];
            status.type = buffer[6];
            status.pwm_value = (buffer[7] << 8) | buffer[8];
        }
        
        selectServo(original);
    } else {
        uint8_t buffer[9];
        if (readData(CMD_GET_STATUS, buffer, 9)) {
            status.current_angle = (buffer[0] << 8) | buffer[1];
            status.target_angle = (buffer[2] << 8) | buffer[3];
            status.is_moving = buffer[4];
            status.speed = buffer[5];
            status.type = buffer[6];
            status.pwm_value = (buffer[7] << 8) | buffer[8];
        }
    }
    
    return status;
}

// 移动到指定角度
void ServoController::moveTo(uint16_t angle, uint8_t speed) {
    moveTo(_selectedServo, angle, speed);
}

void ServoController::moveTo(ServoPin pin, uint16_t angle, uint8_t speed) {
    if (pin != SERVO_PIN_ALL) {
        selectServo(pin);
    }
    
    // 限制角度范围
    if (angle > 180) angle = 180;
    
    // 设置移动速度
    setMoveSpeed(speed);
    
    // 设置目标角度
    setAngle(angle);
}

// 检查是否正在移动
bool ServoController::isMoving() {
    return isMoving(_selectedServo);
}

bool ServoController::isMoving(ServoPin pin) {
    ServoStatus status = getStatus(pin);
    return status.is_moving != 0;
}

bool ServoController::isAnyMoving() {
    for (int i = 0; i < 4; i++) {
        if (isMoving((ServoPin)i)) {
            return true;
        }
    }
    return false;
}

// 等待直到停止移动
void ServoController::waitUntilStopped() {
    waitUntilStopped(_selectedServo);
}

void ServoController::waitUntilStopped(ServoPin pin) {
    while (isMoving(pin)) {
        delay(10);
    }
}

void ServoController::waitUntilAllStopped() {
    while (isAnyMoving()) {
        delay(10);
    }
}

// 批量操作
void ServoController::setAllAngles(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4) {
    setAngle(SERVO_PIN_1, angle1);
    setAngle(SERVO_PIN_2, angle2);
    setAngle(SERVO_PIN_3, angle3);
    setAngle(SERVO_PIN_4, angle4);
}

void ServoController::setAllTypes(ServoType type1, ServoType type2, ServoType type3, ServoType type4) {
    setServoType(SERVO_PIN_1, type1);
    setServoType(SERVO_PIN_2, type2);
    setServoType(SERVO_PIN_3, type3);
    setServoType(SERVO_PIN_4, type4);
}

void ServoController::setAllSpeeds(uint8_t speed1, uint8_t speed2, uint8_t speed3, uint8_t speed4) {
    setMoveSpeed(SERVO_PIN_1, speed1);
    setMoveSpeed(SERVO_PIN_2, speed2);
    setMoveSpeed(SERVO_PIN_3, speed3);
    setMoveSpeed(SERVO_PIN_4, speed4);
}

void ServoController::moveToAll(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4, uint8_t speed) {
    moveTo(SERVO_PIN_1, angle1, speed);
    moveTo(SERVO_PIN_2, angle2, speed);
    moveTo(SERVO_PIN_3, angle3, speed);
    moveTo(SERVO_PIN_4, angle4, speed);
}

// 私有辅助函数：发送命令
bool ServoController::sendCommand(I2CCommand cmd, const uint8_t* data, uint8_t len) {
    Wire.beginTransmission(_i2cAddress);
    Wire.write((uint8_t)cmd);
    
    if (data != nullptr && len > 0) {
        Wire.write(data, len);
    }
    
    return (Wire.endTransmission() == 0);
}

// 私有辅助函数：读取数据
bool ServoController::readData(I2CCommand cmd, uint8_t* buffer, uint8_t len) {
    // 发送命令
    Wire.beginTransmission(_i2cAddress);
    Wire.write((uint8_t)cmd);
    if (Wire.endTransmission() != 0) {
        return false;
    }
    
    // 读取数据
    uint8_t bytesRead = Wire.requestFrom(_i2cAddress, len);
    if (bytesRead != len) {
        return false;
    }
    
    for (uint8_t i = 0; i < len; i++) {
        buffer[i] = Wire.read();
    }
    
    return true;
}

// 私有辅助函数：读取16位无符号整数
uint16_t ServoController::readUInt16() {
    uint8_t buffer[2];
    if (readData(CMD_GET_ANGLE, buffer, 2)) {
        return (buffer[0] << 8) | buffer[1];
    }
    return 0;
}

// 私有辅助函数：写入16位无符号整数
bool ServoController::writeUInt16(uint16_t value) {
    uint8_t data[] = { (uint8_t)(value >> 8), (uint8_t)(value & 0xFF) };
    return sendCommand(CMD_SET_ANGLE, data, 2);
}
3. 使用示例 (example.ino)
cpp
 

#include "ServoController.h"

// 创建舵机控制器实例，I2C地址为0x30
ServoController servo(0x30);

void setup() {
    Serial.begin(9600);
    
    // 初始化舵机控制器
    servo.begin();
    
    // 设置舵机类型
    servo.setServoType(SERVO_PIN_1, SERVO_180_DEG);  // 舵机1为180度舵机
    servo.setServoType(SERVO_PIN_2, SERVO_180_DEG);  // 舵机2为180度舵机
    servo.setServoType(SERVO_PIN_3, SERVO_360_DEG);  // 舵机3为360度舵机
    servo.setServoType(SERVO_PIN_4, SERVO_360_DEG);  // 舵机4为360度舵机
    
    // 设置移动速度
    servo.setMoveSpeed(SERVO_PIN_1, 5);
    servo.setMoveSpeed(SERVO_PIN_2, 5);
    
    // 初始位置
    servo.setAllAngles(90, 90, 0, 0);
    servo.waitUntilAllStopped();
    delay(1000);
    
    // 180度舵机演示
    Serial.println("180度舵机演示");
    servo.moveTo(SERVO_PIN_1, 0, 5);
    servo.moveTo(SERVO_PIN_2, 180, 5);
    servo.waitUntilAllStopped();
    delay(1000);
    
    servo.moveTo(SERVO_PIN_1, 180, 5);
    servo.moveTo(SERVO_PIN_2, 0, 5);
    servo.waitUntilAllStopped();
    delay(1000);
    
    // 360度舵机演示
    Serial.println("360度舵机演示");
    servo.rotate(SERVO_PIN_3, 50);   // 舵机3正向旋转，速度50%
    servo.rotate(SERVO_PIN_4, -50);  // 舵机4反向旋转，速度50%
    delay(2000);
    
    servo.stop(SERVO_PIN_3);         // 停止舵机3
    servo.stop(SERVO_PIN_4);         // 停止舵机4
    delay(1000);
    
    // 批量操作演示
    Serial.println("批量操作演示");
    servo.moveToAll(45, 90, 135, 180, 5);  // 所有舵机移动到不同角度
    servo.waitUntilAllStopped();
    delay(1000);
    
    // 状态查询演示
    Serial.println("状态查询演示");
    for (int i = 0; i < 4; i++) {
        ServoPin pin = (ServoPin)i;
        ServoStatus status = servo.getStatus(pin);
        
        Serial.print("舵机");
        Serial.print(i + 1);
        Serial.print(": 类型=");
        Serial.print(status.type == SERVO_180_DEG ? "180度" : "360度");
        Serial.print(", 当前角度=");
        Serial.print(status.current_angle);
        Serial.print(", 目标角度=");
        Serial.print(status.target_angle);
        Serial.print(", 移动中=");
        Serial.print(status.is_moving ? "是" : "否");
        Serial.print(", 速度=");
        Serial.print(status.speed);
        Serial.print(", PWM值=");
        Serial.println(status.pwm_value);
    }
}

void loop() {
    // 循环演示舵机运动
    static uint8_t demo = 0;
    
    switch (demo) {
        case 0:
            // 180度舵机往复运动
            servo.moveTo(SERVO_PIN_1, 0, 5);
            servo.moveTo(SERVO_PIN_2, 180, 5);
            servo.waitUntilAllStopped();
            break;
            
        case 1:
            servo.moveTo(SERVO_PIN_1, 180, 5);
            servo.moveTo(SERVO_PIN_2, 0, 5);
            servo.waitUntilAllStopped();
            break;
            
        case 2:
            // 360度舵机往复运动
            servo.rotate(SERVO_PIN_3, 50);
            servo.rotate(SERVO_PIN_4, -50);
            delay(2000);
            break;
            
        case 3:
            servo.stop(SERVO_PIN_3);
            servo.stop(SERVO_PIN_4);
            delay(1000);
            break;
    }
    
    demo = (demo + 1) % 4;
}
4. 功能说明
4.1 舵机选择
selectServo(ServoPin pin): 选择要控制的舵机（SERVO_PIN_1到SERVO_PIN_4）
getSelectedServo(): 获取当前选择的舵机
4.2 180度舵机控制
setAngle(uint16_t angle): 设置当前选择的舵机角度（0-180度）
setAngle(ServoPin pin, uint16_t angle): 设置指定舵机角度
getAngle(): 获取当前选择的舵机角度
getAngle(ServoPin pin): 获取指定舵机角度
moveTo(uint16_t angle, uint8_t speed): 以指定速度移动当前选择的舵机到目标角度
moveTo(ServoPin pin, uint16_t angle, uint8_t speed): 以指定速度移动指定舵机到目标角度
4.3 360度舵机控制
setSpeed(uint8_t speed): 设置当前选择的舵机速度（0-100）
setSpeed(ServoPin pin, uint8_t speed): 设置指定舵机速度
rotate(int8_t speed): 旋转当前选择的舵机（-100到100）
rotate(ServoPin pin, int8_t speed): 旋转指定舵机
stop(): 停止当前选择的舵机
stop(ServoPin pin): 停止指定舵机
stopAll(): 停止所有舵机
4.4 通用控制
setMoveSpeed(uint8_t speed): 设置当前选择的舵机移动速度（1-10）
setMoveSpeed(ServoPin pin, uint8_t speed): 设置指定舵机移动速度
getMoveSpeed(): 获取当前选择的舵机移动速度
getMoveSpeed(ServoPin pin): 获取指定舵机移动速度
setPWM(uint16_t pwm): 设置当前选择的舵机PWM值（1000-2000）
setPWM(ServoPin pin, uint16_t pwm): 设置指定舵机PWM值
getPWM(): 获取当前选择的舵机PWM值
getPWM(ServoPin pin): 获取指定舵机PWM值
getStatus(): 获取当前选择的舵机状态
getStatus(ServoPin pin): 获取指定舵机状态
4.5 高级控制
isMoving(): 检查当前选择的舵机是否正在移动
isMoving(ServoPin pin): 检查指定舵机是否正在移动
isAnyMoving(): 检查是否有任何舵机正在移动
waitUntilStopped(): 等待当前选择的舵机停止移动
waitUntilStopped(ServoPin pin): 等待指定舵机停止移动
waitUntilAllStopped(): 等待所有舵机停止移动
4.6 批量操作
setAllAngles(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4): 设置所有舵机角度
setAllTypes(ServoType type1, ServoType type2, ServoType type3, ServoType type4): 设置所有舵机类型
setAllSpeeds(uint8_t speed1, uint8_t speed2, uint8_t speed3, uint8_t speed4): 设置所有舵机速度
moveToAll(uint16_t angle1, uint16_t angle2, uint16_t angle3, uint16_t angle4, uint8_t speed): 移动所有舵机到指定角度
5. 注意事项
I2C地址：确保与STM32从机设置的地址一致
舵机选择：在控制舵机前，确保选择了正确的舵机
舵机类型：在使用前正确设置每个舵机的类型
角度范围：180度舵机的角度范围为0-180度
速度范围：360度舵机的速度范围为-100到100
PWM范围：PWM值范围为1000-2000微秒
电源供应：确保舵机有足够的电源供应
通信错误处理：在实际应用中可能需要添加更多的错误处理机制
批量操作：批量操作可能会增加I2C通信负载，根据实际情况调整
这个库提供了完整的4舵机控制功能，支持180度和360度舵机，通过I2C协议与STM32从机通信。您可以根据实际需求进行扩展或修改。


好的，我来提供STM32从机的完整代码，支持4个舵机引脚的控制。这个代码将包括I2C从机通信、PWM输出和舵机控制逻辑。

1. 头文件 (i2c_servo.h)
c
 

#ifndef __I2C_SERVO_H
#define __I2C_SERVO_H

#include "stm32f1xx_hal.h"

// I2C配置
#define I2C_SLAVE_ADDRESS        0x30    // 从机地址
#define I2C_BUFFER_SIZE          32      // I2C缓冲区大小

// 舵机配置
#define SERVO_MIN_PULSE          1000    // 最小脉冲宽度(μs)
#define SERVO_MAX_PULSE          2000    // 最大脉冲宽度(μs)
#define SERVO_REFRESH_PERIOD     20000   // 刷新周期(μs)
#define SERVO_COUNT             4        // 舵机数量

// 舵机引脚定义
#define SERVO1_PIN              GPIO_PIN_8
#define SERVO1_PORT             GPIOA
#define SERVO1_TIM              TIM1
#define SERVO1_CHANNEL          TIM_CHANNEL_1

#define SERVO2_PIN              GPIO_PIN_9
#define SERVO2_PORT             GPIOA
#define SERVO2_TIM              TIM1
#define SERVO2_CHANNEL          TIM_CHANNEL_2

#define SERVO3_PIN              GPIO_PIN_10
#define SERVO3_PORT             GPIOA
#define SERVO3_TIM              TIM1
#define SERVO3_CHANNEL          TIM_CHANNEL_3

#define SERVO4_PIN              GPIO_PIN_11
#define SERVO4_PORT             GPIOA
#define SERVO4_TIM              TIM1
#define SERVO4_CHANNEL          TIM_CHANNEL_4

// I2C命令定义
typedef enum {
    CMD_SET_ANGLE = 0x01,       // 设置舵机角度
    CMD_GET_ANGLE = 0x02,       // 获取舵机角度
    CMD_SET_SPEED = 0x03,       // 设置舵机速度
    CMD_GET_STATUS = 0x04,      // 获取舵机状态
    CMD_SET_TYPE = 0x05,        // 设置舵机类型
    CMD_GET_TYPE = 0x06,        // 获取舵机类型
    CMD_SET_PWM = 0x07,         // 直接设置PWM值
    CMD_GET_PWM = 0x08,         // 获取当前PWM值
    CMD_ROTATE_CONTINUOUS = 0x09,// 360度舵机连续旋转
    CMD_SET_SERVO_SELECT = 0x0A,// 选择舵机
    CMD_GET_SERVO_SELECT = 0x0B // 获取当前选择的舵机
} I2C_Command_TypeDef;

// 舵机类型定义
typedef enum {
    SERVO_180_DEG = 0,         // 180度舵机
    SERVO_360_DEG = 1          // 360度舵机
} Servo_Type_TypeDef;

// 舵机状态结构体
typedef struct {
    uint16_t current_angle;     // 当前角度(0-180度)或速度(0-100%)
    uint16_t target_angle;      // 目标角度或速度
    uint8_t  is_moving;         // 是否正在移动
    uint8_t  speed;             // 移动速度(1-10)
    uint8_t  type;              // 舵机类型
    uint16_t pwm_value;         // 当前PWM值
} Servo_Status_TypeDef;

// 舵机引脚定义
typedef enum {
    SERVO_PIN_1 = 0,
    SERVO_PIN_2 = 1,
    SERVO_PIN_3 = 2,
    SERVO_PIN_4 = 3,
    SERVO_PIN_ALL = 0xFF        // 所有舵机
} Servo_Pin_TypeDef;

// 函数声明
void I2C_Servo_Init(void);
void I2C_Servo_Process(void);
void Servo_SetAngle(uint8_t servo_id, uint16_t angle);
uint16_t Servo_GetAngle(uint8_t servo_id);
void Servo_SetSpeed(uint8_t servo_id, uint8_t speed);
void Servo_SetType(uint8_t servo_id, Servo_Type_TypeDef type);
Servo_Type_TypeDef Servo_GetType(uint8_t servo_id);
void Servo_SetPWM(uint8_t servo_id, uint16_t pwm);
uint16_t Servo_GetPWM(uint8_t servo_id);
void Servo_RotateContinuous(uint8_t servo_id, int8_t speed);
Servo_Status_TypeDef Servo_GetStatus(uint8_t servo_id);
void Servo_Select(uint8_t servo_id);
uint8_t Servo_GetSelected(void);

#endif /* __I2C_SERVO_H */
2. 实现文件 (i2c_servo.c)
c
 

#include "i2c_servo.h"

// 私有变量
static I2C_HandleTypeDef hi2c1;
static TIM_HandleTypeDef htim1;
static uint8_t i2c_rx_buffer[I2C_BUFFER_SIZE];
static uint8_t i2c_tx_buffer[I2C_BUFFER_SIZE];
static volatile uint8_t i2c_rx_len = 0;
static volatile uint8_t i2c_tx_len = 0;
static volatile uint8_t i2c_cmd_received = 0;

// 舵机状态数组
static Servo_Status_TypeDef servo_status[SERVO_COUNT] = {0};
static uint8_t selected_servo = 0;  // 当前选择的舵机

// 私有函数声明
static void I2C_Slave_Init(void);
static void PWM_Init(void);
static void Process_I2C_Command(void);
static void Update_Servo_Position(uint8_t servo_id);
static void Update_All_Servos(void);
static void Set_PWM_Value(uint8_t servo_id, uint16_t pwm);

// 初始化函数
void I2C_Servo_Init(void) {
    // 初始化舵机状态
    for (int i = 0; i < SERVO_COUNT; i++) {
        servo_status[i].current_angle = 90;
        servo_status[i].target_angle = 90;
        servo_status[i].is_moving = 0;
        servo_status[i].speed = 5;
        servo_status[i].type = SERVO_180_DEG;
        servo_status[i].pwm_value = 1500;
    }
    
    I2C_Slave_Init();
    PWM_Init();
    
    // 初始化所有舵机到中间位置
    for (int i = 0; i < SERVO_COUNT; i++) {
        Servo_SetAngle(i, 90);
    }
}

// I2C从机初始化
static void I2C_Slave_Init(void) {
    hi2c1.Instance = I2C1;
    hi2c1.Init.ClockSpeed = 100000;
    hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
    hi2c1.Init.OwnAddress1 = I2C_SLAVE_ADDRESS;
    hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
    hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
    hi2c1.Init.OwnAddress2 = 0;
    hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
    hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
    
    if (HAL_I2C_Init(&hi2c1) != HAL_OK) {
        Error_Handler();
    }
    
    // 使能I2C中断
    HAL_NVIC_SetPriority(I2C1_EV_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(I2C1_EV_IRQn);
    HAL_NVIC_SetPriority(I2C1_ER_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(I2C1_ER_IRQn);
}

// PWM初始化
static void PWM_Init(void) {
    TIM_OC_InitTypeDef sConfigOC = {0};
    
    htim1.Instance = TIM1;
    htim1.Init.Prescaler = 72-1;  // 72MHz/72 = 1MHz
    htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1.Init.Period = SERVO_REFRESH_PERIOD-1;
    htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1.Init.RepetitionCounter = 0;
    htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    
    if (HAL_TIM_PWM_Init(&htim1) != HAL_OK) {
        Error_Handler();
    }
    
    // 配置所有通道
    for (int i = 0; i < SERVO_COUNT; i++) {
        sConfigOC.OCMode = TIM_OCMODE_PWM1;
        sConfigOC.Pulse = (SERVO_MIN_PULSE + SERVO_MAX_PULSE) / 2;
        sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
        sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
        sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
        sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
        sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
        
        if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1 + i) != HAL_OK) {
            Error_Handler();
        }
    }
    
    // 启动所有PWM通道
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4);
}

// 设置舵机角度
void Servo_SetAngle(uint8_t servo_id, uint16_t angle) {
    if (servo_id >= SERVO_COUNT) return;
    
    if (angle > 180) angle = 180;
    
    servo_status[servo_id].target_angle = angle;
    servo_status[servo_id].is_moving = 1;
}

// 获取舵机角度
uint16_t Servo_GetAngle(uint8_t servo_id) {
    if (servo_id >= SERVO_COUNT) return 0;
    return servo_status[servo_id].current_angle;
}

// 设置舵机速度
void Servo_SetSpeed(uint8_t servo_id, uint8_t speed) {
    if (servo_id >= SERVO_COUNT) return;
    if (speed > 10) speed = 10;
    if (speed < 1) speed = 1;
    servo_status[servo_id].speed = speed;
}

// 设置舵机类型
void Servo_SetType(uint8_t servo_id, Servo_Type_TypeDef type) {
    if (servo_id >= SERVO_COUNT) return;
    servo_status[servo_id].type = type;
}

// 获取舵机类型
Servo_Type_TypeDef Servo_GetType(uint8_t servo_id) {
    if (servo_id >= SERVO_COUNT) return SERVO_180_DEG;
    return (Servo_Type_TypeDef)servo_status[servo_id].type;
}

// 设置PWM值
void Servo_SetPWM(uint8_t servo_id, uint16_t pwm) {
    if (servo_id >= SERVO_COUNT) return;
    
    if (pwm < SERVO_MIN_PULSE) pwm = SERVO_MIN_PULSE;
    if (pwm > SERVO_MAX_PULSE) pwm = SERVO_MAX_PULSE;
    
    servo_status[servo_id].pwm_value = pwm;
    Set_PWM_Value(servo_id, pwm);
}

// 获取PWM值
uint16_t Servo_GetPWM(uint8_t servo_id) {
    if (servo_id >= SERVO_COUNT) return 1500;
    return servo_status[servo_id].pwm_value;
}

// 360度舵机连续旋转
void Servo_RotateContinuous(uint8_t servo_id, int8_t speed) {
    if (servo_id >= SERVO_COUNT) return;
    
    if (servo_status[servo_id].type != SERVO_360_DEG) {
        servo_status[servo_id].type = SERVO_360_DEG;
    }
    
    // 限制速度范围
    if (speed > 100) speed = 100;
    if (speed < -100) speed = -100;
    
    // 将速度映射到PWM值
    uint16_t pwm;
    if (speed == 0) {
        pwm = 1500;  // 停止
    } else if (speed > 0) {
        pwm = 1500 + (uint16_t)speed * 5;  // 1500-2000
    } else {
        pwm = 1500 + (uint16_t)speed * 5;  // 1000-1500
    }
    
    Servo_SetPWM(servo_id, pwm);
    servo_status[servo_id].current_angle = abs(speed);
    servo_status[servo_id].target_angle = abs(speed);
    servo_status[servo_id].is_moving = (speed != 0);
}

// 获取舵机状态
Servo_Status_TypeDef Servo_GetStatus(uint8_t servo_id) {
    if (servo_id >= SERVO_COUNT) {
        Servo_Status_TypeDef empty_status = {0};
        return empty_status;
    }
    return servo_status[servo_id];
}

// 选择舵机
void Servo_Select(uint8_t servo_id) {
    if (servo_id < SERVO_COUNT) {
        selected_servo = servo_id;
    }
}

// 获取当前选择的舵机
uint8_t Servo_GetSelected(void) {
    return selected_servo;
}

// 主处理函数
void I2C_Servo_Process(void) {
    // 处理I2C命令
    if (i2c_cmd_received) {
        Process_I2C_Command();
        i2c_cmd_received = 0;
    }
    
    // 更新所有舵机位置
    Update_All_Servos();
}

// 处理I2C命令
static void Process_I2C_Command(void) {
    if (i2c_rx_len < 1) return;
    
    uint8_t cmd = i2c_rx_buffer[0];
    uint8_t servo_id = selected_servo;
    uint16_t value;
    
    switch (cmd) {
        case CMD_SET_ANGLE:
            if (i2c_rx_len >= 3) {
                value = (i2c_rx_buffer[1] << 8) | i2c_rx_buffer[2];
                Servo_SetAngle(servo_id, value);
            }
            break;
            
        case CMD_GET_ANGLE:
            value = Servo_GetAngle(servo_id);
            i2c_tx_buffer[0] = (value >> 8) & 0xFF;
            i2c_tx_buffer[1] = value & 0xFF;
            i2c_tx_len = 2;
            break;
            
        case CMD_SET_SPEED:
            if (i2c_rx_len >= 2) {
                Servo_SetSpeed(servo_id, i2c_rx_buffer[1]);
            }
            break;
            
        case CMD_GET_STATUS:
            {
                Servo_Status_TypeDef status = Servo_GetStatus(servo_id);
                i2c_tx_buffer[0] = (status.current_angle >> 8) & 0xFF;
                i2c_tx_buffer[1] = status.current_angle & 0xFF;
                i2c_tx_buffer[2] = (status.target_angle >> 8) & 0xFF;
                i2c_tx_buffer[3] = status.target_angle & 0xFF;
                i2c_tx_buffer[4] = status.is_moving;
                i2c_tx_buffer[5] = status.speed;
                i2c_tx_buffer[6] = status.type;
                i2c_tx_buffer[7] = (status.pwm_value >> 8) & 0xFF;
                i2c_tx_buffer[8] = status.pwm_value & 0xFF;
                i2c_tx_len = 9;
            }
            break;
            
        case CMD_SET_TYPE:
            if (i2c_rx_len >= 2) {
                Servo_SetType(servo_id, (Servo_Type_TypeDef)i2c_rx_buffer[1]);
            }
            break;
            
        case CMD_GET_TYPE:
            i2c_tx_buffer[0] = Servo_GetType(servo_id);
            i2c_tx_len = 1;
            break;
            
        case CMD_SET_PWM:
            if (i2c_rx_len >= 3) {
                value = (i2c_rx_buffer[1] << 8) | i2c_rx_buffer[2];
                Servo_SetPWM(servo_id, value);
            }
            break;
            
        case CMD_GET_PWM:
            value = Servo_GetPWM(servo_id);
            i2c_tx_buffer[0] = (value >> 8) & 0xFF;
            i2c_tx_buffer[1] = value & 0xFF;
            i2c_tx_len = 2;
            break;
            
        case CMD_ROTATE_CONTINUOUS:
            if (i2c_rx_len >= 2) {
                Servo_RotateContinuous(servo_id, (int8_t)i2c_rx_buffer[1]);
            }
            break;
            
        case CMD_SET_SERVO_SELECT:
            if (i2c_rx_len >= 2) {
                Servo_Select(i2c_rx_buffer[1]);
            }
            break;
            
        case CMD_GET_SERVO_SELECT:
            i2c_tx_buffer[0] = Servo_GetSelected();
            i2c_tx_len = 1;
            break;
            
        default:
            break;
    }
}

// 更新所有舵机位置
static void Update_All_Servos(void) {
    for (int i = 0; i < SERVO_COUNT; i++) {
        Update_Servo_Position(i);
    }
}

// 更新单个舵机位置
static void Update_Servo_Position(uint8_t servo_id) {
    if (servo_id >= SERVO_COUNT) return;
    
    // 360度舵机不需要更新位置，由PWM直接控制
    if (servo_status[servo_id].type == SERVO_360_DEG) {
        return;
    }
    
    // 180度舵机位置更新
    if (!servo_status[servo_id].is_moving) return;
    
    // 计算步进值
    int16_t step = servo_status[servo_id].target_angle - servo_status[servo_id].current_angle;
    if (step != 0) {
        // 根据速度调整步进
        if (abs(step) > servo_status[servo_id].speed) {
            step = (step > 0) ? servo_status[servo_id].speed : -servo_status[servo_id].speed;
        }
        
        servo_status[servo_id].current_angle += step;
        
        // 转换为PWM值
        uint16_t pulse = SERVO_MIN_PULSE + 
                        (uint32_t)(servo_status[servo_id].current_angle) * 
                        (SERVO_MAX_PULSE - SERVO_MIN_PULSE) / 180;
        
        // 设置PWM占空比
        Set_PWM_Value(servo_id, pulse);
    }
    
    // 检查是否到达目标位置
    if (servo_status[servo_id].current_angle == servo_status[servo_id].target_angle) {
        servo_status[servo_id].is_moving = 0;
    }
}

// 设置PWM值
static void Set_PWM_Value(uint8_t servo_id, uint16_t pwm) {
    if (servo_id >= SERVO_COUNT) return;
    
    // 更新状态中的PWM值
    servo_status[servo_id].pwm_value = pwm;
    
    // 设置定时器比较值
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1 + servo_id, pwm);
}

// I2C事件中断处理函数
void I2C1_EV_IRQHandler(void) {
    HAL_I2C_EV_IRQHandler(&hi2c1);
}

// I2C错误中断处理函数
void I2C1_ER_IRQHandler(void) {
    HAL_I2C_ER_IRQHandler(&hi2c1);
}

// HAL I2C从机接收回调函数
void HAL_I2C_SlaveRxCpltCallback(I2C_HandleTypeDef *hi2c) {
    i2c_rx_len = hi2c->XferCount;
    i2c_cmd_received = 1;
}

// HAL I2C从机发送回调函数
void HAL_I2C_SlaveTxCpltCallback(I2C_HandleTypeDef *hi2c) {
    // 传输完成
}

// HAL I2C从机监听地址匹配回调函数
void HAL_I2C_AddrCallback(I2C_HandleTypeDef *hi2c, uint8_t TransferDirection, uint16_t AddrMatchCode) {
    if (TransferDirection == I2C_DIRECTION_TRANSMIT) {
        // 主机准备发送数据
        HAL_I2C_Slave_Sequential_Receive_IT(hi2c, i2c_rx_buffer, I2C_BUFFER_SIZE, I2C_FIRST_FRAME);
    } else {
        // 主机请求数据
        HAL_I2C_Slave_Sequential_Transmit_IT(hi2c, i2c_tx_buffer, i2c_tx_len, I2C_FIRST_FRAME);
    }
}
3. 主程序 (main.c)
c
 

#include "main.h"
#include "i2c_servo.h"

void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_I2C1_Init(void);
static void MX_TIM1_Init(void);

int main(void) {
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_I2C1_Init();
    MX_TIM1_Init();
    
    // 初始化I2C舵机控制
    I2C_Servo_Init();
    
    while (1) {
        // 处理I2C命令和更新舵机位置
        I2C_Servo_Process();
        HAL_Delay(10);
    }
}

void SystemClock_Config(void) {
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
    RCC_OscInitStruct.HSIState = RCC_HSI_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) {
        Error_Handler();
    }

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                                |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK) {
        Error_Handler();
    }
}

static void MX_GPIO_Init(void) {
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
}

static void MX_I2C1_Init(void) {
    hi2c1.Instance = I2C1;
    hi2c1.Init.ClockSpeed = 100000;
    hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
    hi2c1.Init.OwnAddress1 = I2C_SLAVE_ADDRESS;
    hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
    hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
    hi2c1.Init.OwnAddress2 = 0;
    hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
    hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
    if (HAL_I2C_Init(&hi2c1) != HAL_OK) {
        Error_Handler();
    }
}

static void MX_TIM1_Init(void) {
    TIM_ClockConfigTypeDef sClockSourceConfig = {0};
    TIM_MasterConfigTypeDef sMasterConfig = {0};
    TIM_OC_InitTypeDef sConfigOC = {0};
    TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

    htim1.Instance = TIM1;
    htim1.Init.Prescaler = 72-1;
    htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1.Init.Period = SERVO_REFRESH_PERIOD-1;
    htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1.Init.RepetitionCounter = 0;
    htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(&htim1) != HAL_OK) {
        Error_Handler();
    }
    sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_TIM_PWM_Init(&htim1) != HAL_OK) {
        Error_Handler();
    }
    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK) {
        Error_Handler();
    }
    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = (SERVO_MIN_PULSE + SERVO_MAX_PULSE) / 2;
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
    sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
    if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_2) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_3) != HAL_OK) {
        Error_Handler();
    }
    if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_4) != HAL_OK) {
        Error_Handler();
    }
    sBreakDeadTimeConfig.OffStateRunMode = TIM_OSSR_DISABLE;
    sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
    sBreakDeadTimeConfig.LockLevel = TIM_LOCKLEVEL_OFF;
    sBreakDeadTimeConfig.DeadTime = 0;
    sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
    sBreakDeadTimeConfig.BreakPolarity = TIM_BREAKPOLARITY_HIGH;
    sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
    if (HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig) != HAL_OK) {
        Error_Handler();
    }
}

void Error_Handler(void) {
    while (1) {
    }
}

#ifdef  USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line) {
}
#endif /* USE_FULL_ASSERT */
4. 功能说明
4.1 I2C通信协议
从机地址：0x30
支持的命令：
设置舵机角度 (CMD_SET_ANGLE)
获取舵机角度 (CMD_GET_ANGLE)
设置舵机速度 (CMD_SET_SPEED)
获取舵机状态 (CMD_GET_STATUS)
设置舵机类型 (CMD_SET_TYPE)
获取舵机类型 (CMD_GET_TYPE)
直接设置PWM值 (CMD_SET_PWM)
获取当前PWM值 (CMD_GET_PWM)
360度舵机连续旋转 (CMD_ROTATE_CONTINUOUS)
选择舵机 (CMD_SET_SERVO_SELECT)
获取当前选择的舵机 (CMD_GET_SERVO_SELECT)
4.2 舵机控制
支持4个舵机，每个舵机可以独立配置为180度或360度类型
180度舵机：
角度范围：0-180度
平滑移动到目标角度
可调节移动速度
360度舵机：
速度范围：-100到100（负值表示反向）
直接控制旋转方向和速度
4.3 PWM控制
PWM范围：1000-2000微秒
刷新率：50Hz（20000微秒）
使用TIM1的4个通道分别控制4个舵机
5. 注意事项
I2C地址：确保与主机设置的地址一致
舵机引脚：代码中使用PA8-PA11作为舵机信号输出，可根据需要修改
定时器配置：使用TIM1的4个通道输出PWM信号，可根据需要修改
电源供应：确保舵机有足够的电源供应，建议使用独立电源
舵机类型：使用前正确设置每个舵机的类型
通信错误处理：在实际应用中可能需要添加更多的错误处理机制
定时器精度：定时器配置会影响PWM输出的精度
这个STM32从机代码提供了完整的4舵机控制功能，支持180度和360度舵机，通过I2C协议与上位机通信。您可以根据具体的STM32型号和舵机参数进行相应的调