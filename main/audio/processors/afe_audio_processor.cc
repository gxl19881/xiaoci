#include "afe_audio_processor.h"
#include <esp_log.h>
#include <inttypes.h>

#define PROCESSOR_RUNNING 0x01

#define TAG "AfeAudioProcessor"

AfeAudioProcessor::AfeAudioProcessor()
    : afe_data_(nullptr) {
    event_group_ = xEventGroupCreate();
    
    // 根据配置设置默认降噪模式
#ifdef CONFIG_NOISE_REDUCTION_MILD
    noise_reduction_mode_ = NoiseReductionMode::MILD;
#elif CONFIG_NOISE_REDUCTION_AGGRESSIVE
    noise_reduction_mode_ = NoiseReductionMode::AGGRESSIVE;
#else
    noise_reduction_mode_ = NoiseReductionMode::MODERATE;
#endif

    // 根据配置启用自适应降噪
#ifdef CONFIG_ADAPTIVE_NOISE_REDUCTION
    adaptive_noise_reduction_ = true;
#else
    adaptive_noise_reduction_ = false;
#endif
}

void AfeAudioProcessor::Initialize(AudioCodec* codec, int frame_duration_ms) {
    codec_ = codec;
    frame_samples_ = frame_duration_ms * 16000 / 1000;

    // Pre-allocate output buffer capacity
    output_buffer_.reserve(frame_samples_);

    int ref_num = codec_->input_reference() ? 1 : 0;

    std::string input_format;
    for (int i = 0; i < codec_->input_channels() - ref_num; i++) {
        input_format.push_back('M');
    }
    for (int i = 0; i < ref_num; i++) {
        input_format.push_back('R');
    }

    srmodel_list_t *models = esp_srmodel_init("model");
    char* ns_model_name = esp_srmodel_filter(models, ESP_NSNET_PREFIX, NULL);
    char* vad_model_name = esp_srmodel_filter(models, ESP_VADN_PREFIX, NULL);
    ESP_LOGI(TAG, "SR models: ns=%s, vad=%s", ns_model_name ? ns_model_name : "none", vad_model_name ? vad_model_name : "none");
    
    afe_config_t* afe_config = afe_config_init(input_format.c_str(), NULL, AFE_TYPE_VC, AFE_MODE_HIGH_PERF);
    afe_config->aec_mode = AEC_MODE_VOIP_HIGH_PERF;
    
    // 根据配置选择VAD模式
#ifdef CONFIG_ENHANCED_VAD_SENSITIVITY
    afe_config->vad_mode = VAD_MODE_2; // 使用更严格的VAD模式，减少噪音误触发
    afe_config->vad_min_noise_ms = 200; // 增加最小噪音持续时间，提高稳定性
    afe_config->vad_min_speech_ms = 64; // 减少最小语音持续时间，提高响应速度
    afe_config->vad_delay_ms = 160; // 增加VAD延迟，确保捕获完整语音
#else
    afe_config->vad_mode = VAD_MODE_1; // 标准VAD模式
    afe_config->vad_min_noise_ms = 150;
    afe_config->vad_min_speech_ms = 80;
    afe_config->vad_delay_ms = 128;
#endif

    if (vad_model_name != nullptr) {
        afe_config->vad_model_name = vad_model_name;
    }

    // 强化噪声抑制配置
    if (ns_model_name != nullptr) {
        afe_config->ns_init = true;
        afe_config->ns_model_name = ns_model_name;
        afe_config->afe_ns_mode = AFE_NS_MODE_NET; // 使用神经网络降噪，效果更好
    } else {
        afe_config->ns_init = true; // 即使没有模型也启用基础降噪
        afe_config->afe_ns_mode = AFE_NS_MODE_WEBRTC; // 使用WebRTC降噪作为后备
    }
    ESP_LOGI(TAG, "Noise suppression %s", afe_config->ns_init ? "ENABLED (NSNet)" : "DISABLED");

    afe_config->afe_perferred_core = 1;
    afe_config->afe_perferred_priority = 1;
    afe_config->agc_init = true; // 启用自动增益控制
    afe_config->agc_mode = AFE_AGC_MODE_WEBRTC; // 使用WebRTC AGC
    afe_config->agc_compression_gain_db = 6; // 适中的压缩增益
    afe_config->agc_target_level_dbfs = 6; // 目标电平设置
    afe_config->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    afe_config->afe_linear_gain = 1.5f; // 适度提升线性增益以改善信噪比

#ifdef CONFIG_USE_DEVICE_AEC
    afe_config->aec_init = true;
    afe_config->vad_init = false;
#else
    afe_config->aec_init = false;
    afe_config->vad_init = true;
#endif

    afe_iface_ = esp_afe_handle_from_config(afe_config);
    afe_data_ = afe_iface_->create_from_config(afe_config);
    
    xTaskCreate([](void* arg) {
        auto this_ = (AfeAudioProcessor*)arg;
        this_->AudioProcessorTask();
        vTaskDelete(NULL);
    }, "audio_communication", 8192, this, 3, NULL);
}

