#include "MidiPlayer.h"
#include <string.h>
#include <stdio.h>
#define TAG "MidiPlayer"
// 定义 LEDC 通道和定时器
#define LEDC_CHANNEL LEDC_CHANNEL_2
#define LEDC_TIMER   LEDC_TIMER_1
#define LEDC_MODE    LEDC_LOW_SPEED_MODE


// 歌曲数据定义（示例数据，您需要根据实际情况替换）
const char *MidiPlayer::demo_song = "#,#,A#4,#,F5,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,#,#,A#4,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,A#4,#,F5,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,#,#,A#4,#,D#5,#,G5,#,F5,#,#,D#5,#,#,F5,#,A#4,#,F5,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,#,#,A#4,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,A#4,#,F5,#,D#5,#,A#4,#,D5,#,#,D5,#,#,D#5,#,#,#,A#4,#,D#5,#,G5,#,F5,#,#,D#5,#,#,F5,#,#";

const char *MidiPlayer::my_people_my_country = "#,#,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,C6,C6,G5,G5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#5,A#5,A#5,A#5,D#5,D#5,D#5,D#5,D#5,D#5,F5,F5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,F6,F6,F6,F6,F6,F6,D#6,D#6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,D5,D5,D5,D5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,C6,C6,G5,G5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#5,A#5,A#5,A#5,D#5,D#5,D#5,D#5,D#5,D#5,F5,F5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,F6,F6,F6,F6,F6,F6,D#6,D#6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,D5,D5,D5,D5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#6,D#6,D#6,D#6,F6,F6,F6,F6,G6,G6,G6,G6,F6,F6,F6,F6,D#6,D#6,D#6,D#6,C6,C6,C6,C6,D6,D6,D6,D6,A#5,A#5,A#5,A#5,G5,G5,G5,G5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,D#6,D#6,D#6,D#6,F6,F6,F6,F6,G6,G6,G6,G6,F6,F6,F6,F6,D#6,D#6,D#6,D#6,C6,C6,C6,C6,D6,D6,D6,D6,A#5,A#5,A#5,A#5,G5,G5,G5,G5,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,F5,F5,F5,F5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,C6,C6,G5,G5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,C5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#5,A#5,A#5,A#5,D#5,D#5,D#5,D#5,D#5,D#5,F5,F5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,D#5,D#5,D#5,D#5,G5,G5,G5,G5,D#6,D#6,D#6,D#6,D6,D6,D6,D6,F6,F6,F6,F6,F6,F6,D#6,D#6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,D#6,D#6,D#6,D#6,D6,D6,D6,D6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,D5,D5,D5,D5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,A#4,A#4,A#4,A#4,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#6,D#6,D#6,D#6,F6,F6,F6,F6,G6,G6,G6,G6,F6,F6,F6,F6,D#6,D#6,D#6,D#6,C6,C6,C6,C6,D6,D6,D6,D6,A#5,A#5,A#5,A#5,G5,G5,G5,G5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,A#5,D#6,D#6,D#6,D#6,F6,F6,F6,F6,G6,G6,G6,G6,F6,F6,F6,F6,D#6,D#6,D#6,D#6,C6,C6,C6,C6,D6,D6,D6,D6,A#5,A#5,A#5,A#5,G5,G5,G5,G5,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,C6,A#5,A#5,A#5,A#5,G#5,G#5,G#5,G#5,G5,G5,G5,G5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,F5,D5,D5,D5,D5,C5,C5,C5,C5,A#4,A#4,A#4,A#4,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,G#5,F5,F5,F5,F5,F5,F5,F5,F5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,D#5,#,#,#";

