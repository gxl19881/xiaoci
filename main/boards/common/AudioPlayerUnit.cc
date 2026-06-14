#include "AudioPlayerUnit.h"
#include "esp_log.h"
#include <cstring>

static const char* TAG = "AudioPlayerUnit";

AudioPlayerUnit::AudioPlayerUnit(uart_port_t uart_num, int tx_io_num, int rx_io_num)
    : uart_num_(uart_num), tx_io_num_(tx_io_num), rx_io_num_(rx_io_num),
      uart_queue_(nullptr), response_semaphore_(nullptr), uart_task_handle_(nullptr),
      command_(0), has_return_value_(false), is_received_(false),
      received_data_len_(0), uart_rx_buffer_idx_(0)
{
    memset(received_data_, 0, sizeof(received_data_));
    memset(return_value_, 0, sizeof(return_value_));
    memset(uart_rx_buffer_, 0, sizeof(uart_rx_buffer_));
}

AudioPlayerUnit::~AudioPlayerUnit() {
    if (uart_task_handle_) vTaskDelete(uart_task_handle_);
    if (response_semaphore_) vSemaphoreDelete(response_semaphore_);
    if (uart_queue_) uart_driver_delete(uart_num_);
}

bool AudioPlayerUnit::begin() {
    uart_config_t uart_config = {
        .baud_rate = UNIT_AUDIOPLAYER_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    if (uart_param_config(uart_num_, &uart_config) != ESP_OK) {
        ESP_LOGE(TAG, "UART param config failed");
        return false;
    }
    if (uart_set_pin(uart_num_, tx_io_num_, rx_io_num_, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK) {
        ESP_LOGE(TAG, "UART set pin failed");
        return false;
    }
    const int UART_RX_BUF_SIZE = 1024;
    const int UART_TX_BUF_SIZE = 0;
    const int UART_EVENT_QUEUE_SIZE = 20;
    if (uart_driver_install(uart_num_, UART_RX_BUF_SIZE, UART_TX_BUF_SIZE, UART_EVENT_QUEUE_SIZE, &uart_queue_, 0) != ESP_OK) {
        ESP_LOGE(TAG, "UART driver install failed");
        return false;
    }

    response_semaphore_ = xSemaphoreCreateBinary();
    if (response_semaphore_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create response semaphore");
        uart_driver_delete(uart_num_);
        return false;
    }

    if (xTaskCreate(uartEventTaskWrapper, "audio_player_uart_task", 4096, this, 10, &uart_task_handle_) != pdPASS) {
        ESP_LOGE(TAG, "Failed to create UART event task");
        vSemaphoreDelete(response_semaphore_);
        uart_driver_delete(uart_num_);
        return false;
    }

    uart_flush_input(uart_num_);
    setVolume(20);
    setPlayMode(PlayMode::AllLoop);
    return true;
}

void AudioPlayerUnit::sendCommand(uint8_t command, uint8_t* data, size_t data_len, uint8_t* return_value) {
    memset(received_data_, 0, sizeof(received_data_));
    is_received_ = false;

    uint8_t message[32];
    message[0] = command;
    message[1] = (~command) & 0xFF;
    message[2] = data_len;
    if (data_len && data) memcpy(&message[3], data, data_len);
    uint8_t sum = 0;
    for (size_t i = 0; i < 3 + data_len; i++) sum += message[i];
    message[3 + data_len] = sum & 0xFF;

    command_ = command;
    if (return_value) {
        return_value_[0] = return_value[0];
        return_value_[1] = return_value[1];
        has_return_value_ = true;
    } else {
        has_return_value_ = false;
    }

    uart_write_bytes(uart_num_, (const char*)message, 4 + data_len);
}

void AudioPlayerUnit::processReceivedData(uint8_t* data, size_t data_len) {
    if (data_len < 6 || data_len > sizeof(uart_rx_buffer_)) return;
    uint8_t current_cmd = data[0];
    uint8_t current_cmd_inv = data[1];
    uint8_t payload_len = data[2];
    size_t expected_frame_len = 6 + payload_len;

    if (data_len < expected_frame_len) return;
    bool header_ok = false;
    if ((current_cmd == 0x0A && command_ == 0x05) ||
        (current_cmd == command_ && current_cmd_inv == ((~command_) & 0xFF))) {
        header_ok = true;
    }
    bool valid_rv = true;
    if (has_return_value_) valid_rv = (data[3] == return_value_[0] && data[4] == return_value_[1]);
    uint8_t calculated_checksum = 0;
    for (size_t i = 0; i < expected_frame_len - 1; i++) calculated_checksum += data[i];
    bool checksum_ok = (data[expected_frame_len - 1] == (calculated_checksum & 0xFF));

    if (header_ok && valid_rv && checksum_ok) {
        received_data_len_ = payload_len;
        memcpy(received_data_, &data[5], received_data_len_);
        is_received_ = true;
        if (response_semaphore_) xSemaphoreGive(response_semaphore_);
    }
}

void AudioPlayerUnit::uartEventTaskWrapper(void* pvParameters) {
    static_cast<AudioPlayerUnit*>(pvParameters)->uartEventTask();
}

void AudioPlayerUnit::uartEventTask() {
    uart_event_t event;
    uint8_t dtmp[32];
    for (;;) {
        if (xQueueReceive(uart_queue_, &event, portMAX_DELAY)) {
            switch (event.type) {
                case UART_DATA: {
                    int read_len = uart_read_bytes(uart_num_, dtmp, event.size, 0);
                    if (read_len > 0) processReceivedData(dtmp, read_len);
                    break;
                }
                case UART_FIFO_OVF:
                case UART_BUFFER_FULL: {
                    uart_flush_input(uart_num_);
                    xQueueReset(uart_queue_);
                    uart_rx_buffer_idx_ = 0;
                    break;
                }
                default: break;
            }
        }
    }
    vTaskDelete(NULL);
}

bool AudioPlayerUnit::waitForResponse(uint32_t timeout_ms) {
    if (xSemaphoreTake(response_semaphore_, pdMS_TO_TICKS(timeout_ms)) == pdTRUE) {
        return is_received_;
    } else {
        is_received_ = false;
        return false;
    }
}

PlayStatus AudioPlayerUnit::checkPlayStatus() {
    uint8_t d[] = {0x00};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayStatus>(received_data_[0]);
    return PlayStatus::Error;
}

PlayStatus AudioPlayerUnit::playAudio() {
    uint8_t d[] = {0x01};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayStatus>(received_data_[0]);
    return PlayStatus::Error;
}

PlayStatus AudioPlayerUnit::pauseAudio() {
    uint8_t d[] = {0x02};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayStatus>(received_data_[0]);
    return PlayStatus::Error;
}

PlayStatus AudioPlayerUnit::stopAudio() {
    uint8_t d[] = {0x03};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayStatus>(received_data_[0]);
    return PlayStatus::Error;
}

uint16_t AudioPlayerUnit::nextAudio() {
    uint8_t d[]  = {0x05};
    uint8_t rv[] = {0x03, 0x0E};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(600)) return (uint16_t)(received_data_[0] << 8 | received_data_[1]);
    return 0xFFFF;
}

uint16_t AudioPlayerUnit::previousAudio() {
    uint8_t d[]  = {0x04};
    uint8_t rv[] = {0x03, 0x0E};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(600)) return (uint16_t)(received_data_[0] << 8 | received_data_[1]);
    return 0xFFFF;
}

