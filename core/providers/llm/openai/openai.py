import httpx
import openai
from openai.types import CompletionUsage
from config.logger import setup_logging
from core.utils.util import check_model_key
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.model_name = config.get("model_name")
        self.api_key = config.get("api_key")
        if "base_url" in config:
            self.base_url = config.get("base_url")
        else:
            self.base_url = config.get("url")
        # 增加timeout的配置项，单位为秒
        timeout = config.get("timeout", 300)
        self.timeout = int(timeout) if timeout else 300

        param_defaults = {
            "max_tokens": (500, int),
            "temperature": (0.7, lambda x: round(float(x), 1)),
            "top_p": (1.0, lambda x: round(float(x), 1)),
            "frequency_penalty": (0, lambda x: round(float(x), 1)),
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

        logger.debug(
            f"意图识别参数初始化: {self.temperature}, {self.max_tokens}, {self.top_p}, {self.frequency_penalty}"
        )

        # 校验 API Key（防止中文占位符或非法值导致后续 HTTP 头编码为 ASCII 时抛错）
        self._key_error = None
        model_key_msg = check_model_key("LLM", self.api_key)
        if model_key_msg:
            # 记录错误并阻断客户端初始化，后续接口直接返回可读错误，避免 'ascii' codec 报错
            self._key_error = model_key_msg
            logger.bind(tag=TAG).error(model_key_msg)
            self.client = None
        else:
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )

    @staticmethod
    def _unicode_escape(obj):
        """Deep-convert all str fields to ASCII-safe by using unicode_escape.

        Some OpenAI-compatible backends or middleware incorrectly assume ASCII when
        serializing nested tool descriptions containing non-ASCII characters
        (e.g., Chinese). To improve compatibility, escape all strings in the
        tools payload while preserving data structure.
        """
        if isinstance(obj, str):
            # Convert any non-ascii to \uXXXX sequences; keep a pure ASCII string
            return obj.encode("unicode_escape").decode("ascii")
        if isinstance(obj, list):
            return [LLMProvider._unicode_escape(i) for i in obj]
        if isinstance(obj, dict):
            return {k: LLMProvider._unicode_escape(v) for k, v in obj.items()}
        return obj

    def response(self, session_id, dialogue, **kwargs):
        # 若 API Key 无效，立即返回明确错误，避免请求期 ASCII 头编码异常
        if getattr(self, "_key_error", None):
            err = self._key_error.encode("unicode_escape").decode("ascii")
            yield f"【LLM 配置错误: {err}】"
            return
        try:
            responses = self.client.chat.completions.create(
                model=self.model_name,
                messages=dialogue,
                stream=True,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                temperature=kwargs.get("temperature", self.temperature),
                top_p=kwargs.get("top_p", self.top_p),
                frequency_penalty=kwargs.get(
                    "frequency_penalty", self.frequency_penalty
                ),
            )

            is_active = True
            for chunk in responses:
                try:
                    # 检查是否存在有效的choice且content不为空
                    delta = (
                        chunk.choices[0].delta
                        if getattr(chunk, "choices", None)
                        else None
                    )
                    content = delta.content if hasattr(delta, "content") else ""
                except IndexError:
                    content = ""
                if content:
                    # 处理标签跨多个chunk的情况
                    if "<think>" in content:
                        is_active = False
                        content = content.split("<think>")[0]
                    if "</think>" in content:
                        is_active = True
                        content = content.split("</think>")[-1]
                    if is_active:
                        yield content

        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in response generation: {e}")

    def response_with_functions(self, session_id, dialogue, functions=None):
        # 若 API Key 无效，立即返回明确错误，避免请求期 ASCII 头编码异常
        if getattr(self, "_key_error", None):
            err = self._key_error.encode("unicode_escape").decode("ascii")
            yield f"【LLM 配置错误: {err}】", None
            return
        try:
            safe_tools = self._unicode_escape(functions) if functions else None
            # 使用非流式接口，规避部分兼容端在流式 + tools 下的 Unicode/编码问题
            resp = self.client.chat.completions.create(
                model=self.model_name, messages=dialogue, tools=safe_tools, stream=False
            )

            if resp and getattr(resp, "choices", None):
                choice = resp.choices[0]
                # 先输出正常文本，再输出工具调用（若有）
                content = getattr(choice.message, "content", None)
                if content:
                    yield content, None

                tool_calls = getattr(choice.message, "tool_calls", None)
                if tool_calls:
                    yield None, tool_calls

            # 打印用量信息
            usage_info = getattr(resp, "usage", None)
            if isinstance(usage_info, CompletionUsage):
                logger.bind(tag=TAG).info(
                    f"Token 消耗：输入 {getattr(usage_info, 'prompt_tokens', '未知')}，"
                    f"输出 {getattr(usage_info, 'completion_tokens', '未知')}，"
                    f"共计 {getattr(usage_info, 'total_tokens', '未知')}"
                )

        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in function call streaming: {e}")
            # 避免再次引入非 ASCII 字符到下游日志/接口
            safe_msg = str(e).encode("unicode_escape").decode("ascii")
            yield f"【OpenAI服务响应异常: {safe_msg}】", None