const char *MidiPlayer::turkish_march = "#,#,B5,#,A5,#,G#5,#,A5,#,C6,C6,#,#,#,C4,E4,#,#,#,D6,E4,#,C6,#,B5,B5,#,C6,#,E6,A3,#,#,#,C4,C4,#,#,#,F6,C4,#,E6,#,D#6,E4,#,E6,#,A3,A3,#,A6,#,C4,E4,#,A6,#,A3,A3,#,A6,#,C4,E4,#,A6,#,C7,C7,#,#,#,C4,E4,#,#,#,C4,A6,#,#,#,C4,C4,#,#,#,E3,G6,#,#,#,E4,F#6,#,#,#,E4,G6,#,#,#,E4,E4,#,#,#,E3,G6,#,#,#,E4,F#6,#,#,#,E4,G6,#,#,#,E4,E4,#,#,#,E3,B6,#,#,#,E4,A6,#,#,#,B2,B2,#,#,#,B3,F#6,#,#,#,E3,E3,#,#,#,#,#,#,#,B5,#,A5,#,G#5,#,A5,#,C6,A3,#,#,#,C4,C4,#,#,#,D6,E4,#,C6,#,B5,E4,#,C6,#,E6,E6,#,#,#,C4,E4,#,#,#,F6,E4,#,E6,#,D#6,D#6,#,E6,#,B6,A3,#,A6,#,G#6,E4,#,A6,#,B6,B6,#,A6,#,G#6,C4,#,A6,#,C7,C7,#,#,#,C4,E4,#,#,#,A6,C4,#,#,#,C7,C7,#,#,#,B6,G6,#,#,#,A6,E4,#,#,#,G6,B3,#,#,#,A6,A6,#,#,#,B6,G6,#,#,#,A6,B3,#,#,#,G6,E4,#,#,#,A6,A6,#,#,#,B6,G6,#,#,#,A6,B3,#,#,#,G6,G6,#,#,#,F#6,D#6,#,#,#,E6,E6,#,#,#,#,#,#,#,C6,E6,#,#,#,F6,F6,#,#,#,G6,E6,#,#,#,G6,C4,#,#,#,A6,A6,#,G6,#,F6,E4,#,E6,#,D6,G3,#,#,#,G5,#,#,#,C6,C6,#,#,#,D6,F6,#,#,#,E6,C3,#,#,#,E6,E6,#,#,#,A6,E3,#,G6,#,F6,F6,#,E6,#,D6,G3,#,#,#,#,#,#,#,C6,C6,#,#,#,D6,B5,#,#,#,E6,A2,#,#,#,E6,E6,#,#,#,F6,C3,#,E6,#,D6,D6,#,C6,#,B5,G#5,#,#,#,E5,#,#,#,A5,A5,#,#,#,B5,D6,#,#,#,C6,A2,#,#,#,E6,E6,#,#,#,F6,C3,#,E6,#,D6,D6,#,C6,#,B5,E3,#,#,#,#,#,#,#,B5,#,A5,#,G#5,#,A5,#,C6,C6,#,#,#,C4,E4,#,#,#,D6,C4,#,C6,#,B5,B5,#,C6,#,E6,A3,#,#,#,C4,C4,#,#,#,F6,E4,#,E6,#,D#6,C4,#,E6,#,B6,B6,#,A6,#,G#6,C4,#,A6,#,B6,B6,#,A6,#,G#6,C4,#,A6,#,C7,C7,#,#,#,A3,D#4,#,#,#,A6,D#4,#,#,#,B6,B6,#,#,#,C7,E3,#,#,#,B6,E4,#,#,#,A6,A6,#,#,#,G#6,F3,#,#,#,A6,A6,#,#,#,E6,E3,#,#,#,F6,F6,#,#,#,D6,F3,#,#,#,C6,E3,#,#,#,E3,E3,#,#,#,B5,E3,C6,B5,C6,B5,G#3,C6,B5,#,A5,A5,#,#,#,#,#,#,#,A5,A6,#,#,#,B5,B5,#,#,#,C#6,C#7,#,#,#,A3,#,#,#,A5,A3,#,#,#,B5,B5,#,#,#,C#6,C#7,#,#,#,B5,A3,#,#,#,A5,A5,#,#,#,G#5,G#6,#,#,#,F#5,D2,#,#,#,G#5,G#5,#,#,#,A5,A6,#,#,#,B5,D#3,#,#,#,G#5,G#5,#,#,#,E5,E6,#,#,#,E3,A6,#,#,#,E3,E3,#,#,#,C#6,C#7,#,#,#,A3,#,#,#,A5,A3,#,#,#,B5,B5,#,#,#,C#6,C#7,#,#,#,B5,A3,#,#,#,A5,A5,#,#,#,G#5,G#6,#,#,#,F#5,D2,#,#,#,B5,B5,#,#,#,G#5,G#6,#,#,#,E5,E3,#,#,#,A5,A5,#,#,#,A3,#,#,#,A5,A6,#,#,#,B5,A3,#,#,#,C#6,C#6,#,#,#,A3,#,#,#,A5,A6,#,#,#,B5,A3,#,#,#,C#6,C#6,#,#,#,B5,B6,#,#,#,A5,A3,#,#,#,G#5,G#5,#,#,#,F#5,F#6,#,#,#,G#5,D3,#,#,#,A5,A5,#,#,#,B5,B6,#,#,#,G#5,E2,#,#,#,E5,E5,#,#,#,A5,A6,#,#,#,B5,E3,#,#,#,C#6,C#6,#,#,#,A3,#,#,#,A5,A6,#,#,#,B5,A3,#,#,#,C#6,C#6,#,#,#,B5,B6,#,#,#,A5,A3,#,#,#,G#5,G#5,#,#,#,F#5,F#6,#,#,#,B5,D3,#,#,#,G#5,G#5,#,#,#,E5,E6,#,#,#,A5,A2,#,#,#,A3,#,#,#,C#7,C#7,#,#,#,A3,C#7,C#6,#,E6,C#7,A2,#,#,#,A3,#,#,#,A3,#,#,#,A3,#,#,#,C#7,A2,#,#,#,A3,#,#,#,A3,#,#,#,A3,#,#,#,D7,D7,#,C#7,#,B6,A3,#,C#7,#,D7,D7,#,C#7,#,B6,A3,#,C#7,#,D7,F#6,#,#,#,D3,#,#,#,D3,#,#,#,D3,#,#,#,C#7,A2,#,#,#,C#7,C#7,#,#,#,C#7,E6,#,#,#,E6,C#7,#,#,#,E6,E2,#,#,#,E3,#,#,#,E3,#,#,#,E7,E7,#,#,#,C#7,A6,#,#,#,A3,#,#,#,A3,#,#,#,A3,#,#,#,E6,C#7,#,#,#,A3,#,#,#,A3,#,#,#,A3,#,#,#,D7,D7,#,C#7,#,B6,A3,#,C#7,#,D7,D7,#,C#7,#,B6,A3,#,C#7,#,D7,F#6,#,#,#,D3,#,#,#,D3,#,#,#,D7,D7,#,#,#,C#7,A6,#,#,#,A3,#,#,#,A3,#,#,#,A3,#,#,#,B6,E6,#,#,#,B6,E3,#,#,#,B6,B6,#,#,#,B6,E6,#,#,#,C#6,A6,#,#,#,A3,#,#,#,A3,#,#,#,C#6,C#6,#,#,#,A5,A6,#,#,#,A3,#,#,#,A3,#,#,#,E7,A3,#,#,#,A5,A5,#,#,#,A3,#,#,#,A3,#,#,#,C#6,C#7,#,#,#,A5,A2,#,#,#,C#7,C#7,#,#,#,A6,A5,#,#,#,E7,A2,#,#,#,A6,A3,#,#,#,#,#,#,#,A6,A6,#,#,#,#,#,#,#,A6,E6,#,#,#,#,#,#,#,";

