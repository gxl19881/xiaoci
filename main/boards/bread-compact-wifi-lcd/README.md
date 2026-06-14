# 编译配置命令

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
Xiaozhi Assistant -> Board Type -> wifi-lcd


**修改 psram 配置：**

```
Component config -> ESP PSRAM -> SPI RAM config -> Mode (QUAD/OCT) -> OCT Mode PSRAM
```

**修改 Flash 配置：**

```
Serial flasher config -> Flash size -> 16 MB
Partition Table -> Custom partition CSV file -> partitions/v1/16m.csv
```



**编译：**

```bash
idf.py build
```

**合并BIN：**

```bash
idf.py merge-bin -o xiaozhi-qmyd.bin -f raw
```

idf.py -p COM1140 -b 1152000 flash



需要进入[小智后台](https://xiaozhi.me/)，找到对应设备，修改角色配置，替换音乐播放逻辑，如果想返回原来状态，删除对应内容即可。 
- 选择 DeepSeekV3 大语言模型
- 在人物介绍中末尾加入
  - 收到音乐相关的需求时，只使用 MPC tool `self.music.play_song` 工具，同时禁止使用 `search_music` 功能。
小智后台角色介绍添加：
- 电台选择：根据用户需求从预设的电台列表中模糊搜索，如果找不到则随机选择一个电台播放。预设电台：80后音悦台（ID: 20207761）、流行音乐（ID: 4938）、清晨音乐（ID: 4915）、长沙城市之声（ID: 4237）、怀旧（ID: 1223）。