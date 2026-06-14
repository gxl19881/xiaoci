#ifndef MIDIPLAYER_H
#define MIDIPLAYER_H

#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string>
#include <unordered_map>

// 音符结构体定义
typedef struct {
    const char* note;
    int freq;
} TONE;


#define BUZZER_PIN GPIO_NUM_4

class MidiPlayer {
public:
    // 构造函数和析构函数
    MidiPlayer(gpio_num_t pin);
    ~MidiPlayer();

    // 初始化和去初始化
    void init();
    void deinit();

    // 播放控制函数
    void play(int tempo, uint8_t looping, const char *song);
    void play(int tempo, uint8_t looping, const std::string& song_str);
    void setSong(const char *song);
    void pause();
    void resume();
    void stopPlayback();

    // 状态查询
    uint8_t isStop();
    bool isPaused() const;
    bool isTaskRunning() const;

    // 节奏控制
    void setTempo(int newTempo);
    int getTempo() const;

    // 歌曲选择
    void setMusicIndex(uint8_t index);
    void musicupdate();
    void stopTone();
    void printSongNotes(const char *song);
    void validateAndFixSongData(const char* song); 
    std::string fixMusicNotation(const std::string& input);

    // 静态成员
    static uint8_t musicIndex;

    // 歌曲数据声明（需要在外部定义）
    static const char* my_people_my_country;
    static const char* noname;
    static const char* turkish_march;
    static const char* demo_song;
    static const char* twinkle_star;

private:
    // 硬件相关
    gpio_num_t pinNumber;
    
    // 播放状态
    const char *currentSong;
    const char *songPos;
    bool stopped;
    bool paused;
    uint64_t lastTick;
    int currentTempo;

    // FreeRTOS任务相关
    TaskHandle_t playTaskHandle;
    bool taskRunning;
    int taskTempo;
    uint8_t taskLooping;
    std::string taskSong;

    // 音符频率映射
    std::unordered_map<std::string, int> tonesMap;

    // 内部函数
    int getFrequency(const char *note);
    void playNote(const char *note);
    void startTone(int freq);
    
    inline bool parseNextNote(const char** pos, char* note, int maxLen);

    // 静态任务函数
    static void playTaskFunction(void* parameter);
};

#endif // MIDIPLAYER_H