AfeAudioProcessor::~AfeAudioProcessor() {
    if (afe_data_ != nullptr) {
        afe_iface_->destroy(afe_data_);
    }
    vEventGroupDelete(event_group_);
}

size_t AfeAudioProcessor::GetFeedSize() {
    if (afe_data_ == nullptr) {
        return 0;
    }
    return afe_iface_->get_feed_chunksize(afe_data_) * codec_->input_channels();
}

void AfeAudioProcessor::Feed(std::vector<int16_t>&& data) {
    if (afe_data_ == nullptr) {
        return;
    }
    afe_iface_->feed(afe_data_, data.data());
}

void AfeAudioProcessor::Start() {
    xEventGroupSetBits(event_group_, PROCESSOR_RUNNING);
}

void AfeAudioProcessor::Stop() {
    xEventGroupClearBits(event_group_, PROCESSOR_RUNNING);
    if (afe_data_ != nullptr) {
        afe_iface_->reset_buffer(afe_data_);
    }
}

bool AfeAudioProcessor::IsRunning() {
    return xEventGroupGetBits(event_group_) & PROCESSOR_RUNNING;
}

void AfeAudioProcessor::OnOutput(std::function<void(std::vector<int16_t>&& data)> callback) {
    output_callback_ = callback;
}

void AfeAudioProcessor::OnVadStateChange(std::function<void(bool speaking)> callback) {
    vad_state_change_callback_ = callback;
}

