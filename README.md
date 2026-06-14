[![Banners](docs/images/banner1.png)](https://github.com/xinnan-tech/xiaozhi-esp32-server)

<h1 align="center">智绘课堂·数驱精准——“小慈AI学伴”智能体中枢服务</h1>

<p align="center">
本项目是专为 <b>行空板K10 (Unihiker K10 / DFRobot K10)</b> 深度定制的“小慈AI学伴”配套中枢服务。<br/>
基于优秀的开源项目 <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server">xiaozhi-esp32-server</a> 进行教育场景化升级，<br/>
为<b>“智绘课堂·数驱精准——赋能小学数据驱动教学新范式”</b>提供核心后端支撑。<br/>
支持MQTT+UDP协议、Websocket协议、MCP接入点、声纹识别，并全面助力教育环境的数字化与智能化转型。
</p>

<p align="center">
<a href="./README_en.md">English</a>
· <a href="./docs/FAQ.md">常见问题</a>
· <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/issues">反馈问题</a>
· <a href="./README.md#%E9%83%A8%E7%BD%B2%E6%96%87%E6%A1%A3">部署文档</a>
· <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/releases">更新日志</a>
</p>
<p align="center">
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/releases">
    <img alt="GitHub Contributors" src="https://img.shields.io/github/v/release/xinnan-tech/xiaozhi-esp32-server?logo=docker" />
  </a>
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/graphs/contributors">
    <img alt="GitHub Contributors" src="https://img.shields.io/github/contributors/xinnan-tech/xiaozhi-esp32-server?logo=github" />
  </a>
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/issues">
    <img alt="Issues" src="https://img.shields.io/github/issues/xinnan-tech/xiaozhi-esp32-server?color=0088ff" />
  </a>
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/pulls">
    <img alt="GitHub pull requests" src="https://img.shields.io/github/issues-pr/xinnan-tech/xiaozhi-esp32-server?color=0088ff" />
  </a>
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/LICENSE">
    <img alt="GitHub pull requests" src="https://img.shields.io/badge/license-MIT-white?labelColor=black" />
  </a>
  <a href="https://github.com/xinnan-tech/xiaozhi-esp32-server">
    <img alt="stars" src="https://img.shields.io/github/stars/xinnan-tech/xiaozhi-esp32-server?color=ffcb47&labelColor=black" />
  </a>
</p>

<p align="center">
Spearheaded by Professor Siyuan Liu's Team (South China University of Technology)
</br>
刘思源教授团队主导研发（华南理工大学）
</br>
<img src="./docs/images/hnlg.jpg" alt="华南理工大学" width="50%">
</p>

---

## ✨ 核心功能与优势亮点

### 1. 聚焦“数驱精准”教学新范式
- **学科伴学与互动引导**：交互重心从纯闲聊娱乐，迁移为课辅问答、百科知识搜索、错题思路分析。
- **数据驱动闭环**：通过 WebSocket/MQTT 协议与终端实时通讯，支持将课堂互动数据、提问热点等学情内容反哺给教师终端，真正实现“数据驱动的精准教学”。

### 2. 多模态反馈与智能外设生态（MCP）
- 🤖 **毫秒级 AI 语音对话**：基于流式 ASR + 强大基础模型 (如 DeepSeek / GLM4 / Qwen 等) + TTS 架构，实现无缝互动的教学答疑。
- 🏠 **万物互联控制**：通过设备端 / 云端 MCP 协议，无缝联动课堂生成性教学。

---

## ⚖️ 免责声明与版权鸣谢 (极为重要)

### 💖 版权鸣谢
本项目后端服务代码衍生自 **[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)** 发起的开源后端项目。
固件及后端代码中包含了该项目社区以及前序多位开源贡献者（包含且不限于：空白泡泡糖果、硅灵造物科技、蔓延科技、刘思源教授团队、十方融海等）的心血与创意。
在此，本团队对所有开源先行者为开源社区做出的巨大、无私的贡献致以最崇高的敬意与鸣谢！

### ⚠️ 免责声明 (Disclaimer)
为避免潜在侵权及滥用，保障所有开源参与者的权益，特做以下声明：
1. **开源协议与限制**：本项目作为衍生修改版，继续遵循原仓库的 [MIT 许可证](LICENSE)。本后端服务和相关文档**仅供教育行业数字化探究、前沿学术研究、学校试用及个人的编程学习使用**。
2. **知识产权与商业活动**：相关参与者明确声明，开发者不对任何将本后端、代码或原版涉及代码用于未经授权的**商业牟利、非法倒卖、或侵犯原作者及关联第三方知识产权**的行为进行背书或负责。如因使用者违规挪用而引起的各类版权纠纷、法律诉讼等，一律由违规使用者自行承担全部法律与经济责任。
3. **AI 生成内容免责**：“小慈AI学伴”产生的任何语音、文本解析或观点，均依赖云端大语言模型实时生成，绝不代表本服务端及固件开发者的立场。投入真实教学场景前，校方或使用者务必自行在后台配置和接管安全守护墙及未成年人内容过滤机制。
4. **数据及网络风险概不负责**：部署服务端与自定义通信天然具备不确定风险。本项目未通过网络安全测评，开发者不对任何因此引致的数据遗失、隐私泄露、设备损坏或直接/间接经济损失负任何责任。请严格规范操作，如果暴露在公网，请务必提前做好防数据注入和越权访问拦截。

---

## 部署文档

![Banners](docs/images/banner2.png)

本项目提供两种部署方式，请根据您的具体需求选择：

#### 🚀 部署方式选择
| 部署方式 | 特点 | 适用场景 | 部署文档 | 配置要求 | 视频教程 | 
|---------|------|---------|---------|---------|---------|
| **最简化安装** | 智能对话、IOT、MCP、视觉感知 | 低配置环境，数据存储在配置文件，无需数据库 | [①Docker版](./docs/Deployment.md#%E6%96%B9%E5%BC%8F%E4%B8%80docker%E5%8F%AA%E8%BF%90%E8%A1%8Cserver) / [②源码部署](./docs/Deployment.md#%E6%96%B9%E5%BC%8F%E4%BA%8C%E6%9C%AC%E5%9C%B0%E6%BA%90%E7%A0%81%E5%8F%AA%E8%BF%90%E8%A1%8Cserver)| 如果使用`FunASR`要2核4G，如果全API，要2核2G | - | 
| **全模块安装** | 智能对话、IOT、MCP接入点、声纹识别、视觉感知、OTA、智控台 | 完整功能体验，数据存储在数据库 |[①Docker版](./docs/Deployment_all.md#%E6%96%B9%E5%BC%8F%E4%B8%80docker%E8%BF%90%E8%A1%8C%E5%85%A8%E6%A8%A1%E5%9D%97) / [②源码部署](./docs/Deployment_all.md#%E6%96%B9%E5%BC%8F%E4%BA%8C%E6%9C%AC%E5%9C%B0%E6%BA%90%E7%A0%81%E8%BF%90%E8%A1%8C%E5%85%A8%E6%A8%A1%E5%9D%97) / [③源码部署自动更新教程](./docs/dev-ops-integration.md) | 如果使用`FunASR`要4核8G，如果全API，要2核4G| [本地源码启动视频教程](https://www.bilibili.com/video/BV1wBJhz4Ewe) | 

常见问题及相关教程，可参考[这个链接](./docs/FAQ.md)