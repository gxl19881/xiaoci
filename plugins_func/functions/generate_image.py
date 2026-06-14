import requests
import base64
import json
import asyncio
import time
import hashlib
import hmac
from urllib.parse import quote
import uuid
import os
from datetime import datetime
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
# 兼容不同目录/命名的导入方式，避免在不同镜像或运行路径下导入失败
try:
    from core.handle.imageHandle import (
        send_image_to_device,
        send_image_generation_status,
        compress_image_for_esp32,
        save_image_to_disk,
    )
except ModuleNotFoundError:
    try:
        # 有的环境采用下划线命名
        from core.handle.image_handle import (
            send_image_to_device,
            send_image_generation_status,
            compress_image_for_esp32,
            save_image_to_disk,
        )
    except ModuleNotFoundError as e:
        # 延迟报错到实际调用时，便于服务启动并在函数调用处给出清晰错误
        send_image_to_device = None
        send_image_generation_status = None
        compress_image_for_esp32 = None
        _import_error = e

        # 提供兜底实现，避免容器镜像未包含 imageHandle 时功能完全不可用
        # 兜底1：状态更新通过 conn.websocket 直接发送
        async def _fallback_send_image_generation_status(conn, status, message, prompt=None):
            try:
                payload = {
                    "type": "image_generation_status",
                    "data": {
                        "status": status,
                        "message": message,
                        "prompt": prompt,
                        "timestamp": int(asyncio.get_event_loop().time()),
                    },
                }
                if hasattr(conn, "websocket") and conn.websocket:
                    await conn.websocket.send(json.dumps(payload, ensure_ascii=False))
                    setup_logging().bind(tag=__name__).info(f"[fallback][status]-> {status}: {message} | prompt={prompt}")
            except Exception as _e:
                setup_logging().bind(tag=__name__).error(f"兜底状态发送失败: {_e}")

        # 兜底2：发送图片到设备（直接经由 WebSocket，下行 data.image 为 base64）
        async def _fallback_send_image_to_device(conn, image_data, description="Generated Image"):
            try:
                msg = {
                    "type": "image_display",
                    "data": {
                        "image": image_data,
                        "description": description,
                        "format": "base64",
                        "timestamp": int(asyncio.get_event_loop().time()),
                    },
                }
                if hasattr(conn, "websocket") and conn.websocket:
                    await conn.websocket.send(json.dumps(msg, ensure_ascii=False))
                    setup_logging().bind(tag=__name__).info(f"[fallback] 已下发图片到设备: {description}")
                    return True
                return False
            except Exception as _e:
                setup_logging().bind(tag=__name__).error(f"兜底图片发送失败: {_e}")
                return False

        # 兜底3：图片压缩（有 PIL 则压缩，否则回退原图）
        def _fallback_compress_image_for_esp32(image_base64, target_width=240, target_height=240):
            try:
                import base64 as _b64
                try:
                    from PIL import Image  # 可能不存在
                    import io
                    raw = _b64.b64decode(image_base64)
                    img = Image.open(io.BytesIO(raw))
                    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    return _b64.b64encode(buf.getvalue()).decode()
                except Exception:
                    # 无 PIL 时直接返回原图
                    return image_base64
            except Exception as _e:
                # 无法压缩时返回原图
                setup_logging().bind(tag=__name__).warning(f"兜底压缩失败，使用原图: {_e}")
                return image_base64

        # 将兜底实现赋给缺失的方法名，供后续调用
        send_image_generation_status = _fallback_send_image_generation_status
        send_image_to_device = _fallback_send_image_to_device
        compress_image_for_esp32 = _fallback_compress_image_for_esp32

        # 兜底：保存到磁盘功能（若缺失则提供简单实现写入 data/generated_images）
        def save_image_to_disk(image_base64: str, prompt: str, device_id: str | None = None,
                               save_root: str = "data/generated_images", prefix: str = "compressed"):
            try:
                import os, base64
                from datetime import datetime
                day = datetime.now().strftime("%Y%m%d")
                out_dir = os.path.join(save_root, day)
                os.makedirs(out_dir, exist_ok=True)
                ts = datetime.now().strftime("%H%M%S")
                dev = (device_id or "nodev").replace(":", "-")
                fn = f"{prefix}_{ts}_{dev}.jpg"
                out_path = os.path.join(out_dir, fn)
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(image_base64))
                setup_logging().bind(tag=__name__).info(f"[fallback] 图片已保存: {os.path.abspath(out_path)}")
                return os.path.abspath(out_path)
            except Exception as _e:
                setup_logging().bind(tag=__name__).warning(f"[fallback] 保存图片失败: {_e}")
                return None

