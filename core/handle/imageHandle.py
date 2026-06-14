"""
图片消息处理模块
用于处理图片生成和发送到ESP32设备的相关功能
同时提供将生成的图片保存到本地磁盘的工具函数
"""

import json
import asyncio
import os
import re
import base64
from datetime import datetime
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

async def send_image_to_device(conn, image_data, description="Generated Image"):
    """
    发送图片数据到ESP32设备
    
    Args:
        conn: WebSocket连接对象
        image_data: Base64编码的图片数据
        description: 图片描述
    """
    try:
        # 构造图片消息（固件期望的类型为 display_image）
        image_message = {
            "type": "display_image",
            "data": {
                "image": image_data,
                "description": description,
                "format": "base64",
                "timestamp": int(asyncio.get_event_loop().time())
            }
        }
        
        # 发送到ESP32设备
        if hasattr(conn, 'websocket') and conn.websocket:
            await conn.websocket.send(json.dumps(image_message, ensure_ascii=False))
            logger.bind(tag=TAG).info(f"图片已发送到ESP32设备: {description}")
            return True
        else:
            logger.bind(tag=TAG).error("WebSocket连接不可用")
            return False
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"发送图片到ESP32失败: {e}")
        return False

async def handle_image_generation_request(conn, prompt, style="realistic", size="512x512"):
    """
    处理图片生成请求
    
    Args:
        conn: WebSocket连接对象
        prompt: 图片生成提示词
        style: 图片风格
        size: 图片尺寸
    """
    try:
        # 发送状态更新到设备
        status_message = {
            "type": "image_generation_status",
            "data": {
                "status": "generating",
                "prompt": prompt,
                "message": "正在生成图片，请稍候..."
            }
        }
        
        if hasattr(conn, 'websocket') and conn.websocket:
            await conn.websocket.send(json.dumps(status_message, ensure_ascii=False))
            
        logger.bind(tag=TAG).info(f"开始处理图片生成请求: {prompt}")
        
    except Exception as e:
        logger.bind(tag=TAG).error(f"处理图片生成请求失败: {e}")

async def send_image_generation_status(conn, status, message, prompt=None, extra_data=None):
    """
    发送图片生成状态更新
    
    Args:
        conn: WebSocket连接对象
        status: 状态 (generating, success, error)
        message: 状态消息
        prompt: 原始提示词
        extra_data: 额外的字段 (如 progress)
    """
    try:
        data_payload = {
            "status": status,
            "message": message,
            "prompt": prompt,
            "timestamp": int(asyncio.get_event_loop().time())
        }
        if extra_data and isinstance(extra_data, dict):
            data_payload.update(extra_data)

        status_message = {
            "type": "image_generation_status",
            "data": data_payload
        }
        
        if hasattr(conn, 'websocket') and conn.websocket:
            await conn.websocket.send(json.dumps(status_message, ensure_ascii=False))
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"发送状态更新失败: {e}")

def compress_image_for_esp32(image_base64, target_width=240, target_height=240):
    """
    为ESP32设备压缩图片
    很多ESP32设备屏幕较小，需要压缩图片以适应显示和传输
    
    Args:
        image_base64: Base64编码的原始图片
        target_width: 目标宽度
        target_height: 目标高度
        
    Returns:
        压缩后的Base64图片数据
    """
    try:
        import importlib, io
        Image = importlib.import_module('PIL.Image')
        
        # 解码Base64图片
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # 调整尺寸
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # 转换为RGB模式（ESP32通常支持RGB565）
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # 重新编码为Base64
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        compressed_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        logger.bind(tag=TAG).info(f"图片已压缩至 {target_width}x{target_height}")
        return compressed_base64
        
    except Exception as e:
        logger.bind(tag=TAG).error(f"图片压缩失败: {e}")
        return image_base64  # 失败时返回原图


def _sanitize_filename(text: str, max_len: int = 32) -> str:
    """将提示词转换为安全的文件名片段。保留中英文、数字与部分符号，截断到 max_len。"""
    try:
        # 替换空白为下划线
        text = re.sub(r"\s+", "_", text.strip())
        # 仅保留常见安全字符（中英文、数字、下划线、连字符）
        text = re.sub(r"[^\w\-\u4e00-\u9fff]", "", text)
        if len(text) > max_len:
            text = text[:max_len]
        return text or "img"
    except Exception:
        return "img"


def save_image_to_disk(image_base64: str,
                       prompt: str,
                       device_id: str | None = None,
                       save_root: str = "data/generated_images",
                       prefix: str = "compressed") -> str | None:
    """
    将 Base64 图片保存为本地 JPEG 文件。

    Args:
        image_base64: JPEG Base64 字符串
        prompt: 原始提示词，用于文件名
        device_id: 设备ID，可为空
        save_root: 保存根目录（相对服务工作目录）
        prefix: 文件前缀（compressed/original等）

    Returns:
        保存后的绝对路径。如果失败返回 None。
    """
    try:
        # 计算保存目录：data/generated_images/YYYYMMDD
        day = datetime.now().strftime("%Y%m%d")
        root = save_root
        # 兼容容器内工作目录，若传入的是相对路径，这里保持相对即可（由应用工作目录决定）
        out_dir = os.path.join(root, day)
        os.makedirs(out_dir, exist_ok=True)

        ts = datetime.now().strftime("%H%M%S")
        dev = (device_id or "nodev").replace(":", "-")
        slug = _sanitize_filename(prompt, 24)
        filename = f"{prefix}_{ts}_{dev}_{slug}.jpg"
        out_path = os.path.join(out_dir, filename)

        with open(out_path, "wb") as f:
            f.write(base64.b64decode(image_base64))

        abs_path = os.path.abspath(out_path)
        logger.bind(tag=TAG).info(f"图片已保存: {abs_path}")
        return abs_path
    except Exception as e:
        logger.bind(tag=TAG).warning(f"保存图片到本地失败: {e}")
        return None