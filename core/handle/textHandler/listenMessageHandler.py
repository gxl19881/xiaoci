import time
from typing import Dict, Any

from core.handle.receiveAudioHandle import handleAudioMessage, startToChat
from core.handle.reportHandle import enqueue_asr_report
from core.handle.sendAudioHandle import send_stt_message, send_tts_message
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.util import remove_punctuation_and_length
import asyncio
from core.handle.intentHandler import _try_device_camera_direct

TAG = __name__

class ListenTextMessageHandler(TextMessageHandler):
    """Listen消息处理器"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.LISTEN

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        if "mode" in msg_json:
            conn.client_listen_mode = msg_json["mode"]
            conn.logger.bind(tag=TAG).debug(
                f"客户端拾音模式：{conn.client_listen_mode}"
            )
        if msg_json["state"] == "start":
            conn.client_have_voice = True
            conn.client_voice_stop = False
            conn.last_voice_activity_time = time.time() * 1000
            # 新一轮开始说话，取消任何在等待中的静默触发任务
            try:
                task = getattr(conn, "_silence_trigger_task", None)
                if task and not task.done():
                    task.cancel()
            except Exception:
                pass
        elif msg_json["state"] == "stop":
            conn.client_have_voice = True
            conn.client_voice_stop = True
            if len(conn.asr_audio) > 0:
                await handleAudioMessage(conn, b"")
            # 说话结束后启动3秒静默触发任务（如3秒内无新语音则向服务器发送命令）
            try:
                # 若已有旧任务，先取消
                old = getattr(conn, "_silence_trigger_task", None)
                if old and not old.done():
                    old.cancel()

                async def _silence_trigger_after_3s():
                    try:
                        await asyncio.sleep(3)
                        # 若期间出现新的语音开始，则不触发
                        if not getattr(conn, "client_voice_stop", False):
                            return
                        # 基于最近一条用户语音内容判断是否需要触发拍照等动作
                        last_text = None
                        try:
                            last_text = conn._get_last_user_content()
                        except Exception:
                            last_text = None
                        if last_text:
                            try:
                                _, filtered = remove_punctuation_and_length(last_text)
                            except Exception:
                                filtered = last_text
                            # 1) 优先尝试直达拍照（避免走错到图像生成插件）
                            try:
                                acted = await _try_device_camera_direct(conn, filtered, original_text=last_text)
                            except Exception as _e:
                                conn.logger.bind(tag=TAG).warning(f"静默直达拍照判定异常: {_e}")
                                acted = False
                            if acted:
                                conn.logger.bind(tag=TAG).info("静默3秒：拍照意图直达，已触发设备摄像头")
                            else:
                                # 2) 未匹配直达，则把用户语音作为一轮对话交给LLM解析与执行
                                try:
                                    enqueue_asr_report(conn, last_text, [])
                                except Exception:
                                    pass
                                try:
                                    await startToChat(conn, last_text)
                                    conn.logger.bind(tag=TAG).info("静默3秒：已将最近语音交给LLM处理")
                                except Exception as _e:
                                    conn.logger.bind(tag=TAG).error(f"静默触发LLM失败: {_e}")
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                conn._silence_trigger_task = asyncio.create_task(_silence_trigger_after_3s())
            except Exception:
                pass
        elif msg_json["state"] == "detect":
            conn.client_have_voice = False
            conn.asr_audio.clear()
            # 检测模式下收到内容，也应取消静默触发任务（表示用户仍在互动）
            try:
                task = getattr(conn, "_silence_trigger_task", None)
                if task and not task.done():
                    task.cancel()
            except Exception:
                pass
            if "text" in msg_json:
                conn.last_activity_time = time.time() * 1000
                original_text = msg_json["text"]  # 保留原始文本
                filtered_len, filtered_text = remove_punctuation_and_length(
                    original_text
                )

                # 识别是否是唤醒词
                is_wakeup_words = filtered_text in conn.config.get("wakeup_words")
                # 是否开启唤醒词回复
                enable_greeting = conn.config.get("enable_greeting", True)

                if is_wakeup_words and not enable_greeting:
                    # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                    await send_stt_message(conn, original_text)
                    await send_tts_message(conn, "stop", None)
                    conn.client_is_speaking = False
                elif is_wakeup_words:
                    conn.just_woken_up = True
                    # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                    enqueue_asr_report(conn, "嘿，你好呀", [])
                    await startToChat(conn, "嘿，你好呀")
                else:
                    # 上报纯文字数据（复用ASR上报功能，但不提供音频数据）
                    enqueue_asr_report(conn, original_text, [])
                    # 否则需要LLM对文字内容进行答复
                    await startToChat(conn, original_text)