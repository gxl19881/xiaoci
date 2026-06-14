import os
import base64
from typing import Dict, Any

from config.logger import setup_logging
from core.providers.vllm.base import VLLMProviderBase

TAG = __name__
logger = setup_logging()


class VLLMProvider(VLLMProviderBase):
    """
    视觉提供者：百度 OCR

    契约（与 VLLMProviderBase 保持一致）：
    - 输入：
      - question: str 文本问题（本提供者主要做 OCR，通常忽略或用于日志）
      - base64_image: str 图片的 base64 编码（不含 data:image/*;base64, 前缀）
    - 输出：
      - str 识别出的文本（按行拼接）

    依赖：baidu-aip
    - 环境变量优先覆盖配置：
      - BAIDU_OCR_APP_ID
      - BAIDU_OCR_API_KEY
      - BAIDU_OCR_SECRET_KEY
    - 配置示例（放在 data/.config.yaml 的 VLLM 下）：
      VLLM:
        BaiduOCR:
          type: baidu_ocr
          app_id: "你的AppID"
          api_key: "你的APIKey"
          secret_key: "你的SecretKey"
          mode: accurate_basic   # 可选：general_basic | accurate_basic
          language_type: CHN_ENG
          detect_direction: true
          probability: false
    """

    def __init__(self, config: Dict[str, Any]):
        try:
            from aip import AipOcr  # type: ignore
        except Exception as e:
            logger.bind(tag=TAG).error(
                "未安装 baidu-aip，请在服务器环境中安装依赖 baidu-aip：pip install baidu-aip"
            )
            raise

        # 读取密钥（环境变量优先）
        app_id = (os.getenv("BAIDU_OCR_APP_ID") or config.get("app_id") or "").strip()
        api_key = (os.getenv("BAIDU_OCR_API_KEY") or config.get("api_key") or "").strip()
        secret_key = (os.getenv("BAIDU_OCR_SECRET_KEY") or config.get("secret_key") or "").strip()

        if not app_id or not api_key or not secret_key:
            logger.bind(tag=TAG).warning(
                "Baidu OCR 凭据未配置完整：请设置 BAIDU_OCR_APP_ID/BAIDU_OCR_API_KEY/BAIDU_OCR_SECRET_KEY 环境变量，或在配置中提供 app_id/api_key/secret_key"
            )

        # 初始化 OCR 客户端
        self.client = AipOcr(app_id, api_key, secret_key)

        # 配置网络超时（毫秒）：连接超时与读取超时，避免长时间阻塞
        # 可通过配置项覆盖，默认：连接3s，读取10s
        conn_timeout_ms = int(config.get("connection_timeout_ms", 3000) or 3000)
        sock_timeout_ms = int(config.get("socket_timeout_ms", 10000) or 10000)
        try:
            # baidu-aip 提供的超时配置 API
            self.client.setConnectionTimeoutInMillis(conn_timeout_ms)
            self.client.setSocketTimeoutInMillis(sock_timeout_ms)
            logger.bind(tag=TAG).info(
                f"Baidu OCR 超时设置: connect={conn_timeout_ms}ms, socket={sock_timeout_ms}ms"
            )
        except Exception as _:
            # 兼容旧版SDK无上述方法的情况，不中断，仅记录
            logger.bind(tag=TAG).warning("当前 baidu-aip SDK 不支持超时设置API，可能存在长时间阻塞风险")

        # 参数与模式
        self.mode = (config.get("mode") or "general_basic").strip().lower()
        # 兼容大小写与不同写法
        if self.mode in ("general", "generalbasic", "general_basic"):
            self.mode = "general_basic"
        elif self.mode in ("accurate", "accuratebasic", "accurate_basic"):
            self.mode = "accurate_basic"
        else:
            self.mode = "general_basic"

        # 默认选项
        self.options: Dict[str, Any] = {
            "language_type": config.get("language_type", "CHN_ENG"),  # 中英混合
            "detect_direction": bool(config.get("detect_direction", True)),
            "probability": bool(config.get("probability", False)),
        }

    def response(self, question: str, base64_image: str) -> str:
        # 将 base64 字符串解码为二进制图像数据
        try:
            # 支持可能带有 data:image/...;base64, 前缀的情况
            if "," in base64_image:
                base64_image = base64_image.split(",", 1)[-1]
            image_bytes = base64.b64decode(base64_image)
        except Exception:
            raise ValueError("图片Base64解码失败，请确认上传的内容是否为有效的Base64图片数据")

        # 选择调用的 OCR 方法
        method_name = "basicAccurate" if self.mode == "accurate_basic" else "basicGeneral"
        ocr_func = getattr(self.client, method_name, None)
        if not callable(ocr_func):
            # 理论上 baidu-aip 都存在以上方法，兜底到 basicGeneral
            ocr_func = getattr(self.client, "basicGeneral")

        logger.bind(tag=TAG).info(
            f"Baidu OCR 开始识别，mode={self.mode}, question_len={len(question) if question else 0}"
        )

        result = ocr_func(image_bytes, self.options)

        # 错误处理
        if isinstance(result, dict) and result.get("error_code") is not None:
            err_code = result.get("error_code")
            err_msg = result.get("error_msg") or "Baidu OCR 返回错误"
            raise RuntimeError(f"Baidu OCR 调用失败: {err_code} - {err_msg}")

        words_list = []
        try:
            for item in result.get("words_result", []) or []:
                words = item.get("words")
                if isinstance(words, str) and words.strip():
                    words_list.append(words.strip())
        except Exception:
            # 结构不符合预期时，尽量序列化返回值以便观察
            return str(result)

        text = "\n".join(words_list).strip()
        if not text:
            # 若识别为空，返回一个提示，便于前端/设备侧看到明确信息
            text = "(未识别到文本内容)"
        return text
