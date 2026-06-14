import json
import time
import asyncio
import re
from core.utils import textUtils
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType

TAG = __name__


async def sendAudioMessage(conn, sentenceType, audios, text):
    # 记录是否为本轮会话的首段，用于首帧下行前插入极短延时，确保客户端先进入speaking状态
    _was_first_segment = False
    if conn.tts.tts_audio_first_sentence:
        _was_first_segment = True
        conn.logger.bind(tag=TAG).info(f"发送第一段语音: {text}")
        conn.tts.tts_audio_first_sentence = False
        await send_tts_message(conn, "start", None)

    if sentenceType == SentenceType.FIRST:
        await send_tts_message(conn, "sentence_start", text)

    # 兼容分段文本同时下发的情况（MIDDLE类型也可能携带文本）
    if sentenceType == SentenceType.MIDDLE and text:
        # 当音频流中间夹带文本时，发送 sentence_start 以更新显示的字幕
        conn.logger.bind(tag=TAG).info(f"同步显示分段文本: {text}")
        await send_tts_message(conn, "sentence_start", text)

    # 首帧音频发送前，给设备一个极短缓冲时间处理JSON状态切换（start/sentence_start）
    # 典型值 60~120ms，可显著降低仅播出开头字词的问题
    if _was_first_segment:
        try:
            await asyncio.sleep(0.1)
        except Exception:
            pass

    await sendAudio(conn, audios)
    # 发送句子开始消息
    if sentenceType is not SentenceType.MIDDLE:
        conn.logger.bind(tag=TAG).info(f"发送音频消息: {sentenceType}, {text}")

    # 发送结束消息（如果是最后一个文本）
    if conn.llm_finish_task and sentenceType == SentenceType.LAST:
        await send_tts_message(conn, "stop", None)
        conn.client_is_speaking = False
        if conn.close_after_chat:
            await conn.close()


def calculate_timestamp_and_sequence(conn, start_time, packet_index, frame_duration=60):
    """
    计算音频数据包的时间戳和序列号
    Args:
        conn: 连接对象
        start_time: 起始时间（性能计数器值）
        packet_index: 数据包索引
        frame_duration: 帧时长（毫秒），匹配 Opus 编码
    Returns:
        tuple: (timestamp, sequence)
    """
    # 计算时间戳（使用播放位置计算）
    timestamp = int((start_time + packet_index * frame_duration / 1000) * 1000) % (
        2**32
    )

    # 计算序列号
    if hasattr(conn, "audio_flow_control"):
        sequence = conn.audio_flow_control["sequence"]
    else:
        sequence = packet_index  # 如果没有流控状态，直接使用索引

    return timestamp, sequence


async def _send_to_mqtt_gateway(conn, opus_packet, timestamp, sequence):
    """
    发送带16字节头部的opus数据包给mqtt_gateway
    Args:
        conn: 连接对象
        opus_packet: opus数据包
        timestamp: 时间戳
        sequence: 序列号
    """
    # 为opus数据包添加16字节头部
    header = bytearray(16)
    header[0] = 1  # type
    header[2:4] = len(opus_packet).to_bytes(2, "big")  # payload length
    header[4:8] = sequence.to_bytes(4, "big")  # sequence
    header[8:12] = timestamp.to_bytes(4, "big")  # 时间戳
    header[12:16] = len(opus_packet).to_bytes(4, "big")  # opus长度

    # 发送包含头部的完整数据包
    complete_packet = bytes(header) + opus_packet
    await conn.websocket.send(complete_packet)


