/*
 * MCP Server Implementation
 * Reference: https://modelcontextprotocol.io/specification/2024-11-05
 */

#include "mcp_server.h"
#include <esp_log.h>
#include <esp_app_desc.h>
#include <algorithm>
#include <cstring>
#include <atomic>
#include <chrono>
#include <thread>
#include <esp_pthread.h>

#include "application.h"
#include "display.h"
#include "board.h"
#include "assets/lang_config.h"

#define TAG "MCP"

// 预览相关默认宏（若未在其它地方定义）
#ifndef CONFIG_CAMERA_PREVIEW_TIMEOUT_MS
#define CONFIG_CAMERA_PREVIEW_TIMEOUT_MS 2500
#endif
#ifndef CONFIG_CAMERA_PREVIEW_FPS
#define CONFIG_CAMERA_PREVIEW_FPS 10
#endif

#define DEFAULT_TOOLCALL_STACK_SIZE 6144

McpServer::McpServer()
{
}

McpServer::~McpServer()
{
    for (auto tool : tools_)
    {
        delete tool;
    }
    tools_.clear();
}

void McpServer::AddCommonTools()
{
    // To speed up the response time, we add the common tools to the beginning of
    // the tools list to utilize the prompt cache.
    // Backup the original tools list and restore it after adding the common tools.
    auto original_tools = std::move(tools_);
    auto &board = Board::GetInstance();

    AddTool("self.get_device_status",
            "Provides the real-time information of the device, including the current status of the audio speaker, screen, battery, network, etc.\n"
            "Use this tool for: \n"
            "1. Answering questions about current condition (e.g. what is the current volume of the audio speaker?)\n"
            "2. As the first step to control the device (e.g. turn up / down the volume of the audio speaker, etc.)",
            PropertyList(),
            [&board](const PropertyList &properties) -> ReturnValue
            {
                return board.GetDeviceStatusJson();
            });

    AddTool("self.audio_speaker.set_volume",
            "Set the volume of the audio speaker. If the current volume is unknown, you must call `self.get_device_status` tool first and then call this tool.",
            PropertyList({Property("volume", kPropertyTypeInteger, 0, 100)}),
            [&board](const PropertyList &properties) -> ReturnValue
            {
                auto codec = board.GetAudioCodec();
                codec->SetOutputVolume(properties["volume"].value<int>());
                return true;
            });

    auto backlight = board.GetBacklight();
    if (backlight)
    {
        AddTool("self.screen.set_brightness",
                "Set the brightness of the screen.",
                PropertyList({Property("brightness", kPropertyTypeInteger, 0, 100)}),
                [backlight](const PropertyList &properties) -> ReturnValue
                {
                    uint8_t brightness = static_cast<uint8_t>(properties["brightness"].value<int>());
                    backlight->SetBrightness(brightness, true);
                    return true;
                });
    }

    auto display = board.GetDisplay();
    if (display && !display->GetTheme().empty())
    {
        AddTool("self.screen.set_theme",
                "Set the theme of the screen. The theme can be `light` or `dark`.",
                PropertyList({Property("theme", kPropertyTypeString)}),
                [display](const PropertyList &properties) -> ReturnValue
                {
                    display->SetTheme(properties["theme"].value<std::string>().c_str());
                    return true;
                });
    }

    auto camera = board.GetCamera();
    if (camera)
    {
    AddTool("self.camera.take_photo",
                "Take a photo. Can optionally analyze it with AI, or cache it for later merging.\n"
                "Args:\n"
                "  `question`: The specific question or instruction for the AI analysis. If the user asks to 'merge and analyze X', this field MUST contain the specific instruction 'X' (e.g. 'identify the text', 'find the red car'), NOT just 'take photo' or 'merge'. It must describe the FINAL analysis goal.\n"
                "  `count`: The number of photos to take in sequence. Default is 1. If the user asks to take multiple photos (e.g. 'take two photos', '拍两张'), you MUST set `count` to that number. The system will automatically handle the sequence (alert -> preview -> cache -> repeat -> merge -> analyze). Do NOT call this tool multiple times for a batch request.\n"
                "  `need_analyze`: Default true. Set to `false` if the user says 'first take', 'take photo first', 'just take', 'don't analyze', 'take the first one', '先拍', '先拍一张', or implies a sequence of photos.\n"
                "  `operation`: Optional. 'analyze' (default), 'cache' (take and cache), 'merge_and_analyze' (merge cached photos and analyze). If user says 'merge' or 'analyze all', use 'merge_and_analyze'. If user says 'take first', 'next', 'second', 'third', '先拍', '再拍', use 'cache'.\n"
                "CRITICAL: If `count` > 1, the tool will return the FINAL analysis result of the merged photos. You should NOT ask the user to take the next photo. You should directly present the analysis result. The 'cache' operation is ONLY for manual step-by-step photo taking (count=1). If operation is 'cache' AND count=1, you MUST STOP after the tool returns, reply to the user confirming the photo is cached, and ASK for the next instruction.\n"
                "Return:\n"
                "  Result.",
        PropertyList({
            Property("question", kPropertyTypeString, std::string("")),
            Property("count", kPropertyTypeInteger, 1),
            Property("need_analyze", kPropertyTypeBoolean, true),
            Property("operation", kPropertyTypeString, std::string("analyze"))
        }),
                [camera](const PropertyList &properties) -> ReturnValue {
                    std::string operation = "analyze";
                    try {
                        operation = properties["operation"].value<std::string>();
                    } catch (...) {}

                    std::string question;
                    try {
                        question = properties["question"].value<std::string>();
                    } catch (...) {
                        question = "";
                    }

                    int count = 1;
                    try {
                        count = properties["count"].value<int>();
                    } catch (...) {}
                    if (count < 1) count = 1;

                    // Heuristic: Auto-detect count from question if count is 1
                    // Detect "拍两张", "拍2张", "两张照片", "2张照片", "一共要拍两张" etc.
                    if (count == 1) {
                        if (question.find("拍两张") != std::string::npos || 
                            question.find("拍2张") != std::string::npos ||
                            question.find("两张照片") != std::string::npos ||
                            question.find("2张照片") != std::string::npos ||
                            question.find("一共要拍两张") != std::string::npos) {
                            count = 2;
                            ESP_LOGW(TAG, "Heuristic: Detected 'take 2 photos', setting count=2");
                        } else if (question.find("拍三张") != std::string::npos || 
                                   question.find("拍3张") != std::string::npos ||
                                   question.find("三张照片") != std::string::npos ||
                                   question.find("3张照片") != std::string::npos) {
                            count = 3;
                            ESP_LOGW(TAG, "Heuristic: Detected 'take 3 photos', setting count=3");
                        }
                    }

                    // ----------------------------------------------------------------
                    // 2. 严格校验：防止 "第2题" 误触发 count=2
                    // 只有当问题中明确包含量的单位（如“张”）或“合并”意图时，才允许 count > 1
                    // ----------------------------------------------------------------
                    if (count > 1) {
                         bool implies_multiple = false;
                         // 检查中文关键词
                         if (question.find("张") != std::string::npos || 
                             question.find("合并") != std::string::npos ||
                             question.find("连续") != std::string::npos ||
                             question.find("和") != std::string::npos ||  // 拍A和B
                             // 检查英文关键词
                             question.find("photos") != std::string::npos ||
                             question.find("pictures") != std::string::npos ||
                             question.find("merge") != std::string::npos ||
                             question.find("sequence") != std::string::npos ||
                             question.find("both") != std::string::npos || 
                             question.find("all") != std::string::npos) {
                             implies_multiple = true;
                         }

                         // 特殊情况：如果 count > 1 且未找到明确关键词，则降级为 1
                         if (!implies_multiple) {
                             ESP_LOGW(TAG, "Count is %d but question '%s' lacks keywords (张/merge), forcing count=1", count, question.c_str());
                             count = 1;
                         }
                    }

                    ESP_LOGI(TAG, "Tool self.camera.take_photo called with count=%d, operation=%s", count, operation.c_str());

                    bool need_analyze = true;
                    try {
                        need_analyze = properties["need_analyze"].value<bool>();
                    } catch (...) {}

                    // 修复逻辑：如果 operation 为 cache，强制 count=1
                    // 原因：cache 模式意味着分步拍摄（追加到缓存），而 count>1 的逻辑设计为“新的一组拍摄”（会清空缓存）。
                    // 如果 LLM 在分步拍摄的第二步错误地发送了 count=2（可能是受“拍两张”的历史上下文影响），
                    // 会导致清空第一张照片，且进入多张拍摄循环，用户只拍了一张后系统会卡在等待第二张，导致 Busy 错误。
                    if (operation == "cache" && count > 1) {
                        ESP_LOGW(TAG, "Operation is cache, forcing count=1 to support step-by-step and preserve cache");
                        count = 1;
                    }

                    // Multi-shot sequence logic
                    if (count > 1) {
                        // 如果之前有任务残留导致 busy，尝试强制复位
                        if (camera->CacheCurrentFrame() == false) { // 尝试用 CacheCurrentFrame 检测是否 busy（会返回 false 并 log "Camera is busy"）
                           // 实际上 CacheCurrentFrame 内部会设置 busy，所以更应该直接检查 atom 状态，但接口受限
                           // 此处简化：只要进入新任务，就先强制复位清理旧状态
                           camera->ForceResetStatus();
                        }
                        
                        camera->ClearCachedPhotos();
                        for (int i = 0; i < count; ++i) {
                            char msg[64];
                            snprintf(msg, sizeof(msg), "正在拍摄第 %d/%d 张", i + 1, count);
                            Application::GetInstance().Alert("提示", msg, "neutral", Lang::Sounds::P3_POPUP);
                            
                            ESP_LOGI(TAG, "Tool self.camera.take_photo sequence %d/%d starting interactive preview", i + 1, count);
                            if (!camera->PreviewAndWaitConfirm(0, CONFIG_CAMERA_PREVIEW_FPS)) {
                                return "{\"success\": false, \"message\": \"canceled by user\"}";
                            }
                            
                            if (!camera->CacheCurrentFrame()) {
                                return "{\"success\": false, \"message\": \"Failed to cache photo\"}";
                            }
                        }
                        // 提示模型这是合并后的图片，避免模型被“先拍第一张”等提示词误导
                        auto& board = Board::GetInstance();
                        // auto display = board.GetDisplay();
                        // display->SetChatMessage("system", "照片正在识别中，请耐心等待……");

                        std::string merged_question = question + " (这是一张合并后的图片，包含了所有拍摄内容，请直接分析，忽略分步拍摄指令)";
                        return camera->ExplainCached(merged_question);
                    }

                    // 启发式修正：如果问题中包含“先拍”、“第一张”等关键词，且当前操作为默认的 analyze，则强制转换为 cache
                    // 避免 LLM 忽略 prompt 指令导致直接上传分析
                    if (operation == "analyze") {
                        if (question.find("先拍") != std::string::npos || 
                            question.find("第一张") != std::string::npos ||
                            question.find("take first") != std::string::npos ||
                            question.find("first one") != std::string::npos ||
                            question.find("再拍") != std::string::npos ||
                            question.find("第二张") != std::string::npos ||
                            question.find("第三张") != std::string::npos ||
                            question.find("next one") != std::string::npos ||
                            question.find("second one") != std::string::npos) {
                            ESP_LOGW(TAG, "Heuristic: Force operation to 'cache' based on question keywords");
                            operation = "cache";
                        }
                    }

                    // 兼容旧逻辑：如果 need_analyze=false 且 operation=analyze，则视为 cache
                    if (!need_analyze && operation == "analyze") {
                        operation = "cache";
                    }

                    ESP_LOGI(TAG, "Tool self.camera.take_photo: operation=%s", operation.c_str());

                    if (operation == "merge_and_analyze") {
                        return camera->ExplainCached(question);
                    }

                    // [Optimization] 如果是单次分析模式，拍摄前立即清空旧缓存以释放内存
                    if (operation == "analyze") {
                        // 强制复位任何可能卡住的状态
                        camera->ForceResetStatus();
                        camera->ClearCachedPhotos();
                    }

                    // 对于 analyze 和 cache 操作，都需要预览和拍照
                    ESP_LOGI(TAG, "Tool self.camera.take_photo starting interactive preview (A=confirm, B=cancel)");
                    Application::GetInstance().Alert("提示", "正在打开摄像头", "neutral", Lang::Sounds::P3_POPUP);
                    if (!camera->PreviewAndWaitConfirm(0, CONFIG_CAMERA_PREVIEW_FPS)) {
                        return "{\"success\": false, \"message\": \"canceled by user\"}";
                    }

                    // 若为 analyze 模式，立即显示识别中提示（满足用户需求：按下按键成功拍摄后出现提示）
                    if (operation != "cache") {
                        auto& board = Board::GetInstance();
                        // auto display = board.GetDisplay();
                        // display->SetChatMessage("system", "照片正在识别中，请耐心等待……");
                    }

                    if (operation == "cache") {
                        if (camera->CacheCurrentFrame()) {
                            return "{\"success\": true, \"message\": \"Photo cached. STOP. You MUST reply to the user now. Do NOT call any tool. Say: '第一张照片已暂存，请说拍下一张'\"}";
                        } else {
                            return "{\"success\": false, \"message\": \"Failed to cache photo\"}";
                        }
                    }

                    // operation == "analyze"
                    return camera->Explain(question);
                });
    AddTool("self.camera.recognize_number",
                "识别照片中的数字。当用户要求识别照片中的数字使用此工具，会自动识别照片中数字信息，如果是数学方程，需要直接给出详细的解答。\n"
                "参数:\n"
                "  `question`: 要识别的数字的问题\n"

                "返回:\n"
                "  数学字符、中英文字符，等。",
                // 同样将 question 设为可选
                PropertyList({Property("question", kPropertyTypeString, std::string(""))}),
                [camera](const PropertyList &properties) -> ReturnValue {
                    Application::GetInstance().Alert("提示", "正在打开摄像头", "neutral", Lang::Sounds::P3_POPUP);
                    if (!camera->PreviewAndWaitConfirm(0, CONFIG_CAMERA_PREVIEW_FPS)) {
                        return "{\"success\": false, \"message\": \"canceled by user\"}";
                    }

                    // 立即显示识别中提示
                    auto& board = Board::GetInstance();
                    // auto display = board.GetDisplay();
                    // display->SetChatMessage("system", "照片正在识别中，请耐心等待……");

                    // 由 Explain 内部完成拍照与分辨率选择，这里不再先行 Capture，避免帧缓冲尺寸错配
                    // question 参数为可选；若缺失则使用空字符串
                    std::string question;
                    try {
                        question = properties["question"].value<std::string>();
                    } catch (...) {
                        question = "";
                    }
                    return camera->Explain(question);
                });

    }

    auto music = board.GetMusic();
    if (music)
    {
        AddTool("self.music.play_song",
                "播放指定的歌曲。当用户要求播放音乐时使用此工具，会自动获取歌曲详情并开始流式播放。\n"
                "参数:\n"
                "  `song_name`: 要播放的歌曲名称。\n"
                "返回:\n"
                "  播放状态信息，不需确认，立刻播放歌曲。",
                PropertyList({Property("song_name", kPropertyTypeString)}),
                [music](const PropertyList &properties) -> ReturnValue
                {
                    auto song_name = properties["song_name"].value<std::string>();
                    if (!music->Download(song_name))
                    {
                        return "{\"success\": false, \"message\": \"获取音乐资源失败\"}";
                    }
                    auto download_result = music->GetDownloadResult();
                    ESP_LOGD(TAG, "Music details result: %s", download_result.c_str());
                    return true;
                });
    }

    if (music)
    {
        AddTool("self.music.play_radio",
                "播放指定或者此工具自动匹配的电台。当用户要求播电台时使用此工具，会自动开始流式播放。\n"
                "参数:\n"
                "  `radio_name`: 要播放的电台名称。\n"
                "  `radio_id`: 电台ID。\n"
                "返回:\n"
                "  播放状态信息，不需确认，立刻播放。",
                PropertyList({
                    Property("radio_name", kPropertyTypeString),
                    Property("radio_id", kPropertyTypeString) // 添加电台ID参数
                }),
                [music](const PropertyList &properties) -> ReturnValue
                {
                    auto radio_name = properties["radio_name"].value<std::string>();
                    auto radio_id = properties["radio_id"].value<std::string>(); // 获取电台ID

                    // 优先使用电台ID
                    if (!radio_id.empty())
                    {
                        if (!music->Download(radio_name, radio_id))
                        { // 传递空歌名和电台ID
                            return "{\"success\": false, \"message\": \"获取电台资源失败\"}";
                        }
                    }
                    auto download_result = music->GetDownloadResult();
                    ESP_LOGD(TAG, "Music details result: %s", download_result.c_str());
                    return true;
                });
    }

    // Restore the original tools list to the end of the tools list
    tools_.insert(tools_.end(), original_tools.begin(), original_tools.end());
}

