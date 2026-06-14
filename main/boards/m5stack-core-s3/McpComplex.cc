#include "McpComplex.h"
#include "settings.h"
#include "mcp_server.h"
#include <esp_log.h>
#include "board.h"
#define TAG "McpComplex"

template <typename T, typename Deleter>
using ManagedPtr = std::unique_ptr<T, Deleter>;

// cJSON 特化的删除器
struct CJsonDeleter
{
    void operator()(cJSON *ptr) const
    {
        if (ptr)
        {
            cJSON_Delete(ptr);
        }
    }
};

// 使用模板别名定义 cJSON 智能指针
using CJsonPtr = ManagedPtr<cJSON, CJsonDeleter>;

bool McpComplex::RefreshFollowerCount()
{
    if (uid_.empty())
    {
        ESP_LOGE(TAG, "UID is not set");
        return false;
    }

    if (refresh_in_progress_)
    {
        ESP_LOGI(TAG, "Refresh already in progress");
        return false;
    }

    refresh_in_progress_ = true;

    auto &board = Board::GetInstance();
    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);

    std::string url = "https://api.bilibili.com/x/relation/stat?vmid=" + uid_;
    http->SetHeader("User-Agent", "Mozilla/5.0");

    if (!http->Open("GET", url))
    {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        http->Close();
        refresh_in_progress_ = false;
        return false;
    }

    std::string response = http->ReadAll();
    http->Close();

    ESP_LOGD(TAG, "Raw API response: %.*s...", 200, response.c_str());

    // 使用智能指针自动管理 cJSON 对象
    CJsonPtr root(cJSON_Parse(response.c_str()));
    if (root == nullptr)
    {
        const char *error_ptr = cJSON_GetErrorPtr();
        if (error_ptr != NULL)
        {
            ESP_LOGE(TAG, "JSON parse error before: %s", error_ptr);
        }
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *code = cJSON_GetObjectItem(root.get(), "code");
    if (code == NULL || code->valueint != 0)
    {
        ESP_LOGE(TAG, "API returned error code");
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *data = cJSON_GetObjectItem(root.get(), "data");
    if (data == NULL)
    {
        ESP_LOGE(TAG, "No data field in response");
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *follower = cJSON_GetObjectItem(data, "follower");
    if (follower == NULL)
    {
        ESP_LOGE(TAG, "No follower field in data");
        refresh_in_progress_ = false;
        return false;
    }

    follower_count_ = follower->valueint;
    ESP_LOGI(TAG, "B站用户 %s 的粉丝数：%d", uid_.c_str(), follower_count_);

    // 不再需要手动调用 cJSON_Delete，智能指针会自动释放内存
    refresh_in_progress_ = false;
    return true;
}

bool McpComplex::get_hitokoto()
{
    refresh_in_progress_ = true;
    auto &board = Board::GetInstance();
    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);

    // HttpPtr http(network->CreateHttp(0));  // 使用智能指针管理 HTTP 对象

    std::string url = "https://v1.hitokoto.cn/";
    http->SetHeader("User-Agent", "Mozilla/5.0");

    if (!http->Open("GET", url))
    {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        http->Close();
        refresh_in_progress_ = false;
        return false;
    }

    std::string response = http->ReadAll();
    http->Close();

    // 使用智能指针管理 cJSON 对象
    CJsonPtr root(cJSON_Parse(response.c_str()));
    if (root == nullptr)
    {
        ESP_LOGE(TAG, "Failed to parse JSON response");
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *hitokoto = cJSON_GetObjectItem(root.get(), "hitokoto");
    if (hitokoto && cJSON_IsString(hitokoto))
    {
        hitokoto_ = hitokoto->valuestring;
        from_ = cJSON_GetObjectItem(root.get(), "from")->valuestring;
        ESP_LOGI(TAG, "成功提取一言内容: %s", hitokoto_.c_str());
        ESP_LOGI(TAG, "出自: %s", from_.c_str());
    }

    // 不再需要手动调用 cJSON_Delete
    refresh_in_progress_ = false;
    return true;
}

bool McpComplex::get_note()
{
    refresh_in_progress_ = true;
    auto &board = Board::GetInstance();
    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);
    std::string url = "https://open.iciba.com/dsapi/";

    http->SetHeader("User-Agent", "Mozilla/5.0 (ESP32)");
    http->SetTimeout(10000);

    for (int retry = 0; retry < 3; retry++)
    {
        if (http->Open("GET", url))
            break;
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }

    std::string response = http->ReadAll();
    http->Close();

    if (response.empty())
    {
        ESP_LOGE(TAG, "收到空响应");
        refresh_in_progress_ = false;
        return false;
    }

    // 使用智能指针管理 cJSON 对象
    CJsonPtr root(cJSON_Parse(response.c_str()));
    if (!root)
    {
        ESP_LOGE(TAG, "JSON 解析失败");
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *content = cJSON_GetObjectItem(root.get(), "content");
    cJSON *note = cJSON_GetObjectItem(root.get(), "note");

    if (content && note && cJSON_IsString(content) && cJSON_IsString(note))
    {
        everyday_soup_ = std::string(content->valuestring) + "\n" + note->valuestring;
        ESP_LOGI(TAG, "成功获取鸡汤文: %s", everyday_soup_.c_str());
    }
    else
    {
        ESP_LOGE(TAG, "无效的 JSON 字段");
        refresh_in_progress_ = false;
        return false;
    }

    // 不再需要手动调用 cJSON_Delete
    refresh_in_progress_ = false;
    return true;
}

void McpComplex::wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    McpComplex *instance = static_cast<McpComplex *>(arg);

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP)
    {
        ESP_LOGI("BiliFans", "Wi-Fi connected, updating fans count...");
        instance->OnWifiConnected();
    }
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED)
    {
        ESP_LOGW("BiliFans", "Wi-Fi disconnected, pausing update timer...");
        instance->OnWifiDisconnected();
    }
}

