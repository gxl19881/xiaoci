import os
import sys
import copy
import json
import uuid
import time
import queue
import asyncio
import threading
import traceback
import subprocess
import websockets

from core.utils.util import (
    extract_json_from_string,
    check_vad_update,
    check_asr_update,
    filter_sensitive_info,
)
from typing import Dict, Any
from collections import deque
from core.utils.modules_initialize import (
    initialize_modules,
    initialize_tts,
    initialize_asr,
)
from core.handle.reportHandle import report
from core.providers.tts.default import DefaultTTS
from concurrent.futures import ThreadPoolExecutor
from core.utils.dialogue import Message, Dialogue
from core.providers.asr.dto.dto import InterfaceType
from core.handle.textHandle import handleTextMessage
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from plugins_func.loadplugins import auto_import_modules
from plugins_func.register import Action
from core.auth import AuthenticationError
from config.config_loader import get_private_config_from_api
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
from config.logger import setup_logging, build_module_string, create_connection_logger
from config.manage_api_client import DeviceNotFoundException, DeviceBindException
from core.utils.prompt_manager import PromptManager
from core.utils.voiceprint_provider import VoiceprintProvider
from core.utils import textUtils

TAG = __name__

auto_import_modules("plugins_func.functions")


class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(
        self,
        config: Dict[str, Any],
        _vad,
        _asr,
        _llm,
        _memory,
        _intent,
        server=None,
    ):
        self.common_config = config
        self.config = copy.deepcopy(config)
        self.session_id = str(uuid.uuid4())
        self.logger = setup_logging()
        self.server = server  # 保存server实例的引用

        self.need_bind = False  # 是否需要绑定设备
        self.bind_code = None  # 绑定设备的验证码
        self.last_bind_prompt_time = 0  # 上次播放绑定提示的时间戳(秒)
        self.bind_prompt_interval = 30  # 绑定提示播放间隔(秒)

        self.read_config_from_api = self.config.get("read_config_from_api", False)

        self.websocket = None
        self.headers = None
        self.device_id = None
        self.client_ip = None
        self.prompt = None
        self.welcome_msg = None
        self.max_output_size = 0
        self.chat_history_conf = 0
        self.audio_format = "opus"

        # 客户端状态相关
        self.client_abort = False
        self.client_is_speaking = False
        self.client_listen_mode = "auto"

        # 线程任务相关
        self.loop = asyncio.get_event_loop()
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=5)

        # 添加上报线程池
        self.report_queue = queue.Queue()
        self.report_thread = None
        # 未来可以通过修改此处，调节asr的上报和tts的上报，目前默认都开启
        self.report_asr_enable = self.read_config_from_api
        self.report_tts_enable = self.read_config_from_api

        # 依赖的组件
        self.vad = None
        self.asr = None
        self.tts = None
        self._asr = _asr
        self._vad = _vad
        self.llm = _llm
        self.memory = _memory
        self.intent = _intent

        # 为每个连接单独管理声纹识别
        self.voiceprint_provider = None

        # vad相关变量
        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.client_voice_window = deque(maxlen=5)
        self.first_activity_time = 0.0  # 记录首次活动的时间（毫秒）
        self.last_activity_time = 0.0  # 统一的活动时间戳（毫秒）
        self.client_voice_stop = False
        self.last_is_voice = False

        # asr相关变量
        # 因为实际部署时可能会用到公共的本地ASR，不能把变量暴露给公共ASR
        # 所以涉及到ASR的变量，需要在这里定义，属于connection的私有变量
        self.asr_audio = []
        self.asr_audio_queue = queue.Queue()

        # llm相关变量
        self.llm_finish_task = True
        self.dialogue = Dialogue()

        # tts相关变量
        self.sentence_id = None
        # 处理TTS响应没有文本返回
        self.tts_MessageText = ""

        # iot相关变量
        self.iot_descriptors = {}
        self.func_handler = None

        self.cmd_exit = self.config["exit_commands"]

        # 是否在聊天结束后关闭连接
        self.close_after_chat = False
        self.load_function_plugin = False
        self.intent_type = "nointent"

        self.timeout_seconds = (
            int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # 在原来第一道关闭的基础上加60秒，进行二道关闭
        self.timeout_task = None

        # {"mcp":true} 表示启用MCP功能
        self.features = None

        # 标记连接是否来自MQTT
        self.conn_from_mqtt_gateway = False

        # 初始化提示词管理器
        self.prompt_manager = PromptManager(config, self.logger)

    async def handle_connection(self, ws):
        try:
            # 获取并验证headers
            self.headers = dict(ws.request.headers)
            real_ip = self.headers.get("x-real-ip") or self.headers.get(
                "x-forwarded-for"
            )
            if real_ip:
                self.client_ip = real_ip.split(",")[0].strip()
            else:
                self.client_ip = ws.remote_address[0]
            self.logger.bind(tag=TAG).info(
                f"{self.client_ip} conn - Headers: {self.headers}"
            )

            self.device_id = self.headers.get("device-id", None)

            # 认证通过,继续处理
            self.websocket = ws

            # 检查是否来自MQTT连接
            request_path = ws.request.path
            self.conn_from_mqtt_gateway = request_path.endswith("?from=mqtt_gateway")
            if self.conn_from_mqtt_gateway:
                self.logger.bind(tag=TAG).info("连接来自:MQTT网关")

            # 初始化活动时间戳
            self.first_activity_time = time.time() * 1000
            self.last_activity_time = time.time() * 1000

            # 启动超时检查任务
            self.timeout_task = asyncio.create_task(self._check_timeout())

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id

            # 获取差异化配置
            self._initialize_private_config()
            # 异步初始化
            self.executor.submit(self._initialize_components)

            try:
                async for message in self.websocket:
                    await self._route_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.bind(tag=TAG).info("客户端断开连接")

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(f"Connection error: {str(e)}-{stack_trace}")
            return
        finally:
            try:
                await self._save_and_close(ws)
            except Exception as final_error:
                self.logger.bind(tag=TAG).error(f"最终清理时出错: {final_error}")
                # 确保即使保存记忆失败，也要关闭连接
                try:
                    await self.close(ws)
                except Exception as close_error:
                    self.logger.bind(tag=TAG).error(
                        f"强制关闭连接时出错: {close_error}"
                    )

    async def _save_and_close(self, ws):
        """保存记忆并关闭连接"""
        try:
            if self.memory:
                # 使用线程池异步保存记忆
                def save_memory_task():
                    try:
                        # 创建新事件循环（避免与主循环冲突）
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.memory.save_memory(self.dialogue.dialogue)
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"保存记忆失败: {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass

                # 启动线程保存记忆，不等待完成
                threading.Thread(target=save_memory_task, daemon=True).start()
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"保存记忆失败: {e}")
        finally:
            # 立即关闭连接，不等待记忆保存完成
            try:
                await self.close(ws)
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"保存记忆后关闭连接失败: {close_error}"
                )

    async def _route_message(self, message):
        """消息路由"""
        if isinstance(message, str):
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            if self.vad is None or self.asr is None:
                return

            # 未绑定设备直接丢弃所有音频，不进行ASR处理
            if self.need_bind:
                current_time = time.time()
                # 检查是否需要播放绑定提示
                if (
                    current_time - self.last_bind_prompt_time
                    >= self.bind_prompt_interval
                ):
                    self.last_bind_prompt_time = current_time
                    # 复用现有的绑定提示逻辑
                    from core.handle.receiveAudioHandle import check_bind_device

                    asyncio.create_task(check_bind_device(self))
                # 直接丢弃音频，不进行ASR处理
                return

            # 处理来自MQTT网关的音频包
            if self.conn_from_mqtt_gateway and len(message) >= 16:
                handled = await self._process_mqtt_audio_message(message)
                if handled:
                    return

            # 不需要头部处理或没有头部时，直接处理原始消息
            self.asr_audio_queue.put(message)

    async def _process_mqtt_audio_message(self, message):
        """
        处理来自MQTT网关的音频消息，解析16字节头部并提取音频数据

        Args:
            message: 包含头部的音频消息

        Returns:
            bool: 是否成功处理了消息
        """
        try:
            # 提取头部信息
            timestamp = int.from_bytes(message[8:12], "big")
            audio_length = int.from_bytes(message[12:16], "big")

            # 提取音频数据
            if audio_length > 0 and len(message) >= 16 + audio_length:
                # 有指定长度，提取精确的音频数据
                audio_data = message[16 : 16 + audio_length]
                # 基于时间戳进行排序处理
                self._process_websocket_audio(audio_data, timestamp)
                return True
            elif len(message) > 16:
                # 没有指定长度或长度无效，去掉头部后处理剩余数据
                audio_data = message[16:]
                self.asr_audio_queue.put(audio_data)
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"解析WebSocket音频包失败: {e}")

        # 处理失败，返回False表示需要继续处理
        return False

    def _process_websocket_audio(self, audio_data, timestamp):
        """处理WebSocket格式的音频包"""
        # 初始化时间戳序列管理
        if not hasattr(self, "audio_timestamp_buffer"):
            self.audio_timestamp_buffer = {}
            self.last_processed_timestamp = 0
            self.max_timestamp_buffer_size = 20

        # 如果时间戳是递增的，直接处理
        if timestamp >= self.last_processed_timestamp:
            self.asr_audio_queue.put(audio_data)
            self.last_processed_timestamp = timestamp

            # 处理缓冲区中的后续包
            processed_any = True
            while processed_any:
                processed_any = False
                for ts in sorted(self.audio_timestamp_buffer.keys()):
                    if ts > self.last_processed_timestamp:
                        buffered_audio = self.audio_timestamp_buffer.pop(ts)
                        self.asr_audio_queue.put(buffered_audio)
                        self.last_processed_timestamp = ts
                        processed_any = True
                        break
        else:
            # 乱序包，暂存
            if len(self.audio_timestamp_buffer) < self.max_timestamp_buffer_size:
                self.audio_timestamp_buffer[timestamp] = audio_data
            else:
                self.asr_audio_queue.put(audio_data)

    async def handle_restart(self, message):
        """处理服务器重启请求"""
        try:

            self.logger.bind(tag=TAG).info("收到服务器重启指令，准备执行...")

            # 发送确认响应
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "success",
                        "message": "服务器重启中...",
                        "content": {"action": "restart"},
                    }
                )
            )

            # 异步执行重启操作
            def restart_server():
                """实际执行重启的方法"""
                time.sleep(1)
                self.logger.bind(tag=TAG).info("执行服务器重启...")
                subprocess.Popen(
                    [sys.executable, "app.py"],
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    start_new_session=True,
                )
                os._exit(0)

            # 使用线程执行重启避免阻塞事件循环
            threading.Thread(target=restart_server, daemon=True).start()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"重启失败: {str(e)}")
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "error",
                        "message": f"Restart failed: {str(e)}",
                        "content": {"action": "restart"},
                    }
                )
            )

    def _initialize_components(self):
        try:
            self.selected_module_str = build_module_string(
                self.config.get("selected_module", {})
            )
            self.logger = create_connection_logger(self.selected_module_str)

            """初始化组件"""
            if self.config.get("prompt") is not None:
                user_prompt = self.config["prompt"]
                # 使用快速提示词进行初始化
                prompt = self.prompt_manager.get_quick_prompt(user_prompt)
                self.change_system_prompt(prompt)
                self.logger.bind(tag=TAG).info(
                    f"快速初始化组件: prompt成功 {prompt[:50]}..."
                )

            """初始化本地组件"""
            if self.vad is None:
                self.vad = self._vad
            if self.asr is None:
                self.asr = self._initialize_asr()

            # 初始化声纹识别
            self._initialize_voiceprint()

            # 打开语音识别通道
            asyncio.run_coroutine_threadsafe(
                self.asr.open_audio_channels(self), self.loop
            )
            if self.tts is None:
                self.tts = self._initialize_tts()
            # 打开语音合成通道
            asyncio.run_coroutine_threadsafe(
                self.tts.open_audio_channels(self), self.loop
            )

            """加载记忆"""
            self._initialize_memory()
            """加载意图识别"""
            self._initialize_intent()
            """初始化上报线程"""
            self._init_report_threads()
            """更新系统提示词"""
            self._init_prompt_enhancement()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"实例化组件失败: {e}")

    def _init_prompt_enhancement(self):
        # 更新上下文信息
        self.prompt_manager.update_context_info(self, self.client_ip)
        enhanced_prompt = self.prompt_manager.build_enhanced_prompt(
            self.config["prompt"], self.device_id, self.client_ip
        )
        if enhanced_prompt:
            self.change_system_prompt(enhanced_prompt)
            self.logger.bind(tag=TAG).debug("系统提示词已增强更新")

    def _init_report_threads(self):
        """初始化ASR和TTS上报线程"""
        if not self.read_config_from_api or self.need_bind:
            return
        if self.chat_history_conf == 0:
            return
        if self.report_thread is None or not self.report_thread.is_alive():
            self.report_thread = threading.Thread(
                target=self._report_worker, daemon=True
            )
            self.report_thread.start()
            self.logger.bind(tag=TAG).info("TTS上报线程已启动")

    def _initialize_tts(self):
        """初始化TTS"""
        tts = None
        if not self.need_bind:
            tts = initialize_tts(self.config)

        if tts is None:
            tts = DefaultTTS(self.config, delete_audio_file=True)

        return tts

    def _initialize_asr(self):
        """初始化ASR"""
        if self._asr.interface_type == InterfaceType.LOCAL:
            # 如果公共ASR是本地服务，则直接返回
            # 因为本地一个实例ASR，可以被多个连接共享
            asr = self._asr
        else:
            # 如果公共ASR是远程服务，则初始化一个新实例
            # 因为远程ASR，涉及到websocket连接和接收线程，需要每个连接一个实例
            asr = initialize_asr(self.config)

        return asr

    def _initialize_voiceprint(self):
        """为当前连接初始化声纹识别"""
        try:
            voiceprint_config = self.config.get("voiceprint", {})
            if voiceprint_config:
                voiceprint_provider = VoiceprintProvider(voiceprint_config)
                if voiceprint_provider is not None and voiceprint_provider.enabled:
                    self.voiceprint_provider = voiceprint_provider
                    self.logger.bind(tag=TAG).info("声纹识别功能已在连接时动态启用")
                else:
                    self.logger.bind(tag=TAG).warning("声纹识别功能启用但配置不完整")
            else:
                self.logger.bind(tag=TAG).info("声纹识别功能未启用")
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"声纹识别初始化失败: {str(e)}")

    def _initialize_private_config(self):
        """如果是从配置文件获取，则进行二次实例化"""
        if not self.read_config_from_api:
            return
        """从接口获取差异化的配置进行二次实例化，非全量重新实例化"""
        try:
            begin_time = time.time()
            private_config = get_private_config_from_api(
                self.config,
                self.headers.get("device-id"),
                self.headers.get("client-id", self.headers.get("device-id")),
            )
            private_config["delete_audio"] = bool(self.config.get("delete_audio", True))
            self.logger.bind(tag=TAG).info(
                f"{time.time() - begin_time} 秒，获取差异化配置成功: {json.dumps(filter_sensitive_info(private_config), ensure_ascii=False)}"
            )
        except DeviceNotFoundException as e:
            self.need_bind = True
            private_config = {}
        except DeviceBindException as e:
            self.need_bind = True
            self.bind_code = e.bind_code
            private_config = {}
        except Exception as e:
            self.need_bind = True
            self.logger.bind(tag=TAG).error(f"获取差异化配置失败: {e}")
            private_config = {}

        init_llm, init_tts, init_memory, init_intent = (
            False,
            False,
            False,
            False,
        )

        init_vad = check_vad_update(self.common_config, private_config)
        init_asr = check_asr_update(self.common_config, private_config)

        if init_vad:
            self.config["VAD"] = private_config["VAD"]
            self.config["selected_module"]["VAD"] = private_config["selected_module"][
                "VAD"
            ]
        if init_asr:
            self.config["ASR"] = private_config["ASR"]
            self.config["selected_module"]["ASR"] = private_config["selected_module"][
                "ASR"
            ]
        if private_config.get("TTS", None) is not None:
            init_tts = True
            self.config["TTS"] = private_config["TTS"]
            self.config["selected_module"]["TTS"] = private_config["selected_module"][
                "TTS"
            ]
        if private_config.get("LLM", None) is not None:
            init_llm = True
            self.config["LLM"] = private_config["LLM"]
            self.config["selected_module"]["LLM"] = private_config["selected_module"][
                "LLM"
            ]
        if private_config.get("VLLM", None) is not None:
            self.config["VLLM"] = private_config["VLLM"]
            self.config["selected_module"]["VLLM"] = private_config["selected_module"][
                "VLLM"
            ]
        if private_config.get("Memory", None) is not None:
            init_memory = True
            self.config["Memory"] = private_config["Memory"]
            self.config["selected_module"]["Memory"] = private_config[
                "selected_module"
            ]["Memory"]
        if private_config.get("Intent", None) is not None:
            init_intent = True
            self.config["Intent"] = private_config["Intent"]
            model_intent = private_config.get("selected_module", {}).get("Intent", {})
            self.config["selected_module"]["Intent"] = model_intent
            # 加载插件配置
            if model_intent != "Intent_nointent":
                plugin_from_server = private_config.get("plugins", {})
                for plugin, config_str in plugin_from_server.items():
                    plugin_from_server[plugin] = json.loads(config_str)
                self.config["plugins"] = plugin_from_server
                self.config["Intent"][self.config["selected_module"]["Intent"]][
                    "functions"
                ] = plugin_from_server.keys()
        if private_config.get("prompt", None) is not None:
            self.config["prompt"] = private_config["prompt"]
        # 获取声纹信息
        if private_config.get("voiceprint", None) is not None:
            self.config["voiceprint"] = private_config["voiceprint"]
        if private_config.get("summaryMemory", None) is not None:
            self.config["summaryMemory"] = private_config["summaryMemory"]
        if private_config.get("device_max_output_size", None) is not None:
            self.max_output_size = int(private_config["device_max_output_size"])
        if private_config.get("chat_history_conf", None) is not None:
            self.chat_history_conf = int(private_config["chat_history_conf"])
        if private_config.get("mcp_endpoint", None) is not None:
            self.config["mcp_endpoint"] = private_config["mcp_endpoint"]
        try:
            modules = initialize_modules(
                self.logger,
                private_config,
                init_vad,
                init_asr,
                init_llm,
                init_tts,
                init_memory,
                init_intent,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"初始化组件失败: {e}")
            modules = {}
        if modules.get("tts", None) is not None:
            self.tts = modules["tts"]
        if modules.get("vad", None) is not None:
            self.vad = modules["vad"]
        if modules.get("asr", None) is not None:
            self.asr = modules["asr"]
        if modules.get("llm", None) is not None:
            self.llm = modules["llm"]
        if modules.get("intent", None) is not None:
            self.intent = modules["intent"]
        if modules.get("memory", None) is not None:
            self.memory = modules["memory"]

    def _initialize_memory(self):
        if self.memory is None:
            return
        """初始化记忆模块"""
        self.memory.init_memory(
            role_id=self.device_id,
            llm=self.llm,
            summary_memory=self.config.get("summaryMemory", None),
            save_to_file=not self.read_config_from_api,
        )

        # 获取记忆总结配置
        memory_config = self.config["Memory"]
        memory_type = self.config["Memory"][self.config["selected_module"]["Memory"]][
            "type"
        ]
        # 如果使用 nomen，直接返回
        if memory_type == "nomem":
            return
        # 使用 mem_local_short 模式
        elif memory_type == "mem_local_short":
            memory_llm_name = memory_config[self.config["selected_module"]["Memory"]][
                "llm"
            ]
            if memory_llm_name and memory_llm_name in self.config["LLM"]:
                # 如果配置了专用LLM，则创建独立的LLM实例
                from core.utils import llm as llm_utils

                memory_llm_config = self.config["LLM"][memory_llm_name]
                memory_llm_type = memory_llm_config.get("type", memory_llm_name)
                memory_llm = llm_utils.create_instance(
                    memory_llm_type, memory_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"为记忆总结创建了专用LLM: {memory_llm_name}, 类型: {memory_llm_type}"
                )
                self.memory.set_llm(memory_llm)
            else:
                # 否则使用主LLM
                self.memory.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("使用主LLM作为意图识别模型")

    def _initialize_intent(self):
        if self.intent is None:
            return
        self.intent_type = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ]["type"]
        if self.intent_type == "function_call" or self.intent_type == "intent_llm":
            self.load_function_plugin = True
        """初始化意图识别模块"""
        # 获取意图识别配置
        intent_config = self.config["Intent"]
        intent_type = self.config["Intent"][self.config["selected_module"]["Intent"]][
            "type"
        ]

        # 如果使用 nointent，直接返回
        if intent_type == "nointent":
            return
        # 使用 intent_llm 模式
        elif intent_type == "intent_llm":
            intent_llm_name = intent_config[self.config["selected_module"]["Intent"]][
                "llm"
            ]

            if intent_llm_name and intent_llm_name in self.config["LLM"]:
                # 如果配置了专用LLM，则创建独立的LLM实例
                from core.utils import llm as llm_utils

                intent_llm_config = self.config["LLM"][intent_llm_name]
                intent_llm_type = intent_llm_config.get("type", intent_llm_name)
                intent_llm = llm_utils.create_instance(
                    intent_llm_type, intent_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"为意图识别创建了专用LLM: {intent_llm_name}, 类型: {intent_llm_type}"
                )
                self.intent.set_llm(intent_llm)
            else:
                # 否则使用主LLM
                self.intent.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("使用主LLM作为意图识别模型")

        """加载统一工具处理器"""
        self.func_handler = UnifiedToolHandler(self)

        # 异步初始化工具处理器
        if hasattr(self, "loop") and self.loop:
            asyncio.run_coroutine_threadsafe(self.func_handler._initialize(), self.loop)

    def change_system_prompt(self, prompt):
        self.prompt = prompt
        # 更新系统prompt至上下文
        self.dialogue.update_system_message(self.prompt)

    def chat(self, query, depth=0):
        if query is not None:
            self.logger.bind(tag=TAG).info(f"大模型收到用户消息: {query}")

        # 为最顶层时新建会话ID和发送FIRST请求
        if depth == 0:
            self.llm_finish_task = False
            self.sentence_id = str(uuid.uuid4().hex)
            self.dialogue.put(Message(role="user", content=query))
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=self.sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )

        # 设置最大递归深度，避免无限循环，可根据实际需求调整
        MAX_DEPTH = 5
        force_final_answer = False  # 标记是否强制最终回答

        if depth >= MAX_DEPTH:
            self.logger.bind(tag=TAG).debug(
                f"已达到最大工具调用深度 {MAX_DEPTH}，将强制基于现有信息回答"
            )
            force_final_answer = True
            # 添加系统指令，要求 LLM 基于现有信息回答
            self.dialogue.put(
                Message(
                    role="user",
                    content="[系统提示] 已达到最大工具调用次数限制，请你基于目前已经获取的所有信息，直接给出最终答案。不要再尝试调用任何工具。",
                )
            )

        # Define intent functions
        functions = None
        # 达到最大深度时，禁用工具调用，强制 LLM 直接回答
        if (
            self.intent_type == "function_call"
            and hasattr(self, "func_handler")
            and not force_final_answer
        ):
            functions = self.func_handler.get_functions()
        response_message = []

        try:
            # 使用带记忆的对话
            memory_str = None
            if self.memory is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self.memory.query_memory(query), self.loop
                )
                memory_str = future.result()

            if self.intent_type == "function_call" and functions is not None:
                # 使用支持functions的streaming接口
                llm_responses = self.llm.response_with_functions(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                    functions=functions,
                )
            else:
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
            return None

        # 处理流式响应
        tool_call_flag = False
        # 支持多个并行工具调用 - 使用列表存储
        tool_calls_list = []  # 格式: [{"id": "", "name": "", "arguments": ""}]
        content_arguments = ""
        self.client_abort = False
        emotion_flag = True
        for response in llm_responses:
            if self.client_abort:
                break
            if self.intent_type == "function_call" and functions is not None:
                content, tools_call = response
                if "content" in response:
                    content = response["content"]
                    tools_call = None
                if content is not None and len(content) > 0:
                    content_arguments += content

                if not tool_call_flag and content_arguments.startswith("<tool_call>"):
                    # print("content_arguments", content_arguments)
                    tool_call_flag = True

                if tools_call is not None and len(tools_call) > 0:
                    tool_call_flag = True
                    self._merge_tool_calls(tool_calls_list, tools_call)
            else:
                content = response

            # 在llm回复中获取情绪表情，一轮对话只在开头获取一次
            if emotion_flag and content is not None and content.strip():
                asyncio.run_coroutine_threadsafe(
                    textUtils.get_emotion(self, content),
                    self.loop,
                )
                emotion_flag = False

            if content is not None and len(content) > 0:
                if not tool_call_flag:
                    response_message.append(content)
                    self.tts.tts_text_queue.put(
                        TTSMessageDTO(
                            sentence_id=self.sentence_id,
                            sentence_type=SentenceType.MIDDLE,
                            content_type=ContentType.TEXT,
                            content_detail=content,
                        )
                    )
        # 处理function call
        if tool_call_flag:
            bHasError = False
            # 处理基于文本的工具调用格式
            if len(tool_calls_list) == 0 and content_arguments:
                a = extract_json_from_string(content_arguments)
                if a is not None:
                    try:
                        content_arguments_json = json.loads(a)
                        tool_calls_list.append(
                            {
                                "id": str(uuid.uuid4().hex),
                                "name": content_arguments_json["name"],
                                "arguments": json.dumps(
                                    content_arguments_json["arguments"],
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    except Exception as e:
                        bHasError = True
                        response_message.append(a)
                else:
                    bHasError = True
                    response_message.append(content_arguments)
                if bHasError:
                    self.logger.bind(tag=TAG).error(
                        f"function call error: {content_arguments}"
                    )

            if not bHasError and len(tool_calls_list) > 0:
                # 如需要大模型先处理一轮，添加相关处理后的日志情况
                if len(response_message) > 0:
                    text_buff = "".join(response_message)
                    self.tts_MessageText = text_buff
                    self.dialogue.put(Message(role="assistant", content=text_buff))
                response_message.clear()

                self.logger.bind(tag=TAG).debug(
                    f"检测到 {len(tool_calls_list)} 个工具调用"
                )

                # 收集所有工具调用的 Future
                futures_with_data = []
                for tool_call_data in tool_calls_list:
                    self.logger.bind(tag=TAG).debug(
                        f"function_name={tool_call_data['name']}, function_id={tool_call_data['id']}, function_arguments={tool_call_data['arguments']}"
                    )

                    future = asyncio.run_coroutine_threadsafe(
                        self.func_handler.handle_llm_function_call(
                            self, tool_call_data
                        ),
                        self.loop,
                    )
                    futures_with_data.append((future, tool_call_data))

                # 等待协程结束（实际等待时长为最慢的那个）
                tool_results = []
                for future, tool_call_data in futures_with_data:
                    result = future.result()
                    tool_results.append((result, tool_call_data))

                # 统一处理所有工具调用结果
                if tool_results:
                    self._handle_function_result(tool_results, depth=depth)

        # 存储对话内容
        if len(response_message) > 0:
            text_buff = "".join(response_message)
            self.tts_MessageText = text_buff
            self.dialogue.put(Message(role="assistant", content=text_buff))
        if depth == 0:
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=self.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
            self.llm_finish_task = True
            # 使用lambda延迟计算，只有在DEBUG级别时才执行get_llm_dialogue()
            self.logger.bind(tag=TAG).debug(
                lambda: json.dumps(
                    self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False
                )
            )

        return True

    def _handle_function_result(self, tool_results, depth):
        need_llm_tools = []

        for result, tool_call_data in tool_results:
            if result.action in [
                Action.RESPONSE,
                Action.NOTFOUND,
                Action.ERROR,
            ]:  # 直接回复前端
                text = result.response if result.response else result.result
                self.tts.tts_one_sentence(self, ContentType.TEXT, content_detail=text)
                self.dialogue.put(Message(role="assistant", content=text))
            elif result.action == Action.REQLLM:
                # 收集需要 LLM 处理的工具
                need_llm_tools.append((result, tool_call_data))
            else:
                pass

        if need_llm_tools:
            all_tool_calls = [
                {
                    "id": tool_call_data["id"],
                    "function": {
                        "arguments": (
                            "{}"
                            if tool_call_data["arguments"] == ""
                            else tool_call_data["arguments"]
                        ),
                        "name": tool_call_data["name"],
                    },
                    "type": "function",
                    "index": idx,
                }
                for idx, (_, tool_call_data) in enumerate(need_llm_tools)
            ]
            self.dialogue.put(Message(role="assistant", tool_calls=all_tool_calls))

            for result, tool_call_data in need_llm_tools:
                text = result.result
                if text is not None and len(text) > 0:
                    self.dialogue.put(
                        Message(
                            role="tool",
                            tool_call_id=(
                                str(uuid.uuid4())
                                if tool_call_data["id"] is None
                                else tool_call_data["id"]
                            ),
                            content=text,
                        )
                    )

            self.chat(None, depth=depth + 1)

    def _report_worker(self):
        """聊天记录上报工作线程"""
        while not self.stop_event.is_set():
            try:
                # 从队列获取数据，设置超时以便定期检查停止事件
                item = self.report_queue.get(timeout=1)
                if item is None:  # 检测毒丸对象
                    break
                try:
                    # 检查线程池状态
                    if self.executor is None:
                        continue
                    # 提交任务到线程池
                    self.executor.submit(self._process_report, *item)
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"聊天记录上报线程异常: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"聊天记录上报工作线程异常: {e}")

        self.logger.bind(tag=TAG).info("聊天记录上报线程已退出")

    def _process_report(self, type, text, audio_data, report_time):
        """处理上报任务"""
        try:
            # 执行上报（传入二进制数据）
            report(self, type, text, audio_data, report_time)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"上报处理异常: {e}")
        finally:
            # 标记任务完成
            self.report_queue.task_done()

    def clearSpeakStatus(self):
        self.client_is_speaking = False
        self.logger.bind(tag=TAG).debug(f"清除服务端讲话状态")

    async def close(self, ws=None):
        """资源清理方法"""
        try:
            # 清理音频缓冲区
            if hasattr(self, "audio_buffer"):
                self.audio_buffer.clear()

            # 取消超时任务
            if self.timeout_task and not self.timeout_task.done():
                self.timeout_task.cancel()
                try:
                    await self.timeout_task
                except asyncio.CancelledError:
                    pass
                self.timeout_task = None

            # 清理工具处理器资源
            if hasattr(self, "func_handler") and self.func_handler:
                try:
                    await self.func_handler.cleanup()
                except Exception as cleanup_error:
                    self.logger.bind(tag=TAG).error(
                        f"清理工具处理器时出错: {cleanup_error}"
                    )

            # 触发停止事件
            if self.stop_event:
                self.stop_event.set()

            # 清空任务队列
            self.clear_queues()

            # 关闭WebSocket连接
            try:
                if ws:
                    # 安全地检查WebSocket状态并关闭
                    try:
                        if hasattr(ws, "closed") and not ws.closed:
                            await ws.close()
                        elif hasattr(ws, "state") and ws.state.name != "CLOSED":
                            await ws.close()
                        else:
                            # 如果没有closed属性，直接尝试关闭
                            await ws.close()
                    except Exception:
                        # 如果关闭失败，忽略错误
                        pass
                elif self.websocket:
                    try:
                        if (
                            hasattr(self.websocket, "closed")
                            and not self.websocket.closed
                        ):
                            await self.websocket.close()
                        elif (
                            hasattr(self.websocket, "state")
                            and self.websocket.state.name != "CLOSED"
                        ):
                            await self.websocket.close()
                        else:
                            # 如果没有closed属性，直接尝试关闭
                            await self.websocket.close()
                    except Exception:
                        # 如果关闭失败，忽略错误
                        pass
            except Exception as ws_error:
                self.logger.bind(tag=TAG).error(f"关闭WebSocket连接时出错: {ws_error}")

            if self.tts:
                await self.tts.close()

            # 最后关闭线程池（避免阻塞）
            if self.executor:
                try:
                    self.executor.shutdown(wait=False)
                except Exception as executor_error:
                    self.logger.bind(tag=TAG).error(
                        f"关闭线程池时出错: {executor_error}"
                    )
                self.executor = None

            import gc
            gc.collect()

            self.logger.bind(tag=TAG).info("连接资源已释放")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"关闭连接时出错: {e}")
        finally:
            # 确保停止事件被设置
            if self.stop_event:
                self.stop_event.set()

    def clear_queues(self):
        """清空所有任务队列"""
        if self.tts:
            self.logger.bind(tag=TAG).debug(
                f"开始清理: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}"
            )

            # 使用非阻塞方式清空队列
            for q in [
                self.tts.tts_text_queue,
                self.tts.tts_audio_queue,
                self.report_queue,
            ]:
                if not q:
                    continue
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break

            self.logger.bind(tag=TAG).debug(
                f"清理结束: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}"
            )

    def reset_vad_states(self):
        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.client_voice_stop = False
        self.logger.bind(tag=TAG).debug("VAD states reset.")

    def chat_and_close(self, text):
        """Chat with the user and then close the connection"""
        try:
            # Use the existing chat method
            self.chat(text)

            # After chat is complete, close the connection
            self.close_after_chat = True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Chat and close error: {str(e)}")

    async def _check_timeout(self):
        """检查连接超时"""
        try:
            while not self.stop_event.is_set():
                last_activity_time = self.last_activity_time
                if self.need_bind:
                    last_activity_time = self.first_activity_time

                # 检查是否超时（只有在时间戳已初始化的情况下）
                if last_activity_time > 0.0:
                    current_time = time.time() * 1000
                    if current_time - last_activity_time > self.timeout_seconds * 1000:
                        if not self.stop_event.is_set():
                            self.logger.bind(tag=TAG).info("连接超时，准备关闭")
                            # 设置停止事件，防止重复处理
                            self.stop_event.set()
                            # 使用 try-except 包装关闭操作，确保不会因为异常而阻塞
                            try:
                                await self.close(self.websocket)
                            except Exception as close_error:
                                self.logger.bind(tag=TAG).error(
                                    f"超时关闭连接时出错: {close_error}"
                                )
                        break
                # 每10秒检查一次，避免过于频繁
                await asyncio.sleep(10)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"超时检查任务出错: {e}")
        finally:
            self.logger.bind(tag=TAG).info("超时检查任务已退出")

    def _merge_tool_calls(self, tool_calls_list, tools_call):
        """合并工具调用列表

        Args:
            tool_calls_list: 已收集的工具调用列表
            tools_call: 新的工具调用
        """
        for tool_call in tools_call:
            tool_index = getattr(tool_call, "index", None)
            if tool_index is None:
                if tool_call.function.name:
                    # 有 function_name，说明是新的工具调用
                    tool_index = len(tool_calls_list)
                else:
                    tool_index = len(tool_calls_list) - 1 if tool_calls_list else 0

            # 确保列表有足够的位置
            if tool_index >= len(tool_calls_list):
                tool_calls_list.append({"id": "", "name": "", "arguments": ""})

            # 更新工具调用信息
            if tool_call.id:
                tool_calls_list[tool_index]["id"] = tool_call.id
            if tool_call.function.name:
                tool_calls_list[tool_index]["name"] = tool_call.function.name
            if tool_call.function.arguments:
                tool_calls_list[tool_index]["arguments"] += tool_call.function.arguments
