# EchoEar 喵伴

## 简介

<div align="center">
    <a href="https://oshwhub.com/esp-college/echoear"><b> 立创开源平台 </b></a>
</div>

EchoEar 喵伴是一款智能 AI 开发套件，搭载 ESP32-S3-WROOM-1 模组，1.85 寸 QSPI 圆形触摸屏，双麦阵列，支持离线语音唤醒与声源定位算法。硬件详情等可查看[立创开源项目](https://oshwhub.com/esp-college/echoear)。

## 配置、编译命令

**配置编译目标为 ESP32S3**

```bash
idf.py set-target esp32s3
```

**打开 menuconfig 并配置**

```bash
idf.py menuconfig
```

分别配置如下选项：

### 基本配置
- `Xiaozhi Assistant` → `Board Type` → 选择 `EchoEar`

### 分区表配置
- `Partition Table` → `Partition Table` → 选择 `Custom partition table CSV`
- `Partition Table` → `Custom partition CSV file` → 输入 `partitions/v1/16m_echoear.csv`

### UI风格选择

EchoEar 支持两种不同的UI显示风格，通过修改代码中的宏定义来选择：

#### 自定义表情显示系统 (推荐)
```c
#define USE_LVGL_DEFAULT    0
```
- **特点**: 使用自定义的 `EmoteDisplay` 表情显示系统
- **功能**: 支持丰富的表情动画、眼睛动画、状态图标显示
- **适用**: 智能助手场景，提供更生动的人机交互体验
- **类**: `anim::EmoteDisplay` + `anim::EmoteEngine`

#### LVGL默认显示系统
```c
#define USE_LVGL_DEFAULT    1
```
- **特点**: 使用标准LVGL图形库的显示系统
- **功能**: 传统的文本和图标显示界面
- **适用**: 需要标准GUI控件的应用场景
- **类**: `SpiLcdDisplay`

#### 如何修改
1. 打开 `main/boards/echoear/EchoEar.cc` 文件
2. 找到第29行的宏定义：`#define USE_LVGL_DEFAULT    0`
3. 修改为想要的值（0或1）
4. 重新编译项目

> **说明**: EchoEar 使用16MB Flash，需要使用专门的分区表配置来合理分配存储空间给应用程序、OTA更新、资源文件等。

按 `S` 保存，按 `Q` 退出。

**编译**

```bash
idf.py build
```

**烧录**

将 EchoEar 连接至电脑，**注意打开电源**，并运行：

```bash
idf.py flash
```

**合并BIN：**

```bash
idf.py merge-bin -o xiaozhi-echoear.bin -f raw

```

idf.py -p COM1140 -b 1152000 flash

Wrote 0xfc77b0 bytes to file xiaozhi-echoear.bin, ready to flash to offset 0x0

需要进入[小智后台](https://xiaozhi.me/)，找到对应设备，修改角色配置，替换音乐播放逻辑，如果想返回原来状态，删除对应内容即可。 
- 选择 DeepSeekV3 大语言模型
- 在人物介绍中末尾加入
  - 收到音乐相关的需求时，只使用 MPC tool `self.music.play_song` 工具，同时禁止使用 `search_music` 功能。
- 电台选择：根据用户需求从预设的电台列表中模糊搜索，如果找不到则随机选择一个电台播放。预设电台：80后音悦台（ID: 20207761）、流行音乐（ID: 4938）、清晨音乐（ID: 4915）、长沙城市之声（ID: 4237）、怀旧（ID: 1223）。