# 播放音频
async def sendAudio(conn, audios, frame_duration=60):
    """
    发送单个opus包，支持流控
    Args:
        conn: 连接对象
        opus_packet: 单个opus数据包
        pre_buffer: 快速发送音频
        frame_duration: 帧时长（毫秒），匹配 Opus 编码
    """
    if audios is None or len(audios) == 0:
        return

    if isinstance(audios, bytes):
        if conn.client_abort:
            return

        conn.last_activity_time = time.time() * 1000

        # 获取或初始化流控状态
        if not hasattr(conn, "audio_flow_control"):
            conn.audio_flow_control = {
                "last_send_time": 0,
                "packet_count": 0,
                "start_time": time.perf_counter(),
                "sequence": 0,  # 添加序列号
            }

        flow_control = conn.audio_flow_control
        current_time = time.perf_counter()
        # 计算预期发送时间
        expected_time = flow_control["start_time"] + (
            flow_control["packet_count"] * frame_duration / 1000
        )
        delay = expected_time - current_time

        # 如果延迟严重滞后（例如超过0.5秒），说明发生了长时间的中断或阻塞
        # 此时应该重置起始时间，避免为了追赶进度而瞬间突发大量数据包导致设备缓冲区溢出
        if delay < -0.5:
             conn.logger.bind(tag=TAG).warning(f"音频流控严重滞后: {delay:.3f}s，重置流控基准时间")
             # 重置基准时间，相当于将所有未发送的数据包视为"现在"才开始生成
             # 保持已发送数量不变，仅移动时间窗口
             flow_control["start_time"] = current_time - (flow_control["packet_count"] * frame_duration / 1000)
             # 重新计算，此时 delay 应为 0
             delay = 0

        if delay > 0:
            await asyncio.sleep(delay)
        else:
            # 微小误差累积纠正（正常追赶）
            flow_control["start_time"] += abs(delay)

        if conn.conn_from_mqtt_gateway:
            # 计算时间戳和序列号
            timestamp, sequence = calculate_timestamp_and_sequence(
                conn,
                flow_control["start_time"],
                flow_control["packet_count"],
                frame_duration,
            )
            # 调用通用函数发送带头部的数据包
            await _send_to_mqtt_gateway(conn, audios, timestamp, sequence)
        else:
            # 直接发送opus数据包，不添加头部
            await conn.websocket.send(audios)

        # 更新流控状态
        flow_control["packet_count"] += 1
        flow_control["sequence"] += 1
        flow_control["last_send_time"] = time.perf_counter()
    else:
        # 文件型音频走普通播放
        start_time = time.perf_counter()
        play_position = 0

        # 执行预缓冲
        pre_buffer_frames = min(5, len(audios))
        for i in range(pre_buffer_frames):
            if conn.conn_from_mqtt_gateway:
                # 计算时间戳和序列号
                timestamp, sequence = calculate_timestamp_and_sequence(
                    conn, start_time, i, frame_duration
                )
                # 调用通用函数发送带头部的数据包
                await _send_to_mqtt_gateway(conn, audios[i], timestamp, sequence)
            else:
                # 直接发送预缓冲包，不添加头部
                await conn.websocket.send(audios[i])
        remaining_audios = audios[pre_buffer_frames:]

        # 播放剩余音频帧
        for i, opus_packet in enumerate(remaining_audios):
            if conn.client_abort:
                break

            # 重置没有声音的状态
            conn.last_activity_time = time.time() * 1000

            # 计算预期发送时间
            expected_time = start_time + (play_position / 1000)
            current_time = time.perf_counter()
            delay = expected_time - current_time
            if delay > 0:
                await asyncio.sleep(delay)

            if conn.conn_from_mqtt_gateway:
                # 计算时间戳和序列号（使用当前的数据包索引确保连续性）
                packet_index = pre_buffer_frames + i
                timestamp, sequence = calculate_timestamp_and_sequence(
                    conn, start_time, packet_index, frame_duration
                )
                # 调用通用函数发送带头部的数据包
                await _send_to_mqtt_gateway(conn, opus_packet, timestamp, sequence)
            else:
                # 直接发送opus数据包，不添加头部
                await conn.websocket.send(opus_packet)

            play_position += frame_duration


EMOJI_RANGES = [
    (0x1F600, 0x1F64F),
    (0x1F300, 0x1F5FF),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
]

def is_emoji(char):
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in EMOJI_RANGES)

def check_emoji(text):
    return ''.join(char for char in text if not is_emoji(char) and char != "\n")

