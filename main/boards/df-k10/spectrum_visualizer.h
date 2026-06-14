#pragma once

#include <lvgl.h>

// 频谱图可视化类
class SpectrumVisualizer {
public:
    // 频谱图配置参数
    static const int BAR_COUNT = 6;  // 柱形数量，可修改此值调整频谱图柱形数量
    
    // 创建频谱图对象
    static lv_obj_t* create(lv_obj_t* parent);
    
    // 更新频谱数据
    static void update_data();
    
    // 获取频谱定时器
    static lv_timer_t* get_timer() { return spectrum_timer; }
    
    // 设置频谱值（用于外部设置实际音频数据）
    static void set_value(int index, int value) {
        if (index >= 0 && index < BAR_COUNT) {
            spectrum_values[index] = value;
        }
    }

private:
    // 频谱图绘制事件回调
    static void spectrum_draw_event_cb(lv_event_t* e);
    
    // 更新频谱数据的定时器回调
    static void spectrum_timer_cb(lv_timer_t* timer);
    
    // 频谱图相关变量
    static lv_timer_t* spectrum_timer;       // 更新定时器
    static int spectrum_values[BAR_COUNT];  // 频谱数据
    static const lv_color_t spectrum_colors[12]; // 频谱颜色
    
    // 正弦波相关参数
    static float phase;                      // 当前相位
    static const float phase_step;           // 相位步进
    static const float amplitude;            // 振幅
    static const float offset;               // 偏移量
};
