// static lv_obj_t* spectrum_obj = nullptr;          // 频谱图对象
static lv_timer_t* spectrum_timer = nullptr;       // 更新定时器
static int spectrum_values[6] = {0};              // 频谱数据
static const lv_color_t spectrum_colors[6] = {    // 频谱颜色
    lv_color_hex(0xFF0000), // 红
    lv_color_hex(0xFF7F00), // 橙
    lv_color_hex(0xFFFF00), // 黄
    lv_color_hex(0x00FF00), // 绿
    lv_color_hex(0x0000FF), // 蓝
    lv_color_hex(0x8B00FF)  // 紫
};

// 频谱图绘制事件回调
static void spectrum_draw_event_cb(lv_event_t* e) {
    lv_obj_t* obj = (lv_obj_t*)lv_event_get_target(e);
    lv_layer_t* layer = lv_event_get_layer(e);
    
    // 获取对象区域
    lv_area_t obj_area;
    lv_obj_get_coords(obj, &obj_area);
    
    // 计算可用区域
    int32_t obj_width = lv_area_get_width(&obj_area);
    int32_t obj_height = lv_area_get_height(&obj_area);
    
    // 设置参数
    const int bar_count = 6;  // 柱子数量
    const int min_bar_width = 1;  // 最小柱子宽度
    const int max_bar_width = 3;  // 最大柱子宽度
    const int min_gap = 2;  // 最小间距
    const int max_height = obj_height / 2;  // 最大高度（总高度的一半）
    
    // 计算最优柱子宽度和间距
    int total_gap = (bar_count - 1) * min_gap;  // 最小总间距
    int available_width = obj_width - total_gap;
    int bar_width = available_width / bar_count;
    
    // 限制柱子宽度在合理范围内
    if(bar_width < min_bar_width) bar_width = min_bar_width;
    if(bar_width > max_bar_width) bar_width = max_bar_width;
    
    // 重新计算实际总宽度和起始位置
    int total_width = bar_count * bar_width + (bar_count - 1) * min_gap;
    int start_x = obj_area.x1 + (obj_width - total_width) / 2;
    int center_y = (obj_area.y1 + obj_area.y2) / 2;
    
    // 绘制每个柱形
    for(int i = 0; i < bar_count; i++) {
        // 计算柱形位置
        int x = start_x + i * (bar_width + min_gap);
        int bar_height = (spectrum_values[i] * max_height) / 100;
        
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
        rect_dsc.bg_color = spectrum_colors[i];
        rect_dsc.radius = 2;
        rect_dsc.bg_opa = LV_OPA_COVER;
        
        // 绘制柱形
        lv_draw_rect(layer, &rect_dsc, &bar_area);
    }
}


// 更新频谱数据的定时器回调
static void spectrum_timer_cb(lv_timer_t* timer) {
    // 获取主体对象指针
    lv_obj_t* obj = (lv_obj_t*)lv_timer_get_user_data(timer);;
    
    // 生成新的随机值（0-100）
    for(int i = 0; i < 6; i++) {
        int new_value = rand() % 90;
        
        // 平滑过渡到新值
        if(new_value > spectrum_values[i]) {
            spectrum_values[i] += 10;
            if(spectrum_values[i] > new_value) spectrum_values[i] = new_value;
        } else if(new_value < spectrum_values[i]) {
            spectrum_values[i] -= 10;
            if(spectrum_values[i] < new_value) spectrum_values[i] = new_value;
        }
    }
    
    // 使用获取到的对象指针触发重绘
    if(obj) {
        lv_obj_invalidate(obj);
    }
}