void McpServer::AddTool(McpTool *tool)
{
    // Prevent adding duplicate tools
    if (std::find_if(tools_.begin(), tools_.end(), [tool](const McpTool *t)
                     { return t->name() == tool->name(); }) != tools_.end())
    {
        ESP_LOGW(TAG, "Tool %s already added", tool->name().c_str());
        return;
    }

    ESP_LOGI(TAG, "Add tool: %s", tool->name().c_str());
    tools_.push_back(tool);
}

void McpServer::AddTool(const std::string &name, const std::string &description, const PropertyList &properties, std::function<ReturnValue(const PropertyList &)> callback)
{
    AddTool(new McpTool(name, description, properties, callback));
}

void McpServer::ParseMessage(const std::string &message)
{
    cJSON *json = cJSON_Parse(message.c_str());
    if (json == nullptr)
    {
        ESP_LOGE(TAG, "Failed to parse MCP message: %s", message.c_str());
        return;
    }
    ParseMessage(json);
    cJSON_Delete(json);
}

void McpServer::ParseCapabilities(const cJSON *capabilities)
{
    auto vision = cJSON_GetObjectItem(capabilities, "vision");
    if (cJSON_IsObject(vision))
    {
        auto url = cJSON_GetObjectItem(vision, "url");
        auto token = cJSON_GetObjectItem(vision, "token");
        if (cJSON_IsString(url))
        {
            auto camera = Board::GetInstance().GetCamera();
            if (camera)
            {
                std::string url_str = std::string(url->valuestring);
                std::string token_str;
                if (cJSON_IsString(token))
                {
                    token_str = std::string(token->valuestring);
                }
                camera->SetExplainUrl(url_str, token_str);
            }
        }
    }
}