const char *MidiPlayer::noname = "A#3,A#3,F#3,C#4,C4,C#4,A#3,#,A#3,A#3,F#3,C4,C#4,G#4,F4,#,A#3,A#3,F#3,C#4,C4,C#4,A#3,#,A#3,A#3,F#3,C4,C#4,G#4,F4,#,A#3,A#3,F3,C#4,C4,C#4,A#3,#,A#3,A#3,F3,C4,C#4,G#4,F4,#,F3,F3,F3,D#5,C6,C6,C6,G#3,C4,C4,C4,A#5,G#5,G#5,D#4,F#5,C4,C4,F5,G#3,D#4,D#4,G#5,C4,A#3,A#5,F#3,F#3,A#5,C4,A#5,A#5,A#5,A#3,A#5,A#5,F#3,A#5,A#5,A#5,C#4,A#5,A#5,A#5,F4,A#5,A#5,F#3,A#5,A#5,A#5,C4,C#4,A#3,#,A#3,A#3,F#3,C4,C#4,G#4,F4,#,A#3,A#3,F3,C#4,C4,C#4,A#3,#,A#3,A#3,F3,C4,C#4,G#4,F4,#,D#5,G#3,D#5,D#5,C7,D#3,C7,C6,A#6,A#6,A#6,F3,G#5,G#3,G#3,G#3,F5,C4,F5,F6,D#4,D#4,D#4,G#6,F#3,F#3,F#3,A#5,A#5,A#5,A#5,C#4,A#5,A#5,A#5,F3,A#5,A#5,A#5,F#3,C4,C4,F5,C#4,A#3,A#3,G#5,D#4,G#3,G#3,G#3,A#5,A#5,A#5,A#5,F3,G#3,G#3,C#6,F3,D#6,D#6,D#3,C#6,F3,F3,F3,C6,G#3,G#3,G#3,C#6,A#3,A#3,A#5,A#4,A#5,A#5,A#5,F4,A#5,A#5,A#5,G#3,A#5,A#5,A#5,A#4,A#5,A#5,A#5,F4,A#5,A#5,A#5,G#3,A#5,A#5,A#5,A#4,A#5,A#5,F4,C#4,F3,G#3,G#3,D#3,D#3,G#3,G#3,A#4,A#3,C#5,C#5,C5,C4,C#5,C#5,A#4,A#3,#,A#4,A#3,C4,C4,C#4,C#5,G#4,F4,F4,#,A#4,A#3,C#5,C#5,C5,C4,C#5,C#5,A#3,A#4,#,A#4,F#3,C5,C5,C#5,C#4,G#4,F5,F5,#,A#3,F3,C#5,C#5,C5,C4,C#4,C#4,A#3,A#4,#,A#4,F3,C5,C5,C#5,C#4,G#4,F4,F4,#,F3,D#6,F3,F4,G#4,G#4,G#4,C7,C4,C5,C4,C4,G#6,D#5,D#5,F#6,C5,C5,F6,G#3,D#4,G#6,G#6,G#6,A#4,A#3,A#6,C#4,A#6,A#6,A#6,C#4,A#6,A#3,A#6,A#6,A#4,A#6,A#6,A#6,C#4,A#6,A#6,A#6,F4,A#6,A#6,F#3,A#6,A#6,A#6,C5,C#4,C#4,A#3,A#4,#,A#3,A#4,C5,C5,C#5,C#4,G#4,F5,F5,#,D#5,D#4,F4,F4,G#5,G#4,A#4,A#4,C6,C5,C#6,C#6,D#6,D#5,C#6,C#6,C6,C5,A#5,A#5,G#5,G#4,F4,F4,G#5,G#4,G#5,D#6,C7,D#6,C7,C7,F4,C#6,F4,F3,G#6,G#4,G#3,G#3,G#5,F6,G#5,C5,G#6,D#5,G#6,G#6,F#3,A#5,F#3,F#5,A#5,A#5,A#5,F#5,A#5,A#3,A#5,A#5,A#5,F#5,A#5,F#3,C4,C4,F5,C5,A#3,D#5,G#5,G#5,G#3,F5,G#3,A#5,F5,F5,F5,A#5,G#3,C#6,F5,F5,F#5,D#6,D#3,F5,D#5,D#5,D#5,C6,G#3,F5,G#3,G#3,A#3,A#5,A#5,A#4,A#5,A#5,A#5,F5,A#5,C#4,A#5,A#5,A#5,F5,A#5,A#4,A#5,A#5,A#5,F5,A#5,C#4,A#5,A#5,A#5,F5,A#5,A#4,A#5,A#5,F4,C#4,F3,G#3,F5,G#3,A#5,C#6,C#6,C#6,G#5,D#6,F3,D#6,D#6,D#3,F6,D#3,G#5,F6,F6,F6,G#5,F6,F#3,F6,F6,F6,G#5,F6,D#3,G#3,G#3,G#5,C#6,D#6,C4,D#6,D#6,F3,G#5,F3,F6,G#5,G#5,G#5,F6,F4,A#5,D#6,D#6,G#5,C#6,A#5,F4,G#3,G#3,C6,D#5,A#3,F5,G#5,G#5,F#3,A#5,A#5,F#4,A#5,A#5,A#5,F5,A#5,F4,A#5,A#5,A#5,F5,A#5,F#4,C#4,C#4,C#5,D#4,F4,F4,D#5,F#3,F3,F3,F5,F4,F5,F5,F5,G#4,F4,F4,D#5,C4,C#5,C#5,F4,D#5,G#3,G#3,C5,F4,A#3,A#3,G#5,G#4,F#3,F#3,F5,F#4,F5,F5,F5,D#4,F5,F5,F5,F3,F5,F5,F5,F#4,C#4,C#6,G#5,G#5,F4,A#5,A#5,F#3,G#3,G#3,G#5,F6,G#5,C4,G#5,G#5,D#4,D#6,D#6,C4,C#6,C#6,D#6,G#3,C6,D#4,C6,C6,G#5,F5,G#5,C4,A#3,A#3,F5,A#5,F5,C4,F5,F5,F5,A#5,F5,F3,F5,F5,F5,A#5,F5,D#4,F5,F5,F5,A#5,F5,C#4,F5,F5,F5,A#5,F5,C#4,F#3,D#4,F#3,F#4,B3,G#4,B3,C#5,G#4,B3,B3,F#3,D#6,D#6,C#4,F#3,F#3,D#6,D#5,D#6,D#5,B3,B3,D#5,D#6,C#4,D#5,D#6,D#6,D#4,D#6,D#6,F#3,D#6,D#6,B3,D#5,D#5,G#4,C#4,C#4,D#6,D#5,G#4,D#5,B4,B4,D#5,D#6,F#5,D#6,D#5,D#5,B5,D#5,D#5,F#5,B3,D#4,C#4,D#4,B3,#,B3,C#4,D#4,B4,F#4,#,B3,D#4,C#4,D#4,B3,#,B3,C#4,D#4,B4,F#4,#,F6,F6,F#6,C#4,C4,G#6,C#6,C#6,A#3,C#6,C#6,C#6,A#3,C6,C6,C4,C#4,C#4,C6,G6,F4,C6,G6,G6,F6,F3,F3,G6,C#6,C#6,C#6,G#3,G#6,C4,G#6,G#6,D#4,C6,D#4,G#6,G6,G6,G#3,F6,D#4,G#5,D#6,D#6,B3,A#5,A#5,D#4,A#5,A#5,A#5,F6,A#5,B3,A#5,A#5,A#5,F6,A#5,C#4,A#5,A#5,A#5,F6,A#5,F#4,A#5,A#5,A#5,F6,A#5,D#4,A#5,A#5,D#4,B3,#,B3,C#4,D#4,B4,F#4,#,A#3,F6,F#6,G6,C4,C4,C#6,G#6,A#3,G#6,C#6,C#6,A#3,C6,C6,C4,C#4,C#4,G6,C6,F4,C6,G6,G6,D#5,G#3,D#5,D#5,C6,D#3,C6,C6,F3,A#5,F3,F3,G#5,G#3,G#3,G#3,F5,C4,F5,F5,G#5,D#4,G#5,G#5,B3,A#5,A#5,A#5,A#5,C#4,A#5,A#5,B3,C#6,C#6,B3,B3,D#6,C#4,D#4,D#4,C#6,B4,F#4,F#4,D#6,B3,F6,F6,F6,F6,C#4,F6,F6,B3,D#6,D#6,B3,B3,F#6,C#4,D#4,D#4,F6,B4,F#4,F#4,D#6,A#3,F6,F6,F6,F6,C4,F6,F6,A#3,F#6,F#6,F6,F6,C4,F#6,C#4,C#4,D#6,G#4,F4,F4,F6,F3,C#6,F3,F3,C#6,G#3,C#6,C#6,D#6,C4,D#6,D#6,C6,D#4,D#4,D#4,C4,A#5,A#5,A#5,D#4,G#5,G#5,G#5,B3,F5,F5,F5,F5,C#4,F5,F5,B3,F#5,F#5,B3,B3,G#5,C#4,G#5,G#5,G#5,B4,F#4,F#4,A#5,B3,F5,F5,F5,F5,C#4,F5,F5,B3,F#5,F#5,B3,B3,G#5,C#4,G#5,G#5,G#5,B4,F#4,F#4,A#5,A#3,F5,F#6,F#5,C4,F5,C#6,C#6,F5,A#3,F5,C#6,F5,G6,F5,F5,F5,C#4,F5,G6,F5,G6,F5,F5,F5,F6,F5,F#6,F5,G#3,F5,F5,F5,G#6,G#6,C#6,D#4,D#4,D#4,C6,C4,A#5,G#3,G#3,D#4,D#6,D#6,C4,B3,B3,A#5,D#4,A#5,A#5,A#5,D#4,B3,B3,C#6,B3,D#6,D#6,D#6,D#4,C#6,C#6,C#6,F#4,D#6,D#6,B3,B3,F6,D#4,F6,F6,F6,D#4,B3,B3,D#6,B3,F#6,F#6,F#6,D#4,F6,F6,F6,F#4,D#6,D#6,A#3,A#3,F6,C#4,F6,F6,F6,C#4,A#3,A#3,F#6,A#3,F6,F#6,F#6,C#4,D#6,D#6,D#6,F4,F6,F6,F3,F3,F3,C#6,C#6,C#6,C#6,G#3,C4,C4,C4,D#6,C6,C6,D#4,C#6,C4,C4,A#5,G#3,D#4,D#4,G#5,C4,B3,B3,F5,D#4,F5,F5,F5,D#4,B3,B3,F#5,B3,G#5,G#5,G#5,G#5,D#4,G#5,G#5,F#4,A#5,A#5,B3,B3,F5,D#4,F5,F5,F5,D#4,B3,B3,F#5,B3,G#5,G#5,G#5,G#5,D#4,G#5,G#5,F#4,A#5,A#5,A#3,A#3,C#4,F#5,C4,C4,F5,C#4,F5,F5,F5,F5,A#3,F5,F5,F5,C#4,F5,F5,F4,#,G#3,D#6,G#3,G#5,D#6,D#6,D#6,C7,F3,A#6,F3,F3,G#6,C6,G#3,A#5,G#5,G#5,G#5,F6,F5,D#4,F5,F5,F#3,A#5,F#3,F#5,A#5,A#5,A#5,F#5,A#5,A#3,A#5,A#5,A#5,F#5,A#5,F#3,C4,C4,F5,C5,A#3,G#5,D#5,D#5,G#3,F5,G#3,A#5,F5,F5,F5,A#5,G#3,C#6,F5,F5,F#5,D#6,D#3,F5,D#5,D#5,D#5,F3,G#3,C#6,G#3,G#3,A#3,F5,F5,A#4,F5,F5,F5,A#5,F5,C#4,F5,F5,F5,A#5,F5,A#4,F5,F5,F5,A#5,F5,C#4,F5,F5,F5,A#5,F5,A#4,F5,F5,F4,C#4,F3,A#5,F5,A#5,G#3,D#3,D#3,D#3,C#6,A#5,F3,A#5,A#5,D#3,G#5,D#3,F6,G#5,G#5,G#5,F6,G#5,F#3,G#5,G#5,G#5,F6,G#5,D#3,G#3,G#3,G#5,C#6,A#5,C4,A#5,A#5,F3,G#5,F3,F6,G#5,G#5,G#5,F6,F4,A#5,D#6,D#6,G#5,C#6,A#5,F4,G#3,G#3,D#5,C6,A#3,G#5,F5,F5,F#3,F5,F5,F#4,F5,F5,F5,A#5,F5,F4,F5,F5,F5,A#5,F5,F#4,C#4,C#4,C#5,D#4,F4,F4,D#5,F#3,F3,F3,F5,F4,F5,F5,F5,G#4,F4,F4,D#5,C4,F3,F3,D#5,F4,G#3,G#3,C5,F4,A#3,A#3,G#5,G#4,F#3,F#3,F5,F#4,F5,F5,F5,D#4,F5,F5,F5,F3,F5,F5,F5,F#4,C#4,C#6,G#5,G#5,F4,D#6,D#6,F#3,G#3,G#3,F6,G#5,F6,C4,F6,F6,D#4,A#5,A#5,C4,G#5,G#5,D#6,G#3,D#4,C6,D#4,D#4,G#5,F5,G#5,C4,F#3,F#3,A#5,F5,A#5,C#4,A#5,A#5,A#5,F5,A#5,F3,A#5,A#5,A#5,F5,C#4,G#5,C#6,C#6,F4,A#5,A#5,F#3,F3,F3,F6,G#5,F6,C4,F6,F6,F4,D#6,D#6,C4,G#5,G#5,A#5,F4,G#3,C6,D#5,D#5,A#3,F5,F5,G#4,A#3,A#3,F5,A#5,F5,D#4,F5,F5,F5,A#5,F5,G#3,F5,F5,F5,A#5,F5,D#4,F5,F5,F5,A#5,F5,G#3,F5,F5,F5,A#5,F5,F5,A#3,#,#,A#3,#,A#3,#,A#3,#";
const char* MidiPlayer::twinkle_star = "C4,C4,G4,G4,A4,A4,G4,F4,F4,E4,E4,D4,D4,C4,G4,G4,F4,F4,E4,E4,D4,G4,G4,F4,F4,E4,E4,D4,C4,C4,G4,G4,A4,A4,G4,F4,F4,E4,E4,D4,D4,C4";


