import json
import io
import wave
import uuid
from aiohttp import web
from typing import Optional, Tuple
from config.logger import setup_logging
from core.utils.modules_initialize import initialize_asr


TAG = __name__


class AsrHTTPHandler:
    """简单的HTTP ASR转写接口

    接收浏览器上传的 WAV (PCM 16-bit mono 16kHz) 音频，调用已选ASR模块进行转写。
    路径示例：POST /web/asr/transcribe  multipart/form-data 字段名: audio
    返回: { success: bool, text?: str, message?: str }
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 预初始化一次ASR实例，避免每次请求重复加载模型
        try:
            self.asr = initialize_asr(config)
            self.logger.bind(tag=TAG).info("ASR HTTP Handler 初始化完成")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"ASR初始化失败: {e}")
            self.asr = None

    def _add_cors_headers(self, response: web.StreamResponse):
        response.headers["Access-Control-Allow-Headers"] = (
            "client-id, content-type, device-id, authorization"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"

    async def handle_options(self, request: web.Request):
        resp = web.Response(status=204)
        self._add_cors_headers(resp)
        return resp

    async def handle_post(self, request: web.Request) -> web.Response:
        response: Optional[web.Response] = None
        try:
            if not self.asr:
                raise RuntimeError("ASR模块未初始化")

            # 解析 multipart/form-data
            reader = await request.multipart()
            wav_bytes: Optional[bytes] = None

            while True:
                field = await reader.next()
                if field is None:
                    break
                name = getattr(field, "name", None)
                filename = getattr(field, "filename", None)
                if name == "audio" or filename:
                    wav_bytes = await field.read()
                    break

            if not wav_bytes:
                raise ValueError("缺少音频文件")
            if len(wav_bytes) < 44:
                raise ValueError("音频数据异常")

            # 读取WAV头并校验参数
            with io.BytesIO(wav_bytes) as bio:
                try:
                    with wave.open(bio, "rb") as wf:
                        n_channels = wf.getnchannels()
                        sampwidth = wf.getsampwidth()
                        framerate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                except wave.Error:
                    raise ValueError("仅支持WAV(PCM)音频，请检查上传格式")

            if n_channels != 1 or sampwidth != 2 or framerate != 16000:
                raise ValueError(
                    f"不支持的音频参数，期望单声道/16-bit/16kHz，实际: channels={n_channels}, sampwidth={sampwidth}, rate={framerate}"
                )

            # 调用ASR，使用 PCM 模式
            session_id = f"webui-{uuid.uuid4().hex[:8]}"
            text, _ = await self.asr.speech_to_text([frames], session_id, audio_format="pcm")

            if not text:
                result = {"success": False, "message": "未识别到有效文本"}
            else:
                result = {"success": True, "text": text}

            response = web.json_response(
                result,
                dumps=lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":")),
            )
        except ValueError as e:
            self.logger.bind(tag=TAG).warning(f"ASR请求无效: {e}")
            response = web.json_response(
                {"success": False, "message": str(e)},
                dumps=lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"ASR处理失败: {e}")
            response = web.json_response(
                {"success": False, "message": "服务器内部错误"},
                dumps=lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":")),
            )
        finally:
            if response:
                self._add_cors_headers(response)
            return response
