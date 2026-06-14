#include "McpComplex.h"
#include "settings.h"
#include "mcp_server.h"
#include <esp_log.h>
#include "board.h"
#define TAG "McpComplex"

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

    // auto &board = Board::GetInstance();
    // auto http = board.CreateHttp();

    // auto http = Board::GetInstance()->CreateHttp(0);
    auto& board = Board::GetInstance();
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
    // Add response debugging
    ESP_LOGD(TAG, "Raw API response: %.*s...", 200, response.c_str());
    cJSON *root = cJSON_Parse(response.c_str());
    if (root == NULL)
    {
        // ESP_LOGE(TAG, "Failed to parse JSON response");
        const char *error_ptr = cJSON_GetErrorPtr();
        if (error_ptr != NULL)
        {
            ESP_LOGE(TAG, "JSON parse error before: %s", error_ptr);
        }
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *code = cJSON_GetObjectItem(root, "code");
    if (code == NULL || code->valueint != 0)
    {
        ESP_LOGE(TAG, "API returned error code");
        cJSON_Delete(root);
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *data = cJSON_GetObjectItem(root, "data");
    if (data == NULL)
    {
        ESP_LOGE(TAG, "No data field in response");
        cJSON_Delete(root);
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *follower = cJSON_GetObjectItem(data, "follower");
    if (follower == NULL)
    {
        ESP_LOGE(TAG, "No follower field in data");
        cJSON_Delete(root);
        refresh_in_progress_ = false;
        return false;
    }

    follower_count_ = follower->valueint;
    ESP_LOGI(TAG, "B站用户 %s 的粉丝数：%d", uid_.c_str(), follower_count_);

    cJSON_Delete(root);
    refresh_in_progress_ = false;
    return true;
}

bool McpComplex::get_hitokoto()
{

    refresh_in_progress_ = true;
    auto& board = Board::GetInstance();

    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);

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

    cJSON *root = cJSON_Parse(response.c_str());
    if (root == NULL)
    {
        ESP_LOGE(TAG, "Failed to parse JSON response");
        refresh_in_progress_ = false;
        return false;
    }

    cJSON *hitokoto = cJSON_GetObjectItem(root, "hitokoto");
    if (hitokoto && cJSON_IsString(hitokoto))
    {
        hitokoto_ = hitokoto->valuestring;
        from_ = cJSON_GetObjectItem(root, "from")->valuestring;
        ESP_LOGI(TAG, "成功提取一言内容: %s", hitokoto_.c_str());
        ESP_LOGI(TAG, "出自: %s", from_.c_str());
    }

    cJSON_Delete(root);
    refresh_in_progress_ = false;
    return true;
}

bool McpComplex::get_note()
{
    refresh_in_progress_ = true;
    auto& board = Board::GetInstance();
    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);
    std::string url = "https://open.iciba.com/dsapi/";

    // 添加 HTTPS 配置
    // http->SetSSLVerify(false);  // 禁用 SSL 证书验证
    http->SetHeader("User-Agent", "Mozilla/5.0 (ESP32)");
    http->SetTimeout(10000); // 设置 10 秒超时

    // if (!http->Open("GET", url)) {
    //     ESP_LOGE(TAG, "打开 HTTP 连接失败");
    //     http->Close();
    //     refresh_in_progress_ = false;
    //     return false;
    // }
    for (int retry = 0; retry < 3; retry++)
    {
        if (http->Open("GET", url))
            break;
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
    // 读取并检查响应
    std::string response = http->ReadAll();
    http->Close();

    if (response.empty())
    {
        ESP_LOGE(TAG, "收到空响应");
        refresh_in_progress_ = false;
        return false;
    }

    // 解析 JSON
    cJSON *root = cJSON_Parse(response.c_str());
    if (!root)
    {
        ESP_LOGE(TAG, "JSON 解析失败");
        refresh_in_progress_ = false;
        return false;
    }

    // 安全获取字段
    cJSON *content = cJSON_GetObjectItem(root, "content");
    cJSON *note = cJSON_GetObjectItem(root, "note");

    if (content && note && cJSON_IsString(content) && cJSON_IsString(note))
    {
        everyday_soup_ = std::string(content->valuestring) + "\n" + note->valuestring;
        ESP_LOGI(TAG, "成功获取鸡汤文: %s", everyday_soup_.c_str());
    }
    else
    {
        ESP_LOGE(TAG, "无效的 JSON 字段");
        cJSON_Delete(root);
        refresh_in_progress_ = false;
        return false;
    }

    cJSON_Delete(root);
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

McpComplex::McpComplex() : midiPlayer_(BUZZER_PIN)
{
    // 从设置中读取亮度等级
    InitializeEvent();

    midiPlayer_.init();
    midiPlayer_.play(500, 0, MidiPlayer::twinkle_star); // 500ms间隔播放

    auto &mcp_server = McpServer::GetInstance();

    mcp_server.AddTool("self.Midi.createMusic",
                       "你是音乐大师,按照用户要求创制midi音乐曲目,把曲目返回给用户,使用科学音高记号法，用逗号分割音符，如 'C4', 'A4' 等,每个八度从C开始到B结束,包含半音(升降号):C#、D#、F#、G#、A#，使用 '#' 表示静音(频率为0)。"
                       "曲目完整准确,音符200个以上,不得使用中文逗号"
                       "例如小星星是 'C4,C4,G4,G4,A4,A4,G4,F4,F4,E4,E4,D4,D4,C4'",
                       PropertyList({Property("music", kPropertyTypeString)}), [this](const PropertyList &properties) -> ReturnValue
                       {
            music_ = properties["music"].value<std::string>();
            ESP_LOGI(TAG, "创编的曲目内容为: %s", music_.c_str());

 
            // this->midiPlayer_.printSongNotes(music_f);
            // music_ = this->midiPlayer_.fixMusicNotation(music_);
            this->midiPlayer_.printSongNotes(music_.c_str());
            this->midiPlayer_.play(150, 0, music_.c_str()); // 使用成员变量

            return true; });

    mcp_server.AddTool("self.Midi.playMidi",
                       "播放N首midi曲目,把曲目编号返回给用户,如第1首返回'1'",
                       PropertyList({Property("index", kPropertyTypeInteger)}), [this](const PropertyList &properties) -> ReturnValue
                       {
            uint8_t  index_ = properties["index"].value<int>();
            ESP_LOGI(TAG, "播放第%d首曲目", index_);
            this->midiPlayer_.setMusicIndex(index_);
            this->midiPlayer_.musicupdate();

            return true; });

    mcp_server.AddTool("self.Midi.stop",
                       "停止播放midi曲目",
                       PropertyList(), [this](const PropertyList &properties) -> ReturnValue
                       { 
            this->midiPlayer_.stopPlayback() ;
                        
                        return true; });

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
                       { return follower_count_; });

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