// 静态变量，用于 musicupdate() 切换歌曲
uint8_t MidiPlayer::musicIndex = 0;



// 频率映射表
static const TONE noteFrequencies[] = {
    {"C0", 16}, {"C#0", 17}, {"D0", 18}, {"D#0", 19}, {"E0", 21}, {"F0", 22}, 
    {"F#0", 23}, {"G0", 24}, {"G#0", 26}, {"A0", 28}, {"A#0", 29}, {"B0", 31}, 
    {"C1", 33}, {"C#1", 35}, {"D1", 37}, {"D#1", 39}, {"E1", 41}, {"F1", 44}, 
    {"F#1", 46}, {"G1", 49}, {"G#1", 52}, {"A1", 55}, {"A#1", 58}, {"B1", 62},
    {"C2", 65}, {"C#2", 69}, {"D2", 73}, {"D#2", 78}, {"E2", 82}, {"F2", 87}, 
    {"F#2", 92}, {"G2", 98}, {"G#2", 104}, {"A2", 110}, {"A#2", 117}, {"B2", 123}, 
    {"C3", 131}, {"C#3", 139}, {"D3", 147}, {"D#3", 156}, {"E3", 165}, {"F3", 175}, 
    {"F#3", 185}, {"G3", 196}, {"G#3", 208}, {"A3", 220}, {"A#3", 233}, {"B3", 247}, 
    {"C4", 262}, {"C#4", 277}, {"D4", 294}, {"D#4", 311}, {"E4", 330}, {"F4", 349}, 
    {"F#4", 370}, {"G4", 392}, {"G#4", 415}, {"A4", 440}, {"A#4", 466}, {"B4", 494}, 
    {"C5", 523}, {"C#5", 554}, {"D5", 587}, {"D#5", 622}, {"E5", 659}, {"F5", 698}, 
    {"F#5", 740}, {"G5", 784}, {"G#5", 831}, {"A5", 880}, {"A#5", 932}, {"B5", 988}, 
    {"C6", 1047}, {"C#6", 1109}, {"D6", 1175}, {"D#6", 1245}, {"E6", 1319}, {"F6", 1397}, 
    {"F#6", 1480}, {"G6", 1568}, {"G#6", 1661}, {"A6", 1760}, {"A#6", 1865}, {"B6", 1976}, 
    {"C7", 2093}, {"C#7", 2217}, {"D7", 2349}, {"D#7", 2489}, {"E7", 2637}, {"F7", 2794}, 
    {"F#7", 2960}, {"G7", 3136}, {"G#7", 3322}, {"A7", 3520}, {"A#7", 3729}, {"B7", 3951}, 
    {"C8", 4186}, {"C#8", 4435}, {"D8", 4699}, {"D#8", 4978}, {"E8", 5274}, {"F8", 5588}, 
    {"F#8", 5920}, {"G8", 6272}, {"G#8", 6645}, {"A8", 7040}, {"A#8", 7459}, {"B8", 7902}, 
    {"C9", 8372}, {"C#9", 8870}, {"D9", 9397}, {"D#9", 9956}, {"E9", 10548}, {"F9", 11175}, 
    {"F#9", 11840}, {"G9", 12544}, {"G#9", 13290}, {"A9", 14080}, {"A#9", 14917}, {"B9", 15804},
    {"#", 0} // 静音符号
};