void McpServer::ParseMessage(const cJSON *json)
{
    // Check JSONRPC version
    auto version = cJSON_GetObjectItem(json, "jsonrpc");
    if (version == nullptr || !cJSON_IsString(version) || strcmp(version->valuestring, "2.0") != 0)
    {
        ESP_LOGE(TAG, "Invalid JSONRPC version: %s", version ? version->valuestring : "null");
        return;
    }

    // Check method
    auto method = cJSON_GetObjectItem(json, "method");
    if (method == nullptr || !cJSON_IsString(method))
    {
        ESP_LOGE(TAG, "Missing method");
        return;
    }

    auto method_str = std::string(method->valuestring);
    if (method_str.find("notifications") == 0)
    {
        return;
    }

    // Check params
    auto params = cJSON_GetObjectItem(json, "params");
    if (params != nullptr && !cJSON_IsObject(params))
    {
        ESP_LOGE(TAG, "Invalid params for method: %s", method_str.c_str());
        return;
    }

    auto id = cJSON_GetObjectItem(json, "id");
    if (id == nullptr || !cJSON_IsNumber(id))
    {
        ESP_LOGE(TAG, "Invalid id for method: %s", method_str.c_str());
        return;
    }
    auto id_int = id->valueint;

    if (method_str == "initialize")
    {
        if (cJSON_IsObject(params))
        {
            auto capabilities = cJSON_GetObjectItem(params, "capabilities");
            if (cJSON_IsObject(capabilities))
            {
                ParseCapabilities(capabilities);
            }
        }
        auto app_desc = esp_app_get_description();
        std::string message = "{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{\"tools\":{}},\"serverInfo\":{\"name\":\"" BOARD_NAME "\",\"version\":\"";
        message += app_desc->version;
        message += "\"}}";
        ReplyResult(id_int, message);
    }
    else if (method_str == "tools/list")
    {
        std::string cursor_str = "";
        if (params != nullptr)
        {
            auto cursor = cJSON_GetObjectItem(params, "cursor");
            if (cJSON_IsString(cursor))
            {
                cursor_str = std::string(cursor->valuestring);
            }
        }
        GetToolsList(id_int, cursor_str);
    }
    else if (method_str == "tools/call")
    {
        if (!cJSON_IsObject(params))
        {
            ESP_LOGE(TAG, "tools/call: Missing params");
            ReplyError(id_int, "Missing params");
            return;
        }
        auto tool_name = cJSON_GetObjectItem(params, "name");
        if (!cJSON_IsString(tool_name))
        {
            ESP_LOGE(TAG, "tools/call: Missing name");
            ReplyError(id_int, "Missing name");
            return;
        }
        auto tool_arguments = cJSON_GetObjectItem(params, "arguments");
        if (tool_arguments != nullptr && !cJSON_IsObject(tool_arguments))
        {
            ESP_LOGE(TAG, "tools/call: Invalid arguments");
            ReplyError(id_int, "Invalid arguments");
            return;
        }
            auto stack_size = cJSON_GetObjectItem(params, "stackSize");
            if (stack_size != nullptr && !cJSON_IsNumber(stack_size))
            {
                ESP_LOGE(TAG, "tools/call: Invalid stackSize");
                ReplyError(id_int, "Invalid stackSize");
                return;
            }
            // Optional timeout in milliseconds for the tool call (watchdog). Default 35000ms.
            int timeout_ms = 125000;
            auto timeout_item = cJSON_GetObjectItem(params, "timeoutMs");
            if (timeout_item != nullptr) {
                if (!cJSON_IsNumber(timeout_item)) {
                    ESP_LOGE(TAG, "tools/call: Invalid timeoutMs");
                    ReplyError(id_int, "Invalid timeoutMs");
                    return;
                }
                timeout_ms = timeout_item->valueint;
                if (timeout_ms <= 0) timeout_ms = 125000;
            }
            ESP_LOGI(TAG, "tools/call: %s processing with timeout_ms=%d", tool_name->valuestring, timeout_ms);
            DoToolCall(id_int, std::string(tool_name->valuestring), tool_arguments, stack_size ? stack_size->valueint : DEFAULT_TOOLCALL_STACK_SIZE, timeout_ms);
    }
    else
    {
        ESP_LOGE(TAG, "Method not implemented: %s", method_str.c_str());
        ReplyError(id_int, "Method not implemented: " + method_str);
    }
}

