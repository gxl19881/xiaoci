import openai
import json
import os
import time
from config.logger import setup_logging
from core.utils.util import check_model_key
from core.providers.vllm.base import VLLMProviderBase

TAG = __name__
logger = setup_logging()


class VLLMProvider(VLLMProviderBase):
    def __init__(self, config):
        self.model_name = config.get("model_name")

        # 允许使用环境变量覆盖配置文件中的 api_key，避免把真实密钥写入仓库
        # 支持多种环境变量名称，便于不同服务商的部署：
        # - VLLM_API_KEY（推荐通用名）
        # - ARK_API_KEY（火山方舟 Doubao）
        # - OPENAI_API_KEY（兼容默认）
        # - ZHIPU_API_KEY（兼容智谱）
        env_key = (
            os.getenv("VLLM_API_KEY", "").strip()
            or os.getenv("ARK_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
            or os.getenv("ZHIPU_API_KEY", "").strip()
        )
        file_key = (config.get("api_key") or "").strip()
        self.api_key = env_key or file_key

        if "base_url" in config:
            self.base_url = config.get("base_url")
        else:
            self.base_url = config.get("url")

        param_defaults = {
            "max_tokens": (500, int),
            "temperature": (0.7, lambda x: round(float(x), 1)),
            "top_p": (1.0, lambda x: round(float(x), 1)),
        }

        for param, (default, converter) in param_defaults.items():
            value = config.get(param)
            try:
                setattr(
                    self,
                    param,
                    converter(value) if value not in (None, "") else default,
                )
            except (ValueError, TypeError):
                setattr(self, param, default)

        model_key_msg = check_model_key("VLLM", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)

        if not self.api_key or self.api_key == "你的api_key":
            # 给出更友好的提示，指导使用环境变量
            logger.bind(tag=TAG).warning(
                "VLLM api_key 未正确配置。请在部署环境设置环境变量 VLLM_API_KEY=你的真实密钥，或在 config.yaml 中填写 api_key (不要提交到公共仓库)。"
            )

        # 请求超时（秒）：支持从模块配置或环境变量覆盖
        # - 配置键：timeout_seconds
        # - 环境变量优先级：VLLM_TIMEOUT_SECONDS > VISION_TIMEOUT_SECONDS > OPENAI_TIMEOUT_SECONDS
        def _as_int(v, default):
            try:
                return int(float(v))
            except Exception:
                return default

        self.timeout_seconds = _as_int(
            config.get("timeout_seconds"),
            _as_int(
                os.getenv("VLLM_TIMEOUT_SECONDS")
                or os.getenv("VISION_TIMEOUT_SECONDS")
                or os.getenv("OPENAI_TIMEOUT_SECONDS"),
                300,  # 默认将视觉请求超时提升到300s，适配超大模型
            ),
        )

        # 简单重试次数（针对瞬时连接错误/偶发超时），默认1次；可通过配置 retries 或环境变量 VLLM_RETRIES 调整
        self.retries = _as_int(config.get("retries") or os.getenv("VLLM_RETRIES"), 1)

        # 初始化 OpenAI 兼容客户端，设置超时避免长期阻塞
        try:
            self.client = openai.OpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds
            )
        except TypeError:
            # 旧版SDK不支持timeout参数，回落
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

    def response(self, question, base64_image):
        question = question + "(请使用中文回复，绝对不要使用任何Emoji表情符号，也不要使用Markdown格式)"
        try:
            start_ts = time.time()
            # 兼容：若入参已是完整的 data URL，则直接使用；否则按 JPEG 组装
            try:
                if isinstance(base64_image, str) and base64_image.strip().startswith("data:"):
                    image_data_url = base64_image
                else:
                    image_data_url = f"data:image/jpeg;base64,{base64_image}"
            except Exception:
                image_data_url = f"data:image/jpeg;base64,{base64_image}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            },
                        },
                    ],
                }
            ]

            # 若SDK支持 with_options，可在此覆盖超时
            client_with_options = getattr(self.client, "with_options", None)
            if callable(client_with_options):
                oc = self.client.with_options(timeout=self.timeout_seconds)
            else:
                oc = self.client

            last_err = None
            attempts = max(1, int(self.retries) + 1)  # 首次 + 重试次数
            for i in range(attempts):
                try:
                    response = oc.chat.completions.create(
                        model=self.model_name, messages=messages, stream=False
                    )
                    elapsed = time.time() - start_ts
                    logger.bind(tag=TAG).info(
                        f"VLLM请求完成 model={self.model_name}, elapsed={elapsed:.2f}s, attempt={i+1}/{attempts}, timeout={self.timeout_seconds}s"
                    )
                    return response.choices[0].message.content
                except Exception as ie:
                    # 仅对瞬时连接错误/超时进行有限重试
                    last_err = ie
                    try:
                        em = str(ie)
                    except Exception:
                        em = ""
                    transient = (
                        "Connection error" in em
                        or "timeout" in em.lower()
                        or "timed out" in em.lower()
                        or "ReadTimeout" in em
                    )
                    if i < attempts - 1 and transient:
                        # 轻微退避后重试
                        try:
                            time.sleep(1.2)
                        except Exception:
                            pass
                        continue
                    raise

        except Exception as e:
            # 统一转义异常信息，避免在部分日志环境中触发ASCII编码问题
            try:
                err_msg = str(e).encode("unicode_escape").decode("ascii")
            except Exception:
                err_msg = "<error message encoding failed>"
            logger.bind(tag=TAG).error(f"Error in response generation: {err_msg}")
            raise