const int NUM_NOTES = sizeof(noteFrequencies) / sizeof(noteFrequencies[0]);

// 构造函数
MidiPlayer::MidiPlayer(gpio_num_t pin) :
    pinNumber(pin),
    currentSong(nullptr),
    songPos(nullptr),
    stopped(false),
    paused(false),
    lastTick(0),
    currentTempo(120),
    playTaskHandle(nullptr),
    taskRunning(false),
    taskTempo(120),
    taskLooping(0)
{
    // 初始化音符频率映射表
    for (int i = 0; i < NUM_NOTES; ++i) {
        tonesMap[noteFrequencies[i].note] = noteFrequencies[i].freq;
    }
}

// 析构函数
MidiPlayer::~MidiPlayer() {
    stopPlayback();
    deinit();
}
#if 0
// 静态任务函数
void MidiPlayer::playTaskFunction(void* parameter) {
    MidiPlayer* player = static_cast<MidiPlayer*>(parameter);
    
    uint64_t currentTime;
    uint64_t lastTick = esp_timer_get_time() / 1000;
    
    ESP_LOGI(TAG, "Playback task started");
    
    while (player->taskRunning && !player->stopped) {
        if (player->paused) {
            vTaskDelay(pdMS_TO_TICKS(10));
            lastTick = esp_timer_get_time() / 1000; // 暂停时更新时间戳
            continue;
        }
        
        currentTime = esp_timer_get_time() / 1000;
        
        if (currentTime - lastTick >= (uint64_t)player->taskTempo) {
            if (player->songPos && *player->songPos) {
                char note[4] = {0};
                
                if (sscanf(player->songPos, "%3[^,]", note) == 1) {
                    player->playNote(note);
                    
                    player->songPos = strchr(player->songPos, ',');
                    if (player->songPos) {
                        player->songPos++;
                    } else {
                        player->songPos = nullptr;
                    }
                } else {
                    ESP_LOGW(TAG, "Failed to parse note from: %s", player->songPos);
                    player->songPos = nullptr;
                }
            } else {
                // 歌曲播放完毕
                if (player->taskLooping) {
                    player->songPos = player->currentSong;
                    ESP_LOGI(TAG, "Looping song...");
                } else {
                    player->stopped = true;
                    player->stopTone();
                    ESP_LOGI(TAG, "End of song.");
                    break;
                }
            }
            lastTick = currentTime;
        }
        
        vTaskDelay(pdMS_TO_TICKS(10)); // 短暂延时
    }
    
    // 任务结束清理
    player->taskRunning = false;
    player->playTaskHandle = nullptr;
    player->stopTone();
    ESP_LOGI(TAG, "Playback task ended and deleted");
    
    vTaskDelete(NULL);
}
#endif
#if 1
// 新增的函数：单次扫描解析音符
inline bool MidiPlayer::parseNextNote(const char** pos, char* note, int maxLen) {
    if (!pos || !*pos || **pos == '\0') return false;
    
    int len = 0;
    while (**pos && **pos != ',' && len < maxLen - 1) {
        note[len++] = *(*pos)++;
    }
    
    note[len] = '\0';
    
    // 跳过逗号
    if (**pos == ',') (*pos)++;
    
    return len > 0;
}


