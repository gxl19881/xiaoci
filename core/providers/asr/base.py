import os
import sys
import io
import wave
import uuid
import json
import time
import queue
import asyncio
import traceback
import threading
import opuslib_next
import concurrent.futures
from abc import ABC, abstractmethod
from config.logger import setup_logging
from typing import Optional, Tuple, List
from core.handle.receiveAudioHandle import startToChat
from core.handle.reportHandle import enqueue_asr_report
from core.utils.util import remove_punctuation_and_length
from core.handle.receiveAudioHandle import handleAudioMessage

TAG = __name__
logger = setup_logging()


class ASRProviderBase(ABC):
    def __init__(self):
        # 提供者级别的首选语言，默认None表示自动
        self.preferred_language: Optional[str] = None

    # 打开音频通道
    async def open_audio_channels(self, conn):
        conn.asr_priority_thread = threading.Thread(
            target=self.asr_text_priority_thread, args=(conn,), daemon=True
        )
        conn.asr_priority_thread.start()

    # 有序处理ASR音频
    def asr_text_priority_thread(self, conn):
        while not conn.stop_event.is_set():
            try:
                message = conn.asr_audio_queue.get(timeout=1)
                future = asyncio.run_coroutine_threadsafe(
                    handleAudioMessage(conn, message),
                    conn.loop,
                )
                future.result()
            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"处理ASR文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}"
                )
                continue

    # 接收音频
    async def receive_audio(self, conn, audio, audio_have_voice):
        if conn.client_listen_mode == "auto" or conn.client_listen_mode == "realtime":
            have_voice = audio_have_voice
        else:
            have_voice = conn.client_have_voice
        
        conn.asr_audio.append(audio)
        if not have_voice and not conn.client_have_voice:
            conn.asr_audio = conn.asr_audio[-10:]
            return

        if conn.client_voice_stop:
            asr_audio_task = conn.asr_audio.copy()
            conn.asr_audio.clear()
            conn.reset_vad_states()

            if len(asr_audio_task) > 15:
                await self.handle_voice_stop(conn, asr_audio_task)

    # 处理语音停止
    async def handle_voice_stop(self, conn, asr_audio_task: List[bytes]):
        """并行处理ASR和声纹识别"""
        try:
            total_start_time = time.monotonic()
            
            # 准备音频数据
            if conn.audio_format == "pcm":
                pcm_data = asr_audio_task  # 直接来自客户端的PCM片段
            else:
                pcm_data = self.decode_opus(asr_audio_task)  # 先解码为PCM

            # 合并为单一PCM缓冲并确保对齐到16位（偶数字节）
            combined_pcm_data = b"".join(pcm_data)
            fixed_pcm_data = combined_pcm_data
            if len(fixed_pcm_data) % 2 != 0:
                # 修正奇数字节导致的int16对齐问题
                logger.bind(tag=TAG).warning(
                    f"PCM长度非偶数，修正: {len(fixed_pcm_data)} -> {len(fixed_pcm_data) - 1}"
                )
                fixed_pcm_data = fixed_pcm_data[:-1]

            # 端序处理：
            # - 若显式指定 be，则执行 byteswap -> 以 LE 供 ASR
            # - 若显式指定 le，则保持不变
            # - 若未指定，则自动在原样与byteswap两者中择优
            try:
                if conn.audio_format == "pcm":
                    explicit_endian = getattr(conn, "pcm_endian", "le")
                    from array import array

                    def _metrics(a: "array"):
                        n = len(a)
                        if n == 0:
                            return 0, 0.0, 0.0
                        peak = max(max(a), -min(a))
                        # RMS
                        rms = (sum((int(s) * int(s) for s in a)) / n) ** 0.5
                        # 饱和占比（接近全幅的样本比例）
                        clip = sum(1 for s in a if abs(int(s)) >= 32760) / n
                        return peak, rms, clip

                    if explicit_endian in ("le", "be"):
                        if explicit_endian == "be":
                            arr = array('h'); arr.frombytes(fixed_pcm_data)
                            if sys.byteorder == 'little':
                                arr.byteswap()
                            fixed_pcm_data = arr.tobytes()
                            logger.bind(tag=TAG).info("已将BE PCM转换为LE以供ASR使用")
                    else:
                        # 自动检测：比较原样与byteswap的指标，择优
                        arr_le = array('h'); arr_le.frombytes(fixed_pcm_data)
                        arr_sw = array('h', arr_le)
                        arr_sw.byteswap()
                        peak_le, rms_le, clip_le = _metrics(arr_le)
                        peak_sw, rms_sw, clip_sw = _metrics(arr_sw)

                        choose_sw = False
                        # 选择条件：更低的饱和占比优先；否则更合理的RMS范围且更低
                        if clip_sw + 1e-6 < clip_le * 0.5:
                            choose_sw = True
                        elif (500 <= rms_sw <= 9000) and (rms_sw + 1e-6 < rms_le * 0.8):
                            choose_sw = True

                        if choose_sw:
                            fixed_pcm_data = arr_sw.tobytes()
                            conn.pcm_endian = "be"
                            logger.bind(tag=TAG).warning(
                                f"自动检测到可能的大端PCM，已进行byteswap。rms_le={rms_le:.1f}, clip_le={clip_le:.3f} -> rms_sw={rms_sw:.1f}, clip_sw={clip_sw:.3f}"
                            )
                        else:
                            conn.pcm_endian = "le"
            except Exception as e:
                logger.bind(tag=TAG).warning(f"PCM端序处理失败(继续用原数据): {e}")

            # 打印基础幅度统计，辅助排查采样幅值/字节序问题
            try:
                from array import array
                samples = array('h')  # 本机字节序的有符号16位整型
                samples.frombytes(fixed_pcm_data)
                n = len(samples)
                if n > 0:
                    peak = max(max(samples), -min(samples))
                    # 简单RMS 与削波比
                    rms = (sum((int(s) * int(s) for s in samples)) / n) ** 0.5
                    clip_ratio = sum(1 for s in samples if abs(int(s)) >= 32760) / n
                    # 采样均值与前16个样本（用于观察端序/直流偏置/饱和）
                    mean_val = sum(int(s) for s in samples) / n
                    head_samples = list(int(x) for x in samples[:16])
                    logger.bind(tag=TAG).info(
                        f"PCM统计: bytes={len(fixed_pcm_data)}, samples={n}, peak={peak}, rms={rms:.1f}, mean={mean_val:.1f}, clip={clip_ratio:.3f}, head16={head_samples}"
                    )
            except Exception as e:
                logger.bind(tag=TAG).warning(f"PCM统计失败: {e}")

            # 供ASR使用的输入片段：
            # - PCM: 使用一个合并且对齐后的单片，以避免提供者侧拼接/对齐错误
            # - Opus: 保持原始片段（由提供者自行处理）
            if conn.audio_format == "pcm":
                asr_input_chunks = [fixed_pcm_data]
            else:
                asr_input_chunks = asr_audio_task
            
            # 预先准备WAV数据
            wav_data = None
            if conn.voiceprint_provider and fixed_pcm_data:
                wav_data = self._pcm_to_wav(fixed_pcm_data)
            
            # 定义ASR任务
            def run_asr():
                start_time = time.monotonic()
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        # 将连接的语言偏好传递给提供者
                        self.preferred_language = getattr(conn, "asr_language", None)
                        result = loop.run_until_complete(
                            self.speech_to_text(asr_input_chunks, conn.session_id, conn.audio_format)
                        )
                        end_time = time.monotonic()
                        logger.bind(tag=TAG).info(f"ASR耗时: {end_time - start_time:.3f}s")
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    end_time = time.monotonic()
                    logger.bind(tag=TAG).error(f"ASR失败: {e}")
                    return ("", None)
            
            # 定义声纹识别任务
            def run_voiceprint():
                if not wav_data:
                    return None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        # 使用连接的声纹识别提供者
                        result = loop.run_until_complete(
                            conn.voiceprint_provider.identify_speaker(wav_data, conn.session_id)
                        )
                        return result
                    finally:
                        loop.close()
                except Exception as e:
                    logger.bind(tag=TAG).error(f"声纹识别失败: {e}")
                    return None
            
            # 使用线程池执行器并行运行
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as thread_executor:
                asr_future = thread_executor.submit(run_asr)
                
                if conn.voiceprint_provider and wav_data:
                    voiceprint_future = thread_executor.submit(run_voiceprint)
                    
                    # 等待两个线程都完成
                    asr_result = asr_future.result(timeout=15)
                    voiceprint_result = voiceprint_future.result(timeout=15)
                    
                    results = {"asr": asr_result, "voiceprint": voiceprint_result}
                else:
                    asr_result = asr_future.result(timeout=15)
                    results = {"asr": asr_result, "voiceprint": None}
            
            
            # 处理结果
            raw_text, _ = results.get("asr", ("", None))
            speaker_name = results.get("voiceprint", None)
            
            # 记录识别结果
            if raw_text:
                logger.bind(tag=TAG).info(f"识别文本: {raw_text}")
            if speaker_name:
                logger.bind(tag=TAG).info(f"识别说话人: {speaker_name}")
            
            # 性能监控
            total_time = time.monotonic() - total_start_time
            logger.bind(tag=TAG).info(f"总处理耗时: {total_time:.3f}s")
            
            # 检查文本长度
            text_len, _ = remove_punctuation_and_length(raw_text)
            self.stop_ws_connection()
            
            if text_len > 0:
                # 构建包含说话人信息的JSON字符串
                enhanced_text = self._build_enhanced_text(raw_text, speaker_name)
                
                # 使用自定义模块进行上报
                await startToChat(conn, enhanced_text)
                enqueue_asr_report(conn, enhanced_text, asr_input_chunks)
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"处理语音停止失败: {e}")
            import traceback
            logger.bind(tag=TAG).debug(f"异常详情: {traceback.format_exc()}")

    def _build_enhanced_text(self, text: str, speaker_name: Optional[str]) -> str:
        """构建包含说话人信息的文本"""
        if speaker_name and speaker_name.strip():
            return json.dumps({
                "speaker": speaker_name,
                "content": text
            }, ensure_ascii=False)
        else:
            return text

    def _pcm_to_wav(self, pcm_data: bytes) -> bytes:
        """将PCM数据转换为WAV格式"""
        if len(pcm_data) == 0:
            logger.bind(tag=TAG).warning("PCM数据为空，无法转换WAV")
            return b""
        
        # 确保数据长度是偶数（16位音频）
        if len(pcm_data) % 2 != 0:
            pcm_data = pcm_data[:-1]
        
        # 创建WAV文件头
        wav_buffer = io.BytesIO()
        try:
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)      # 单声道
                wav_file.setsampwidth(2)      # 16位
                wav_file.setframerate(16000)  # 16kHz采样率
                wav_file.writeframes(pcm_data)
            
            wav_buffer.seek(0)
            wav_data = wav_buffer.read()
            
            return wav_data
        except Exception as e:
            logger.bind(tag=TAG).error(f"WAV转换失败: {e}")
            return b""

    def stop_ws_connection(self):
        pass

    def save_audio_to_file(self, pcm_data: List[bytes], session_id: str) -> str:
        """PCM数据保存为WAV文件"""
        module_name = __name__.split(".")[-1]
        file_name = f"asr_{module_name}_{session_id}_{uuid.uuid4()}.wav"
        file_path = os.path.join(self.output_dir, file_name)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 2 bytes = 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(pcm_data))

        return file_path

    @abstractmethod
    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, audio_format="opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        """将语音数据转换为文本"""
        pass

    @staticmethod
    def decode_opus(opus_data: List[bytes]) -> List[bytes]:
        """将Opus音频数据解码为PCM数据"""
        try:
            decoder = opuslib_next.Decoder(16000, 1)
            pcm_data = []
            buffer_size = 960  # 每次处理960个采样点 (60ms at 16kHz)
            
            for i, opus_packet in enumerate(opus_data):
                try:
                    if not opus_packet or len(opus_packet) == 0:
                        continue
                    
                    pcm_frame = decoder.decode(opus_packet, buffer_size)
                    if pcm_frame and len(pcm_frame) > 0:
                        pcm_data.append(pcm_frame)
                        
                except opuslib_next.OpusError as e:
                    logger.bind(tag=TAG).warning(f"Opus解码错误，跳过数据包 {i}: {e}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"音频处理错误，数据包 {i}: {e}")
            
            return pcm_data
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"音频解码过程发生错误: {e}")
            return []
