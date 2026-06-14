#ifndef AFE_AUDIO_PROCESSOR_H
#define AFE_AUDIO_PROCESSOR_H

#include <esp_afe_sr_models.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/event_groups.h>

#include <string>
#include <vector>
#include <functional>

#include "audio_processor.h"
#include "audio_codec.h"

// 降噪模式枚举
enum class NoiseReductionMode {
    MILD = 0,       // 轻度降噪
    MODERATE = 1,   // 中度降噪  
    AGGRESSIVE = 2  // 强力降噪
};

class AfeAudioProcessor : public AudioProcessor {
public:
    AfeAudioProcessor();
    ~AfeAudioProcessor();

    void Initialize(AudioCodec* codec, int frame_duration_ms) override;
    void Feed(std::vector<int16_t>&& data) override;
    void Start() override;
    void Stop() override;
    bool IsRunning() override;
    void OnOutput(std::function<void(std::vector<int16_t>&& data)> callback) override;
    void OnVadStateChange(std::function<void(bool speaking)> callback) override;
    size_t GetFeedSize() override;
    void EnableDeviceAec(bool enable) override;
    
    // 新增降噪控制方法
    void SetNoiseReductionMode(NoiseReductionMode mode);
    NoiseReductionMode GetNoiseReductionMode() const { return noise_reduction_mode_; }
    void SetAdaptiveNoiseReduction(bool enable);
    bool IsAdaptiveNoiseReductionEnabled() const { return adaptive_noise_reduction_; }

private:
    EventGroupHandle_t event_group_ = nullptr;
    esp_afe_sr_iface_t* afe_iface_ = nullptr;
    esp_afe_sr_data_t* afe_data_ = nullptr;
    std::function<void(std::vector<int16_t>&& data)> output_callback_;
    std::function<void(bool speaking)> vad_state_change_callback_;
    AudioCodec* codec_ = nullptr;
    int frame_samples_ = 0;
    bool is_speaking_ = false;
    std::vector<int16_t> output_buffer_;
    NoiseReductionMode noise_reduction_mode_ = NoiseReductionMode::MODERATE;
    bool adaptive_noise_reduction_ = false;
    uint32_t noise_level_accumulator_ = 0;
    uint32_t noise_sample_count_ = 0;

    void AudioProcessorTask();
};

#endif 