// inline bool MidiPlayer::parseNextNote(const char** pos, char* note, int maxLen) {
//     // 跳过非音符字符（只允许字母、数字和#）
//     while (**pos && !(isalnum(**pos) || **pos == '#')) (*pos)++;
    
//     int i = 0;
//     while (**pos && **pos != ',' && i < maxLen-1) {
//         // 过滤无效字符（只保留大写字母、数字和#）
//         if(isalnum(**pos) || **pos == '#'){
//             note[i++] = toupper(**pos);
//         }
//         (*pos)++;
//     }
//     note[i] = '\0';

//     // 增强有效性检查（格式必须类似 C4 或 A#5）
//     if(i < 2 || !isalpha(note[0]) || !isdigit(note[i-1])) {
//         ESP_LOGE(TAG, "无效音符格式: %s", note);
//         return false;
//     }
    
//     return i > 0;
// }




void MidiPlayer::playTaskFunction(void* parameter) {
    MidiPlayer* player = static_cast<MidiPlayer*>(parameter);
    
    const char* songPos = player->currentSong;
    uint64_t lastTick = esp_timer_get_time() / 1000;
    
    ESP_LOGI(TAG, "Optimized playback task started");
    
    while (player->taskRunning && !player->stopped) {
        if (player->paused) {
            vTaskDelay(pdMS_TO_TICKS(10));
            lastTick = esp_timer_get_time() / 1000;
            continue;
        }
        
        uint64_t currentTime = esp_timer_get_time() / 1000;
        
        if (currentTime - lastTick >= (uint64_t)player->taskTempo) {
            char note[4];
            
            // 使用新的 parseNextNote 函数
            if (player->parseNextNote(&songPos, note, sizeof(note))) {
                player->playNote(note);
            } else {
                // 歌曲结束
                if (player->taskLooping) {
                    songPos = player->currentSong; // 重置
                    ESP_LOGI(TAG, "Looping song...");
                } else {
                    player->stopped = true;
                    player->stopTone();
                    ESP_LOGI(TAG, "End of song.");
                    break;
                }
            }
            lastTick = currentTime;
        }
        
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    
        // 任务结束清理
    player->taskRunning = false;
    player->playTaskHandle = nullptr;
    player->stopTone();
    ESP_LOGI(TAG, "Playback task ended and deleted");
    
    vTaskDelete(NULL);
}

#endif



void MidiPlayer::printSongNotes(const char *song) {
    if(!song) return;
    
    char* song_copy = strdup(song);
    char* note = strtok(song_copy, ",");
    
    ESP_LOGI(TAG, "Song Notes:");
    while(note != nullptr) {
        ESP_LOGI(TAG, "Note: %s", note);
        note = strtok(nullptr, ",");
    }
    
    free(song_copy);
}

// 初始化
void MidiPlayer::init() {
    ESP_LOGI(TAG, "Initializing buzzer on GPIO %d", pinNumber);

    gpio_reset_pin(pinNumber);
    gpio_set_direction(pinNumber, GPIO_MODE_OUTPUT);

    ledc_timer_config_t timer_conf = {
        .speed_mode      = LEDC_MODE,        
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num       = LEDC_TIMER,
        .freq_hz         = 20,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer_conf));


    // 配置 LEDC 通道
    ledc_channel_config_t channel_conf = {
        .gpio_num =  pinNumber,
        .speed_mode = LEDC_MODE,
        .channel = LEDC_CHANNEL,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER,
        .duty = 0, // 初始关闭震动
        .hpoint = 0,
        .flags = {.output_invert = 0}};

    ESP_ERROR_CHECK(ledc_channel_config(&channel_conf));

    this->paused = false;
    this->stopped = true;
    this->lastTick = esp_timer_get_time() / 1000;
}