void AfeAudioProcessor::AudioProcessorTask() {
    auto fetch_size = afe_iface_->get_fetch_chunksize(afe_data_);
    auto feed_size = afe_iface_->get_feed_chunksize(afe_data_);
    ESP_LOGI(TAG, "Audio communication task started, feed size: %d fetch size: %d",
        feed_size, fetch_size);

    while (true) {
        xEventGroupWaitBits(event_group_, PROCESSOR_RUNNING, pdFALSE, pdTRUE, portMAX_DELAY);

        auto res = afe_iface_->fetch_with_delay(afe_data_, portMAX_DELAY);
        if ((xEventGroupGetBits(event_group_) & PROCESSOR_RUNNING) == 0) {
            continue;
        }
        if (res == nullptr || res->ret_value == ESP_FAIL) {
            if (res != nullptr) {
                ESP_LOGI(TAG, "Error code: %d", res->ret_value);
            }
            continue;
        }

        // VAD state change and noise level monitoring
        if (vad_state_change_callback_) {
            if (res->vad_state == VAD_SPEECH && !is_speaking_) {
                is_speaking_ = true;
                vad_state_change_callback_(true);
            } else if (res->vad_state == VAD_SILENCE && is_speaking_) {
                is_speaking_ = false;
                vad_state_change_callback_(false);
            }
        }

        // 自适应降噪：监控背景噪音水平
        if (adaptive_noise_reduction_ && res->vad_state == VAD_SILENCE) {
            // 计算当前帧的噪音水平（RMS）
            uint32_t noise_level = 0;
            size_t samples = res->data_size / sizeof(int16_t);
            for (size_t i = 0; i < samples; i++) {
                int32_t sample = res->data[i];
                noise_level += (sample * sample);
            }
            noise_level /= samples;
            
            noise_level_accumulator_ += noise_level;
            noise_sample_count_++;
            
            // 每100帧评估一次噪音水平并调整降噪模式
            if (noise_sample_count_ >= 100) {
                uint32_t avg_noise_level = noise_level_accumulator_ / noise_sample_count_;
                
                NoiseReductionMode new_mode = noise_reduction_mode_;
                if (avg_noise_level > 5000000) { // 高噪音环境
                    new_mode = NoiseReductionMode::AGGRESSIVE;
                } else if (avg_noise_level > 1000000) { // 中等噪音环境
                    new_mode = NoiseReductionMode::MODERATE;
                } else { // 安静环境
                    new_mode = NoiseReductionMode::MILD;
                }
                
                if (new_mode != noise_reduction_mode_) {
                    ESP_LOGI(TAG, "Auto-adjusting noise reduction: %d -> %d (noise level: %" PRIu32 ")", 
                             static_cast<int>(noise_reduction_mode_), static_cast<int>(new_mode), avg_noise_level);
                    SetNoiseReductionMode(new_mode);
                }
                
                // 重置累计器
                noise_level_accumulator_ = 0;
                noise_sample_count_ = 0;
            }
        }

        if (output_callback_) {
            size_t samples = res->data_size / sizeof(int16_t);
            
            // Add data to buffer
            output_buffer_.insert(output_buffer_.end(), res->data, res->data + samples);
            
            // Output complete frames when buffer has enough data
            while (output_buffer_.size() >= frame_samples_) {
                if (output_buffer_.size() == frame_samples_) {
                    // If buffer size equals frame size, move the entire buffer
                    output_callback_(std::move(output_buffer_));
                    output_buffer_.clear();
                    output_buffer_.reserve(frame_samples_);
                } else {
                    // If buffer size exceeds frame size, copy one frame and remove it
                    output_callback_(std::vector<int16_t>(output_buffer_.begin(), output_buffer_.begin() + frame_samples_));
                    output_buffer_.erase(output_buffer_.begin(), output_buffer_.begin() + frame_samples_);
                }
            }
        }
    }
}

void AfeAudioProcessor::EnableDeviceAec(bool enable) {
    if (enable) {
#if CONFIG_USE_DEVICE_AEC
        afe_iface_->disable_vad(afe_data_);
        afe_iface_->enable_aec(afe_data_);
#else
        ESP_LOGE(TAG, "Device AEC is not supported");
#endif
    } else {
        afe_iface_->disable_aec(afe_data_);
        afe_iface_->enable_vad(afe_data_);
    }
}

void AfeAudioProcessor::SetNoiseReductionMode(NoiseReductionMode mode) {
    noise_reduction_mode_ = mode;
    ESP_LOGI(TAG, "Noise reduction mode set to: %d", static_cast<int>(mode));
    
    // 注意：动态调整VAD模式需要重新初始化AFE，这里仅记录模式设置
    // 在实际应用中，可以通过重新配置AFE或调用相应的控制接口来实现
    // 目前先通过日志输出来确认模式切换
}

void AfeAudioProcessor::SetAdaptiveNoiseReduction(bool enable) {
    adaptive_noise_reduction_ = enable;
    ESP_LOGI(TAG, "Adaptive noise reduction %s", enable ? "enabled" : "disabled");
    
    if (enable) {
        noise_level_accumulator_ = 0;
        noise_sample_count_ = 0;
    }
}
