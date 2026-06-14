# 使用说明 


1. 设置编译目标为 esp32s3

```shell
idf.py set-target esp32s3```


2. **修改 psram 配置：**

```
Component config -> ESP PSRAM -> SPI RAM config -> Mode (QUAD/OCT) -> QUAD Mode PSRAM
```

3. 编译烧录程序

```shell
idf.py build flash monitor
```

idf.py merge-bin -o xiaozhi-m5stackCore3.bin -f raw



 
1. Set compilation target to esp32s3
```shell
idf.py set-target esp32s3
```
2. **Open menuconfig:**
```bash
idf.py menuconfig
```

3. **Select board:**
```
Xiaozhi Assistant -> Board Type -> m5stack-core-s3
```
4. **Modify psram configuration:**
```
Component config -> ESP PSRAM -> SPI RAM config -> Mode (QUAD/OCT) -> QUAD Mode PSRAM
```
5. Compile, flash and monitor the program
```shell
idf.py build flash monitor
```




需要进入[小智后台](https://xiaozhi.me/)，找到对应设备，修改角色配置，替换音乐播放逻辑，如果想返回原来状态，删除对应内容即可。 

- 选择 DeepSeekV3 大语言模型
- 在人物介绍中末尾加入
- 收到音乐相关的需求时，只使用 MPC tool `self.music.play_song` 工具，同时禁止使用 `search_music` 功能。
    
- 电台选择：根据用户需求从预设的电台列表中模糊搜索，如果找不到则随机选择一个电台播放。预设电台：80后音悦台（ID: 20207761）、流行音乐（ID: 4938）、清晨音乐（ID: 4915）、长沙城市之声（ID: 4237）、怀旧（ID: 1223）。
