#include "protocol.h"
#include "application.h"

#include <esp_log.h>

#define TAG "Protocol"

void Protocol::OnIncomingJson(std::function<void(const cJSON* root)> callback) {
    on_incoming_json_ = callback;
}

void Protocol::OnIncomingAudio(std::function<void(std::unique_ptr<AudioStreamPacket> packet)> callback) {
    on_incoming_audio_ = callback;
}

void Protocol::OnAudioChannelOpened(std::function<void()> callback) {
    on_audio_channel_opened_ = callback;
}

void Protocol::OnAudioChannelClosed(std::function<void()> callback) {
    on_audio_channel_closed_ = callback;
}

void Protocol::OnNetworkError(std::function<void(const std::string& message)> callback) {
    on_network_error_ = callback;
}

void Protocol::SetError(const std::string& message) {
    error_occurred_ = true;
    if (on_network_error_ != nullptr) {
        on_network_error_(message);
    }
}

void Protocol::SendAbortSpeaking(AbortReason reason) {
    const auto &sid = Application::GetInstance().GetStudentId();
    std::string message = "{\"session_id\":\"" + session_id_ + "\",\"type\":\"abort\"";
    if (!sid.empty()) {
        message += ",\"student_id\":\"" + sid + "\"";
    }
    if (reason == kAbortReasonWakeWordDetected) {
        message += ",\"reason\":\"wake_word_detected\"";
    }
    message += "}";
    SendText(message);
}

void Protocol::SendWakeWordDetected(const std::string& wake_word) {
    const auto &sid = Application::GetInstance().GetStudentId();
    std::string json = "{\"session_id\":\"" + session_id_ + 
                      "\",\"type\":\"listen\",\"state\":\"detect\",\"text\":\"" + wake_word + "\"";
    if (!sid.empty()) {
        json.pop_back(); // remove trailing '}'
        json += ",\"student_id\":\"" + sid + "\"}";
    }
    SendText(json);
}

void Protocol::SendStartListening(ListeningMode mode) {
    const auto &sid = Application::GetInstance().GetStudentId();
    std::string message = "{\"session_id\":\"" + session_id_ + "\"";
    message += ",\"type\":\"listen\",\"state\":\"start\"";
    if (mode == kListeningModeRealtime) {
        message += ",\"mode\":\"realtime\"";
    } else if (mode == kListeningModeAutoStop) {
        message += ",\"mode\":\"auto\"";
    } else {
        message += ",\"mode\":\"manual\"";
    }
    if (!sid.empty()) {
        message += ",\"student_id\":\"" + sid + "\"";
    }
    message += "}";
    SendText(message);
}

void Protocol::SendStopListening() {
    const auto &sid = Application::GetInstance().GetStudentId();
    std::string message = "{\"session_id\":\"" + session_id_ + "\",\"type\":\"listen\",\"state\":\"stop\"";
    if (!sid.empty()) {
        message += ",\"student_id\":\"" + sid + "\"";
    }
    message += "}";
    SendText(message);
}

void Protocol::SendMcpMessage(const std::string& payload) {
    const auto &sid = Application::GetInstance().GetStudentId();
    std::string message = "{\"session_id\":\"" + session_id_ + "\",\"type\":\"mcp\",\"payload\":" + payload;
    if (!sid.empty()) {
        message += ",\"student_id\":\"" + sid + "\"";
    }
    message += "}";
    ESP_LOGI(TAG, "SendMcpMessage bytes=%u", (unsigned)message.size());
    if (!SendText(message)) {
        ESP_LOGE(TAG, "SendMcpMessage failed (ws disconnected or send error)");
    }
}

bool Protocol::IsTimeout() const {
    const int kTimeoutSeconds = 120;
    auto now = std::chrono::steady_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::seconds>(now - last_incoming_time_);
    bool timeout = duration.count() > kTimeoutSeconds;
    if (timeout) {
        ESP_LOGE(TAG, "Channel timeout %ld seconds", (long)duration.count());
    }
    return timeout;
}