void McpServer::ReplyResult(int id, const std::string &result)
{
    // If result is not a valid JSON value, wrap it as a JSON string to avoid breaking JSON-RPC payload
    auto is_json_value = [](const std::string &s) -> bool {
        if (s.empty()) return false;
        // Quick heuristic: valid JSON value typically starts with { [ " t f n - digit
        char c = 0;
        for (char ch : s) { if (!isspace((unsigned char)ch)) { c = ch; break; } }
        if (c == '{' || c == '[' || c == '"' || c == 't' || c == 'f' || c == 'n' || c == '-' || (c >= '0' && c <= '9')) {
            cJSON *tmp = cJSON_Parse(s.c_str());
            if (tmp) { cJSON_Delete(tmp); return true; }
        }
        return false;
    };
    auto json_escape = [](const std::string &s) -> std::string {
        std::string out; out.reserve(s.size() + 16);
        out.push_back('"');
        for (unsigned char ch : s) {
            switch (ch) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (ch < 0x20) {
                        char buf[7];
                        snprintf(buf, sizeof(buf), "\\u%04x", ch);
                        out += buf;
                    } else {
                        out.push_back((char)ch);
                    }
            }
        }
        out.push_back('"');
        return out;
    };

    std::string safe_result = is_json_value(result) ? result : json_escape(result);

    std::string payload = "{\"jsonrpc\":\"2.0\",\"id\":";
    payload += std::to_string(id) + ",\"result\":";
    payload += safe_result;
    payload += "}";
    ESP_LOGI(TAG, "ReplyResult id=%d, result_len=%u", id, (unsigned)safe_result.size());
    Application::GetInstance().SendMcpMessage(payload);
}

