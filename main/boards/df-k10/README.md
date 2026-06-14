# DFRobot 行空板 K10

## 按键配置

* A：短按-打断/唤醒，长按1s-音量调大
* B：短按-打断/唤醒，长按1s-音量调小

## 编译配置命令

**配置编译目标为 ESP32S3：**

```bash
idf.py set-target esp32s3
```

**打开 menuconfig：**

```bash
idf.py menuconfig
```

**选择板子：**

```
Xiaozhi Assistant -> Board Type -> DFRobot 行空板 K10
```

**修改 psram 配置：**

```
Component config -> ESP PSRAM -> SPI RAM config -> Mode (QUAD/OCT) -> Octal Mode PSRAM
```

**编译：**

```bash
idf.py build
```

idf.py merge-bin -o xiaozhi-dfk10.bin -f raw

cd build

通过网盘分享的文件：merged_firmware.bin
链接: https://pan.baidu.com/s/1yxz85UxFfmOff8Z1vICIcQ?pwd=bxkp 提取码: bxkp

需要进入[小智后台](https://xiaozhi.me/)，找到对应设备，修改角色配置，替换音乐播放逻辑，如果想返回原来状态，删除对应内容即可。 

- 选择 DeepSeekV3 大语言模型
- 在人物介绍中末尾加入
  - 收到音乐相关的需求时，只使用 MPC tool `self.music.play_song` 工具，同时禁止使用 `search_music` 功能。
    
- 电台选择：根据用户需求从预设的电台列表中模糊搜索，如果找不到则随机选择一个电台播放。预设电台：80后音悦台（ID: 20207761）、流行音乐（ID: 4938）、清晨音乐（ID: 4915）、长沙城市之声（ID: 4237）、怀旧（ID: 1223）。