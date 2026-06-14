import time
import os
import sys
import io
import psutil
import numpy as np
from config.logger import setup_logging
from typing import Optional, Tuple, List
from core.providers.asr.base import ASRProviderBase
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
import shutil
from core.providers.asr.dto.dto import InterfaceType

TAG = __name__
logger = setup_logging()

MAX_RETRIES = 2
RETRY_DELAY = 1  # 重试延迟（秒）


# 捕获标准输出
class CaptureOutput:
    def __enter__(self):
        self._output = io.StringIO()
        self._original_stdout = sys.stdout
        sys.stdout = self._output

    def __exit__(self, exc_type, exc_value, traceback):
        sys.stdout = self._original_stdout
        self.output = self._output.getvalue()
        self._output.close()

        # 将捕获到的内容通过 logger 输出
        if self.output:
            logger.bind(tag=TAG).info(self.output.strip())


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        super().__init__()
        
        # 内存检测，要求大于2G
        min_mem_bytes = 2 * 1024 * 1024 * 1024
        total_mem = psutil.virtual_memory().total
        if total_mem < min_mem_bytes:
            logger.bind(tag=TAG).error(f"可用内存不足2G，当前仅有 {total_mem / (1024*1024):.2f} MB，可能无法启动FunASR")
        
        self.interface_type = InterfaceType.LOCAL
        self.model_dir = config.get("model_dir")
        self.model_hub = config.get("hub", "hf")  # 可为 'hf' 或 'ms'
        self.output_dir = config.get("output_dir")  # 修正配置键名
        self.delete_audio_file = delete_audio_file

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        # 记录当前加载的模型来源便于排查
        logger.bind(tag=TAG).info(
            f"加载FunASR模型: model_dir={self.model_dir}, hub={self.model_hub}"
        )
        with CaptureOutput():
            self.model = AutoModel(
                model=self.model_dir,
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
                hub=self.model_hub,
                # device="cuda:0",  # 启用GPU加速
            )

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str, audio_format="opus"
    ) -> Tuple[Optional[str], Optional[str]]:
        """语音转文本主处理逻辑"""
        file_path = None
        retry_count = 0

        while retry_count < MAX_RETRIES:
            try:
                # 合并所有opus数据包
                if audio_format == "pcm":
                    pcm_data = opus_data
                else:
                    pcm_data = self.decode_opus(opus_data)

                combined_pcm_data = b"".join(pcm_data)

                # 检查磁盘空间
                if not self.delete_audio_file:
                    free_space = shutil.disk_usage(self.output_dir).free
                    if free_space < len(combined_pcm_data) * 2:  # 预留2倍空间
                        raise OSError("磁盘空间不足")

                # 判断是否保存为WAV文件
                if self.delete_audio_file:
                    pass
                else:
                    file_path = self.save_audio_to_file(pcm_data, session_id)

                # 语音识别
                start_time = time.time()
                # 将int16 PCM转换为float32波形，范围[-1,1]，并显式提供采样率
                try:
                    pcm_i16 = np.frombuffer(combined_pcm_data, dtype=np.int16)
                    wav_f32 = (pcm_i16.astype(np.float32)) / 32768.0
                    # 基础幅度统计（以int16尺度计算便于对比日志）
                    peak_i16 = float(np.max(np.abs(pcm_i16))) if pcm_i16.size else 0.0
                    rms_i16 = float(np.sqrt(np.mean(np.square(pcm_i16.astype(np.float32))))) if pcm_i16.size else 0.0
                    clip_ratio = float(np.mean(np.abs(pcm_i16) >= 32760)) if pcm_i16.size else 0.0
                    logger.bind(tag=TAG).info(
                        f"ASR输入统计: peak={peak_i16:.1f}, rms={rms_i16:.1f}, clip={clip_ratio:.3f}"
                    )
                    # 1) 防削波预衰减：若峰值极高或剪裁比例>1%，先-6dB
                    if peak_i16 >= 32000 or clip_ratio > 0.01:
                        wav_f32 *= 0.5
                        logger.bind(tag=TAG).warning("检测到可能的削波，已对输入做-6dB预衰减")
                    # 2) 去直流偏置 + 轻量AGC：若电平偏低，放大到目标RMS（限制最大增益与峰值不超过0.95）
                    if wav_f32.size:
                        # 去直流
                        mean_dc = float(np.mean(wav_f32))
                        if abs(mean_dc) > 1e-5:
                            wav_f32 = wav_f32 - mean_dc
                            logger.bind(tag=TAG).debug(f"已去直流: {mean_dc:.6f}")
                        rms_f32 = float(np.sqrt(np.mean(np.square(wav_f32))))
                        peak_f32 = float(np.max(np.abs(wav_f32))) if wav_f32.size else 0.0
                        target_rms = 0.06  # ≈ int16 RMS 2000，对语音较稳妥
                        if rms_f32 > 0 and rms_f32 < target_rms * 0.8:
                            gain = min(target_rms / rms_f32, 6.0)  # 最多约+15.5dB
                            if peak_f32 > 1e-6:
                                gain = min(gain, 0.95 / peak_f32)  # 峰值限制
                            wav_f32 = np.clip(wav_f32 * gain, -1.0, 1.0)
                            logger.bind(tag=TAG).info(f"已应用AGC增益: x{gain:.2f}")
                    # 3) 预加重（高通近似）：暂时关闭，避免对FunASR特征提取造成干扰
                    # if wav_f32.size:
                    #     pre_emphasis = 0.97
                    #     wav_f32 = np.append(wav_f32[0], wav_f32[1:] - pre_emphasis * wav_f32[:-1])
                    # 打印处理后统计
                    if wav_f32.size:
                        peak_a = float(np.max(np.abs(wav_f32)))
                        rms_a = float(np.sqrt(np.mean(np.square(wav_f32))))
                        logger.bind(tag=TAG).info(
                            f"ASR输入(处理后)统计: peak={peak_a:.3f}, rms={rms_a:.3f}"
                        )
                    input_audio = wav_f32
                    logger.bind(tag=TAG).debug(
                        f"提供ASR输入: float32[{len(wav_f32)}] @16kHz"
                    )
                except Exception as _e:
                    # 回退：直接投喂原始字节（历史兼容），但不推荐
                    logger.bind(tag=TAG).warning(
                        f"转换float32失败，回退字节输入: {_e}"
                    )
                    input_audio = combined_pcm_data

                # 语言选择：优先使用连接传入的首选语言，否则自动+中文回退
                def _normalize_lang(lang: str) -> str:
                    if not lang:
                        return "auto"
                    l = lang.strip().lower()
                    # FunASR常用语言码：中文推荐使用"zh"（而非"zn"）
                    if l in ("zh", "zh-cn", "zh_cn", "cn", "zho", "zh-hans"):
                        return "zh"
                    # 其它常见值原样或按别名映射
                    alias = {
                        "en-us": "en",
                        "en_gb": "en",
                        "jp": "ja",
                        "kr": "ko",
                    }
                    return alias.get(l, l)

                if getattr(self, "preferred_language", None):
                    pref_lang_raw = self.preferred_language
                    pref_lang = _normalize_lang(pref_lang_raw)
                    logger.bind(tag=TAG).info(
                        f"使用首选ASR语言: {pref_lang_raw} -> {pref_lang}"
                    )
                    result = self.model.generate(
                        input=input_audio,
                        cache={},
                        language=pref_lang,
                        use_itn=True,
                        ban_emo_unk=True,
                        merge_vad=True,
                        merge_length_s=15,
                        batch_size_s=60,
                        fs=16000,
                    )
                    text = rich_transcription_postprocess(result[0]["text"])
                else:
                    # 首次：自动语言
                    result = self.model.generate(
                        input=input_audio,
                        cache={},
                        language="auto",
                        use_itn=True,
                        ban_emo_unk=True,
                        merge_vad=True,
                        merge_length_s=15,
                        batch_size_s=60,
                        fs=16000,
                    )
                    text = rich_transcription_postprocess(result[0]["text"])
                # 若疑似乱码（英/韩/符号占比较高而CJK比例过低）则回退一次中文
                try:
                    s = text
                    if s:
                        total = len(s)
                        cjk = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')
                        latin = sum(1 for ch in s if ('A' <= ch <= 'Z') or ('a' <= ch <= 'z'))
                        hangul = sum(1 for ch in s if '\uac00' <= ch <= '\ud7af')
                        ratio_cjk = cjk / max(1, total)
                        ratio_non_cjk = (latin + hangul) / max(1, total)
                        logger.bind(tag=TAG).debug(
                            f"文本字符占比统计: CJK={ratio_cjk:.3f}, Latin+Hangul={ratio_non_cjk:.3f} | 原文: {s}"
                        )
                        if ratio_cjk < 0.15 and ratio_non_cjk > 0.30:
                            logger.bind(tag=TAG).warning("检测到疑似乱码，回退强制中文识别一次")
                            result2 = self.model.generate(
                                input=input_audio,
                                cache={},
                                language="zh",
                                use_itn=True,
                                ban_emo_unk=True,
                                merge_vad=True,
                                merge_length_s=15,
                                batch_size_s=60,
                                fs=16000,
                            )
                            text2 = rich_transcription_postprocess(result2[0]["text"])
                            if text2 and text2 != text:
                                logger.bind(tag=TAG).info(f"强制中文回退后文本: {text2}")
                                text = text2
                except Exception as _e:
                    logger.bind(tag=TAG).debug(f"乱码回退判断失败: {_e}")
                logger.bind(tag=TAG).debug(
                    f"语音识别耗时: {time.time() - start_time:.3f}s | 结果: {text}"
                )

                return text, file_path

            except OSError as e:
                retry_count += 1
                if retry_count >= MAX_RETRIES:
                    logger.bind(tag=TAG).error(
                        f"语音识别失败（已重试{retry_count}次）: {e}", exc_info=True
                    )
                    return "", file_path
                logger.bind(tag=TAG).warning(
                    f"语音识别失败，正在重试（{retry_count}/{MAX_RETRIES}）: {e}"
                )
                time.sleep(RETRY_DELAY)

            except Exception as e:
                logger.bind(tag=TAG).error(f"语音识别失败: {e}", exc_info=True)
                return "", file_path

            finally:
                # 文件清理逻辑
                if self.delete_audio_file and file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.bind(tag=TAG).debug(f"已删除临时音频文件: {file_path}")
                    except Exception as e:
                        logger.bind(tag=TAG).error(
                            f"文件删除失败: {file_path} | 错误: {e}"
                        )