void McpServer::ReplyError(int id, const std::string &message)
{
    // Ensure error message is JSON-safe
    auto json_escape = [](const std::string &s) -> std::string {
        std::string out; out.reserve(s.size() + 16);
        out.push_back('"');
        for (unsigned char ch : s) {
            switch (ch) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (ch < 0x20) {
                        char buf[7];
                        snprintf(buf, sizeof(buf), "\\u%04x", ch);
                        out += buf;
                    } else {
                        out.push_back((char)ch);
                    }
            }
        }
        out.push_back('"');
        return out;
    };

    std::string payload = "{\"jsonrpc\":\"2.0\",\"id\":" + std::to_string(id) + ",\"error\":{\"message\":" + json_escape(message) + "}}";
    ESP_LOGW(TAG, "ReplyError id=%d, message_len=%u", id, (unsigned)message.size());
    Application::GetInstance().SendMcpMessage(payload);
}

void McpServer::GetToolsList(int id, const std::string &cursor)
{
    const int max_payload_size = 8000;
    std::string json = "{\"tools\":[";

    bool found_cursor = cursor.empty();
    auto it = tools_.begin();
    std::string next_cursor = "";

    while (it != tools_.end())
    {
        // 如果我们还没有找到起始位置，继续搜索
        if (!found_cursor)
        {
            if ((*it)->name() == cursor)
            {
                found_cursor = true;
            }
            else
            {
                ++it;
                continue;
            }
        }

        // 添加tool前检查大小
        std::string tool_json = (*it)->to_json() + ",";
        if (json.length() + tool_json.length() + 30 > max_payload_size)
        {
            // 如果添加这个tool会超出大小限制，设置next_cursor并退出循环
            next_cursor = (*it)->name();
            break;
        }

        json += tool_json;
        ++it;
    }

    if (json.back() == ',')
    {
        json.pop_back();
    }

    if (json.back() == '[' && !tools_.empty())
    {
        // 如果没有添加任何tool，返回错误
        ESP_LOGE(TAG, "tools/list: Failed to add tool %s because of payload size limit", next_cursor.c_str());
        ReplyError(id, "Failed to add tool " + next_cursor + " because of payload size limit");
        return;
    }

    if (next_cursor.empty())
    {
        json += "]}";
    }
    else
    {
        json += "],\"nextCursor\":\"" + next_cursor + "\"}";
    }

    ReplyResult(id, json);
}

