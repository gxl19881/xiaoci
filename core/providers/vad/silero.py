import time
import numpy as np
import torch
import opuslib_next
from config.logger import setup_logging
from core.providers.vad.base import VADProviderBase

TAG = __name__
logger = setup_logging()


class VADProvider(VADProviderBase):
    def __init__(self, config):
        logger.bind(tag=TAG).info("SileroVAD", config)
        self.model, _ = torch.hub.load(
            repo_or_dir=config["model_dir"],
            source="local",
            model="silero_vad",
            force_reload=False,
        )
        # 配置
        self.sample_rate = 16000
        self.channels = 1

        # 仅在需要解码 Opus 时使用该解码器
        self.decoder = opuslib_next.Decoder(self.sample_rate, self.channels)

        # 处理空字符串的情况
        threshold = config.get("threshold", "0.5")
        threshold_low = config.get("threshold_low", "0.2")
        min_silence_duration_ms = config.get("min_silence_duration_ms", "1000")

        self.vad_threshold = float(threshold) if threshold else 0.5
        self.vad_threshold_low = float(threshold_low) if threshold_low else 0.2

        self.silence_threshold_ms = (
            int(min_silence_duration_ms) if min_silence_duration_ms else 1000
        )

        # 至少要多少帧才算有语音
        self.frame_window_threshold = 3

        # 每次送入模型的采样点数（与现有实现保持一致：512 采样点）
        self.chunk_samples = 512
        # 解码失败限频与自动回退
        self._last_decode_err_log_ms = 0
        self._decode_err_count = {}

    def _append_pcm_to_buffer(self, conn, pcm_bytes: bytes):
        """将PCM字节追加到连接缓冲，保证偶数字节对齐（int16小端）。"""
        try:
            if not pcm_bytes:
                return
            # 如果不是偶数字节，丢弃最后一个字节以保证int16对齐
            if len(pcm_bytes) % 2 == 1:
                pcm_bytes = pcm_bytes[:-1]
            conn.client_audio_buffer.extend(pcm_bytes)
        except Exception as e:
            logger.bind(tag=TAG).error(f"追加PCM到缓冲区失败: {e}")

    def is_vad(self, conn, audio_packet: bytes):
        """
        执行语音活动检测：
        - 若 conn.audio_format == "pcm"，直接按小端 int16 追加并处理；
        - 否则，按 Opus 数据解码后再处理。
        返回：当前窗口是否检测到语音。
        """
        try:
            # 根据音频格式处理输入数据
            fmt = getattr(conn, "audio_format", "opus")
            if fmt == "pcm":
                # 直接使用原始PCM小端字节
                self._append_pcm_to_buffer(conn, audio_packet)
            else:
                # 默认仍按 Opus 解码
                try:
                    pcm_frame = self.decoder.decode(audio_packet, 960)
                    conn.client_audio_buffer.extend(pcm_frame)
                    # 成功一次则清零该连接的错误计数
                    if conn.session_id in self._decode_err_count:
                        self._decode_err_count.pop(conn.session_id, None)
                except opuslib_next.OpusError as e:
                    # 统计连续解码失败次数
                    cnt = self._decode_err_count.get(conn.session_id, 0) + 1
                    self._decode_err_count[conn.session_id] = cnt

                    now_ms = int(time.time() * 1000)
                    if now_ms - self._last_decode_err_log_ms > 1000:
                        self._last_decode_err_log_ms = now_ms
                        logger.bind(tag=TAG).info(
                            f"Opus解码错误({cnt}次): {e} | fmt={getattr(conn, 'audio_format', 'opus')}"
                        )

                    # 若连续错误达到阈值，自动回退为 PCM 直通，避免刷屏
                    if cnt >= 5 and getattr(conn, "audio_format", "opus") != "pcm":
                        try:
                            conn.audio_format = "pcm"
                            logger.bind(tag=TAG).warning(
                                "检测到连续Opus解码失败，自动切换该连接audio_format为PCM；请确认设备上行是否为PCM。"
                            )
                        except Exception:
                            pass
                    return False

            # 处理缓冲区中的完整帧（每次处理 chunk_samples 采样点）
            client_have_voice = False
            need_bytes = self.chunk_samples * 2
            while len(conn.client_audio_buffer) >= need_bytes:
                # 取出一个chunk
                chunk = conn.client_audio_buffer[:need_bytes]
                conn.client_audio_buffer = conn.client_audio_buffer[need_bytes:]

                # 转为模型输入张量
                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                if audio_int16.size == 0:
                    continue
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                audio_tensor = torch.from_numpy(audio_float32)

                # VAD 推理
                with torch.no_grad():
                    speech_prob = self.model(audio_tensor, self.sample_rate).item()

                # 双阈值判断
                if speech_prob >= self.vad_threshold:
                    is_voice = True
                elif speech_prob <= self.vad_threshold_low:
                    is_voice = False
                else:
                    is_voice = conn.last_is_voice

                # 延续与窗口更新
                conn.last_is_voice = is_voice
                conn.client_voice_window.append(is_voice)
                client_have_voice = (
                    conn.client_voice_window.count(True) >= self.frame_window_threshold
                )

                # 语音结束判定（静默超过阈值）
                if conn.client_have_voice and not client_have_voice:
                    stop_duration = time.time() * 1000 - conn.last_voice_activity_time
                    if stop_duration >= self.silence_threshold_ms:
                        conn.client_voice_stop = True
                if client_have_voice:
                    conn.client_have_voice = True
                    conn.last_voice_activity_time = time.time() * 1000

            return client_have_voice
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio packet: {e}")
            return False