from core.utils.modules_initialize import (
    initialize_modules,
    initialize_tts,
    initialize_asr,
)
from core.handle.reportHandle import report
from core.providers.tts.default import DefaultTTS
from concurrent.futures import ThreadPoolExecutor
from core.utils.dialogue import Message, Dialogue
from core.providers.asr.dto.dto import InterfaceType
from core.handle.textHandle import handleTextMessage
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from plugins_func.loadplugins import auto_import_modules
from plugins_func.register import Action, ActionResponse
from core.auth import AuthMiddleware, AuthenticationError
from config.config_loader import get_private_config_from_api
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
from config.logger import setup_logging, build_module_string, create_connection_logger
from config.manage_api_client import DeviceNotFoundException, DeviceBindException
from core.utils.prompt_manager import PromptManager
from core.utils.voiceprint_provider import VoiceprintProvider
from core.utils import textUtils

TAG = __name__

auto_import_modules("plugins_func.functions")


class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(
        self,
        config: Dict[str, Any],
        _vad,
        _asr,
        _llm,
        _memory,
        _intent,
        server=None,
    ):
        self.common_config = config
        self.config = copy.deepcopy(config)
        self.session_id = str(uuid.uuid4())
        self.logger = setup_logging()
        self.server = server  # 婵烇絽娲换鍌炴偤閳虹棜rver闁诲骸婀遍崑妯兼閵夊剭闁告洜闂?
        self.auth = AuthMiddleware(config)
        self.need_bind = False
        self.bind_code = None
        self.read_config_from_api = self.config.get("read_config_from_api", False)

        self.websocket = None
        self.headers = None
        self.device_id = None
        self.client_ip = None
        self.student_id = None
        self.prompt = None
        self.welcome_msg = None
        self.max_output_size = 0
        self.chat_history_conf = 0
        self.audio_format = "opus"
        # PCM缂備焦姊荤喊宥夋煥濞戞瑥鍝虹紒濯奸柕鍫濆閻熸繈鏌熺粙鎸庢悙闁?None)闂佹寧绋戦懟鎮楅獮鍨仾闁哥〒缁粩鐔兼偋閸喖鏌涢幒鎾舵噧婵犻悪婕嘡闂傚倸鍟抽崺鏍煠瀹勯澏妤佷繆閸嬫挻绻涢弶鎴犳鏉堢箚闁稿本鐔槐锝夋煛閸曢柛濯撮悹鎭掑妽閺?'le' 闂?'be'
        self.pcm_endian = None
        # PCM缂傚倸鍊归悧婊堟偉濠婂牊鏅?s16' (婵帗绋? 闂?'u16'闂佹寧绋掗柦ne 闁荤偞绋忛崝搴濮樿泛瀚夐柨娑欏姍瀵増鎯旂粈澶愭煟閵忓巶SR闂傚倸鍟抽崺鏍倶韫囨梻绠氶柣鍤婂鏅濋幏鐘诲幢濡悞?婵烇絽娲换鍐灚姊规俊?        self.pcm_encoding = None
        # ASR闁荤姴娲犻弸鍛存煕鐎ｇ闁靛牅绮欓弫宥夊醇濠婂懍绱ｆ繝?'zh'/'en'/'yue'闂佹寧绋戠紒杈箞閹崇喖濡烽妶鍫紓浣歌嫰閹煎垂閹姤娼忛妸鍊掓繛鎾寸缁嬫牠鍩閹虫捇宕靛鍫濈闁靛绠戦湁?        self.asr_language = None

        # 闁诲骸绠嶉崹娲春濞戞氨鍗氬鎮傞獮濞达絿鍎粊鏌煕?        self.client_abort = False
        self.client_is_speaking = False
        self.client_listen_mode = "auto"
        # 闂佺儵鏅滈崹鐢稿箚婢舵劖婵炲棙鎸鹃崣楣冩倵閻熸壆澧涘鍨虹粋鎺旀嫚閹绘帞鍨闁轰降鍊栫粙澶嬫償閵忕帛闂佸憡鑹剧花鑲博鐎靛憡鏆滅憸搴￠崒鐐撮悗娑欓悡鍫煥濞戞澧涚紓浣哥敮妲?        self.listen_silence_task = None
        self.last_audio_frame_time = 0.0

        # 缂備焦宕樺鏇煝閸忚偐閻犲洦褰冮梺鐑櫇闁?        self.loop = asyncio.get_event_loop()
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=5)

        # 濠电儑缍濠靛仦缁嬪绻濋崘鎾剁磼閹规劖纭堕柍鑽帶鏁?        self.report_queue = queue.Queue()
        self.report_thread = None
        # 闂佸搫鐗婇梽宥夋煕濞嗗海闉嶉梻浣蜂孩缂佽鍟粚閬嶅极閻撳酣濡堕崨瀛樻櫖鐎归崘闂佽壈妗换姒畆闂佹眹鍔岀氱箔閸岀偛绠柕澶堝劜鐎氱灜ts闂佹眹鍔岀氱箔閸岀偛绠柕澶岄梺鐑櫅婵帗绋掗梻浣圭紒杈灴瀹?        self.report_asr_enable = self.read_config_from_api
        self.report_tts_enable = self.read_config_from_api

        # 婵炴挻纰嶇换鍡欑矉閸稒鍎嶉柛鏇犵厑婵?        self.vad = None
        self.asr = None
        self.tts = None
        self._asr = _asr
        self._vad = _vad
        self.llm = _llm
        self.memory = _memory
        self.intent = _intent

        # 婵炴垶鎸鹃崕鎯侀埄鍐紒缁樼洴楠炴帡濡烽妷闂佺粯鐟幃鍫曞幢濡鐭楃紓浣稿闁诲灴瀹?        self.voiceprint_provider = None

        # vad闂佺儵鏅濋柛娅诲洤鐭楁慨妞诲亾闁?        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.last_activity_time = 0.0  # 缂傚倷鑳堕崰宥囩博閹惧剭闁告洏浠梺鍛婃煟閸斿秴閸岀偞閻庢稒閻撳牓鏌妯煎缂備礁鐢?        self.client_voice_stop = False
        self.client_voice_window = deque(maxlen=5)
        self.last_is_voice = False

        # asr闂佺儵鏅濋柛娅诲洤鐭楁慨妞诲亾闁?        # 闂佹悶鍎虫慨宕囨嫻閻旇　鍋撻崷浠辨俊鐐劸闁靛鍡涙煛閸愮【鐟滅増鐓￠幊妤呭箣閹烘梻鐛梺璇插闁哥焸瀹曟宕ｉ敓鐘冲剭闁告洘瀚抽梺闈濡剧櫇R闂佹寧绋戞總鏃傜箔婢舵劖鍤勯柤鎭掑劚鎯熼梺鍛婄懄閿曞闯濞叉辈闁规崘瀚欑紓鍌欑劍閻熷矗閺囩闁绘R
        # 闂佸湱閸嬫挸閻樺姕缂佸缍婂畷锝嗙節閸屾氨鍘扐SR闂佹眹鍔岀氭径鎰厒闊洢鍎崇粈澶愭閸絽浜鹃柣鐔告磻缁浣稿璇查幘铏柣搴惌绮婚悢鍏兼櫖閻忕偟鏅锝呭鍐猳nnection闂佹眹鍔岀氭煛閸繆婢舵劖鐓?        self.asr_audio = []
        self.asr_audio_queue = queue.Queue()

        # llm闂佺儵鏅濋柛娅诲洤鐭楁慨妞诲亾闁?        self.llm_finish_task = True
        self.dialogue = Dialogue()

        # tts闂佺儵鏅濋柛娅诲洤鐭楁慨妞诲亾闁?        self.sentence_id = None
        # 婵犳硾鐎氬箖婵係闂佸憡绻傜粔瀵歌姳閹绘巻鏌柍鍟粻鎺楁煛閸屾碍澶勬繝閻楀牊浜柡鍌涘缁
        self.tts_MessageText = ""

        # iot闂佺儵鏅濋柛娅诲洤鐭楁慨妞诲亾闁?        self.iot_descriptors = {}
        self.func_handler = None

        self.cmd_exit = self.config["exit_commands"]

        # 闂佸搫瀚崕濠囨煕閿斿搫濮濞存粎澧楀鍕煛閸愬皾闂佸搫閸犲酣骞冨鍛闁规儼濮敍鏃堝级閳哄啫浠悽?        self.close_after_chat = False
        self.load_function_plugin = False
        self.intent_type = "nointent"

        self.timeout_seconds = (
            int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # 闂侀潻璐熼崝宀鏁鍫曞瑜庣粙澶愬焵閺屽棝骞橀崘鎻掔稑闂傚倸鍊归悾閬嶆煕閳哄嫭婵炴垶鎸搁敃鎱?0缂備礁鐢濠靛洦浜繛鎴炵矋缁傚秴鐣濋崟闂佺绻戞繛濠?        self.timeout_task = None

        # {"mcp":true} 闁荤偞绋忛崝搴濮樿泛瑙柡涓哖闂佸憡姊婚崰鏇礂?        self.features = None

        # 闂佸搫绉村寮堕埡鍐沪閻尦瀵即骞嗘笟瀵爼濡烽妸MQTT
        self.conn_from_mqtt_gateway = False

        # 闂佸憡甯楃换鍌炴煕閺嶅鐟滈鑳剁划鍫熺捄缂備胶濯寸槐鏇箖婵犲洤闂?        self.prompt_manager = PromptManager(config, self.logger)
        try:
            self._data_root = os.path.abspath(os.path.join(os.getcwd(), "data"))
        except Exception:
            self._data_root = os.path.abspath("data")
        # 闁荤喐鐟婊呯磽娴ｈ灏伴柣蹇撳畷绻濆缂傚倸鍊归幐鎼佹偤閵婃櫖闁稿灪閺嗗繐濠婂啳TTP濠甸崕鑼暜閹惧剭闁告洘鐓繛鍡楃箲缁婵炵鍋愭刊瀵告?        self._seen_vision_ids = set()

        # 閻庤鎮堕崕閬嶅矗閹稿孩浜柟鐗堝亹闁煎摜閸嬫挻鎷呴崷鐏遍柣鐘辩鎼存粎妲愬鎾村仺闁靛鍊楅懝楣冩煛閸鍛婄閻樼數鐭氭繛璇闯闁诲笒閹冲繐閸岀偞鏅?        self._tool_running = False

        # WebSocket闁哄鏅滈崝姗鏌ｅ鍨厫闁崇紒妤鏈粚鍗為崶浠繛瀵稿濠?        self.ws_open = False
        self._ping_keepalive_task = None
        # 闁荤喐鐟?閻庤鎮堕崕閬嶅矗閸绠憸鎴煟濡灝鐓愰柍绛忕紒杈懇閹粙濡搁妶鍥闁诲繒鍋涚换妤呭棘閳磼鐏炵偓婵櫕閹奸箖宕梺?        self._vision_inflight = False
        # 闂佸搫鍊瑰姗鏌娆庝孩闁荤喐鐟紒缁樿壘鐓悹浣芥珪瀹曟煡鏌涢弬琛亾瀹曞洨闂?        self._vision_keepalive_task = None

    def mark_active(self):
        """Mark this connection as active (updates last_activity_time)."""
        try:
            self.last_activity_time = time.time() * 1000
        except Exception:
            pass

    async def _try_replay_recent_vision_result(self, window_seconds: int = 60):
        """Try to replay recent vision result for the same client.

        - Looks up `data/vision_records/YYYYMMDD` for recent JSON files containing the
          short client-id in filename, sorted by mtime, within `window_seconds`.
        - If found, will read the latest entries and send them back to the client.
        """
        try:
            cid = (self.headers.get("client-id", "") or "")[:8]
            if not cid:
                return
            from datetime import datetime, timedelta
            base = os.path.abspath(os.path.join(os.getcwd(), "data", "vision_records"))
            day_dir = os.path.join(base, datetime.now().strftime("%Y%m%d"))
            if not os.path.isdir(day_dir):
                return
            now = datetime.now()
            candidates = [
                f for f in os.listdir(day_dir) if f.endswith(".json") and cid in f
            ]
            if not candidates:
                return
            # sort by mtime desc
            candidates.sort(
                key=lambda fn: os.path.getmtime(os.path.join(day_dir, fn)),
                reverse=True,
            )
            for fn in candidates[:5]:
                p = os.path.join(day_dir, fn)
                mtime = datetime.fromtimestamp(os.path.getmtime(p))
                if (now - mtime).total_seconds() > window_seconds:
                    continue
                try:
                    import json as _json
                    with open(p, "r", encoding="utf-8") as jf:
                        data = _json.load(jf)
                    if isinstance(data, dict) and data.get("success") is True and data.get("action") == "RESPONSE":
                        text = data.get("response") or ""
                        if not text:
                            continue
                        try:
                            from core.utils import textUtils as _txu
                            text = _txu.sanitize_for_device(text)
                        except Exception:
                            pass
                        # 闂佺儵鏅涢悺鏁涙浜繛鎴炵矒瀹曟岸宕卞楠炴鎱妶澶嬫櫖閻忕偟鍋撶紒?FIRST/MIDDLE/LAST闂佹寧绋戦惌鍌涘閳哄懎绀傜圭墛瀵板嫰宕堕埡鍛煑闁靛／鍕彧婵炴垶鎸哥粔鎾偩瀵?                        self._speak_vision_response(text)
                        # 闂佸憡鑹鹃張鏌涢幇鎳冮柛娆忔閳暩闁?                        self.dialogue.put(Message(role="assistant", content=text))
                        try:
                            self._append_conversation_event(question=self._get_last_user_content(), reply=text, source="realtime")
                        except Exception:
                            pass
                        self.logger.bind(tag=TAG).info("Replayed recent vision response to client.")
                        # 闂佸憡甯￠弨閬嶅蓟婵犲伅铏规嫚閹绘崼妤呮煛閸愬煟婵健閺佸秴鐣濋崟鎱鍕伄闁逛紮缍侀獮鎺楀瑜庣徊濠氭偠濮樻瘷鏌￠崘鐓愮紒鏂块幃?                        self.last_activity_time = time.time() * 1000
                        return
                except Exception:
                    continue
        except Exception as _e:
            try:
                self.logger.bind(tag=TAG).warning(f"闂備焦褰冪粔椋庢崲濞戞碍鍠嗛柛姘槐鎺楀箻鐎甸晲鍑介梺鎼炲劤閸嬬偤寮担鐟扮窞閺夊熆? {_e}")
            except Exception:
                pass

    def _append_conversation_event(self, question: str, reply: str, files=None, source: str = "realtime"):
        """闁诲繐绻愬鏃傜博鐎涙濮滈柣鐘叉处缁诲倿宕幘璇茬?data/conversations/YYYYMMDD/<session_id>.jsonl
        - conversation_id 闂備焦褰冨寮妶鍫涗汗闁规儳鍟块柡澶嗘櫇閸嬬偟鏁幘鍎?session_id闂佹寧绋戦悧鍡涘箖閹惧闁充氦闁绘劖娼欐径宥夋煕閹板櫣缂傚秴闁挎繂鎳庨悡鍌炴煕濮樼紒鏃鎸冲宕堕敂浠嬫煥?        - 闁诲孩鍐荤粻鎴ｉ崸妤绾柕澶堝妼濞堜即鏌熼悜澧插绮嶅鍕礄閻樼數闁诲孩绋掓繛?self.student_id闂佹寧绋戦悧鍡涙煛鐎ｇ煁闁绘嚇瀵灚寰勬繝鍌滀户婵炴垶鎹佸锝夊煘閺嶅亾濞戞瑥閹惧湱妲?        """
        try:
            from datetime import datetime as _dt
            import json as _json
            # 闁诲孩绋掕摫闁靛棗鍊垮畷婊冮崨鐝濋梺鍛婄墬閻楁寮搁崘瀚夌紒杈箞瀹曠節濮樺綉 Markdown/LaTeX/闂佺粯闁伙絺鏅濈划鏁冮埀閸鏅悘鐐跺亹缁犱粙鎮归崶鍔嶉柣鎿勭節閹洨锝傛櫇閻熸偣娴ｇ懓鍔繛鎴炴尨閸嬫捇鏌?
            
            try:
                from core.utils import textUtils as _txu
                _q = _txu.sanitize_for_device(question or "")
                _r = _txu.sanitize_for_device(reply or "")
            except Exception:
                _q = question or ""
                _r = reply or ""
            now = _dt.now()
            date_str = now.strftime("%Y%m%d")
            out_dir = os.path.join(self._data_root, "conversations", date_str)
            os.makedirs(out_dir, exist_ok=True)
            cid = (self.session_id or _dt.now().strftime("%H%M%S"))
            line = {
                "timestamp": now.isoformat(timespec="seconds"),
                "source": source or "realtime",
                "student_id": (self.student_id or ""),
                "question": _q,
                "reply": _r,
                "files": [f for f in (files or []) if f],
            }
            with open(os.path.join(out_dir, f"{cid}.jsonl"), "a", encoding="utf-8") as f:
                f.write(_json.dumps(line, ensure_ascii=False) + "\n")
        except Exception as _e:
            try:
                self.logger.bind(tag=TAG).warning(f"婵烇絽娲换鍌炴偤閵婂亾閻敻鎯侀悾灞惧闁哄娉曠粔鍨幆鎵翱閻? {_e}")
            except Exception:
                pass

    def _get_last_user_content(self) -> str:
        try:
            for m in reversed(self.dialogue.dialogue):
                if getattr(m, "role", None) == "user" and getattr(m, "content", None):
                    return m.content
        except Exception:
            pass
        return ""

    async def handle_connection(self, ws):
        try:
            # 闂佸吋鍎抽崲鑼堕崶宓侀柛娲滃畷锝夋偣閸处eaders
            self.headers = dict(ws.request.headers)

            if self.headers.get("device-id", None) is None:
                # 闁诲繐绻戠换鍡涙儊缁?URL 闂佹眹鍔岀氭偂閿涘嫭瀚氶柕蹇曞濡鏌笟闁煎灚鍨块幊鐣￠弶璺偧 device-id
                from urllib.parse import parse_qs, urlparse

                # Get request path from WebSocket
                request_path = ws.request.path
                if not request_path:
                    self.logger.bind(tag=TAG).error("Failed to get request path")
                    return
                parsed_url = urlparse(request_path)
                query_params = parse_qs(parsed_url.query)
                if "device-id" in query_params:
                    self.headers["device-id"] = query_params["device-id"][0]
                    self.headers["client-id"] = query_params["client-id"][0]
                else:
                    await ws.send("缂備焦鏌紞鎾存叏濠垫挾鍒伴柣鏍埣閺佸秶浠禒瀣柍鍦絾闁哄鏅濋崑鐐垫暜閹炬櫖鐎归崘濯撮悹鎭掑妽閺嗗紨est_page.html")
                    await self.close(ws)
                    return
            real_ip = self.headers.get("x-real-ip") or self.headers.get(
                "x-forwarded-for"
            )
            if real_ip:
                self.client_ip = real_ip.split(",")[0].strip()
            else:
                self.client_ip = ws.remote_address[0]
            self.logger.bind(tag=TAG).info(
                f"{self.client_ip} conn - Headers: {self.headers}"
            )

            # 闂佸湱绮崝鏇￠崶宓侀柟濯介妵鎰板即閻愬搫鐭楅柛鎴欏楃粈鍕煠濮瑰洤鍔氶梺瑙勬尦闂侀潻璐熼崝宥堝鎾崇閻庯絼绮撴繛鎴炴尵閻愬姊虹敮濠勮姳?Student-Id闂?
            
            try:
                sid_header = (
                    self.headers.get("Student-Id")
                    or self.headers.get("student-id")
                    or self.headers.get("student_id")
                )
                if sid_header:
                    self.student_id = str(sid_header).strip()
                    self.logger.bind(tag=TAG).info(
                        f"闂佸湱绮崝鏇￠崶绀嗛柡澶婃健瀹?闂佸搫閸庢挳宕靛姊昦der): {self.student_id}"
                    )
                else:
                    self.logger.bind(tag=TAG).info("闂佸搫鐗婇煬鐞eader婵炴垶鎸哥徊娲煟濠婂嫭绶查梺?Student-Id)")
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(
                    f"闁荤喐鐟辩徊楣冩倵缁辩笭ader婵炴垶鎸鹃幐鍗紆dent-Id閻庨潧鎼佹偉? {_e}"
                )

            # 闁诲繐绻戠换鍡涙儊缁?Header 闂?URL 闂佸搫琚崕鎾煕濞嗗繐褰掑汲閻斿摜鐟滈绶氬畷锝夊冀閸欐儳閻楀牆鐏柣妤冮煫鍥劤缁澶婇崗娴庡储濞戞氨妫憸婵堟閻坏ader > Query
            try:
                audio_fmt_header = (
                    self.headers.get("Audio-Format")
                    or self.headers.get("audio-format")
                    or self.headers.get("audio_format")
                )
                fmt_from_header = (
                    str(audio_fmt_header).strip().lower() if audio_fmt_header else None
                )

                # 闁荤喐鐟辩徊楣冩倵娴犲钃熼柕澶堝姂瀹曪綁宕掑娆愰梺鎸庣閻楀棛绱撴担鍝鐞氭瑩鏌＄ｅ缂佽鲸绻冪粋鎺楀閵堝洠鏁闂佸吋鍎抽崲鑼?audio_format闂?                from urllib.parse import parse_qs, urlparse

                parsed_url_all = urlparse(ws.request.path or "")
                query_params_all = parse_qs(parsed_url_all.query)
                fmt_from_query = None
                if "audio_format" in query_params_all:
                    fmt_from_query = (
                        query_params_all.get("audio_format", [None])[0] or ""
                    ).strip().lower()

                final_fmt = fmt_from_header or fmt_from_query
                if final_fmt in ("pcm", "opus"):
                    self.audio_format = final_fmt
                    self.logger.bind(tag=TAG).info(
                        f"闂傚倸婵炲鏌鍥付缂佹唻绱曢幏瀣箚瑜忛弳? {self.audio_format} (闂佸搫閸庤尙鑺? {'Header' if fmt_from_header else 'Query'})"
                    )
                elif final_fmt:
                    self.logger.bind(tag=TAG).warning(
                        f"闂佽　鍋撻悹鍝勬惈閻撳倿鏌￠崼寮梻鍌氭繛濠囨煛瀹洤甯剁紒? {final_fmt}闂佹寧绋戞總鏃傛崲濮樿泛绠板〒姘ｅ亾缂佸? {self.audio_format}"
                    )
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(f"闁荤喐鐟辩徊楣冩倵娴犲闁规湹绮欏浠嬫偂鎼达絿婵犲劶缁墽鎲? {_e}")

            # 闁荤喐鐟辩徊楣冩倵缁插構M缂備焦姊荤喊宥夋煥濞戞瀚扮憸鐗堢叀閺屽懏寰勬繛澶哥矒闂佹寧绋掗悺宀癕-Endian/pcm-endian/pcm_endian闂佹寧绋戦懟鍩濡法鎷?le 闂?be
            try:
                endian_header = (
                    self.headers.get("PCM-Endian")
                    or self.headers.get("pcm-endian")
                    or self.headers.get("pcm_endian")
                )
                if endian_header:
                    endian = str(endian_header).strip().lower()
                    if endian in ("le", "be"):
                        self.pcm_endian = endian
                        self.logger.bind(tag=TAG).info(
                            f"PCM缂備焦姊荤喊宥夋偣娴ｇ懓鍔柣? {self.pcm_endian} (闂佸搫閸庤尙鑺? Header)"
                        )
                    else:
                        self.logger.bind(tag=TAG).warning(
                            f"闂佽　鍋撻悹鍝勬惈閻撳倿鏌￠崼寮CM缂備焦姊荤喊? {endian}闂佹寧绋戞總鏃傛崲濮樿泛绠板〒姘ｅ亾缂佸? {self.pcm_endian}"
                        )
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(f"闁荤喐鐟辩徊楣冩倵缁插構M缂備焦姊荤喊宥呴幆鎵翱閻? {_e}")

            # 闁荤喐鐟辩徊楣冩倵缁插構M缂傚倸鍊归悧婊堟偉濠婂牊鏅悘鐐舵鐠佹煡姊洪柕鍥閺佸秴閸栨摤-Encoding/pcm-encoding/pcm_encoding闂佹寧绋戦懟鍩濡法鎷?s16 闂?u16
            try:
                enc_header = (
                    self.headers.get("PCM-Encoding")
                    or self.headers.get("pcm-encoding")
                    or self.headers.get("pcm_encoding")
                )
                if enc_header:
                    enc = str(enc_header).strip().lower()
                    if enc in ("s16", "u16"):
                        self.pcm_encoding = enc
                        self.logger.bind(tag=TAG).info(
                            f"PCM缂傚倸鍊归悧婊堟偉濠婂懏濯奸柟鍛瘞: {self.pcm_encoding} (闂佸搫閸庤尙鑺? Header)"
                        )
                    else:
                        self.logger.bind(tag=TAG).warning(
                            f"闂佽　鍋撻悹鍝勬惈閻撳倿鏌￠崼寮CM缂傚倸鍊归悧婊堟偉? {enc}闂佹寧绋戞總鏃傛崲濮樿泛绠板〒姘ｅ亾缂佸? {self.pcm_encoding}"
                        )
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(f"闁荤喐鐟辩徊楣冩倵缁插構M缂傚倸鍊归悧婊堟偉濠婂嫬绶為弶鍩? {_e}")

            # 闁荤喐鐟辩徊楣冩倵缁辩R闁荤姴娲犻弸鍛存偡閺囩偞婵炴彃閺佸秶浠挊澶庨梻渚濡甸弮鍫熸櫖婵炲棛娅嘡-Language/asr-language/asr_language闂佹寧绋戦悧鍛閵夌箚?zh/en/yue闂?
            
            try:
                asr_lang_header = (
                    self.headers.get("ASR-Language")
                    or self.headers.get("asr-language")
                    or self.headers.get("asr_language")
                )
                if asr_lang_header:
                    lang = str(asr_lang_header).strip().lower()
                    if all(c.isalpha() or c in ("-", "_") for c in lang):
                        self.asr_language = lang
                        self.logger.bind(tag=TAG).info(
                            f"ASR language: {self.asr_language} (Header)"
                        )
                    else:
                        self.logger.bind(tag=TAG).warning(
                            f"Invalid ASR language: {lang}"
                        )
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(f"闁荤喐鐟辩徊楣冩倵缁辩R闁荤姴娲犻弸鍛幆鎵翱閻? {_e}")

            # 闁哄鏅滅粙鏍偣娴ｉ潧娑儊?            await self.auth.authenticate(self.headers)

            # 闁荤姳闄嶉崐娑儊婢舵劖鐒绘慨妯虹－缁?缂傚倷缍閸涙毎婵犳硾鐎氬箖?            self.websocket = ws
            self.ws_open = True
            self.device_id = self.headers.get("device-id", None)

            # 濠典壕闂佸搫琚崕鎻掗幖浣歌闁挎棁濮梽宥夋煠妞嬪骸QTT闁哄鏅濋崑鐐垫暜?            request_path = ws.request.path
            self.conn_from_mqtt_gateway = request_path.endswith("?from=mqtt_gateway")
            if self.conn_from_mqtt_gateway:
                self.logger.bind(tag=TAG).info("Connection from MQTT gateway")

            # 闂佸憡甯楃换鍌炴煕閺嶅婵＄偛娼畷婵嬪閿斾粙姊婚崒姘辨憼闁?            self.last_activity_time = time.time() * 1000

            # 闂佸憡鑹捐闁诲笒閹冲繐閸屾娑焵瀵濡烽妶鍡楀簥闂?            self.timeout_task = asyncio.create_task(self._check_timeout())
            # 闂佸憡鑹捐Ping婵烇絽娲换鍐幐搴ｉ悹鍥絻闂佹寧绋戦懟宕抽搹閫涚剨闁瑰瓨绮忛崢姊婚崒姘辩礊婢跺瞼纾?NAT闂傚倸鍊界亸娆撴偪閸稑妫樼紒?
            
            try:
                self._ping_keepalive_task = asyncio.create_task(self._ping_keepalive())
            except Exception:
                self._ping_keepalive_task = None
            # 闂佸憡甯楃换鍌炴煕濡嫭鐝柣鏍电悼閹峰鎮崼鐔翠户闁荤姴鎼崰娑氭濠靛鐒奸柛璧嬮梺鍦劦閸撴繃鏅跺鍫濊閹艰揪绲块崣姘舵煛閸愬煟婵硶閹博婵犳碍鍋?            self.mark_active()

            # 闁诲繐绻戠换鍡涙儊閹矂鎮伴妷鐐婇柣鎰摠閺夊綊鏌￠崼姘壕闁哄鏅滈崹濂告偡濞嗗繒鍒掗妸鍑犳繝濠冨姉缁鍕潧褰掓偡濞嗘瑧鐣辩憸鏉垮块弫宥呯暆閸曠礆闂佺绻愮粔鐟伴崱妯肩畽闁绘劖娼欑紞鎴煙闂堟盯骞冨闇夊锝堛閺屾煥?
            
            try:
                asyncio.create_task(self._try_replay_recent_vision_result())
            except Exception:
                pass

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id

            # 闂佸吋鍎抽崲鑼堕崶妲愰幘璇茬闁哄秴璧嬬紓?            self._initialize_private_config()
            # 閻庨潧褰掓煕閹烘挾绠撻梺?            self.executor.submit(self._initialize_components)

            try:
                async for message in self.websocket:
                    await self._route_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.bind(tag=TAG).info("闁诲骸绠嶉崹娲春濞戞氨鍗氶柡灞芥搐闁充氦闁绘劖娼欐径?)

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(f"Connection error: {str(e)}-{stack_trace}")
            return
        finally:
            # 闂佸搫绉村锟闂佺绻戞繛濠?
            
            try:
                self.ws_open = False
            except Exception:
                pass
            try:
                await self._save_and_close(ws)
            except Exception as final_error:
                self.logger.bind(tag=TAG).error(f"闂佸搫鐗冮崑鎾剁磽娴ｅ摜澧涚紒鏂块幃鍫曞幢濡鏌涢幋鐐撮柡? {final_error}")
                # 缂佸墽闂佸憡閸樻牗绻涢崶婵犻潧妫涢幗鐘绘偣娴ｈ绶茬紒璇插瑰鍕綇琚濋梺鎸庣婵傛梻寮崘鍟哄锝囪鐘绘閸屾粎闂?
                
                try:
                    await self.close(ws)
                except Exception as close_error:
                    self.logger.bind(tag=TAG).error(
                        f"閻庡灚鎯堥柛瀹曟骞庨懞绱柡澶嗘櫇閸嬬偟鏁幘绫嶉悹鍝勬惈濮ｅ姊? {close_error}"
                    )

    async def _save_and_close(self, ws):
        """婵烇絽娲换鍌炴偤閵婂闁哄娉曠粻鎾撮悙鑸电【闁告鍥紒缁樼洴楠?""
        try:
            if self.memory:
                # 婵炶揪缍濞夋洟寮妶鍥／閻犳亽鍔夐弻鎱崷缂佽鲸鎸搁柕澶堝楃粻浠嬫倵濞戞瑩鐓?                def save_memory_task():
                    try:
                        # 闂佸憡甯楃粙鎴犵磽閹捐妫樺棰佽兌閻垵閻樼儤纭鹃柟閹磭妲愬鎾寸劶闁歌祴婵炴垶鎸哥花鑲潧鑻鐐叉瀹曟鎳犲畷鎰版煥?                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.memory.save_memory(self.dialogue.dialogue)
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"婵烇絽娲换鍌炴偤閵婂闁哄娉曠粻鎾抽幆鎵翱閻? {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass

                # 闂佸憡鑹捐缂備焦宕樺鏇煝閸忚偐婵犻潧妫涢幗鐘绘偣娴ｈ绶茬紒璇插块弫宥囦沪閼叉喒缂備焦绋戠紒鍓佸枔閳嚀閺堝垂?                threading.Thread(target=save_memory_task, daemon=True).start()
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"婵烇絽娲换鍌炴偤閵婂闁哄娉曠粻鎾抽幆鎵翱閻? {e}")
        finally:
            # 缂備焦鏌规挸妫濆畷妤呭箮閼虹川闁哄鏅濋崑鐐垫暜閹炬櫖閻忕偠鍋愰悷婵堢磼濞戞娆悢鐑樺闁哄娉曠粻鎾抽崶绠撻柣鍔庨埀鎳撻張宕?
            
            try:
                await self.close(ws)
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"婵烇絽娲换鍌炴偤閵婂闁哄娉曠粻鎾绘煕濮橀柛娅诲洦缂佺粯鐩獮鎺楀閵夛絼鏉柣? {close_error}"
                )

    async def _route_message(self, message):
        """濠电偞鍨甸悧濠冨閸涘磯闁?""
        if isinstance(message, str):
            # 闂佽　鍋撻悹鍝勬惈閻撳倹绻涢幋婵堝濞寸厧鎳樺畷锛勫湱濮电粙澶愭倻濡眹浠柣?            self.mark_active()
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            if self.vad is None or self.asr is None:
                return

            # 婵犳硾鐎氬箖婵犲洤绾柕澶堝妼濞堢檿QTT缂傚倸鍟崹鐢稿矗瑜旈幆鍐礋閸欐儳閻楀牆鐏悗?            if self.conn_from_mqtt_gateway and len(message) >= 16:
                handled = await self._process_mqtt_audio_message(message)
                if handled:
                    self.mark_active()
                    return

            # 婵炴垶鎸哥粔鐟般掗崜浣瑰暫濞达絾鎮舵禒鍫閸斿矂鏌ｉ悙鍙夐柛鍔岄埢浠嬪焺閸愮暢婵犲煐閹告娊宕曢幘绫嶉悹浣告贡缁澶愭煟閳轰胶鎽犻悽鐡鍕礋閸婄偤鏌涘鐓庢瀻濠电偞鍨甸悧濠冨?            self.asr_audio_queue.put(message)
            # 闂佸搫娲悺寮绘繝鍥珘闁宠閹兼番鍨洪弳鏌涢幒宥呭祮闁绘捁鍩栭敍鎰板箣濠靛洤闂佸搫鍟悥鐓庨崸妤佹櫖闁稿灪閺嗗繐濠婂啴鍙勬繛绗哄濆鍛村礃閹绘帞浼堥柣搴悢妲?
            
            try:
                self.last_audio_frame_time = time.time() * 1000
            except Exception:
                pass
            self.mark_active()

    async def _process_mqtt_audio_message(self, message):
        """
        婵犳硾鐎氬箖婵犲洤绾柕澶堝妼濞堢檿QTT缂傚倸鍟崹鐢稿矗瑜旈幆鍐礋閸欐儳閻楀牆鐏紒澶屽厴楠炰胶妲愬鍫熷枂闁挎繂妫涢埀?6闁诲孩绋掑绶為柟鎯濡姷鍋犻崺鏍笟瀹曪綁寮介崣鎯悧鍫濈仸闁哄棛鍠栭獮?
        Args:
            message: 闂佸憡鐗曢幊搴箚閸喎绶為柟鎯闂佹眹鍔岀氫即鎮￠懜纰夌矗闁瑰鍋熷暩闂?
        Returns:
            bool: 闂佸搫瀚崕濠囨煙鐎涙濮囧绋掑鍕礋閸婄偛濠婂啯缂佸鍏橀獮?        """
        try:
            # 闂佸湱绮崝鏇￠崶绶為柟鎯婵烇絽娲犻崜婵囧?            timestamp = int.from_bytes(message[8:12], "big")
            audio_length = int.from_bytes(message[12:16], "big")

            # 闂佸湱绮崝鏇￠崶闁规湹绮欏鎮崼婵?            if audio_length > 0 and len(message) >= 16 + audio_length:
                # 闂佸搫鐗嗛悗鍨皑閳畝鎼佸汲鏉堝劅闁挎棁鍋愮粈澶愭煙缂佹濮囩憸鏉挎川閸掓帡宕滆閳幆鍐礋閸欐儳閻楀牆鐏柡鍡欏枛楠?                audio_data = message[16 : 16 + audio_length]
                # 闂佺硶鏅炲鑺卞宕奸弴鐕傜吹闂佽娼欓悿鍥崲濡吋鍋橀悘鐐村劤缁楁捇骞栭弶鎴犵闂?                self._process_websocket_audio(audio_data, timestamp)
                return True
            elif len(message) > 16:
                # 濠电偛澶囬崜婵嗘笟楠炴劙宕惰閺嗕即姊婚埀宕归梺鐟扮摠閻楃娀寮虫潏鍎熼柨鏃囧閿熸煛娴ｅ摜澧崇紒杈箞瀹曠磼濡櫣婵犲煐閹告娊宕曢幘瑙幖杈剧節閹爼宕卞閳锋牕閿濆棛鎳勯柡鍡欏枛楠?                audio_data = message[16:]
                self.asr_audio_queue.put(audio_data)
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"闁荤喐鐟辩徊楣冩倵缁插穲bSocket闂傚倸婵炲鏌涢弽鍣归柕鍥灩閹? {e}")

        # 婵犳硾鐎氬箖婵犲啫绶為弶鍩挎洟鏌妯肩劮缂佺粯鍨垮畷璺洪悶se闁荤偞绋忛崝搴濮樿埖闁冲暫濞达絿鍎崺娑氱磽娓氶幃?        return False

    def _process_websocket_audio(self, audio_data, timestamp):
        """婵犳硾鐎氬箖婵俠Socket闂佸搫绉堕崢妲愰敓鐘冲剭闁告洖寰撴俊澧楅崹鐢?""
        # 闂佸憡甯楃换鍌炴煕閺嶅婵＄偛鍊垮鑽稒閻撳牓骞栭弶鎴犵闁镐笉闁挎稑瀚崐?        if not hasattr(self, "audio_timestamp_buffer"):
            self.audio_timestamp_buffer = {}
            self.last_processed_timestamp = 0
            self.max_timestamp_buffer_size = 20

        # 婵犵鍐插綊鎮樻径鎰睄闁告礃閿涚喖鏌熺壕瀣彧婵弶鎮傞弻鍛村箳閹村剭闁告洖澧庣粈澶愭煟閳轰胶鎽犻悽鐡鍕礋閸?        if timestamp >= self.last_processed_timestamp:
            self.asr_audio_queue.put(audio_data)
            self.last_processed_timestamp = timestamp

            # 婵犳硾鐎氬箖婵犲嫮纾介柟鎯暱閺嗛亶鏌涢弽銆冮柤鍨灴閹啴宕熼崐鐢电磽娴ｅ摜妯?            processed_any = True
            while processed_any:
                processed_any = False
                for ts in sorted(self.audio_timestamp_buffer.keys()):
                    if ts > self.last_processed_timestamp:
                        buffered_audio = self.audio_timestamp_buffer.pop(ts)
                        self.asr_audio_queue.put(buffered_audio)
                        self.last_processed_timestamp = ts
                        processed_any = True
                        break
        else:
            # 婵炴垶鏌畷鑺卞畷鐘诲椽閸愰梺鍝勬閸婃悂鎮?            if len(self.audio_timestamp_buffer) < self.max_timestamp_buffer_size:
                self.audio_timestamp_buffer[timestamp] = audio_data
            else:
                self.asr_audio_queue.put(audio_data)

    async def handle_restart(self, message):
        """婵犳硾鐎氬箖婵犲洤瀚夌规噹闂侀潻绲婚崝鎴闯閹间礁瑙?""
        try:

            self.logger.bind(tag=TAG).info("闂佽　鍋撻悹鍝勬惈閻撳倿鏌￠崼婵堝鍠栧畷鎶藉閳轰焦闂佸憡鑹鹃惁鐟伴悩妲愬瀣闁搁獮宥?..")

            # 闂佸憡鐟崹鍧楀焵閼冲爼鍨惧鍏煎闁靛牆鎳忛幆娆撳箹?            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "success",
                        "message": "闂佸搫鐗嗙粔瀛樻叏閻旂厧闂柕濞炬櫅濞呮煕濮樺啿骞...",
                        "content": {"action": "restart"},
                    }
                )
            )

            # 閻庨潧褰掓煙缁楁稑妫濋弻灞介崨鍓婚梺鐟扮仢缁夊磭绱?            def restart_server():
                """闁诲骸婀遍崑楠炲秷闂備焦褰冪粔鎾箚鎼村剭闁告洜鍘靛?""
                time.sleep(1)
                self.logger.bind(tag=TAG).info("闂佸湱鐟抽崱娑樺珘鐎规噹闂侀潻绲婚崝鎴闯閹间礁瑙?..")
                subprocess.Popen(
                    [sys.executable, "app.py"],
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    start_new_session=True,
                )
                os._exit(0)

            # 婵炶揪缍濞夋洟寮妶鍥／閻犳亽鍔夐弻鏌熺粭娑樻閺屽苯閸涘壔闂備胶浠柛妯稿濆鑲嫚閸欏閻庯絺鏅滈悗鍨緲缁?            threading.Thread(target=restart_server, daemon=True).start()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"闂備焦褰冪粔鎾箚鎼寸窞閺夊熆? {str(e)}")
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "error",
                        "message": f"Restart failed: {str(e)}",
                        "content": {"action": "restart"},
                    }
                )
            )

    def _initialize_components(self):
        try:
            self.selected_module_str = build_module_string(
                self.config.get("selected_module", {})
            )
            self.logger = create_connection_logger(self.selected_module_str)

            """闂佸憡甯楃换鍌炴煕閺嶅缂佺缁?""
            if self.config.get("prompt") is not None:
                user_prompt = self.config["prompt"]
                # 婵炶揪缍濞夋洟寮妶鍫杸闁虫瀾鐟滈鑳剁划鍫熺捄闁哄鏅滅粙鏍煕閹烘挾绠撻梺?                prompt = self.prompt_manager.get_quick_prompt(user_prompt)
                self.change_system_prompt(prompt)
                self.logger.bind(tag=TAG).info(
                    f"闂婃礌閸嬫捇鎮畡鎵淮婵犵數浣冨皺缁辨帡宕? prompt闂佺懓鐡崝鏇熸叏?{prompt[:50]}..."
                )

            """闂佸憡甯楃换鍌炴煕閺嶅婵犳导鏉戞嵍闁圭數鐓佹繛瀵稿缂佽鲸鐟畷鎴閵夌闂佸憡鐗楅悧妲愭导瀛樺殣闁靛鍎卞鍧楁倶閻愪壕闁诲骸婀遍崑妯兼閵夌＝闁告繂瀚禍濂告煕閹烘挾鎳勯悗鍨矒濡線鍩瀹曪繝鎼归梺鍛婂笚缁嬫垹绱撻幘缁樻櫖?""
            # VAD闂佹寧绋掗惌妲愬畷妤呭醇濠靛鍋柕濞垮劚瀵潡鎮橀悙浜鹃柣搴贡閸嬫娆妷鏅归埀鏉堢窞闁告鍋涢悘鐔兼煙缁嬪灝銆掗崼鏇炵婵犻潧妫濆畷?            if self.vad is None:
                if self._vad is not None:
                    self.vad = self._vad
                else:
                    try:
                        modules = initialize_modules(
                            self.logger,
                            self.config,
                            init_vad=True,
                            init_asr=False,
                            init_llm=False,
                            init_tts=False,
                            init_memory=False,
                            init_intent=False,
                        )
                        self.vad = modules.get("vad", None)
                        if self.vad is not None:
                            self.logger.bind(tag=TAG).info("闂佸湱婵炴挸鐖煎畷姘崱娑樼闁哄湒闂佺懓鐡崝鏇熸叏?)
                        else:
                            self.logger.bind(tag=TAG).warning("闂佸湱婵炴挸鐖煎畷姘崱娑樼闁哄湒婵犲劶缁墽鎲撮敃鍌涙櫖鐎归埀骞嬫搴ｇ＜婵＄嵆D濠靛亾瀹曞洨")
                    except Exception as _e:
                        self.logger.bind(tag=TAG).error(f"闂佸湱婵炴挸鐖煎畷姘崱娑樼闁哄湒閻庨潧鎼佹偉? {_e}")

            # ASR闂佹寧绋掗惌妲愬畷妤呭醇濠靛鍋柕濞垮劚瀵潡鎮橀悙浜鹃梺鍝勭墛閸曢箖鎮楅崷浠掔紒韬插劦閺佸秴濠婂啴鏌涜箛瀣闁荤＝闁告繂瀚禍濂告煙鐎涙澧悹鎰枑濞艰?婵炴垶鎸哥粔纾嬮弻鍋紒杈箞瀹曟艾韫囨挾闂佸搫鍟冲娑垂閸弿閻?            if self.asr is None:
                try:
                    if (
                        self._asr is not None
                        and getattr(self._asr, "interface_type", None) == InterfaceType.LOCAL
                    ):
                        self.asr = self._asr
                    else:
                        self.asr = self._initialize_asr()
                except Exception as _e:
                    self.logger.bind(tag=TAG).error(f"闂佸湱婵炴挸鐖煎畷姘崱娑樼闁哄牆灏燫閻庨潧鎼佹偉? {_e}")

            # 闂佸憡甯楃换鍌炴煕閺嶅闁挎稒鍔楅惀娑甸崨闂?            self._initialize_voiceprint()

            # 闂佺懓鐏氶幐鍝閹寸姵瀚氶柣鎾冲閹风娀宕卞閻掑姊哄畝鍛婄?            if self.asr is not None:
                asyncio.run_coroutine_threadsafe(
                    self.asr.open_audio_channels(self), self.loop
                )
            if self.tts is None:
                self.tts = self._initialize_tts()
            # 闂佺懓鐏氶幐鍝閹寸姵瀚氶柣鎾崇埣瀹曞醇閻旈浜ｉ梻浣稿摵濞?            asyncio.run_coroutine_threadsafe(
                self.tts.open_audio_channels(self), self.loop
            )

            # 闂備焦褰冪粔鐑芥煥濞戞瑨澹樻繝閻氬尡S闂備礁鍝哄婊冨娴滃憡娼忛埡浣哥？闂佸憡鑹鹃崙鐣屾濠靛牊鍠嗛柨鏇楀亾鐟滄澘鍊圭粙澶愬焵閳诲酣鍩埀鍩缁秴銆掗懜鍨氦闁硅揪绲块幉瀛樺緞瀹濞夋煛鐎ｉ柍绠樻繛鍫熷灴閹矂鎮伴妷鐐婇柣鎰摠閺?            # 婵炴垶鏌濞瀹曠兘濡搁敃缂嶆垿鏌熼棃娑箖濡啰鍗氶悗锝囬柣鐔哥懕缁犳垼閸岀偞鏅悘鐐舵鐠佹煡鏌圭姵婵炲弶缈籘S闁诲繐绻戠喊宥呭畷姘崱娑樼闁哄诞鍥殜闁哄鍨剁粈闂佽　鍋撻柟浣锋澀闁?
            
            try:
                asyncio.run_coroutine_threadsafe(
                    self._try_replay_recent_vision_result(), self.loop
                )
            except Exception as _e:
                self.logger.bind(tag=TAG).warning(
                    f"TTS闂佸憡甯楃换鍌炴煕閺嶅闁归幉鎾晝閳崒婊勫枂闁稿哺瀹曞爼鎮欑涙婢掓繝鍎肩划鍓喆? {_e}"
                )

            """闂佸憡姊绘慨鎯崶濯奸柡澶庢硶缁?""
            self._initialize_memory()
            """闂佸憡姊绘慨鎯崶绠涢煫鍥尰缁傚牓鎮归崶闁?""
            self._initialize_intent()
            """闂佸憡甯楃换鍌炴煕閺嶅缂佹鍊块獮搴瑜嶅鐘电磼?""
            self._init_report_threads()
            """闂佸搫娲悺寮绘繝鍕闁煎鍊楅崺鐘绘煙缂佹濮夐柕鍥皑閹?""
            self._init_prompt_enhancement()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"闁诲骸婀遍崑妯兼閵夌闁哄秶鐓佹繛瀵稿濞夋盯濡甸幋鐘冲? {e}")

    def _init_prompt_enhancement(self):
        # 闂佸搫娲悺寮绘繝鍐鐘辫兌閻熸捇鏌￠崒姘煑濞ｅ洤楠?        self.prompt_manager.update_context_info(self, self.client_ip)
        enhanced_prompt = self.prompt_manager.build_enhanced_prompt(
            self.config["prompt"], self.device_id, self.client_ip
        )
        if enhanced_prompt:
            self.change_system_prompt(enhanced_prompt)
            self.logger.bind(tag=TAG).info("缂備礁鍚圭紒妞介獮鎾诲箛娴犳盯鎮归崶闁告垟鍓濋弲鍫曟倷閹绘帞绠掗梺鍝勬搐閻蓟?)

    def _init_report_threads(self):
        """闂佸憡甯楃换鍌炴煕閺嶉檮SR闂佸憡绮孴S婵炴垶鎸搁敃鎱妶鍥／閻犳亽鍔夐弻?""
        if not self.read_config_from_api or self.need_bind:
            return
        if self.chat_history_conf == 0:
            return
        if self.report_thread is None or not self.report_thread.is_alive():
            self.report_thread = threading.Thread(
                target=self._report_worker, daemon=True
            )
            self.report_thread.start()
            self.logger.bind(tag=TAG).info("TTS婵炴垶鎸搁敃鎱妶鍥／閻犳亽鍔夐弻鐟版啞瑜板啴骞嗘惔绀?)

    def _initialize_tts(self):
        """闂佸憡甯楃换鍌炴煕閺嶅姛TS"""
        tts = None
        if not self.need_bind:
            tts = initialize_tts(self.config)

        if tts is None:
            tts = DefaultTTS(self.config, delete_audio_file=True)

        return tts

    def _initialize_asr(self):
        """闂佸憡甯楃换鍌炴煕閺嶉檮SR闂佹寧绋戦悧鍡涘触鐎ｅ亾绾懎閿涙劙宕熼弸渚玈R闂佹眹鍔岀氬磿韫囨稑绀冪痪鏉跨粈?""
        try:
            if self._asr is not None and getattr(self._asr, "interface_type", None) == InterfaceType.LOCAL:
                # 婵犵鍐插綊鎮樻径鎰闁告R闂佸搫瀚幏閬嶆煕閿旀儳婵犻崶绀夐柍钘夋噽缁澶愭煕閹烘挾鎳呮繛鎻掓健楠炴帡濡烽妷鍋?                return self._asr
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"婵緲鐎氭偪閸淩濠典壕闂佸搫琚崕閬嶅閹寸姵瀚婚柕澶岄梺鎼炲劤閸嬪焵閸嬫捇鏌涢弬璇插闁抽柛鐏氶幈? {e}")

        # 闁哄鏅滅划搴煛閸繄濠靛枛楠炲寮介妸绱梺鍦帛閸旀帞娆崹绱ｉ柛鏇熺瑼SR闂佹寧绋掔喊宥囧灚绮撻弻濠傞崶鐎梺鍛婃煟閸斿秹鍩缁渚宕归崹鍙忛悗锝夋煛閸屾稒绶查柣瀚粭?        return initialize_asr(self.config)

    def _initialize_voiceprint(self):
        """婵炴垶鎸搁幖绱炵ｇ鐎圭墢缁犻箖鏌熼幁鎺戝姎闁哥仛閹憋絽鐟欏嫬婵閹风娀宕卞閻?""
        try:
            voiceprint_config = self.config.get("voiceprint", {})
            if voiceprint_config:
                voiceprint_provider = VoiceprintProvider(voiceprint_config)
                if voiceprint_provider is not None and voiceprint_provider.enabled:
                    self.voiceprint_provider = voiceprint_provider
                    self.logger.bind(tag=TAG).info("婵犳竟鍡楀鍐珰闁搁悞濂告煕閺冨倸鏋欓柛蹇旈柟缁樺笚闊级閳哄啫浠悽鎸冲鎹勯崫鍕戞鏌熺粈渚骞嗘惔鍋?)
                else:
                    self.logger.bind(tag=TAG).warning("婵犳竟鍡楀鍐珰闁搁悞濂告煕閺冨倸鏋欓柛蹇斿畷寮妶鍡樺闁哥鐢磭绱撻崘鎲归柣搴ｆ嚀閺堝汲?)
            else:
                self.logger.bind(tag=TAG).info("婵犳竟鍡楀鍐珰闁搁悞濂告煕閺冨倸鏋欓柛蹇斿鐢稿箚鎼村仺?)
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"婵犳竟鍡楀鍐珰闁搁悞濂告煕閹烘挾绠撻梺鍛婄墬閻楁洟濡甸幋鐘冲? {str(e)}")

    def _initialize_private_config(self):
        """婵犵鍐插綊鎮樻径鎰強缂佸閺屽閸梺鍝勫稿锝呴姀鍤旂瑰嫭婢樼徊鍧楁煥濞戞瀚伴柛浜繛鎴炵矋缁傚秶浠崜鍋撻崷浠掔紒韬插劦瀹?""
        if not self.read_config_from_api:
            return
        """婵炲濮寸涙暜閹剧煑闁挎繂鐗嗙粻鏌涘鎰婵￠柛灞捐壘闂佹眹鍔岀氫即宕妶鍥＞缂佺粯閹壆浠懖妾跺鐐叉閳－閺夎棄銆掑鍨叀閺佸秴鐣濋崟闂佺绻堥崝鎴闯濞茬厒鐎规閻撻柣搴贡閸嬫娆妷绀?""
        try:
            begin_time = time.time()
            private_config = get_private_config_from_api(
                self.config,
                self.headers.get("device-id"),
                self.headers.get("client-id", self.headers.get("device-id")),
            )
            private_config["delete_audio"] = bool(self.config.get("delete_audio", True))
            self.logger.bind(tag=TAG).info(
                f"{time.time() - begin_time} 缂備礁鐢濠靛鍤旂瑰嫭婢樼徊璺懓鎽滅壕浠嬫煕閺嶅闁告鍊楃槐鏃堝垂濮樿泛绀? {json.dumps(filter_sensitive_info(private_config), ensure_ascii=False)}"
            )
        except DeviceNotFoundException as e:
            self.need_bind = True
            private_config = {}
        except DeviceBindException as e:
            self.need_bind = True
            self.bind_code = e.bind_code
            private_config = {}
        except Exception as e:
            self.need_bind = True
            self.logger.bind(tag=TAG).error(f"闂佸吋鍎抽崲鑼堕崶妲愰幘璇茬闁哄秴璧嬬紓鍌氬暔娴滃鎮? {e}")
            private_config = {}

        init_llm, init_tts, init_memory, init_intent = (
            False,
            False,
            False,
            False,
        )

        init_vad = check_vad_update(self.common_config, private_config)
        init_asr = check_asr_update(self.common_config, private_config)

        if init_vad:
            self.config["VAD"] = private_config["VAD"]
            self.config["selected_module"]["VAD"] = private_config["selected_module"][
                "VAD"
            ]
        if init_asr:
            self.config["ASR"] = private_config["ASR"]
            self.config["selected_module"]["ASR"] = private_config["selected_module"][
                "ASR"
            ]
        if private_config.get("TTS", None) is not None:
            init_tts = True
            self.config["TTS"] = private_config["TTS"]
            self.config["selected_module"]["TTS"] = private_config["selected_module"][
                "TTS"
            ]
        if private_config.get("LLM", None) is not None:
            init_llm = True
            self.config["LLM"] = private_config["LLM"]
            self.config["selected_module"]["LLM"] = private_config["selected_module"][
                "LLM"
            ]
        if private_config.get("VLLM", None) is not None:
            self.config["VLLM"] = private_config["VLLM"]
            self.config["selected_module"]["VLLM"] = private_config["selected_module"][
                "VLLM"
            ]
        if private_config.get("Memory", None) is not None:
            init_memory = True
            self.config["Memory"] = private_config["Memory"]
            self.config["selected_module"]["Memory"] = private_config[
                "selected_module"
            ]["Memory"]
        if private_config.get("Intent", None) is not None:
            init_intent = True
            self.config["Intent"] = private_config["Intent"]
            model_intent = private_config.get("selected_module", {}).get("Intent", {})
            self.config["selected_module"]["Intent"] = model_intent
            # 闂佸憡姊绘慨鎯崶绠甸柟鍝勭闂備焦婢樼粔鍫曟偪?            if model_intent != "Intent_nointent":
                plugin_from_server = private_config.get("plugins", {})
                for plugin, config_str in plugin_from_server.items():
                    plugin_from_server[plugin] = json.loads(config_str)
                self.config["plugins"] = plugin_from_server
                self.config["Intent"][self.config["selected_module"]["Intent"]][
                    "functions"
                ] = plugin_from_server.keys()
        if private_config.get("prompt", None) is not None:
            self.config["prompt"] = private_config["prompt"]
        # 闂佸吋鍎抽崲鑼堕崶鐝堕柟鐢垫綎婵烇絽娲犻崜婵囧?        if private_config.get("voiceprint", None) is not None:
            self.config["voiceprint"] = private_config["voiceprint"]
        if private_config.get("summaryMemory", None) is not None:
            self.config["summaryMemory"] = private_config["summaryMemory"]
        if private_config.get("device_max_output_size", None) is not None:
            self.max_output_size = int(private_config["device_max_output_size"])
        if private_config.get("chat_history_conf", None) is not None:
            self.chat_history_conf = int(private_config["chat_history_conf"])
        if private_config.get("mcp_endpoint", None) is not None:
            self.config["mcp_endpoint"] = private_config["mcp_endpoint"]
        try:
            modules = initialize_modules(
                self.logger,
                private_config,
                init_vad,
                init_asr,
                init_llm,
                init_tts,
                init_memory,
                init_intent,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"闂佸憡甯楃换鍌炴煕閺嶅缂佺缁傛帞鎹勯幁鎺嶆澀闁? {e}")
            modules = {}
        if modules.get("tts", None) is not None:
            self.tts = modules["tts"]
        if modules.get("vad", None) is not None:
            self.vad = modules["vad"]
        if modules.get("asr", None) is not None:
            self.asr = modules["asr"]
        if modules.get("llm", None) is not None:
            self.llm = modules["llm"]
        if modules.get("intent", None) is not None:
            self.intent = modules["intent"]
        if modules.get("memory", None) is not None:
            self.memory = modules["memory"]

    def _initialize_memory(self):
        if self.memory is None:
            return
        """闂佸憡甯楃换鍌炴煕閺嶅闂婃搐濡瑨鍟梺?""
        self.memory.init_memory(
            role_id=self.device_id,
            llm=self.llm,
            summary_memory=self.config.get("summaryMemory", None),
            save_to_file=not self.read_config_from_api,
        )

        # 闂佸吋鍎抽崲鑼堕崶濯奸柡澶庢硶缁犳捇鏌熷畷鐢靛垝閵婄厐鐎规川閺?        memory_config = self.config["Memory"]
        memory_type = self.config["Memory"][self.config["selected_module"]["Memory"]][
            "type"
        ]
        # 婵犵鍐插綊鎮樻径瀣閻犳亽鍔嶉弳?nomen闂佹寧绋戦惉鐓庨崸妤绠抽柕澶堝妿缁犳煡鏌?        if memory_type == "nomem":
            return
        # 婵炶揪缍濞夋洟寮?mem_local_short 濠靛亾瀹曞洨
        elif memory_type == "mem_local_short":
            memory_llm_name = memory_config[self.config["selected_module"]["Memory"]][
                "llm"
            ]
            if memory_llm_name and memory_llm_name in self.config["LLM"]:
                # 婵犵鍐插綊鎮樻径鎰厐鐎规川閺嬪倸濠婂啯缂佹鎹囬幃浠嬪焼濮楃嫻闂佹寧绋戦懟宕瑰畷姘鑲闂佺粯鐟宀勬煟閵婃LM闁诲骸婀遍崑妯兼?                from core.utils import llm as llm_utils

                memory_llm_config = self.config["LLM"][memory_llm_name]
                memory_llm_type = memory_llm_config.get("type", memory_llm_name)
                memory_llm = llm_utils.create_instance(
                    memory_llm_type, memory_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"婵炴垶鎹囩紓姘剁叓閸柍鍚圭紒鍔戝畷姘鑲婵炲瓨绮屽鏃傜箔閹剧粯鍋柍M: {memory_llm_name}, 缂備線鎮? {memory_llm_type}"
                )
                self.memory.set_llm(memory_llm)
            else:
                # 闂佸憡鐔粻鎴垂閹峰懐鎹勯妸娈繛鎴炴尵閻湢M
                self.memory.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("婵炶揪缍濞夋洟寮妶鍡欑紒婵炶揪绲剧划鍫嫻閻旂厧绠涢煫鍥尰缁傚牓鎮归崶闁告铻ｉ柍纾埀?)

    def _initialize_intent(self):
        if self.intent is None:
            return
        self.intent_type = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ]["type"]
        if self.intent_type == "function_call" or self.intent_type == "intent_llm":
            self.load_function_plugin = True
        """闂佸憡甯楃换鍌炴煕閺嶅闁告挷鍗冲畷鍫曞箲閹伴梺鍛婂储娓氬畷?""
        # 闂佸吋鍎抽崲鑼堕崶绠涢煫鍥尰缁傚牓鎮归崶闁告閺屽閸?        intent_config = self.config["Intent"]
        intent_type = self.config["Intent"][self.config["selected_module"]["Intent"]][
            "type"
        ]

        # 婵犵鍐插綊鎮樻径瀣閻犳亽鍔嶉弳?nointent闂佹寧绋戦惉鐓庨崸妤绠抽柕澶堝妿缁犳煡鏌?        if intent_type == "nointent":
            return
        # 婵炶揪缍濞夋洟寮?intent_llm 濠靛亾瀹曞洨
        elif intent_type == "intent_llm":
            intent_llm_name = intent_config[self.config["selected_module"]["Intent"]][
                "llm"
            ]

            if intent_llm_name and intent_llm_name in self.config["LLM"]:
                # 婵犵鍐插綊鎮樻径鎰厐鐎规川閺嬪倸濠婂啯缂佹鎹囬幃浠嬪焼濮楃嫻闂佹寧绋戦懟宕瑰畷姘鑲闂佺粯鐟宀勬煟閵婃LM闁诲骸婀遍崑妯兼?                from core.utils import llm as llm_utils

                intent_llm_config = self.config["LLM"][intent_llm_name]
                intent_llm_type = intent_llm_config.get("type", intent_llm_name)
                intent_llm = llm_utils.create_instance(
                    intent_llm_type, intent_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"婵炴垶鎸鹃崕宕滄导鏉戠倞闁硅鍔楀鏇煕閹烘垹浠悗鐐瑰涘鑺遍埄鍐柟鎹愬煐閺嗗粯LM: {intent_llm_name}, 缂備線鎮? {intent_llm_type}"
                )
                self.intent.set_llm(intent_llm)
            else:
                # 闂佸憡鐔粻鎴垂閹峰懐鎹勯妸娈繛鎴炴尵閻湢M
                self.intent.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("婵炶揪缍濞夋洟寮妶鍡欑紒婵炶揪绲剧划鍫嫻閻旂厧绠涢煫鍥尰缁傚牓鎮归崶闁告铻ｉ柍纾埀?)

        """闂佸憡姊绘慨鎯崶纾奸柣鏂垮閻庤鎮堕崕閬嶅矗閹稿骸绶為柛鏇炵偤鏌?""
        self.func_handler = UnifiedToolHandler(self)

        # 閻庨潧褰掓煕閹烘挾绠撻梺鍛婄墬閻楁洘瀵奸幇鏉跨鐎瑰嫪鍗抽幃鍫曞幢濡胶褰?        if hasattr(self, "loop") and self.loop:
            asyncio.run_coroutine_threadsafe(self.func_handler._initialize(), self.loop)

    def change_system_prompt(self, prompt):
        self.prompt = prompt
        # 闂佸搫娲悺寮绘繝鍕闁煎鍊楅崺鐖宺ompt闂佺厧鍢查崢鏍箔閸屾稓閻庯絿?        self.dialogue.update_system_message(self.prompt)

    def chat(self, query, depth=0):
        self.logger.bind(tag=TAG).info(f"婵犵垻閸曟笟瀹曞湱锝嗘瘑闂佸憡甯楁竟鍡涘极閵堝绠ｉ梺鍨暩闂? {query}")
        self.llm_finish_task = False

        # 婵炴垶鎸鹃崕銆掗懜鐐逛簻閻犻缚娅ｅ鎾煛閸愮厫闁哄苯閺夌偞澹嗙粣妤呮偣閸床D闂佸憡绮岄懟閸岀偞鐒诲鎾粹淩ST闁荤姴娲弨閬嶆儑?        if depth == 0:
            self.sentence_id = str(uuid.uuid4().hex)
            self.dialogue.put(Message(role="user", content=query))
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=self.sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )
            # 婵炴垶鎸哥憸棰佸IRST闂佸憡閻洤閹捐泛鍔嬫俊鐐舵硶閹?            self.mark_active()

        # Define intent functions
        functions = None
        if self.intent_type == "function_call" and hasattr(self, "func_handler"):
            functions = self.func_handler.get_functions()
        response_message = []

        try:
            # 婵炶揪缍濞夋洟寮妶鍥殰闁挎洑娴囩粻娑幢濞嗘劗鏆犻柣搴ｆ暩闁?            memory_str = None
            if self.memory is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self.memory.query_memory(query), self.loop
                )
                memory_str = future.result()

            if self.intent_type == "function_call" and functions is not None:
                # 婵炶揪缍濞夋洟寮妶澶婄哗閻庡灚鏀nctions闂佹眹鍔屾晶鏅卹eaming闂佽浜介崕杈?                llm_responses = self.llm.response_with_functions(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                    functions=functions,
                )
            else:
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 婵犳硾鐎氬箖婵犲洤绀勬繛鍙夋珦 {query}: {e}")
            return None

        # 婵犳硾鐎氬箖婵犲伅瑙勬媴閸濋梺鍛婄箓缁夊鑺?        tool_call_flag = False
        function_name = None
        function_id = None
        function_arguments = ""
        content_arguments = ""
        self.client_abort = False
        emotion_flag = True
        for response in llm_responses:
            if self.client_abort:
                break
            if self.intent_type == "function_call" and functions is not None:
                content, tools_call = response
                if "content" in response:
                    content = response["content"]
                    tools_call = None
                if content is not None and len(content) > 0:
                    content_arguments += content

                if not tool_call_flag and content_arguments.startswith("<tool_call>"):
                    # print("content_arguments", content_arguments)
                    tool_call_flag = True

                if tools_call is not None and len(tools_call) > 0:
                    tool_call_flag = True
                    if tools_call[0].id is not None:
                        function_id = tools_call[0].id
                    if tools_call[0].function.name is not None:
                        function_name = tools_call[0].function.name
                    if tools_call[0].function.arguments is not None:
                        function_arguments += tools_call[0].function.arguments
            else:
                content = response

            # 闂侀潻鑵归弳鏀峬闂佹悶鍎抽崑娑橀幘宕囬梺鍛婄懄閻楁宕曡箛鏇犵＜闁靛棗鍟撮獮鍡涘椽閸愭繛鎴炴尨閸嬫捇寮堕悙鍨珰婵犻潧妫楀鏌涢敂鍝勫缂佽鲸鍨跺鍕鐎ｉ梺鍛婄懄閻楁梻绮弶鎴旀瀻?            if emotion_flag and content is not None and content.strip():
                asyncio.run_coroutine_threadsafe(
                    textUtils.get_emotion(self, content),
                    self.loop,
                )
                emotion_flag = False

            if content is not None and len(content) > 0:
                if not tool_call_flag:
                    # 闂佸憡鐟崹鍧楀焵缁渚宕哄畝閹峰骞嗚瀹曟粌閸瑦绻涢崣澶愬几閸愬珘缂佽鲸绻堥弻鍡涘垂鐢娊鏌涢幋锝嗘?###/####/**/闁?缂備焦绋戦梺?
                    
                    try:
                        from core.utils import textUtils as _txu
                        _clean = _txu.sanitize_for_device(content)
                    except Exception:
                        _clean = content
                    response_message.append(_clean)
                    self.tts.tts_text_queue.put(
                        TTSMessageDTO(
                            sentence_id=self.sentence_id,
                            sentence_type=SentenceType.MIDDLE,
                            content_type=ContentType.TEXT,
                            content_detail=_clean,
                        )
                    )
                    # 濠电到缁绘垵閹惧疇閸岀偛绀嗛梺鍨悡濠电偛寮跺鎺旂矚?                    self.mark_active()
        # 婵犳硾鐎氬箖婵傜本nction call
        if tool_call_flag:
            bHasError = False
            if function_id is None:
                a = extract_json_from_string(content_arguments)
                if a is not None:
                    try:
                        content_arguments_json = json.loads(a)
                        function_name = content_arguments_json["name"]
                        function_arguments = json.dumps(
                            content_arguments_json["arguments"], ensure_ascii=False
                        )
                        function_id = str(uuid.uuid4().hex)
                    except Exception as e:
                        bHasError = True
                        response_message.append(a)
                else:
                    bHasError = True
                    response_message.append(content_arguments)
                if bHasError:
                    self.logger.bind(tag=TAG).error(
                        f"function call error: {content_arguments}"
                    )
            if not bHasError:
                # 婵犵鍐插灝銆掗崜浣瑰暫濞达絾鎮舵禍锝嗕繆閳－閳厴瀹曟宕煎瀣仩闁告礈闁哄鍋熺粈澶嬬箾閿濆牊鎱悙鐑樺剮缂佸鐏濊鐘茬捄鍝勯柟瀹曟償閿濆棛鏆犻梺鍝勫暔閸庤京鎹弮鍫濈畾闁告稒鐎?                if len(response_message) > 0:
                    text_buff = "".join(response_message)
                    self.tts_MessageText = text_buff
                    self.dialogue.put(Message(role="assistant", content=text_buff))
                response_message.clear()
                self.logger.bind(tag=TAG).debug(
                    f"function_name={function_name}, function_id={function_id}, function_arguments={function_arguments}"
                )
                function_call_data = {
                    "name": function_name,
                    "id": function_id,
                    "arguments": function_arguments,
                }

                # 婵炶揪缍濞夋洟寮妶鍥＜闁绘柨澧庨悗瑙勬偠閸庨亶宕ｉ幐搴＄窞闁告洖鐐烘煕閿濆啫濡奸梺鑽仜濡瑦鏅跺澶婂珘濠泛缁憋綁鏌涜箛鏇熺効闁诲枛閹?                result = asyncio.run_coroutine_threadsafe(
                    self.func_handler.handle_llm_function_call(
                        self, function_call_data
                    ),
                    self.loop,
                ).result()
                # 閻庤鎮堕崕閬嶅矗閸绠憸鎴煛閸灈婵硶閹叉挳宕遍弴锛勫鐐插级濡叉帞绮氶弫宥囦沪閻ｅ本缍勯梺钘夊閺呭煘閺嶉柤鐓庡瀛濋梺?
                
                try:
                    self._tool_running = True
                    self.mark_active()
                except Exception:
                    pass
                self._handle_function_result(result, function_call_data, depth=depth)
                # 閻庤鎮堕崕閬嶅矗鐠哄亾閻熺増婀伴柛宀搁弫宥囦沪閽樺鎮煎鐐村灥閻楀懐鎹璺虹?
                
                try:
                    self._tool_running = False
                    self.mark_active()
                except Exception:
                    pass

        # 闁诲孩绋掗敋闁稿绉堕埀鏁搁柣绮欏畷姗宕?        if len(response_message) > 0:
            text_buff = "".join(response_message)
            self.tts_MessageText = text_buff
            self.dialogue.put(Message(role="assistant", content=text_buff))
            # 闂傚倸鐗忛崑娑吹闁秴鏋侀柟宄扮灱濞堝爼鏌ｉ崝蹇涙儗閹礋閸撲胶鐛柣鐘辩劍濠绱炲鍫涗汗闁规儳鍟块柡澶屽仧閹?
            
            try:
                self._append_conversation_event(question=query, reply=text_buff, source="realtime")
            except Exception:
                pass
        if depth == 0:
            self.logger.bind(tag=TAG).info(f"[CHAT_FINISH_DEBUG] chat()闂佸憡鐟崹鍧楀焵娣囩枆ST: sentence_id={self.sentence_id}, tool_call_flag={tool_call_flag}")
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=self.sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
            # 缂傚倷鐒幐璇查埢鎾诲礂閸濇闂佸憡甯￠弨閬嶅蓟婵犲伅娲及韫囨洍鏀?            self.mark_active()
        self.llm_finish_task = True
        self.logger.bind(tag=TAG).info(f"[CHAT_FINISH_DEBUG] chat()闁诲海鎳撻張宕? llm_finish_task=True")
        # 婵炶揪缍濞夋洟寮玜mbda閻庣偣鍊栭崕鑲崲濠婂懏濯奸柨娑樺閺嗘煥濞戞瀚扮憸鎶婂洤瀚夊璺洪煬鐝糆BUG缂備胶瀚忛崘鍔堕梺鍝勫暢閸牗鏅堕悩璇茬鐟滄吇et_llm_dialogue()
        self.logger.bind(tag=TAG).debug(
            lambda: json.dumps(
                self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False
            )
        )

        return True

    def _handle_function_result(self, result, function_call_data, depth):
        if result.action == Action.RESPONSE:  # 闂佺儵鏅涢悺鏁幘鐐婇柣鎰叀瀹曟粌?            text = result.response
            try:
                from core.utils import textUtils as _txu
                text = _txu.sanitize_for_device(text)
            except Exception:
                pass
            self.tts.tts_one_sentence(self, ContentType.TEXT, content_detail=text)
            self.dialogue.put(Message(role="assistant", content=text))
            # 闂佸憡鍨兼慨寮抽悢鐑樺闁告劖娈柣鐘烘缁愮偤鏌娆庝孩閻熸粎澧楀鏍礊鐎ｇ鐎圭墢閺嬪倿鎮楅悽鐢告儊?
            
            try:
                self._append_conversation_event(question=self._get_last_user_content(), reply=text, source="realtime")
            except Exception:
                pass
        elif result.action == Action.REQLLM:  # 闁荤姴閸熶即寮妶澶婄闁兼亽鍎插鍫曟煕濮橀柛鐔插亾闁荤姴娲弨閬嶆儑閻辰m闂佹眹鍨婚崰鎰板垂濮樿泛鐐婇柣?            text = result.result
            if text is not None and len(text) > 0:
                function_id = function_call_data["id"]
                function_name = function_call_data["name"]
                function_arguments = function_call_data["arguments"]
                self.dialogue.put(
                    Message(
                        role="assistant",
                        tool_calls=[
                            {
                                "id": function_id,
                                "function": {
                                    "arguments": (
                                        "{}"
                                        if function_arguments == ""
                                        else function_arguments
                                    ),
                                    "name": function_name,
                                },
                                "type": "function",
                                "index": 0,
                            }
                        ],
                    )
                )

                self.dialogue.put(
                    Message(
                        role="tool",
                        tool_call_id=(
                            str(uuid.uuid4()) if function_id is None else function_id
                        ),
                        content=text,
                    )
                )
                self.chat(text, depth=depth + 1)
        elif result.action == Action.NOTFOUND or result.action == Action.ERROR:
            text = result.response if result.response else result.result
            try:
                from core.utils import textUtils as _txu
                text = _txu.sanitize_for_device(text)
            except Exception:
                pass
            self.tts.tts_one_sentence(self, ContentType.TEXT, content_detail=text)
            self.dialogue.put(Message(role="assistant", content=text))
        else:
            pass

    def handle_vision_bridge(self, payload: dict):
        """婵犳硾鐎氬箖婵犲洤绾柕澶堝妼濞堢檹TTP闁荤喐鐟婊堟煙閹帒鍔氱憸鐗堢洴閹啴宕熼崐杈叏濠靛嫬鍔紒鍔戝绋块崟濠傞獮鎺楀閿濆倸浜?
        婵炲濮撮幊搴￠幏瀣箚瑜斿鐢稿焵娣囪櫣鎹崓濂P闂佹悶鍎抽崑妯兼閸撲胶纾奸柟鎯禍鏌￠崘鏋勭紓宥嗘缁嬪宕崟绠查柟鐓庣摠濞叉濠靛鐒奸柛璧嬮柣搴ｆ暩闁绘櫕缁汲闁秴绫嶉柛娲橀敍鐔兼煛閸愰柟濂告敱閹棃寮埀宕归妸妫樼紒杈灴婵?
        Args:
            payload: vision_handler 闁哄鏅滈弻閺嶅剭闁告厹N闁诲孩绋掗柛姘ｅ亾闂佹寧绋戦懟鍨畷?response 婵炴垶鎸告姝岄弻鐒?correlation_id闂?        """
        try:
            if not isinstance(payload, dict):
                return
            corr_id = payload.get("correlation_id")
            if corr_id and corr_id in self._seen_vision_ids:
                return  # 閻庣懓鎲鍐煟閻愬弶缂佽鍟撮弫宥呯暆閸曠礆闂佺绻愮粔褰掑闯閸涘绶炵规鐏忥繝鏌?            text = payload.get("response") or ""
            if not text:
                return
            # 闂佸搫绉村鐟版啞瑜板啴鏌?            if corr_id:
                if len(self._seen_vision_ids) > 100:
                    # 缂備胶濮崑鎾绘煕濡焦绀嬫俊鐐瀹曟岸宕奸弴鐔诲亖闂佸憡鑹鹃悧鍡涘閸剨?                    self._seen_vision_ids.clear()
                self._seen_vision_ids.add(corr_id)
            # 闂佸憡鐟崹鍧楀焵缁渚宕哄畝閹峰骞嗚瀹曟粌閸瑦绻?
            
            try:
                from core.utils import textUtils as _txu
                text = _txu.sanitize_for_device(text)
            except Exception:
                pass
            # 婵炶揪缍濞夋洟寮妶澶婄闁搁獮妯绘叏閵堝瀚夐柣鏂垮悑閿涚喖鏌妯绘拱闁绘牭绲块幏瀣箯瀹閹插瓨寰勬繝鍐惈闂佸湱鐟抽崱娑氬祦閻犲搫鎼悡鏇煛閸屾粌婵＄偠娉曢幑?
            
            try:
                # 闂佸憡鑹捐闁荤喐鐟婊呯磼濞戞娆悢鍝繝闈涙处閵囩喖鏌妯肩伇婵炴彃娼畷姘跺箥濞夋煛鐎ｇ煁闁规悂浜堕獮搴閵夋闂?                self.vision_wait_start()
                self.mark_active()
            except Exception:
                pass
            # 婵炶揪缍濞夋洟寮妶澶婄闁搁獮妯绘叏閵堝鏅归埀鍨惧鑽繝闈涙处缁犳帡鏌￠崟鎹ｉ柍閹?FIRST->MIDDLE->LAST 缂傚倷鐒幐璇查弫宥呯暆閸曟叏濠靛嫬鐏柣锝嗗仼婵炲棙鎸昏闂佸憡甯楅梺濂告敱濞兼瑩骞冨鍐＜缂佽鲸鎸鹃弫?            self._speak_vision_response(text)
            try:
                # 闂佽鍎宠闁诲海鎳撻張宕瑰璺鸿閹肩补鑼笉濠电缚閸鎮峰蹇曟崲濮?                self.vision_wait_stop()
                self.mark_active()
            except Exception:
                pass
            self.logger.bind(tag=TAG).info("閻庣懓鎲￠悡锟犲焵娣囪櫣鎹崓鍖盩P濠甸崕鑼暜鐎靛憡鍠嗛柛姘槐鎺楀箻鐎甸晲鍑介梺鍛婂浮缂佽鲸澹嗛幏鐘查幘鍓侀梺鍛婂笒濡瑩鏌熼幆鎾绘煥?)
        except Exception as _e:
            try:
                self.logger.bind(tag=TAG).warning(f"婵犳硾鐎氬箖婵犲嫭鍠嗛柛鑹鹃柕澶涚畱婢跺秶绱撴担瑙勫鞍闁诲繐闁稿本姘崺? {_e}")
            except Exception:
                pass

    # 闂佸搫鍊瑰姗鏌娆庝孩闁荤喐鐟柣鍨甸柛娑氬鐐跺蔼闁归叄瀹曟垵閸曞幍濠?    def vision_wait_start(self, interval_sec: float = 8.0):
        """閻庨潧浜炬繝鐢告偡濞嗗繘鎮洪幋婵嬪川缁犺姤绻涢煫涓茬紒杈箞瀹曞閿旇棄鐒搁梺鍛婂浮閺閬嶅蓟婵犲伅娲及韫囨洍鏀梺鍝勫暙閻栫厧閸鏅归崟绱氶梺绋跨箰缁夋潙閹叉挳宕卞杈＜闁规儳娴滃级閳哄倹鐓繛鍙夌墵瀹曟粌閸縿鎺楀川閸婄偤鏌?""
        try:
            # 闂佸吋鐪归崕閬嶅礄閿熺姴瀚夊璺哄畷鏌煕閺傝　鍋撻崘鑼户婵炴垶鎸哥粔褰掑闯閸涘绶炵规噽绾惧鏌?            if self._vision_keepalive_task and not self._vision_keepalive_task.done():
                return
            self._vision_inflight = True

            async def _keepalive():
                try:
                 
