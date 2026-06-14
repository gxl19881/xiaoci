import os
import uuid
import json
import time
import queue
import asyncio
import traceback
import websockets
from asyncio import Task
from config.logger import setup_logging
from core.utils import opus_encoder_utils
from core.utils.tts import MarkdownCleaner
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)

        self.interface_type = InterfaceType.DUAL_STREAM
        # 基础配置
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("api_key is required for CosyVoice TTS")

        # WebSocket配置
        self.ws_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
        self.ws = None
        self._monitor_task = None
        self.last_active_time = None

        # 模型和音色配置
        self.model = config.get("model", "cosyvoice-v2")
        self.voice = config.get("voice", "longxiaochun_v2")  # 默认音色
        if config.get("private_voice"):
            self.voice = config.get("private_voice")

        # 音频参数配置
        self.format = config.get("format", "pcm")
        sample_rate = config.get("sample_rate", "24000")
        self.sample_rate = int(sample_rate) if sample_rate else 24000

        volume = config.get("volume", "50")
        self.volume = int(volume) if volume else 50

        rate = config.get("rate", "1.0")
        self.rate = float(rate) if rate else 1.0

        pitch = config.get("pitch", "1.0")
        self.pitch = float(pitch) if pitch else 1.0

        self.header = {
            "Authorization": f"Bearer {self.api_key}",
            # "user-agent": "your_platform_info", // 可选
            # "X-DashScope-WorkSpace": workspace, // 可选，阿里云百炼业务空间ID
            "X-DashScope-DataInspection": "enable",
        }

        # 创建Opus编码器
        self.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=self.sample_rate, channels=1, frame_size_ms=60
        )

    async def _ensure_connection(self):
        """确保WebSocket连接可用，支持60秒内连接复用"""
        try:
            current_time = time.time()
            # 增加对连接状态的检查: open=1
            is_connected = self.ws is not None and not getattr(self.ws, "closed", True) and getattr(self.ws, "state", 0) == 1
            
            if is_connected and current_time - self.last_active_time < 60:
                # 一分钟内才可以复用链接进行连续对话
                logger.bind(tag=TAG).info(f"使用已有链接...")
                return self.ws
            logger.bind(tag=TAG).info("开始建立新连接...")

            self.ws = await websockets.connect(
                self.ws_url,
                additional_headers=self.header,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
            )

            logger.bind(tag=TAG).info("WebSocket连接建立成功")
            self.last_active_time = current_time
            return self.ws
        except Exception as e:
            logger.bind(tag=TAG).error(f"建立连接失败: {str(e)}")
            self.ws = None
            self.last_active_time = None
            raise

    def tts_text_priority_thread(self):
        """流式TTS文本处理线程"""
        while not self.conn.stop_event.is_set():
            try:
                message = self.tts_text_queue.get(timeout=1)
                
                # 处理静音模式：只显示文本，不进行TTS合成，也不建立WebSocket会话
                if getattr(self.conn, "silent_mode_once", False):
                    # 如果不是文本内容（例如是控制信号），直接跳过处理但保留信号传递
                    if message.content_type != ContentType.TEXT:
                        self.tts_audio_queue.put((message.sentence_type, [], message.content_detail))
                        if message.sentence_type == SentenceType.LAST:
                            logger.bind(tag=TAG).info("静音模式会话结束")
                        continue

                    # 文本处理：进行缓冲和断句，避免逐字显示
                    if message.content_detail:
                        self.tts_text_buff.append(message.content_detail)
                        combined_text = "".join(self.tts_text_buff)

                        # 简单的断句逻辑（同下方正常TTS逻辑）
                        if len(combined_text) > 0 and (any(p in combined_text for p in self.punctuations) or len(combined_text) > 50):
                            import re
                            pattern = f"([{''.join(self.punctuations)}])"
                            parts = re.split(pattern, combined_text)
                            
                            current_sentence = ""
                            segments_to_send = []
                            
                            for part in parts:
                                if part in self.punctuations:
                                    current_sentence += part
                                    if current_sentence:
                                        segments_to_send.append(current_sentence)
                                        current_sentence = ""
                                else:
                                    current_sentence += part
                            
                            # 发送完整句子
                            for seg in segments_to_send:
                                logger.bind(tag=TAG).debug(f"静音模式发送文本(自动断句): {seg}")
                                self.tts_audio_queue.put((SentenceType.MIDDLE, [], seg))
                            
                            # 处理剩余
                            if len(current_sentence) > 50:
                                logger.bind(tag=TAG).debug(f"静音模式发送文本(长句强制): {current_sentence}")
                                self.tts_audio_queue.put((SentenceType.MIDDLE, [], current_sentence))
                                self.tts_text_buff = []
                            else:
                                self.tts_text_buff = [current_sentence] if current_sentence else []
                    
                    if message.sentence_type == SentenceType.LAST:
                         # 发送剩余缓冲
                        remaining_text = "".join(self.tts_text_buff)
                        if remaining_text:
                            logger.bind(tag=TAG).debug(f"静音模式发送剩余文本: {remaining_text}")
                            self.tts_audio_queue.put((SentenceType.MIDDLE, [], remaining_text))
                        self.tts_text_buff = []
                        
                        logger.bind(tag=TAG).info("静音模式会话结束")
                        # 发送结束信号
                        self.tts_audio_queue.put((SentenceType.LAST, [], None))
                    continue

                logger.bind(tag=TAG).debug(
                    f"收到TTS任务｜{message.sentence_type.name} ｜ {message.content_type.name} | 会话ID: {self.conn.sentence_id}"
                )

                if message.sentence_type == SentenceType.FIRST:
                    self.conn.client_abort = False

                if self.conn.client_abort:
                    try:
                        logger.bind(tag=TAG).info("收到打断信息，终止TTS文本处理线程")
                        continue
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"取消TTS会话失败: {str(e)}")
                        continue

                if message.sentence_type == SentenceType.FIRST:
                    # 初始化会话
                    try:
                        if not getattr(self.conn, "sentence_id", None): 
                            self.conn.sentence_id = uuid.uuid4().hex
                            logger.bind(tag=TAG).info(f"自动生成新的 会话ID: {self.conn.sentence_id}")

                        logger.bind(tag=TAG).info("开始启动TTS会话...")
                        future = asyncio.run_coroutine_threadsafe(
                            self.start_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result()
                        self.before_stop_play_files.clear()
                        logger.bind(tag=TAG).info("TTS会话启动成功")
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"启动TTS会话失败: {str(e)}")
                        continue

                elif ContentType.TEXT == message.content_type:
                     if message.content_detail:
                        self.tts_text_buff.append(message.content_detail)
                        # 简单的断句逻辑
                        combined_text = "".join(self.tts_text_buff)
                        if len(combined_text) > 0 and (any(p in combined_text for p in self.punctuations) or len(combined_text) > 50):
                            # 有标点或长度超过50，尝试拆分或发送
                            import re
                            # 使用正则拆分，保留标点
                            pattern = f"([{''.join(self.punctuations)}])"
                            parts = re.split(pattern, combined_text)
                            
                            # 重新组合：内容+标点
                            current_sentence = ""
                            segments_to_send = []
                            
                            for part in parts:
                                if part in self.punctuations:
                                    current_sentence += part
                                    if current_sentence:
                                        segments_to_send.append(current_sentence)
                                        current_sentence = ""
                                else:
                                    current_sentence += part
                            
                            # 发送所有完整的句子
                            for seg in segments_to_send:
                                try:
                                    logger.bind(tag=TAG).debug(f"开始发送TTS文本(自动断句): {seg}")
                                    self._push_text_to_sync_queue(seg)
                                    # 增加延时，控制发送速率
                                    time.sleep(0.05)
                                    future = asyncio.run_coroutine_threadsafe(
                                        self.text_to_speak(seg, None),
                                        loop=self.conn.loop,
                                    )
                                    future.result()
                                except Exception as e:
                                    logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")

                            # 看看是否因为长句强制触发
                            if len(current_sentence) > 50:
                                # 剩余部分依然很长（说明没标点），强制发
                                try:
                                    logger.bind(tag=TAG).debug(f"开始发送TTS文本(长句强制): {current_sentence}")
                                    self._push_text_to_sync_queue(current_sentence)
                                    # 增加延时，控制发送速率
                                    time.sleep(0.05)
                                    future = asyncio.run_coroutine_threadsafe(
                                        self.text_to_speak(current_sentence, None),
                                        loop=self.conn.loop,
                                    )
                                    future.result()
                                    self.tts_text_buff = []
                                except Exception as e:
                                    logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
                            else:
                                # 放回缓冲
                                self.tts_text_buff = [current_sentence] if current_sentence else []
                        else:
                            # 文本太短且无标点，继续缓冲
                            pass

                elif ContentType.FILE == message.content_type:
                    logger.bind(tag=TAG).info(
                        f"添加音频文件到待播放列表: {message.content_file}"
                    )
                    if message.content_file and os.path.exists(message.content_file):
                        # 先处理文件音频数据
                        self._process_audio_file_stream(message.content_file, callback=lambda audio_data: self.handle_audio_file(audio_data, message.content_detail))

                if message.sentence_type == SentenceType.LAST:
                    # 将缓冲区剩余文本发送出去
                    remaining_text = "".join(self.tts_text_buff)
                    if remaining_text:
                        try:
                            logger.bind(tag=TAG).debug(f"开始发送剩余TTS文本: {remaining_text}")
                            self._push_text_to_sync_queue(remaining_text)
                            # 增加延时，控制发送速率
                            time.sleep(0.05)
                            future = asyncio.run_coroutine_threadsafe(
                                self.text_to_speak(remaining_text, None),
                                loop=self.conn.loop,
                            )
                            future.result()
                            self.tts_text_buff = []
                        except Exception as e:
                            logger.bind(tag=TAG).error(f"发送剩余TTS文本失败: {str(e)}")

                    try:
                        logger.bind(tag=TAG).info("开始结束TTS会话...")
                        future = asyncio.run_coroutine_threadsafe(
                            self.finish_session(self.conn.sentence_id),
                            loop=self.conn.loop,
                        )
                        future.result()
                    except Exception as e:
                        logger.bind(tag=TAG).error(f"结束TTS会话失败: {str(e)}")
                        continue

            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理TTS文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue


    async def text_to_speak(self, text, _):
        """发送文本到TTS服务进行合成"""
        try:
            # 自动重连逻辑
            if self.ws is None or getattr(self.ws, "closed", True):
                conn_id = getattr(self.conn, "sentence_id", None) or uuid.uuid4().hex
                logger.bind(tag=TAG).warning(f"WebSocket连接已断开，尝试恢复会话(ID:{conn_id})...")
                try:
                    await self.start_session(conn_id)
                    await asyncio.sleep(0.05)
                except Exception as recover_err:
                     logger.bind(tag=TAG).error(f"TTS会话恢复失败: {recover_err}")
                     return

            if self.ws is None:
                logger.bind(tag=TAG).warning("WebSocket连接不存在，终止发送文本")
                return

            # 过滤Markdown, emoji和其他垃圾字符
            filtered_text = MarkdownCleaner.clean_markdown(text)
            # 移除所有emoji，使用更普适的正则，排除常见的Emoji范围
            # 使用非贪婪匹配移除可能包含emoji的字符
            import re
            # 过滤掉非中英文、非数字、非标点的字符
            # 严格白名单过滤：只保留 中文、英文、数字、常见标点、空白符
            # 注意：\w 在Python3中包含Unicode字符(含Emoji)，因此必须移除 \w，改用明确范围
            filtered_text = re.sub(r'[^\s,.，。！？!?；;:：\u4e00-\u9fa5a-zA-Z0-9]', '', filtered_text)
            filtered_text = filtered_text.strip()
            
            if not filtered_text:
                logger.bind(tag=TAG).warning("文本过滤后为空，替换为静音占位符以维持会话")
                filtered_text = "，"

            # 发送continue-task消息

            continue_task_message = {
                "header": {
                    "action": "continue-task",
                    "task_id": self.conn.sentence_id,
                    "streaming": "duplex",
                },
                "payload": {"input": {"text": filtered_text}},
            }

            await self.ws.send(json.dumps(continue_task_message))
            self.last_active_time = time.time()
            logger.bind(tag=TAG).debug(f"已发送文本: {filtered_text}")

        except Exception as e:
            logger.bind(tag=TAG).error(f"发送TTS文本失败: {str(e)}")
            if self.ws:
                try:
                    await self.ws.close()
                except:
                    pass
                self.ws = None
            raise

    async def start_session(self, session_id):
        """启动TTS会话"""
        logger.bind(tag=TAG).info(f"开始会话～～{session_id}")
        try:
            # 检查并清理上一个会话的监听任务
            if (
                self._monitor_task is not None
                and isinstance(self._monitor_task, Task)
                and not self._monitor_task.done()
            ):
                logger.bind(tag=TAG).info("检测到未完成的上个会话，关闭监听任务...")
                await self.close()

            # 确保连接可用
            await self._ensure_connection()

            # 启动监听任务
            self._monitor_task = asyncio.create_task(self._start_monitor_tts_response())

            # 发送run-task消息启动会话
            parameters = {
                "text_type": "PlainText",
                "voice": self.voice,
                "format": self.format,
                "sample_rate": self.sample_rate,
                "volume": self.volume,
            }
            # 只有当非默认值时才发送rate/pitch，避免某些模型(如CosyVoice)报418参数错误
            if self.rate != 1.0:
                parameters["rate"] = self.rate
            if self.pitch != 1.0:
                parameters["pitch"] = self.pitch

            run_task_message = {
                "header": {
                    "action": "run-task",
                    "task_id": session_id,
                    "streaming": "duplex",
                },
                "payload": {
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": self.model,
                    "parameters": parameters,
                    "input": {}
                },
            }

            await self.ws.send(json.dumps(run_task_message))
            self.last_active_time = time.time()
            logger.bind(tag=TAG).info("会话启动请求已发送")
        except Exception as e:
            logger.bind(tag=TAG).error(f"启动会话失败: {str(e)}")
            await self.close()
            raise

    async def finish_session(self, session_id):
        """结束TTS会话"""
        logger.bind(tag=TAG).info(f"关闭会话～～{session_id}")
        try:
            if self.ws and session_id:
                # 发送finish-task消息
                finish_task_message = {
                    "header": {
                        "action": "finish-task",
                        "task_id": session_id,
                        "streaming": "duplex",
                    },
                    "payload": {
                        "input": {}
                    }
                }

                await self.ws.send(json.dumps(finish_task_message))
                self.last_active_time = time.time()
                logger.bind(tag=TAG).info("会话结束请求已发送")
                # 等待监听任务完成
                if self._monitor_task:
                    try:
                        await self._monitor_task
                    except Exception as e:
                        logger.bind(tag=TAG).error(
                            f"等待监听任务完成时发生错误: {str(e)}"
                        )
                    finally:
                        self._monitor_task = None

        except Exception as e:
            logger.bind(tag=TAG).error(f"关闭会话失败: {str(e)}")
            await self.close()
            raise

    async def close(self):
        """清理资源"""
        # 取消监听任务
        if self._monitor_task:
            try:
                self._monitor_task.cancel()
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.bind(tag=TAG).warning(f"关闭时取消监听任务错误: {e}")
            self._monitor_task = None

        # 关闭WebSocket连接
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
            self.ws = None
            self.last_active_time = None

    async def _start_monitor_tts_response(self):
        """监听TTS响应"""
        try:
            session_finished = False
            while not self.conn.stop_event.is_set():
                try:
                    msg = await self.ws.recv()
                    self.last_active_time = time.time()

                    # 检查客户端是否中止
                    if self.conn.client_abort:
                        logger.bind(tag=TAG).info("收到打断信息，终止监听TTS响应")
                        break

                    if isinstance(msg, str):  # JSON控制消息
                        try:
                            data = json.loads(msg)
                            event = data["header"].get("event")

                            if event == "task-started":
                                logger.bind(tag=TAG).debug("TTS任务启动成功~")
                                self.tts_audio_queue.put((SentenceType.FIRST, [], None))
                            elif event == "result-generated":
                                # 只有当音频和文本同时准备好时，才发送给前端展示
                                # 这里的 text 可能为空，取决于 alibl 的返回
                                # 收到单句结束信号，清除当前正处理的文本标记，以便下一段音频能取到新文本
                                if hasattr(self, "_current_sync_text"):
                                    self._current_sync_text = None
                                pass
                            elif event == "task-finished":
                                logger.bind(tag=TAG).debug("TTS任务完成~")
                                # 任务完成时，如果还有剩余文本没发（例如最后一段），这里可以兜底发送
                                # 检查队列里是否有剩余
                                remaining_text = self._pop_text_from_sync_queue()
                                while remaining_text:
                                    logger.bind(tag=TAG).debug(f"任务完成，补发剩余文本: {remaining_text}")
                                    self.tts_audio_queue.put(
                                        (SentenceType.FIRST, [], remaining_text)
                                    )
                                    remaining_text = self._pop_text_from_sync_queue()
                                
                                # 同时清除状态
                                if hasattr(self, "_current_sync_text"):
                                    self._current_sync_text = None

                                self._process_before_stop_play_files()
                                session_finished = True
                                break
                            elif event == "task-failed":
                                error_code = data["header"].get("error_code", "unknown")
                                error_message = data["header"].get("error_message", "未知错误")
                                logger.bind(tag=TAG).error(
                                    f"TTS任务失败: {error_code} - {error_message}"
                                )
                                # 失败时，将文本作为消息发送给设备显示（不含音频）
                                if self.conn.tts_MessageText:
                                    logger.bind(tag=TAG).info(f"TTS失败，降级显示文本: {self.conn.tts_MessageText}")
                                    
                                    # 兜底过滤 Emoji
                                    import re
                                    downgrade_text = self.conn.tts_MessageText
                                    # 严格白名单过滤：只保留 中文、英文、数字、常见标点、空白符
                                    # 移除 \w，因为它可能匹配 Emoji
                                    downgrade_text = re.sub(r'[^\s,.，。！？!?；;:：\u4e00-\u9fa5a-zA-Z0-9]', '', downgrade_text)
                                    downgrade_text = downgrade_text.strip()
                                    
                                    self.tts_audio_queue.put(
                                        (SentenceType.FIRST, [], downgrade_text)
                                    )
                                    self.conn.tts_MessageText = None
                                break
                        except json.JSONDecodeError:
                            logger.bind(tag=TAG).warning("收到无效的JSON消息")
                    elif isinstance(msg, (bytes, bytearray)):
                        self.opus_encoder.encode_pcm_to_opus_stream(
                            msg, False, callback=self.handle_opus
                        )
                except websockets.ConnectionClosed:
                    logger.bind(tag=TAG).warning("WebSocket连接已关闭")
                    break
                except Exception as e:
                    logger.bind(tag=TAG).error(
                        f"处理TTS响应时出错: {e}\n{traceback.format_exc()}"
                    )
                    break

            # 仅在连接异常且非正常结束时才关闭连接
            if not session_finished and self.ws:
                try:
                    await self.ws.close()
                except:
                    pass
                self.ws = None
        # 监听任务退出时清理引用
        finally:
            self._monitor_task = None

    def _push_text_to_sync_queue(self, text):
        """将文本推入同步队列，处理多段并发的情况"""
        if not hasattr(self.conn, "tts_text_sync_queue"):
            self.conn.tts_text_sync_queue = queue.Queue()
        self.conn.tts_text_sync_queue.put(text)

    def _pop_text_from_sync_queue(self):
        """从同步队列取出文本"""
        if not hasattr(self.conn, "tts_text_sync_queue"):
            return None
        try:
            return self.conn.tts_text_sync_queue.get_nowait()
        except queue.Empty:
            return None

    def handle_opus(self, opus_data):
        """处理 Opus 音频数据"""
        # 当收到第一帧音频数据时，尝试获取同步文本
        text_to_display = None
        
        if not hasattr(self, "_current_sync_text"):
             self._current_sync_text = None
        
        if self._current_sync_text is None:
            # 尝试取出新的一句
            self._current_sync_text = self._pop_text_from_sync_queue()
            if self._current_sync_text:
                text_to_display = self._current_sync_text
        
        if text_to_display:
            logger.bind(tag=TAG).info(f"收到音频流，同步显示文本: {text_to_display}")
            # 这里的音频数据不需要包装成list，直接作为bytes放入，让 sendAudio 使用流控模式
            self.tts_audio_queue.put((SentenceType.MIDDLE, opus_data, text_to_display))
        else:
             # 仅发送音频
            self.tts_audio_queue.put((SentenceType.MIDDLE, opus_data, None))

    def to_tts(self, text: str) -> list:
        """非流式生成音频数据，用于生成音频及测试场景"""
        try:
            # 创建事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 生成会话ID
            session_id = uuid.uuid4().hex
            # 存储音频数据
            audio_data = []

            async def _generate_audio():
                ws = await websockets.connect(
                    self.ws_url,
                    additional_headers=self.header,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10,
                    max_size=10 * 1024 * 1024,
                )

                try:
                    # 发送run-task消息启动会话
                    run_task_message = {
                        "header": {
                            "action": "run-task",
                            "task_id": session_id,
                            "streaming": "duplex",
                        },
                        "payload": {
                            "task_group": "audio",
                            "task": "tts",
                            "function": "SpeechSynthesizer",
                            "model": self.model,
                            "parameters": {
                                "text_type": "PlainText",
                                "voice": self.voice,
                                "format": self.format,
                                "sample_rate": self.sample_rate,
                                "volume": self.volume,
                                "rate": self.rate,
                                "pitch": self.pitch,
                            },
                            "input": {}
                        },
                    }
                    await ws.send(json.dumps(run_task_message))

                    # 等待任务启动
                    task_started = False
                    while not task_started:
                        msg = await ws.recv()
                        if isinstance(msg, str):
                            data = json.loads(msg)
                            header = data.get("header", {})
                            if header.get("event") == "task-started":
                                task_started = True
                                logger.bind(tag=TAG).debug("TTS任务已启动")
                            elif header.get("event") == "task-failed":
                                error_code = header.get("error_code", "unknown")
                                error_message = header.get("error_message", "未知错误")
                                raise Exception(
                                    f"启动任务失败: {error_code} - {error_message}"
                                )

                    # 发送文本
                    filtered_text = MarkdownCleaner.clean_markdown(text)
                    # 发送continue-task消息
                    continue_task_message = {
                        "header": {
                            "action": "continue-task",
                            "task_id": session_id,
                            "streaming": "duplex",
                        },
                        "payload": {"input": {"text": filtered_text}},
                    }
                    await ws.send(json.dumps(continue_task_message))

                    # 发送finish-task消息
                    finish_task_message = {
                        "header": {
                            "action": "finish-task",
                            "task_id": session_id,
                            "streaming": "duplex",
                        },
                        "payload": {
                            "input": {}
                        }
                    }
                    await ws.send(json.dumps(finish_task_message))

                    # 接收音频数据
                    task_finished = False
                    while not task_finished:
                        msg = await ws.recv()
                        if isinstance(msg, (bytes, bytearray)):
                            self.opus_encoder.encode_pcm_to_opus_stream(
                                msg,
                                end_of_stream=False,
                                callback=lambda opus: audio_data.append(opus)
                            )
                        elif isinstance(msg, str):
                            data = json.loads(msg)
                            header = data.get("header", {})
                            if header.get("event") == "task-finished":
                                task_finished = True
                                logger.bind(tag=TAG).debug("TTS任务完成")
                            elif header.get("event") == "task-failed":
                                error_code = header.get("error_code", "unknown")
                                error_message = header.get("error_message", "未知错误")
                                raise Exception(
                                    f"合成失败: {error_code} - {error_message}"
                                )

                finally:
                    # 清理资源
                    try:
                        await ws.close()
                    except:
                        pass

            # 运行异步任务
            loop.run_until_complete(_generate_audio())
            loop.close()

            return audio_data

        except Exception as e:
            logger.bind(tag=TAG).error(f"生成音频数据失败: {str(e)}")
            return []
