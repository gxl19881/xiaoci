#include "spectrum_visualizer.h"
#include <math.h>

// 定义PI常量（如果未定义）
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// 初始化静态成员变量
lv_timer_t* SpectrumVisualizer::spectrum_timer = nullptr;
int SpectrumVisualizer::spectrum_values[BAR_COUNT] = {0};
const lv_color_t SpectrumVisualizer::spectrum_colors[12] = {
    lv_color_hex(0xFF0000), // 红色
    lv_color_hex(0xFF4500), // 橙红色
    lv_color_hex(0xFF7F00), // 橙色
    lv_color_hex(0xFFA500), // 深橙色
    lv_color_hex(0xFFD700), // 金色
    lv_color_hex(0xFFFF00), // 黄色
    lv_color_hex(0xADFF2F), // 黄绿色
    lv_color_hex(0x00FF00), // 绿色
    lv_color_hex(0x00CED1), // 深青色
    lv_color_hex(0x0000FF), // 蓝色
    lv_color_hex(0x4B0082), // 靛蓝色
    lv_color_hex(0x8B00FF)  // 紫色
};

float SpectrumVisualizer::phase = 0.0f;
const float SpectrumVisualizer::phase_step = 0.1f;
const float SpectrumVisualizer::amplitude = 45.0f;
const float SpectrumVisualizer::offset = 50.0f;

// 频谱图绘制事件回调
void SpectrumVisualizer::spectrum_draw_event_cb(lv_event_t* e) {
    lv_obj_t* obj = (lv_obj_t*)lv_event_get_target(e);
    lv_layer_t* layer = lv_event_get_layer(e);
    
    // 获取对象区域
    lv_area_t obj_area;
    lv_obj_get_coords(obj, &obj_area);
    
    // 计算可用区域
    int32_t obj_width = lv_area_get_width(&obj_area);
    int32_t obj_height = lv_area_get_height(&obj_area);
    
    // 设置参数
    const int min_bar_width = 1;  // 最小柱子宽度
    const int max_bar_width = 3;  // 最大柱子宽度
    const int min_gap = 2;  // 最小间距
    const int max_height = obj_height / 2;  // 最大高度（总高度的一半）
    
    // 计算最优柱子宽度和间距
    int total_gap = (BAR_COUNT - 1) * min_gap;  // 最小总间距
    int available_width = obj_width - total_gap;
    int bar_width = available_width / BAR_COUNT;
    
    // 限制柱子宽度在合理范围内
    if(bar_width < min_bar_width) bar_width = min_bar_width;
    if(bar_width > max_bar_width) bar_width = max_bar_width;
    
    // 重新计算实际总宽度和起始位置
    int total_width = BAR_COUNT * bar_width + (BAR_COUNT - 1) * min_gap;
    int start_x = obj_area.x1 + (obj_width - total_width) / 2;
    int center_y = (obj_area.y1 + obj_area.y2) / 2;
    
    // 绘制每个柱形
    for(int i = 0; i < BAR_COUNT; i++) {
        // 计算柱形位置
        int x = start_x + i * (bar_width + min_gap);
        int bar_height = (spectrum_values[i] * max_height) / 110;
        
        // 设置柱形区域（上下对称）
        lv_area_t bar_area = {
            .x1 = x,
            .y1 = center_y - bar_height,
            .x2 = x + bar_width - 1,
            .y2 = center_y + bar_height
        };
        
        // 设置绘制样式
        lv_draw_rect_dsc_t rect_dsc;
        lv_draw_rect_dsc_init(&rect_dsc);
        rect_dsc.bg_color = spectrum_colors[i+5];
        rect_dsc.radius = 2;
        rect_dsc.bg_opa = LV_OPA_COVER;
        
        // 绘制柱形
        lv_draw_rect(layer, &rect_dsc, &bar_area);
    }
}

// 更新频谱数据的定时器回调
void SpectrumVisualizer::spectrum_timer_cb(lv_timer_t* timer) {
    // 获取主体对象指针
    lv_obj_t* obj = (lv_obj_t*)lv_timer_get_user_data(timer);
    
    // 使用正弦波生成新的值
    for(int i = 0; i < BAR_COUNT; i++) {
        // 计算每个频段的正弦波值
        float freq = (i + 1) * 0.5f;  // 不同频段使用不同频率
        // float freq = BAR_COUNT * 0.5f;  // 不同频段使用不同频率
        float sin_value = sinf(phase * freq);
        int new_value = (int)(offset + amplitude * sin_value);
        
        // 限制在0-100范围内
        if(new_value < 0) new_value = 0;
        if(new_value > 100) new_value = 100;
        
        // 平滑过渡到新值
        if(new_value > spectrum_values[i]) {
            spectrum_values[i] += 5;
            if(spectrum_values[i] > new_value) spectrum_values[i] = new_value;
        } else if(new_value < spectrum_values[i]) {
            spectrum_values[i] -= 5;
            if(spectrum_values[i] < new_value) spectrum_values[i] = new_value;
        }
    }
    
    // 更新相位
    phase += phase_step;
    if(phase > 2 * M_PI) {
        phase -= 2 * M_PI;
    }
    
    // 触发重绘
    if(obj) {
        lv_obj_invalidate(obj);
    }
}

// 创建频谱图
lv_obj_t* SpectrumVisualizer::create(lv_obj_t* parent) {
    // 创建基础对象
    lv_obj_t *spectrum_obj = lv_obj_create(parent);
    lv_obj_set_size(spectrum_obj, 60,35);
    lv_obj_align(spectrum_obj, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_bg_color(spectrum_obj, lv_color_white(), 0);
    lv_obj_set_style_border_width(spectrum_obj, 0, 0);
    lv_obj_set_style_pad_all(spectrum_obj, 0, 0);
    
    // 添加绘制事件回调
    lv_obj_add_event_cb(spectrum_obj, spectrum_draw_event_cb, LV_EVENT_DRAW_MAIN, NULL);
    
    // 创建更新定时器
    spectrum_timer = lv_timer_create(spectrum_timer_cb, 30, spectrum_obj);
    
    return spectrum_obj;
}

// 更新频谱数据
void SpectrumVisualizer::update_data() {
    if (spectrum_timer) {
        spectrum_timer_cb(spectrum_timer);
    }
}