// // 设置歌曲
// void MidiPlayer::setSong(const char *song) {
//     printSongNotes(song);
//     this->currentSong = song;
//     this->songPos = this->currentSong;
//     this->stopped = false;
//     ESP_LOGI(TAG, "Song set%s", song);
// }

// 在McpComplex.cc中添加函数实现
std::string MidiPlayer::fixMusicNotation(const std::string& input) {
    std::string output;
    output.reserve(input.length());
    bool last_was_comma = false;

    for (char c : input) {
        // 仅处理中文逗号（Unicode: U+FF0C）
        if (c == '\xFF0C') {
            if (!last_was_comma) {
                output += ',';
                last_was_comma = true;
            }
            continue;
        }

        // 保留合法字符
        if (isalnum((unsigned char)c) || c == '#' || c == ',') {
            // 处理连续逗号
            if (c == ',') {
                if (last_was_comma) continue;
                last_was_comma = true;
            } else {
                last_was_comma = false;
            }
            output += c;
        }
    }

    // 去除末尾多余符号
    while (!output.empty() && 
          (output.back() == ',' || output.back() == '#')) {
        output.pop_back();
    }

    return output;
}



void MidiPlayer::setSong(const char *song) {
    // 增加有效性检查
    if(!song) return;
    
    // ESP_LOGI(TAG, "开始验证歌曲数据...");
    // for(const char* p = song; *p; p++) {
    //     if(!(isalnum((unsigned char)*p) || *p == '#' || *p == ',')) {
    //         ESP_LOGW(TAG, "发现非法字符 0x%02x 在偏移 %d", *p, (int)(p - song));
    //     }
    // }
    // ESP_LOGI(TAG, "歌曲验证完成");
    // // 增加调试日志，打印原始歌曲数据
    // ESP_LOGI(TAG, "原始歌曲数据: %.*s...", 50, song);
    
    // printSongNotes(song);
    this->currentSong = song;
    this->songPos = this->currentSong;
    this->stopped = false;
    
    // 改进日志格式，增加长度显示
    ESP_LOGI(TAG, "成功设置歌曲 (长度:%d) [%.*s...]", 
           strlen(song), 20, song);
}