uint16_t AudioPlayerUnit::playAudioByIndex(uint16_t index) {
    uint8_t d[]  = {0x06, (uint8_t)((index >> 8) & 0xFF), (uint8_t)(index & 0xFF)};
    uint8_t rv[] = {0x03, 0x0E};
    sendCommand(0x04, d, 3, rv);
    if (waitForResponse(500)) return (uint16_t)(received_data_[0] << 8 | received_data_[1]);
    return 0xFFFF;
}

uint8_t AudioPlayerUnit::playAudioByName(const char* name) {
    uint8_t buf[32]  = {0};
    buf[0] = 0x07;
    size_t len = strlen(name);
    if (len > 30) len = 30;
    memcpy(&buf[1], name, len);
    uint8_t rv[] = {0x03, 0x0E};
    sendCommand(0x04, buf, len + 1, rv);
    if (waitForResponse(500)) return received_data_[0];
    return 0xFF;
}

void AudioPlayerUnit::decreaseVolume() {
    uint8_t d[] = {0x03};
    sendCommand(0x06, d, 1, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

void AudioPlayerUnit::increaseVolume() {
    uint8_t d[] = {0x02};
    sendCommand(0x06, d, 1, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

void AudioPlayerUnit::setVolume(uint8_t volume) {
    uint8_t d[] = {0x01, volume};
    sendCommand(0x06, d, 2, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

uint8_t AudioPlayerUnit::getVolume() {
    uint8_t d[]  = {0x00};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x06, d, 1, rv);
    if (waitForResponse(600)) return received_data_[0];
    return 0xFF;
}

uint16_t AudioPlayerUnit::getTotalAudioCount() {
    uint8_t d[]  = {0x0D};
    uint8_t rv[] = {0x03, 0x0D};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return (uint16_t)(received_data_[0] << 8 | received_data_[1]);
    return 0xFFFF;
}

uint16_t AudioPlayerUnit::getCurrentAudioNumber() {
    uint8_t d[]  = {0x0E};
    uint8_t rv[] = {0x03, 0x0E};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return (uint16_t)(received_data_[0] << 8 | received_data_[1]);
    return 0xFFFF;
}

StorageDevice AudioPlayerUnit::getStorageDevice() {
    uint8_t d[]  = {0x08};
    uint8_t rv[] = {0x02, 0x08};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<StorageDevice>(received_data_[0]);
    return StorageDevice::Error;
}

PlayDevice AudioPlayerUnit::getPlayDevice() {
    uint8_t d[]  = {0x09};
    uint8_t rv[] = {0x02, 0x09};
    sendCommand(0x04, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayDevice>(received_data_[0]);
    return PlayDevice::Error;
}

PlayMode AudioPlayerUnit::getPlayMode() {
    uint8_t d[]  = {0x00};
    uint8_t rv[] = {0x02, 0x00};
    sendCommand(0x0B, d, 1, rv);
    if (waitForResponse(500)) return static_cast<PlayMode>(received_data_[0]);
    return PlayMode::Error;
}

void AudioPlayerUnit::setPlayMode(PlayMode mode) {
    uint8_t d[] = {0x01, static_cast<uint8_t>(mode)};
    sendCommand(0x0B, d, 2, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

void AudioPlayerUnit::startCombinePlay(uint8_t mode, uint8_t* input_data, size_t data_len) {
    if (data_len > 30) return;
    uint8_t buf[32] = {0};
    buf[0] = mode;
    memcpy(&buf[1], input_data, data_len);
    sendCommand(0x0C, buf, data_len + 1, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

void AudioPlayerUnit::endCombinePlay() {
    uint8_t d[] = {0x02};
    sendCommand(0x0C, d, 1, nullptr);
    vTaskDelay(pdMS_TO_TICKS(100));
}

bool AudioPlayerUnit::intoSleepMode() {
    uint8_t msg[] = {0x0D, 0xF3, 0x01, 0x01, 0x02};
    uart_write_bytes(uart_num_, (const char*)msg, sizeof(msg));
    return true;
}