void McpServer::DoToolCall(int id, const std::string &tool_name, const cJSON *tool_arguments, int stack_size, int timeout_ms)
{
    // [Fix] 针对相机工具（self.camera.take_photo），如果遇到工具正在运行（上一轮未正常释放），
    // 强制复位状态，允许新请求进入。这是为了防止相机任务卡死导致后续所有请求被拒。
    if (tool_running_.load())
    {
        if (tool_name == "self.camera.take_photo") {
            ESP_LOGW(TAG, "tools/call: Force resetting stuck tool state for camera request");
            tool_running_.store(false);
            // 稍等一下让旧线程/任务有机会感知（如果还活着）
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }

    if (tool_running_.load())
    {
        ESP_LOGW(TAG, "tools/call: A tool is already running, reject new call %s", tool_name.c_str());
        // ReplyError(id, "Another tool is running");
        // Return a tool result indicating busy, so LLM knows what happened and can wait or retry later
        ReplyResult(id, "{\"success\": false, \"message\": \"System is busy processing previous request. Please wait.\"}");
        return;
    }

    auto tool_iter = std::find_if(tools_.begin(), tools_.end(),
                                  [&tool_name](const McpTool *tool)
                                  {
                                      return tool->name() == tool_name;
                                  });

    if (tool_iter == tools_.end())
    {
        ESP_LOGE(TAG, "tools/call: Unknown tool: %s", tool_name.c_str());
        ReplyError(id, "Unknown tool: " + tool_name);
        return;
    }

    PropertyList arguments = (*tool_iter)->properties();
    try
    {
        for (auto &argument : arguments)
        {
            bool found = false;
            if (cJSON_IsObject(tool_arguments))
            {
                auto value = cJSON_GetObjectItem(tool_arguments, argument.name().c_str());
                if (argument.type() == kPropertyTypeBoolean && cJSON_IsBool(value))
                {
                    argument.set_value<bool>(value->valueint == 1);
                    found = true;
                }
                else if (argument.type() == kPropertyTypeInteger && cJSON_IsNumber(value))
                {
                    argument.set_value<int>(value->valueint);
                    found = true;
                }
                else if (argument.type() == kPropertyTypeString && cJSON_IsString(value))
                {
                    argument.set_value<std::string>(value->valuestring);
                    found = true;
                }
            }

            if (!argument.has_default_value() && !found)
            {
                ESP_LOGE(TAG, "tools/call: Missing valid argument: %s", argument.name().c_str());
                ReplyError(id, "Missing valid argument: " + argument.name());
                return;
            }
        }
        // Robustness: ensure camera tools always have a 'question' property present
        if ((tool_name == "self.camera.take_photo" || tool_name == "self.camera.recognize_number")) {
            bool has_question = true;
            try { (void)arguments["question"]; }
            catch (const std::exception &) { has_question = false; }
            if (!has_question) {
                ESP_LOGW(TAG, "tools/call: inject default 'question' for %s", tool_name.c_str());
                arguments.AddProperty(Property("question", kPropertyTypeString, std::string("")));
            }
        }
        // Allow overriding timeout via arguments.timeoutMs as a fallback
        if (cJSON_IsObject(tool_arguments)) {
            auto tmo = cJSON_GetObjectItem(tool_arguments, "timeoutMs");
            if (cJSON_IsNumber(tmo) && tmo->valueint > 0 && tmo->valueint < 600000) {
                timeout_ms = tmo->valueint;
            }
        }
    }
    catch (const std::exception &e)
    {
        ESP_LOGE(TAG, "tools/call: %s", e.what());
        ReplyError(id, e.what());
        return;
    }

    // Configure thread stack/prio
    esp_pthread_cfg_t cfg = esp_pthread_get_default_config();
    cfg.thread_name = "tool_call";
    
    bool is_camera_tool = (tool_name.rfind("self.camera.", 0) == 0);

    // Try to use PSRAM for stack to save internal RAM
    // Note: Stack in PSRAM might be slower, but for tool calls (network/logic) it's usually fine.
    // We need to ensure CONFIG_SPIRAM_ALLOW_STACK_EXTERNAL_MEMORY is enabled in sdkconfig, 
    // but we can't check it at runtime easily. We assume if SPIRAM is present, we can try.
    // However, blindly setting it might fail if the config is not set.
    // Safe bet: If we have lots of PSRAM, try it.
    bool use_psram = false;
    if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) > 50000) {
        cfg.stack_alloc_caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
        // If in PSRAM, we can afford a larger stack to avoid overflow
        stack_size = 8192; 
        use_psram = true;
    } else {
        // Fallback to internal RAM
        if (is_camera_tool) {
            // 4KB is tight but necessary for internal RAM
            stack_size = 4096; 
        }
    }

    cfg.stack_size = stack_size;
    cfg.prio = 5;
    esp_pthread_set_cfg(&cfg);

    // Diagnostics
    size_t free_internal = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    size_t free_psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    ESP_LOGI(TAG, "tools/call: create thread %s stack=%d (in_ext=%d) free_internal=%u free_psram=%u", 
             tool_name.c_str(), stack_size, use_psram, (unsigned)free_internal, (unsigned)free_psram);

    // 内部RAM较低时，避免创建线程，直接同步执行以提升成功率（有些情况下 ~11KB 也会失败）
    // 但对于相机交互类工具（耗时且需等待用户输入），同步执行会阻塞网络/主循环导致断连，
    // 因此相机工具必须尝试创建线程，若失败则报错，不可回退到同步执行。
    // If we are using PSRAM for stack, we don't need to worry about internal RAM for the stack itself,
    // but TCB still uses internal RAM.
    if (!use_psram && free_internal < 10000 && !is_camera_tool) {
        ESP_LOGW(TAG, "tools/call: low internal RAM (%uB), run sync without thread", (unsigned)free_internal);
        try {
            auto result = (*tool_iter)->Call(arguments);
            ReplyResult(id, result);
        } catch (const std::exception &e) {
            ESP_LOGE(TAG, "tools/call(sync-lowmem): %s", e.what());
            ReplyError(id, e.what());
        }
        tool_running_.store(false);
        return;
    }

    tool_running_.store(true);
    auto replied = std::make_shared<std::atomic<bool>>(false);
    bool tool_thread_started = false;
    // 1) 尝试创建工具执行线程
    try {
        tool_call_thread_ = std::thread([this, id, tool_iter, arguments = std::move(arguments), replied]() mutable {
            ESP_LOGI(TAG, "tools/call: thread started, task_name=%s", pcTaskGetName(NULL));
            try {
                auto result = (*tool_iter)->Call(arguments);
                if (!replied->exchange(true)) {
                    ReplyResult(id, result);
                } else {
                    ESP_LOGW(TAG, "tools/call(inner): late result dropped id=%d", id);
                }
            } catch (const std::exception& e) {
                ESP_LOGE(TAG, "tools/call(inner): %s", e.what());
                if (!replied->exchange(true)) {
                    ReplyError(id, e.what());
                }
            }
            tool_running_.store(false);
        });
        tool_call_thread_.detach();
        tool_thread_started = true;
    } catch (const std::exception &e) {
        ESP_LOGE(TAG, "tools/call: tool thread create failed (%s)", e.what());
        
        if (is_camera_tool) {
            ESP_LOGE(TAG, "tools/call: camera tool cannot run sync, aborting");
            if (!replied->exchange(true)) {
                ReplyError(id, "Failed to create thread for camera tool (low memory)");
            }
        } else {
            ESP_LOGW(TAG, "tools/call: fallback to sync execution");
            // 创建工具线程失败，直接同步执行一次
            try {
                auto result = (*tool_iter)->Call(arguments);
                if (!replied->exchange(true)) {
                    ReplyResult(id, result);
                }
            } catch (const std::exception &e2) {
                ESP_LOGE(TAG, "tools/call(sync): %s", e2.what());
                if (!replied->exchange(true)) {
                    ReplyError(id, e2.what());
                }
            }
        }
        tool_running_.store(false);
        return;
    }

    // 2) 单独尝试创建看门狗线程（失败仅记录日志，不再二次执行工具）
    try {
        std::thread([this, id, replied, timeout_ms, tool_name]() {  // Capture tool_name
            if (timeout_ms <= 0) return;
            int slept = 0; const int step = 100;
            while (slept < timeout_ms) {
                if (replied->load()) return;
                std::this_thread::sleep_for(std::chrono::milliseconds(step));
                slept += step;
            }
            if (!replied->exchange(true)) {
                ESP_LOGW(TAG, "tools/call: timeout %d ms reached, sending ReplyError", timeout_ms);
                
                // [Added] 如果是相机工具超时，在设备端弹出提示
                if (tool_name == "self.camera.take_photo" || tool_name == "self.camera.recognize_number") {
                     Application::GetInstance().Schedule([tool_name]() {
                         // Application::GetInstance().Alert("提示", "识别超时，请重新拍摄", "error", Lang::Sounds::P3_ERR_REG);
                     });
                     
                     // 还要复位相机状态，防止下次调用被拒
                     auto camera = Board::GetInstance().GetCamera();
                     if (camera) {
                         camera->ForceResetStatus();
                     }
                }

                ReplyError(id, "Tool execution timed out");
                tool_running_.store(false);
            }
        }).detach();
    } catch (const std::exception &e) {
        ESP_LOGW(TAG, "tools/call: watchdog thread create failed (%s), continue without watchdog", e.what());
    }
}