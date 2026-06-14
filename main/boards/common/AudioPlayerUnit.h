#ifndef AUDIO_PLAYER_UNIT_H
#define AUDIO_PLAYER_UNIT_H

#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include <cstdint>
#include <cstddef>

/**
 * 串口波特率
 */
#define UNIT_AUDIOPLAYER_BAUD 9600

/**
 * 播放模式
 */
enum class PlayMode : uint8_t {
    AllLoop = 0,
    SingleLoop,
    FolderLoop,
    Random,
    SingleStop,
    AllOnce,
    FolderOnce,
    Error = 0xFF
};

/**
 * 播放状态
 */
enum class PlayStatus : uint8_t {
    Stopped = 0,
    Playing,
    Paused,
    Error = 0xFF
};

/**
 * 存储设备类型
 */
enum class StorageDevice : uint8_t {
    UDisk = 1,
    SD,
    Flash,
    UDiskOrSD,
    FlashOrUDisk,
    FlashOrSD,
    Error = 0xFF
};

/**
 * 播放设备类型
 */
enum class PlayDevice : uint8_t {
    UDisk = 0,
    SD,
    Flash,
    Error = 0xFF
};

/**
 * @brief 音频播放器单元类
 */
class AudioPlayerUnit {
public:
    AudioPlayerUnit(uart_port_t uart_num, int tx_io_num, int rx_io_num);
    ~AudioPlayerUnit();

    // 初始化与响应
    bool begin();
    bool waitForResponse(uint32_t timeout_ms);

    // 播放控制
    PlayStatus checkPlayStatus();
    PlayStatus playAudio();
    PlayStatus pauseAudio();
    PlayStatus stopAudio();
    PlayStatus currentStatus ;

    uint16_t nextAudio();
    uint16_t previousAudio();
    uint16_t playAudioByIndex(uint16_t index);
    uint8_t playAudioByName(const char* name);

    // 音量
    void decreaseVolume();
    void increaseVolume();
    void setVolume(uint8_t volume);
    uint8_t getVolume();

    // 查询
    uint16_t getTotalAudioCount();
    uint16_t getCurrentAudioNumber();
    StorageDevice getStorageDevice();
    PlayDevice getPlayDevice();
    PlayMode getPlayMode();
    void setPlayMode(PlayMode mode);

    // 组合播放
    void startCombinePlay(uint8_t mode, uint8_t* input_data, size_t data_len);
    void endCombinePlay();

    // 睡眠
    bool intoSleepMode();

private:
    uart_port_t uart_num_;
    int tx_io_num_;
    int rx_io_num_;
    QueueHandle_t uart_queue_;
    SemaphoreHandle_t response_semaphore_;
    TaskHandle_t uart_task_handle_;

    uint8_t command_;
    uint8_t return_value_[2];
    bool has_return_value_;
    bool is_received_;
    uint8_t received_data_[32];
    size_t received_data_len_;
    uint8_t uart_rx_buffer_[32];
    size_t uart_rx_buffer_idx_;

    void sendCommand(uint8_t command, uint8_t* data, size_t data_len, uint8_t* return_value);
    void processReceivedData(uint8_t* data, size_t data_len);
    static void uartEventTaskWrapper(void* pvParameters);
    void uartEventTask();

    // 禁止拷贝
    AudioPlayerUnit(const AudioPlayerUnit&) = delete;
    AudioPlayerUnit& operator=(const AudioPlayerUnit&) = delete;
};

#endif // AUDIO_PLAYER_UNIT_H
