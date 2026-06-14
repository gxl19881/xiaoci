#ifndef MCP_COMPLEX_H  // 添加头文件保护
#define MCP_COMPLEX_H

#include "board.h"
#include <esp_log.h>
#include <cJSON.h>
#include "esp_event.h"
#include "esp_wifi.h"
// #include "audio_player_unit_event.h"

class McpComplex 
{
private:
    std::string uid_ = "396355825";     //396355825
        int follower_count_ = -1;
    bool refresh_in_progress_ = false;
    esp_timer_handle_t clock_timer_handle_ = nullptr;

   std::string hitokoto_; 
   std::string from_;

   std::string everyday_soup_;
    // int follower_count_ = 0;

    bool wifi_connected_ = false; // 标记 Wi-Fi 状态

    bool RefreshFollowerCount();

    static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data);

    void OnWifiConnected();

    void OnWifiDisconnected();

    void UpdateFansCount();

    void InitializeEvent();
    bool get_hitokoto();
    bool get_note();
   
    std::string music_;


public:
 
    ~McpComplex()
    {
        if (clock_timer_handle_)
        {
            esp_timer_stop(clock_timer_handle_);
            esp_timer_delete(clock_timer_handle_);
            clock_timer_handle_ = nullptr;
        }

        esp_event_handler_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, &McpComplex::wifi_event_handler);
        esp_event_handler_unregister(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, &McpComplex::wifi_event_handler);
    }

    explicit McpComplex();
};

#endif // LED_STRIP_CONTROL_H