TAG = __name__
logger = setup_logging()

GENERATE_IMAGE_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "生成图片并发送到ESP32设备显示。用户可以描述想要生成的图片内容，"
            "比如'生成一张猫咪的图片'。如果用户想要在上一张图片基础上进行修改（例如'把猫变成白色的'，'背景换成森林'），"
            "请务必在prompt参数中合并之前的描述和新的修改细节，形成一个全新的完整画面描述（例如'一张在森林背景下的白色猫咪'），"
            "不要只发增量修改的内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片描述提示词，用于生成图片的详细描述",
                },
                "style": {
                    "type": "string",
                    "description": "图片风格，如: realistic, cartoon, anime, abstract等，默认为realistic",
                    "default": "realistic"
                },
                "size": {
                    "type": "string", 
                    "description": "图片尺寸，如: 512x512, 1024x1024等，默认512x512",
                    "default": "512x512"
                }
            },
            "required": ["prompt"],
        },
    },
}



def _now_ms():
    return int(time.time() * 1000)


def _short_b64_info(b64str):
    try:
        return f"len={len(b64str)} head={b64str[:16]}..."
    except Exception:
        return "len=?"


def generate_image_dalle(prompt, api_key, style="realistic", size="512x512"):
    """使用DALL-E生成图片"""
    try:
        t0 = _now_ms()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json"
        }
        
        logger.bind(tag=TAG).info(f"[dalle] request -> size={size} style={style}")
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json=data,
            timeout=30
        )
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[dalle] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            b64 = result['data'][0]['b64_json']
            logger.bind(tag=TAG).info(f"[dalle] ok {_short_b64_info(b64)}")
            return b64
        else:
            logger.bind(tag=TAG).error(f"DALL-E API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"DALL-E生成图片失败: {e}")
        return None

def generate_image_stability(prompt, api_key, style="realistic", size="512x512"):
    """使用Stability AI生成图片"""
    try:
        t0 = _now_ms()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 将尺寸转换为宽高
        width, height = map(int, size.split('x'))
        
        data = {
            "text_prompts": [{"text": prompt}],
            "cfg_scale": 7,
            "width": width,
            "height": height,
            "steps": 20,
            "samples": 1
        }
        
        logger.bind(tag=TAG).info(f"[stability] request -> size={width}x{height} style={style}")
        response = requests.post(
            "https://api.stability.ai/v1/generation/stable-diffusion-v1-6/text-to-image",
            headers=headers,
            json=data,
            timeout=60
        )
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[stability] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            b64 = result['artifacts'][0]['base64']
            logger.bind(tag=TAG).info(f"[stability] ok {_short_b64_info(b64)}")
            return b64
        else:
            logger.bind(tag=TAG).error(f"Stability AI API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"Stability AI生成图片失败: {e}")
        return None

def generate_image_local_sd(prompt, api_url, style="realistic", size="512x512"):
    """使用本地Stable Diffusion生成图片"""
    try:
        t0 = _now_ms()
        # 将尺寸转换为宽高
        width, height = map(int, size.split('x'))
        
        data = {
            "prompt": prompt,
            "negative_prompt": "blurry, low quality, distorted",
            "width": width,
            "height": height,
            "steps": 20,
            "cfg_scale": 7,
            "sampler_index": "Euler a"
        }
        
        logger.bind(tag=TAG).info(f"[local_sd] request -> url={api_url} size={width}x{height} style={style}")
        response = requests.post(
            f"{api_url}/sdapi/v1/txt2img",
            json=data,
            timeout=120
        )
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[local_sd] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            b64 = result['images'][0]  # 已经是base64格式
            logger.bind(tag=TAG).info(f"[local_sd] ok {_short_b64_info(b64)}")
            return b64
        else:
            logger.bind(tag=TAG).error(f"本地SD API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"本地SD生成图片失败: {e}")
        return None

def generate_image_zhipu(prompt, api_key, style="realistic", size="512x512"):
    """使用智谱AI生成图片"""
    try:
        t0 = _now_ms()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # 智谱AI尺寸要求：512-2048px，且为16整数倍
        def validate_zhipu_size(size_str):
            try:
                # 针对 CogView-3 模型，默认 512x512 可能导致 500 错误或效果不佳，强制提升至 1024x1024
                if size_str == "512x512":
                    return "1024x1024"

                width, height = map(int, size_str.split('x'))
                
                # 1. 基础限制：长宽范围 512-2880 (这里保守取 2048，因 CogView-3 文档曾提及)
                # 错误提示称 2880，但通常模型 2048 够用了
                def clamp(x):
                    return max(512, min(2880, x))
                
                w = clamp(width)
                h = clamp(height)
                
                # 2. 像素总数限制：不超过 2^21 (2,097,152)
                MAX_PIXELS = 2097152
                if w * h > MAX_PIXELS:
                    import math
                    ratio = math.sqrt(MAX_PIXELS / (w * h))
                    w = int(w * ratio)
                    h = int(h * ratio)
                
                # 3. 必须是 16 的整数倍
                def round_to_16(x):
                    val = ((x + 8) // 16) * 16
                    return max(512, val)
                
                w = round_to_16(w)
                h = round_to_16(h)
                
                # 4. 再次检查总像素（因为取整可能导致溢出）
                while w * h > MAX_PIXELS:
                    # 削减较大的一边
                    if w >= h and w > 528:
                        w -= 16
                    elif h > 528:
                        h -= 16
                    else:
                        break

                return f"{w}x{h}"
            except:
                return "1024x1024"  # 默认安全尺寸
        
        valid_size = validate_zhipu_size(size)
        
        data = {
            "model": "cogview-3",
            "prompt": prompt,
            "size": valid_size,
            "quality": "standard",
            "n": 1
        }
        
        logger.bind(tag=TAG).info(f"[zhipu] request -> size={valid_size} style={style}")
        response = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/images/generations",
            headers=headers,
            json=data,
            timeout=60
        )
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[zhipu] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            # 获取图片URL并下载为base64
            image_url = result['data'][0]['url']
            logger.bind(tag=TAG).info(f"[zhipu] downloading image: {image_url}")
            t1 = _now_ms()
            img_response = requests.get(image_url, timeout=30)
            dt1 = _now_ms() - t1
            logger.bind(tag=TAG).info(f"[zhipu] image download <- status={img_response.status_code} dt={dt1}ms size={len(img_response.content) if hasattr(img_response,'content') else '?'}")
            if img_response.status_code == 200:
                b64 = base64.b64encode(img_response.content).decode()
                logger.bind(tag=TAG).info(f"[zhipu] ok {_short_b64_info(b64)}")
                return b64
            return None
        else:
            logger.bind(tag=TAG).error(f"智谱AI API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"智谱AI生成图片失败: {e}")
        return None

def generate_image_baidu(prompt, api_key, secret_key, style="realistic", size="512x512"):
    """使用百度文心一格生成图片"""
    try:
        t0 = _now_ms()
        # 获取access_token
        token_url = "https://aip.baidubce.com/oauth/2.0/token"
        token_params = {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key
        }
        
        logger.bind(tag=TAG).info("[baidu] get token ->")
        token_response = requests.post(token_url, params=token_params, timeout=10)
        logger.bind(tag=TAG).info(f"[baidu] get token <- status={token_response.status_code}")
        if token_response.status_code != 200:
            logger.bind(tag=TAG).error(f"百度获取token失败: {token_response.text}")
            return None
            
        access_token = token_response.json()["access_token"]
        
        # 生成图片
        headers = {"Content-Type": "application/json"}
        width, height = map(int, size.split('x'))
        
        data = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": 20,
            "n": 1
        }
        
        api_url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/text2image/sd_xl?access_token={access_token}"
        logger.bind(tag=TAG).info(f"[baidu] request -> size={width}x{height} style={style}")
        response = requests.post(api_url, headers=headers, json=data, timeout=60)
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[baidu] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            b64 = result['data'][0]['b64_image']
            logger.bind(tag=TAG).info(f"[baidu] ok {_short_b64_info(b64)}")
            return b64
        else:
            logger.bind(tag=TAG).error(f"百度文心API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"百度文心生成图片失败: {e}")
        return None

def generate_image_alibaba(prompt, api_key, style="realistic", size="512x512"):
    """使用阿里云通义万相生成图片"""
    try:
        t0 = _now_ms()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        width, height = map(int, size.split('x'))
        data = {
            "model": "wanx-v1",
            "input": {
                "prompt": prompt,
                "image_size": f"{width}*{height}"
            },
            "parameters": {
                "style": style,
                "n": 1
            }
        }
        
        logger.bind(tag=TAG).info(f"[alibaba] request -> size={width}x{height} style={style}")
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
            headers=headers,
            json=data,
            timeout=60
        )
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[alibaba] response <- status={response.status_code} dt={dt}ms")
        
        if response.status_code == 200:
            result = response.json()
            image_url = result['output']['results'][0]['url']
            # 下载图片并转换为base64
            logger.bind(tag=TAG).info(f"[alibaba] downloading image: {image_url}")
            t1 = _now_ms()
            img_response = requests.get(image_url, timeout=30)
            dt1 = _now_ms() - t1
            logger.bind(tag=TAG).info(f"[alibaba] image download <- status={img_response.status_code} dt={dt1}ms size={len(img_response.content) if hasattr(img_response,'content') else '?'}")
            if img_response.status_code == 200:
                b64 = base64.b64encode(img_response.content).decode()
                logger.bind(tag=TAG).info(f"[alibaba] ok {_short_b64_info(b64)}")
                return b64
            return None
        else:
            logger.bind(tag=TAG).error(f"阿里云API错误: {response.text}")
            return None
            
    except Exception as e:
        logger.bind(tag=TAG).error(f"阿里云生成图片失败: {e}")
        return None

@register_function("generate_image", GENERATE_IMAGE_FUNCTION_DESC, ToolType.IOT_CTL)
async def generate_image(conn, prompt: str, style: str = "realistic", size: str = "512x512"):
    """生成图片并发送到ESP32设备"""
    logger.bind(tag=TAG).info(f"Entered generate_image function with prompt: {prompt}")
    # 确保依赖的图像处理方法已可用
    if any(v is None for v in [send_image_to_device, send_image_generation_status, compress_image_for_esp32]):
        msg = f"图像处理模块导入失败: {_import_error if '_import_error' in globals() else 'unknown import error'}"
        logger.bind(tag=TAG).error(msg)
        return ActionResponse(Action.REQLLM, "图片生成失败：服务端图像模块缺失，请检查部署镜像或代码版本", None)
    req_id = f"img-{uuid.uuid4().hex[:8]}-{int(time.time())}"
    device_id = getattr(conn, 'device_id', None) or (getattr(conn, 'headers', {}) or {}).get('device-id')
    client_id = getattr(conn, 'client_id', None) or (getattr(conn, 'headers', {}) or {}).get('client-id')
    # 提取学号（优先取连接上的 student_id，其次尝试头）
    try:
        sid = getattr(conn, 'student_id', None)
        if not sid:
            headers = getattr(conn, 'headers', {}) or {}
            sid = headers.get('Student-Id') or headers.get('student-id') or headers.get('student_id')
            sid = str(sid).strip() if sid else None
    except Exception:
        sid = None

    logger.bind(tag=TAG).info(
        f"[{req_id}] 开始生成图片 | device={device_id} client={client_id} sid={sid} prompt={prompt} style={style} size={size}"
    )
    
    # 启动动态提示语动画（生成中...循环 + 模拟进度）
    stop_animation = asyncio.Event()
    async def _animate_status():
        base_msg = "图片正在生成中，请耐心等待"
        dots = 1
        current_progress = 5
        while not stop_animation.is_set():
            try:
                # 动态省略号文本
                msg = base_msg + "." * dots
                dots = (dots % 6) + 1
                
                # 模拟进度增长 (上限99%)
                if current_progress < 99:
                    # 前半段快一点，后半段慢一点
                    increment = 5 if current_progress < 60 else 2
                    current_progress += increment
                    if current_progress > 99: current_progress = 99
                
                await send_image_generation_status(conn, "generating", msg, prompt, extra_data={"progress": current_progress})
            except Exception: pass
            
            try:
                await asyncio.wait_for(stop_animation.wait(), timeout=0.8)
            except asyncio.TimeoutError: pass

    anim_task = asyncio.create_task(_animate_status())
    logger.bind(tag=TAG).info(f"[{req_id}] 动态状态提示已启动")
    
    # 获取配置
    image_config = conn.config.get("plugins", {}).get("generate_image", {})
    provider = image_config.get("provider", "stability")  # 默认使用Stability AI
    # 先取出尺寸，避免 f-string 中使用嵌套花括号导致格式错误
    esp32_width_cfg = image_config.get("esp32_width", 240)
    esp32_height_cfg = image_config.get("esp32_height", 240)
    logger.bind(tag=TAG).info(
        f"[{req_id}] 使用提供商: {provider} | cfg=esp32_w={esp32_width_cfg}, esp32_h={esp32_height_cfg}"
    )
    
    image_base64 = None
    
    # 获取 asyncio loop 用于将同步阻塞的 requests 调用放入线程池执行
    loop = asyncio.get_running_loop()

    try:
        # 根据配置的提供商生成图片
        if provider == "dalle":
            api_key = image_config.get("openai_api_key")
            if not api_key:
                await send_image_generation_status(conn, "error", "未配置OpenAI API密钥", prompt)
                logger.bind(tag=TAG).error(f"[{req_id}] 配置缺失: openai_api_key")
                return ActionResponse(Action.REQLLM, "未配置OpenAI API密钥，无法使用DALL-E生成图片", None)
            # 使用 run_in_executor 避免阻塞主线程
            image_base64 = await loop.run_in_executor(None, generate_image_dalle, prompt, api_key, style, size)
            
        elif provider == "stability":
            api_key = image_config.get("stability_api_key")
            if not api_key:
                await send_image_generation_status(conn, "error", "未配置Stability AI API密钥", prompt)
                logger.bind(tag=TAG).error(f"[{req_id}] 配置缺失: stability_api_key")
                return ActionResponse(Action.REQLLM, "未配置Stability AI API密钥，无法生成图片", None)
            image_base64 = await loop.run_in_executor(None, generate_image_stability, prompt, api_key, style, size)
            
        elif provider == "zhipu":
            api_key = image_config.get("zhipu_api_key")
            if not api_key:
                await send_image_generation_status(conn, "error", "未配置智谱AI API密钥", prompt)
                logger.bind(tag=TAG).error(f"[{req_id}] 配置缺失: zhipu_api_key")
                return ActionResponse(Action.REQLLM, "未配置智谱AI API密钥，无法生成图片", None)
            image_base64 = await loop.run_in_executor(None, generate_image_zhipu, prompt, api_key, style, size)
            
        elif provider == "baidu":
            api_key = image_config.get("baidu_api_key")
            secret_key = image_config.get("baidu_secret_key")
            if not api_key or not secret_key:
                await send_image_generation_status(conn, "error", "未配置百度API密钥", prompt)
                logger.bind(tag=TAG).error(f"[{req_id}] 配置缺失: baidu_api_key/baidu_secret_key")
                return ActionResponse(Action.REQLLM, "未配置百度API密钥，无法使用文心一格生成图片", None)
            image_base64 = await loop.run_in_executor(None, generate_image_baidu, prompt, api_key, secret_key, style, size)
            
        elif provider == "alibaba":
            api_key = image_config.get("alibaba_api_key")
            if not api_key:
                await send_image_generation_status(conn, "error", "未配置阿里云API密钥", prompt)
                logger.bind(tag=TAG).error(f"[{req_id}] 配置缺失: alibaba_api_key")
                return ActionResponse(Action.REQLLM, "未配置阿里云API密钥，无法使用通义万相生成图片", None)
            image_base64 = await loop.run_in_executor(None, generate_image_alibaba, prompt, api_key, style, size)
            
        elif provider == "local_sd":
            api_url = image_config.get("local_sd_url", "http://127.0.0.1:7860")
            logger.bind(tag=TAG).info(f"[{req_id}] local_sd_url={api_url}")
            image_base64 = await loop.run_in_executor(None, generate_image_local_sd, prompt, api_url, style, size)
            
        else:
            await send_image_generation_status(conn, "error", f"不支持的图片生成提供商: {provider}", prompt)
            return ActionResponse(Action.REQLLM, f"不支持的图片生成提供商: {provider}", None)
            
    finally:
        stop_animation.set()
        try:
            await anim_task
        except Exception: pass
    
    if not image_base64:
        await send_image_generation_status(conn, "error", "图片生成失败，请稍后重试", prompt)
        logger.bind(tag=TAG).error(f"[{req_id}] 生成失败，provider={provider}")
        return ActionResponse(Action.REQLLM, "图片生成失败，请稍后重试", None)
    
    # 压缩图片适配ESP32屏幕
    try:
        # 根据配置获取ESP32屏幕尺寸（复用上面的配置值）
        esp32_width = esp32_width_cfg
        esp32_height = esp32_height_cfg
        t0 = _now_ms()
        compressed_image = compress_image_for_esp32(image_base64, esp32_width, esp32_height)
        dt = _now_ms() - t0
        logger.bind(tag=TAG).info(f"[{req_id}] 压缩完成 -> {esp32_width}x{esp32_height} dt={dt}ms | {_short_b64_info(compressed_image)}")
    except Exception as e:
        logger.bind(tag=TAG).warning(f"图片压缩失败，使用原图: {e}")
        compressed_image = image_base64

    # 保存图片到本地（压缩后与原图可选）
    try:
        device_id_safe = device_id if isinstance(device_id, str) else None
        saved_path = save_image_to_disk(compressed_image, prompt, device_id_safe, prefix="compressed")
        if saved_path:
            logger.bind(tag=TAG).info(f"[{req_id}] 本地已保存(压缩图): {saved_path}")
            # 写入同名 JSON 元数据，便于 Web 页面按学号聚合
            try:
                meta = {
                    "source": "generated",
                    "date": datetime.now().strftime("%Y%m%d"),
                    "timestamp": int(time.time()),
                    "file": os.path.basename(saved_path),
                    "student_id": sid or "",
                    "device_id": device_id_safe or "",
                    "client_id": client_id or "",
                    "provider": image_config.get("provider", ""),
                    "style": style,
                    "size": size,
                    "prompt": prompt,
                    "req_id": req_id,
                }
                base, _ = os.path.splitext(saved_path)
                meta_path = base + ".json"
                wrote = False
                try:
                    with open(meta_path, "w", encoding="utf-8") as jf:
                        json.dump(meta, jf, ensure_ascii=False, indent=2)
                    wrote = os.path.isfile(meta_path)
                except Exception as we:
                    logger.bind(tag=TAG).warning(f"[{req_id}] 写入元数据失败(同目录): {we}")
                if wrote:
                    logger.bind(tag=TAG).info(f"[{req_id}] 元数据已保存: {meta_path}")
                else:
                    # 回退：写入到 data/generated_images/_meta/YYYYMMDD/ 同名json
                    try:
                        meta_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "generated_images", "_meta", meta["date"]))
                        os.makedirs(meta_dir, exist_ok=True)
                        meta_path2 = os.path.join(meta_dir, os.path.basename(base) + ".json")
                        with open(meta_path2, "w", encoding="utf-8") as jf:
                            json.dump(meta, jf, ensure_ascii=False, indent=2)
                        logger.bind(tag=TAG).info(f"[{req_id}] 元数据已保存(备用目录): {meta_path2}")
                    except Exception as me2:
                        logger.bind(tag=TAG).warning(f"[{req_id}] 保存元数据失败(备用目录): {me2}")
            except Exception as me:
                logger.bind(tag=TAG).warning(f"[{req_id}] 保存元数据失败: {me}")
        # 如有需要，也可以保存原图（体积较大，默认关闭）
        # original_path = save_image_to_disk(image_base64, prompt, device_id_safe, prefix="original")
        # if original_path:
        #     logger.bind(tag=TAG).info(f"[{req_id}] 本地已保存(原图): {original_path}")
    except Exception as e:
        logger.bind(tag=TAG).warning(f"[{req_id}] 本地保存图片失败: {e}")
    
    # 发送图片到ESP32
    t1 = _now_ms()
    success = False
    try:
        success = await send_image_to_device(conn, compressed_image, prompt)
    finally:
        dt1 = _now_ms() - t1
        logger.bind(tag=TAG).info(f"[{req_id}] 下发完成 result={success} dt={dt1}ms")
    
    if success:
        try:
            await send_image_generation_status(conn, "success", f"图片'{prompt}'已生成并发送到设备", prompt)
            logger.bind(tag=TAG).info(f"[{req_id}] 状态已推送: success")

            # 手动发送 tts stop 信号，确保设备退出 Speaking 状态回到 Idle
            if hasattr(conn, "websocket") and conn.websocket:
                stop_msg = {
                    "type": "tts",
                    "state": "stop",
                    "session_id": getattr(conn, "session_id", "")
                }
                await conn.websocket.send(json.dumps(stop_msg))
                logger.bind(tag=TAG).info(f"[{req_id}] 已发送 tts stop 信号重置设备状态")

        except Exception as e:
            logger.bind(tag=TAG).warning(f"[{req_id}] 状态推送/重置失败: {e}")
        return ActionResponse(
            Action.RESPONSE, 
            None, 
            None
        )
    else:
        try:
            await send_image_generation_status(conn, "error", "图片发送到设备失败", prompt)
            logger.bind(tag=TAG).info(f"[{req_id}] 状态已推送: error(下发失败)")
        except Exception as e:
            logger.bind(tag=TAG).warning(f"[{req_id}] 状态推送失败(error): {e}")
        return ActionResponse(
            Action.REQLLM, 
            f"图片生成成功，但发送到设备时出现问题，请检查设备连接", 
            None
        )