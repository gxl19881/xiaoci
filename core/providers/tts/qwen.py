import uuid
import json
import asyncio
import aiohttp
from core.providers.tts.base import TTSProviderBase
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_key = config.get("api_key")
        self.model = config.get("model", "cosyvoice-v1")
        self.voice = config.get("voice", "longwan")
        
        # 强制使用 wav 格式以保证兼容性 (包含 Header，避免 ffmpeg 解析 raw pcm 失败)
        # 无论 config.yaml 中配置的是 pcm 还是 mp3，这里均请求 wav。
        # Base/ffmpeg 后续会将其统一转换为设备需要的格式（通常是 opus 或 pcm）。
        self.format = "wav" # strict override
        
        self.sample_rate = config.get("sample_rate", 22050)
        self.volume = config.get("volume", 50)
        self.rate = config.get("rate", 1.0)
        self.pitch = config.get("pitch", 1.0)
        
        # CosyVoice 仅支持 WebSocket 接口
        self.ws_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        # WebSocket 握手头
        self.headers = {
            "Authorization": f"Bearer {self.api_key}"
            # "Content-Type" usually not strictly required for WS handshake but let's keep it minimal
        }

    async def text_to_speak(self, text, output_file):
        if not text:
            return None

        task_id = uuid.uuid4().hex
        
        # 构造 CosyVoice 标准 WebSocket 请求
        payload = {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex"
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
                    "pitch": self.pitch
                },
                "input": {
                    "text": text
                }
            }
        }
        
        # 结束帧 (必须发送，否则服务端会一直等待后续流式输入，导致 hang 住)
        finish_payload = {
             "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {}
            }
        }

        audio_data = bytearray()
        
        try:
            logger.bind(tag=TAG).info(f"QwenTTS WS Start: {self.model} / {self.voice}")
            
            async with aiohttp.ClientSession() as session:
                # 增加超时设置，防止无限等待
                async with session.ws_connect(self.ws_url, headers=self.headers, timeout=10) as ws:
                    # 发送任务指令
                    await ws.send_str(json.dumps(payload))
                    # 立即发送结束指令，告知非流式输入已完成
                    await ws.send_str(json.dumps(finish_payload))
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            # 处理 JSON 控制消息
                            try:
                                msg_json = json.loads(msg.data)
                                header = msg_json.get("header", {})
                                event = header.get("event")
                                
                                if event == "task-finished":
                                    logger.bind(tag=TAG).info(f"QwenTTS Task Finished. Total bytes: {len(audio_data)}")
                                    break
                                elif event == "task-failed":
                                    err_msg = header.get("error_message", "Unknown Error")
                                    logger.bind(tag=TAG).error(f"QwenTTS Task Failed: {err_msg}")
                                    # 关闭连接并抛出异常
                                    await ws.close()
                                    raise Exception(f"DashScope WS Error: {err_msg}")
                            except json.JSONDecodeError:
                                pass
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            # 处理音频二进制数据
                            audio_data.extend(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.bind(tag=TAG).error(f"QwenTTS WS Connection Error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            logger.bind(tag=TAG).warn("QwenTTS WS Connection Closed")
                            break
            
            if len(audio_data) == 0:
                logger.bind(tag=TAG).warn("QwenTTS received 0 bytes of audio")
                return None
                
            # 保存到文件
            if output_file:
                with open(output_file, "wb") as f:
                    f.write(audio_data)
                return output_file
            else:
                return audio_data
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"TTS generation failed: {e}")
            raise Exception(f"{__name__} error: {e}")
            
            if resp.status_code == 200:
                # 检查是否为音频流
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                     try:
                         data = resp.json()
                         if "output" in data and "url" in data["output"]:
                             audio_url = data["output"]["url"]
                             audio_resp = requests.get(audio_url)
                             audio_bytes = audio_resp.content
                             if output_file:
                                 with open(output_file, "wb") as f:
                                     f.write(audio_bytes)
                             else:
                                 return audio_bytes
                         elif "code" in data:
                             # 尝试捕获特定错误，比如 "InvalidParameter"
                             raise Exception(f"DashScope Error: {data}")
                         else:
                             raise Exception(f"Unknown JSON response: {data}")
                     except Exception as e:
                         # 如果无法解析JSON，可能是二进制（尽管 Content-Type 撒谎）
                         # 或者就是纯文本错误
                         if len(resp.content) > 100 and b"RIFF" in resp.content[:20]:
                              # WAV header check
                              if output_file:
                                  with open(output_file, "wb") as f:
                                      f.write(resp.content)
                              else:
                                  return resp.content
                         raise Exception(f"DashScope response invalid: {resp.text}")
                else:
                    audio_bytes = resp.content
                    if output_file:
                        with open(output_file, "wb") as file_to_save:
                            file_to_save.write(audio_bytes)
                    else:
                        return audio_bytes
            else:
                 # 尝试解析错误信息
                err_msg = resp.text
                try:
                    err_json = resp.json()
                    if "message" in err_json:
                        err_msg = err_json["message"]
                    elif "code" in err_json:
                         err_msg = f"{err_json['code']}: {err_json.get('message','')}"
                except:
                    pass
                raise Exception(
                    f"{__name__} status_code: {resp.status_code} error: {err_msg}"
                )
        except Exception as e:
            logger.bind(tag=TAG).error(f"TTS generation failed: {e}")
            raise Exception(f"{__name__} error: {e}")