def sanitize_for_device(text: str) -> str:
    if not text:
        return text
    s = text
    lines = s.splitlines()
    cleaned_lines = []
    heading_re = re.compile(r"^\s{0,3}#{1,6}\s*")
    for ln in lines:
        ln = heading_re.sub("", ln)
        cleaned_lines.append(ln)
    s = "\n".join(cleaned_lines)
    s = s.replace("**", "").replace("__", "")
    s = s.replace("`", "")
    s = re.sub(r"\*(\S.*?)\*", r"\1", s)
    s = s.replace("\\(", "(").replace("\\)", ")")
    s = s.replace("$$", "")
    s = s.replace("$", "")
    s = s.replace("\\div", "÷")
    s = s.replace("\\times", "×")
    s = re.sub(r"\\boldsymbol\s*\{(.*?)\}", r"\1", s)
    s = re.sub(r"\\mathbf\s*\{(.*?)\}", r"\1", s)
    s = re.sub(r"\\text\s*\{(.*?)\}", r"\1", s)
    s = s.replace("\\", "")
    lines = [re.sub(r"\s+$", "", ln) for ln in s.splitlines()]
    s = "\n".join(lines)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s

def keep_cn_en_punct(text: str) -> str:
    if not text:
        return text
    s = str(text)
    for _ in range(2):
        s = re.sub(r"\{[^{}]*\}", "", s)
        s = re.sub(r"\[[^\[\]]*\]", "", s)
    allowed_ascii = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?:;()'- /+\n")
    exclude_ascii = set("{}[]<>:@#&=\\`~^|")
    def _keep(ch: str) -> bool:
        if ch in exclude_ascii:
            return False
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            return True
        if 0x0080 <= code <= 0x024F:
            return True
        if ch in ("、", "。", "，", "！", "？", "；", "：", "（", "）", "《", "》", "—", "…", "“", "”", "‘", "’"):
            return True
        if ch == " " or ch == "\n":
            return True
        if ch in allowed_ascii:
            return True
        return False
    s = "".join(ch for ch in s if _keep(ch))
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = "\n".join(ln.strip() for ln in s.splitlines())
    return s

async def send_tts_message(conn, state, text=None):
    """发送 TTS 状态消息"""
    if text is None and state == "sentence_start":
        return
    message = {"type": "tts", "state": state, "session_id": conn.session_id}
    if text is not None:
        # 发送到设备前清洗文本：先常规清洗，再强白名单过滤，仅保留中英字符+常用标点
        # 使用本地定义的清洗函数，避免模块加载问题
        try:
            cleaned = sanitize_for_device(text)
            cleaned = keep_cn_en_punct(cleaned)
            message["text"] = check_emoji(cleaned)
        except Exception as e:
            # 兜底：如果清洗失败，发送原始文本或简单清洗
            conn.logger.bind(tag=TAG).warning(f"文本清洗失败，发送原始文本: {e}")
            message["text"] = textUtils.get_string_no_punctuation_or_emoji(text) if hasattr(textUtils, 'get_string_no_punctuation_or_emoji') else text

    # 任一TTS状态消息视为一次活动，刷新连接活跃时间，降低边界超时风险
    try:
        conn.last_activity_time = time.time() * 1000
    except Exception:
        pass

    # TTS播放结束
    if state == "stop":
        # 播放提示音
        tts_notify = conn.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = conn.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            audios = audio_to_data(stop_tts_notify_voice, is_opus=True)
            await sendAudio(conn, audios)
        # 清除服务端讲话状态
        conn.clearSpeakStatus()

    # 发送消息到客户端
    await conn.websocket.send(json.dumps(message))


async def send_stt_message(conn, text):
    """发送 STT 状态消息"""
    end_prompt_str = conn.config.get("end_prompt", {}).get("prompt")
    if end_prompt_str and end_prompt_str == text:
        await send_tts_message(conn, "start")
        return

    # 解析JSON格式，提取实际的用户说话内容
    display_text = text
    try:
        # 尝试解析JSON格式
        if text.strip().startswith("{") and text.strip().endswith("}"):
            parsed_data = json.loads(text)
            if isinstance(parsed_data, dict) and "content" in parsed_data:
                # 如果是包含说话人信息的JSON格式，只显示content部分
                display_text = parsed_data["content"]
                # 保存说话人信息到conn对象
                if "speaker" in parsed_data:
                    conn.current_speaker = parsed_data["speaker"]
    except (json.JSONDecodeError, TypeError):
        # 如果不是JSON格式，直接使用原始文本
        display_text = text
    stt_text = textUtils.get_string_no_punctuation_or_emoji(display_text)
    await conn.websocket.send(
        json.dumps({"type": "stt", "text": stt_text, "session_id": conn.session_id})
    )
    conn.client_is_speaking = True
    await send_tts_message(conn, "start")