// 播放函数（使用FreeRTOS任务）
void MidiPlayer::play(int tempo, uint8_t looping, const char *song) {
    // 如果任务正在运行，先停止它
    if (taskRunning && playTaskHandle != nullptr) {
        stopPlayback();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    // printSongNotes(song);
    // 设置歌曲和参数
    if (song) {
        setSong(song);
        // taskSong = std::string(song);
    }
    
    taskTempo = 60000/tempo;
    taskLooping = looping;
    this->currentTempo = taskTempo;
    
    // 重置状态
    this->stopped = false;
    this->paused = false;
    this->taskRunning = true;
    
    // 创建播放任务
    BaseType_t result = xTaskCreate(
        playTaskFunction,
        "MidiPlayTask",
        4096,
        this,
        5,
        &playTaskHandle
    );
    
    if (result == pdPASS) {
        ESP_LOGI(TAG, "Playback task created successfully");
    } else {
        ESP_LOGE(TAG, "Failed to create playback task");
        taskRunning = false;
    }
}

// std::string版本的播放函数
void MidiPlayer::play(int tempo, uint8_t looping, const std::string& song_str) {
    play(tempo, looping, song_str.c_str());
}

// 停止播放
void MidiPlayer::stopPlayback() {
    if (taskRunning) {
        ESP_LOGI(TAG, "Stopping playback task");
        taskRunning = false;
        stopped = true;
        
        if (playTaskHandle != nullptr) {
            for (int i = 0; i < 10 && playTaskHandle != nullptr; i++) {
                vTaskDelay(pdMS_TO_TICKS(10));
            }
               
            if (playTaskHandle != nullptr) {
                vTaskDelete(playTaskHandle);
                playTaskHandle = nullptr;
                ESP_LOGW(TAG, "Forcibly deleted playback task");
            }
        }
        
        stopTone();
        ESP_LOGI(TAG, "Playback stopped");
    }
}

// 暂停播放
void MidiPlayer::pause() {
    if (!this->paused) {
        ESP_LOGI(TAG, "Pausing playback");
        this->paused = true;
        stopTone(); // 停止当前音符
    }
}

// 恢复播放
void MidiPlayer::resume() {
    if (this->paused) {
        ESP_LOGI(TAG, "Resuming playback");
        this->paused = false;
    }
}

// 设置节奏
void MidiPlayer::setTempo(int newTempo) {
    if (newTempo > 0) {
        this->currentTempo = 60000/newTempo;
        this->taskTempo = 60000/newTempo;
        ESP_LOGI(TAG, "Tempo set to: %d ms", this->currentTempo);
    } else {
        ESP_LOGW(TAG, "Invalid tempo value: %d. Tempo must be positive.", newTempo);
    }
}

// 获取当前节奏
int MidiPlayer::getTempo() const {
    return this->currentTempo;
}

// 检查是否停止
uint8_t MidiPlayer::isStop() {
    return this->stopped;
}

// 检查是否暂停
bool MidiPlayer::isPaused() const {
    return this->paused;
}

// 检查任务是否运行
bool MidiPlayer::isTaskRunning() const {
    return this->taskRunning;
}

// // 获取音符频率
// int MidiPlayer::getFrequency(const char *note) {
//     std::string noteStr(note);
//     ESP_LOGI(TAG, "Note set to: %s", noteStr.c_str());
//     auto it = tonesMap.find(noteStr);
//     if (it != tonesMap.end()) {
//         return it->second;
//     }
//     return 0; // 静音
// }


int MidiPlayer::getFrequency(const char *note) {
    // 新增有效性检查
    // ESP_LOGE(TAG, "无效音符格式: %s",note);
    // if(!note || strlen(note) < 2 || !isalpha(note[0]) || !isdigit(note[strlen(note)-1])) {
    //     ESP_LOGE(TAG, "无效音符格式: %s", note ? note : "(null)");
    //     return 0;
    // }
    
    std::string noteStr(note);
    auto it = tonesMap.find(noteStr);
    return (it != tonesMap.end()) ? it->second : 0;
}
// 播放音符
void MidiPlayer::playNote(const char *note) {
    int freq = getFrequency(note);
    
    static int lastFreq = 0;
    if (freq != lastFreq) {
        lastFreq = freq;
        if (freq > 0) {
            startTone(freq);
        } else {
            stopTone();
        }
    }
}

// 开始发声
void MidiPlayer::startTone(int freq) {
    ledc_set_freq(LEDC_MODE, LEDC_TIMER, freq);
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, 500);// 设置占空比为50%，1023 没法发声。
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

// 停止发声
void MidiPlayer::stopTone() {
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, 0);
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

// 设置音乐索引
void MidiPlayer::setMusicIndex(uint8_t index) {
    musicIndex = (index-1) % 4;
    ESP_LOGI(TAG, "Switching to music index: %d", musicIndex);
}

// 音乐更新函数
void MidiPlayer::musicupdate() {
    switch (musicIndex) {
        case 0:
            play(500, 0, my_people_my_country);
            break;
        case 1:
            play(400, 0, noname);
            break;
        case 2:
            play(500, 0, turkish_march);
            break;
        case 3:
            play(500, 0, demo_song);
            break;
        default:
            break;
    }
}

// 去初始化
void MidiPlayer::deinit() {
    ESP_LOGI(TAG, "Deinitializing MidiPlayer");
    stopPlayback();
    stopTone();
}
