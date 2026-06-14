# 音频降噪功能说明

## 概述

本项目已集成了ESP-SR框架的AFE（Audio Front-End）音频前端处理功能，提供了强大的环境噪音抑制能力，显著提升语音采集质量。

## 功能特性

### 1. 噪声抑制 (Noise Suppression)
- **神经网络降噪 (NSNET)**: 使用深度学习模型进行噪声抑制，效果优于传统算法
- **WebRTC降噪**: 作为后备方案，在无神经网络模型时使用

### 2. 语音活动检测 (VAD)
- **智能语音检测**: 精确识别语音与噪音，减少误触发
- **可配置敏感度**: 根据环境调整VAD参数

### 3. 自动增益控制 (AGC)
- **动态音量调节**: 自动调整音频信号强度
- **目标电平维持**: 保持音频输出在最佳范围

### 4. 多级降噪模式
- **轻度降噪**: 保持语音自然度，适用于安静环境
- **中度降噪**: 平衡噪音抑制和语音质量，适用于一般环境  
- **强力降噪**: 最大化噪音抑制，适用于高噪音环境

### 5. 自适应降噪
- **环境感知**: 实时监控背景噪音水平
- **智能调整**: 根据噪音水平自动切换降噪模式
- **动态优化**: 每100帧评估一次并调整参数

## 配置选项

在 `idf.py menuconfig` 中可配置以下选项：

### Xiaozhi Assistant -> Audio Settings

1. **Enable Audio Noise Reduction** (默认启用)
   - 启用完整的音频前端处理功能

2. **Default Noise Reduction Mode**
   - 轻度降噪 (MILD)
   - 中度降噪 (MODERATE) - 默认
   - 强力降噪 (AGGRESSIVE)

3. **Enable Adaptive Noise Reduction** (默认启用)
   - 根据环境噪音自动调整降噪强度

4. **Enhanced VAD Sensitivity** (默认启用)
   - 增强语音活动检测敏感度

## 性能参数

### 降噪效果
- **轻度模式**: 5-10dB 噪音抑制
- **中度模式**: 10-15dB 噪音抑制  
- **强力模式**: 15-20dB 噪音抑制

### 处理延迟
- **总延迟**: < 100ms
- **帧处理**: 60ms (Opus帧大小)

### 资源消耗
- **CPU占用**: 约15-25% (ESP32-S3)
- **内存使用**: 约200KB PSRAM
- **核心分配**: 优先使用核心1

## API接口

### AudioService类
```cpp
// 设置降噪模式 (0=轻度, 1=中度, 2=强力)
void SetNoiseReductionMode(int mode);

// 获取当前降噪模式
int GetNoiseReductionMode() const;

// 启用/禁用自适应降噪
void SetAdaptiveNoiseReduction(bool enable);

// 检查自适应降噪状态
bool IsAdaptiveNoiseReductionEnabled() const;
```

### AfeAudioProcessor类
```cpp
// 设置降噪模式
void SetNoiseReductionMode(NoiseReductionMode mode);

// 获取降噪模式
NoiseReductionMode GetNoiseReductionMode() const;

// 控制自适应降噪
void SetAdaptiveNoiseReduction(bool enable);
bool IsAdaptiveNoiseReductionEnabled() const;
```

## 使用建议

### 环境适配
1. **安静室内**: 使用轻度降噪，保持语音自然度
2. **一般环境**: 使用中度降噪，平衡效果和质量
3. **嘈杂环境**: 使用强力降噪，最大化噪音抑制
4. **动态环境**: 启用自适应降噪，自动调整

### 参数调优
1. **语音响应慢**: 降低 `vad_min_speech_ms` 参数
2. **噪音误触发**: 增加 `vad_min_noise_ms` 参数
3. **语音截断**: 增加 `vad_delay_ms` 参数

### 性能优化
1. **减少延迟**: 选择轻度降噪模式
2. **节省资源**: 禁用自适应降噪
3. **最佳效果**: 启用所有功能并使用强力模式

## 故障排除

### 常见问题
1. **降噪效果不明显**
   - 检查是否启用了 `CONFIG_USE_AUDIO_PROCESSOR`
   - 确认使用了正确的降噪模式

2. **语音被过度抑制**
   - 降低降噪强度到轻度模式
   - 调整VAD参数

3. **音频延迟较大**
   - 禁用不必要的音频处理功能
   - 使用较低的降噪等级

4. **内存不足**
   - 确保启用了PSRAM
   - 检查内存分配模式设置

### 日志分析
查看标签为 "AfeAudioProcessor" 的日志输出，包含：
- 初始化参数
- 降噪模式切换
- 自适应调整信息

## 技术支持

如需进一步的技术支持或自定义配置，请参考：
- ESP-SR官方文档
- 项目Issue页面
- 开发者社区讨论