void McpComplex::OnWifiConnected()
{
    wifi_connected_ = true;
    UpdateFansCount();
    if (clock_timer_handle_)
    {
        esp_timer_start_periodic(clock_timer_handle_, 5 * 60 * 1000000);
    }
}

void McpComplex::OnWifiDisconnected()
{
    wifi_connected_ = false;
    if (clock_timer_handle_)
    {
        esp_timer_stop(clock_timer_handle_);
    }
}

void McpComplex::UpdateFansCount()
{
    RefreshFollowerCount();
    if (follower_count_ < 0)
    {
        ESP_LOGE(TAG, "Failed to get fans count");
    }
    ESP_LOGI(TAG, "Fans count updated: %d", follower_count_);
}
void McpComplex::InitializeEvent()
{
    esp_timer_create_args_t clock_timer_args = {
        .callback = [](void *arg)
        {
            McpComplex *instance = (McpComplex *)(arg);
            instance->UpdateFansCount();
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "BiliFansUpdateTimer",
        .skip_unhandled_events = true};
    esp_timer_create(&clock_timer_args, &clock_timer_handle_);

    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &McpComplex::wifi_event_handler, this));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &McpComplex::wifi_event_handler, this));
}

McpComplex::McpComplex()
{
    // 从设置中读取亮度等级

    // audio_player_unit_begin(UART_NUM_1, 17, 18);
    // audio_player_unit_set_volume(25); //最大30
    // audio_player_unit_pause_audio();
    // audio_player_unit_play_audio();
    // audio_player_unit_set_play_mode(AUDIO_PLAYER_MODE_RANDOM);
    // // 初始化后操作

    auto &mcp_server = McpServer::GetInstance();

    // ----------------------------------------------------------------------------

    mcp_server.AddTool("self.audio_unit.current_songs",
                       "Get the currently playing song number of the music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法
                        return player->getCurrentAudioNumber(); });

    mcp_server.AddTool("self.audio_unit.total_songs",
                       "Get the total number of songs in the music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                        
                        return player->getTotalAudioCount(); });

    mcp_server.AddTool("self.audio_unit.set_volume",
                       "Set the volume of the external music player",
                       PropertyList({Property("volume", kPropertyTypeInteger, 0, 30)}), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        uint8_t volume_ = static_cast<uint8_t>(properties["volume"].value<int>());
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                        
                        player->setVolume(volume_);
                        return player->getVolume(); });

    mcp_server.AddTool("self.audio_unit.get_volume",
                       "Get the volume of the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                        
                        return player->getVolume(); });

    mcp_server.AddTool("self.audio_unit.decrease_volume",
                       "Decrease the volume of the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                        
                        player->decreaseVolume();
                        return player->getVolume(); });

    mcp_server.AddTool("self.audio_unit.increase_volume",
                       "Increase the volume of the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                       
                        player->increaseVolume();
                        return player->getVolume(); });

    mcp_server.AddTool("self.audio_unit.play_song",
                       "Start playing a song on the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法
                       player->playAudio();
                        return true; });

    mcp_server.AddTool("self.audio_unit.stop_song",
                       "Stop playing the current song on the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                       
                        player->stopAudio();
                        return true; });

    mcp_server.AddTool("self.audio_unit.previous_song",
                       "Play the previous song on the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                        
                        
                        player->previousAudio();
                        return true; });

    mcp_server.AddTool("self.audio_unit.next_song",
                       "Play the next song on the external music player",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        auto &board = Board::GetInstance();
                        auto *player = board.GetAudioPlayer(); // 假设有一个获取音频播放器的方法                       
                        
                        player->nextAudio();
 
                      return true; });


    // ... existing code ...
    //  ----------------------------------------------------------------------------

    mcp_server.AddTool("self.BilibiliFans.uid",
                       "B站用户ID",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { return uid_; });
    mcp_server.AddTool("self.BilibiliFans.set_uid",
                       "设置B站用户ID",
                       PropertyList({Property("uid", kPropertyTypeString)}), [this](const PropertyList &properties) -> ReturnValue
                       {
            uid_ = properties["uid"].value<std::string>();
            ESP_LOGI(TAG, "设置B站用户ID为: %s", uid_.c_str());
            return true; });
    mcp_server.AddTool("self.BilibiliFans.report_fansCount",
                       "汇报粉丝数量",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
                        UpdateFansCount();
                        return follower_count_; });

    mcp_server.AddTool("self.BilibiliFans.flash_fansCount",
                       "刷新粉丝数量",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       {
        ESP_LOGI(TAG, "刷新B站粉丝数量");
        UpdateFansCount();
        return true; });
    mcp_server.AddTool("self.tts",
                       "复读机功能当用户说TTS_{文本}例如TTS_{你好}那么提取文本你好返回给用户，不说其他废话，只说需要复读的内容\n"
                       "参数:\n"
                       "  `text`: 用户播放文本\n"
                       "功能:\n"
                       "  原样不修改重复用户说的话\n"
                       "返回:\n"
                       "  成功或失败的状态及提示信息",
                       PropertyList({Property("text", kPropertyTypeString)}),
                       [this](const PropertyList &properties) -> ReturnValue
                       {
                           // 1. 参数验证
                           std::string text = properties["text"].value<std::string>();
                           return "{\"success\": true, \"message\": \"" + std::string(text) + "\"}";
                       });
    mcp_server.AddTool("self.translator",
                       "同声传译功能当用户说翻译_{文本}例如翻译_{你好}那么提取文本并翻译成英语返回给用户，如果用户说的是英文就把所说内容翻译成中文，不说其他废话 \n"
                       "参数:\n"
                       "  `text`: 中英互译用户所说的文本\n"
                       "功能:\n"
                       "   中英互译用户所说的文本\n"
                       "返回:\n"
                       "  成功或失败的状态及提示信息",
                       PropertyList({Property("text", kPropertyTypeString)}),
                       [this](const PropertyList &properties) -> ReturnValue
                       {
                           // 1. 参数验证
                           std::string text = properties["text"].value<std::string>();
                           return "{\"success\": true, \"message\": \"" + std::string(text) + "\"}";
                       });

    mcp_server.AddTool("self.get_hitokoto",
                       "给我开心地随便说一句话，一言",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       {
                        get_hitokoto();
                           return hitokoto_; });
    mcp_server.AddTool("self.hitokoto_source",
                       "刚才随便说的那一句是出自哪里",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { return from_; });
    mcp_server.AddTool("self.get_note",
                       "获取每日中英对照鸡汤文",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       {
         get_note();
                           return  everyday_soup_; });
}
