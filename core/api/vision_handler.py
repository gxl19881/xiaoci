import json
import base64
import copy
import re
from aiohttp import web
import uuid
from urllib.parse import urlparse, urlunparse
from config.logger import setup_logging
from core.utils.util import get_vision_url, is_valid_image_file, get_local_ip
from core.utils.vllm import create_instance
from config.config_loader import get_private_config_from_api
from core.utils.auth import AuthToken
import base64
from typing import Tuple, Optional
import os
from datetime import datetime
from plugins_func.register import Action
import asyncio
from concurrent.futures import ThreadPoolExecutor
from core.conn_registry import find as find_connections
import threading

TAG = __name__
EXCEL_LOCK = threading.Lock()

def save_vision_record_task(persist_dir, device_id, client_id, image_data, original_upload_bytes, return_json):
    """在独立线程中执行的文件持久化任务"""
    try:
        # 以日期分目录
        day = datetime.now().strftime("%Y%m%d")
        out_dir = os.path.join(persist_dir, day)
        os.makedirs(out_dir, exist_ok=True)

        # 生成安全的文件前缀（时间-设备-客户端）
        ts = datetime.now().strftime("%H%M%S")
        dev = (device_id or "").replace(":", "-")
        cid = (client_id or "")[:8]
        prefix = f"{ts}_{dev}_{cid}" if cid else f"{ts}_{dev}"

        # 保存“发送给模型”的最终图片
        img_ext = ".jpg"
        if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
            img_ext = ".png"
        elif image_data.startswith(b"GIF87a") or image_data.startswith(b"GIF89a"):
            img_ext = ".gif"
        elif image_data.startswith(b"BM"):
            img_ext = ".bmp"
        elif image_data.startswith(b"II*\x00") or image_data.startswith(b"MM\x00*"):
            img_ext = ".tiff"
        elif image_data.startswith(b"RIFF"):
            img_ext = ".webp"

        saved_image_path = os.path.join(out_dir, prefix + img_ext)
        with open(saved_image_path, "wb") as f:
            f.write(image_data)

        saved_orig_path = None
        # 附加：同时保存设备原始上传的字节
        if original_upload_bytes:
            orig_ext = ".jpg"
            ob = original_upload_bytes
            if ob.startswith(b"\x89PNG\r\n\x1a\n"):
                orig_ext = ".png"
            elif ob.startswith(b"GIF87a") or ob.startswith(b"GIF89a"):
                orig_ext = ".gif"
            elif ob.startswith(b"BM"):
                orig_ext = ".bmp"
            elif ob.startswith(b"II*\x00") or ob.startswith(b"MM\x00*"):
                orig_ext = ".tiff"
            elif ob.startswith(b"RIFF"):
                orig_ext = ".webp"
            elif ob.startswith(b"\xFF\xD8\xFF"):
                orig_ext = ".jpg"
            else:
                orig_ext = ".bin"

            saved_orig_path = os.path.join(out_dir, prefix + ".orig" + orig_ext)
            with open(saved_orig_path, "wb") as of:
                of.write(original_upload_bytes)

        # 保存返回 JSON
        saved_json_path = os.path.join(out_dir, prefix + ".json")
        with open(saved_json_path, "w", encoding="utf-8") as jf:
            jf.write(json.dumps(return_json, ensure_ascii=False, indent=2))
        
        # 记录到Excel（如果包含学号）
        student_id = return_json.get("student_id")
        if student_id:
            try:
                import openpyxl
                excel_path = os.path.join(persist_dir, "student_records.xlsx")
                prompt_text = return_json.get("question", "")
                with EXCEL_LOCK:
                    if not os.path.exists(excel_path):
                        wb = openpyxl.Workbook()
                        ws = wb.active
                        ws.title = "Records"
                        ws.append(["时间", "学号", "设备ID", "提示词", "回复内容", "图片路径", "JSON路径"])
                    else:
                        wb = openpyxl.load_workbook(excel_path)
                        ws = wb.active
                    
                    ws.append([
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        student_id,
                        device_id,
                        prompt_text,
                        return_json.get("response", ""),
                        saved_image_path,
                        saved_json_path
                    ])
                    wb.save(excel_path)
            except Exception as excel_err:
                print(f"Error saving to Excel: {excel_err}")

        return saved_image_path, saved_json_path, saved_orig_path
    except Exception as e:
        return None, None, None


def perform_image_processing(image_data, q_params, h_params):
    """
    在线程池中执行的CPU密集型图片处理任务
    """
    try:
        from PIL import Image
        from io import BytesIO
        
        # 尝试解码验证图片完整性

        # 根据设备型号决定是否旋转180度
        board_type = (h_params.get("X-Board-Type") or "").strip()
        need_rotate_180 = board_type == "guition-jc4880p443"

        # --- Multi-Image Stitching Logic (Merge multiple JPEGs) ---
        img = None
        orig_fmt = 'JPEG'
        
        can_be_multi = False
        if len(image_data) > 1024:
             if image_data.count(b'\xff\xd8') > 1:
                 can_be_multi = True
        
        if can_be_multi:
            images = []
            start = 0
            while True:
                soi = image_data.find(b'\xff\xd8', start)
                if soi == -1:
                    break
                eoi = image_data.find(b'\xff\xd9', soi)
                if eoi == -1:
                    next_soi = image_data.find(b'\xff\xd8', soi + 2)
                    end = next_soi if next_soi != -1 else len(image_data)
                else:
                    end = eoi + 2
                
                try:
                    part = image_data[soi:end]
                    if len(part) > 100:
                        img_part = Image.open(BytesIO(part))
                        img_part.load()
                        if need_rotate_180:
                            img_part = img_part.transpose(Image.ROTATE_180)
                        images.append(img_part)
                except Exception:
                    pass
                start = end
            
            if len(images) > 1:
                # Vertical stitching (Top to Bottom)
                max_width = max(i.width for i in images)
                total_height = sum(i.height for i in images)
                new_img = Image.new('RGB', (max_width, total_height), color=(255, 255, 255))
                y_offset = 0
                for i in images:
                    # Align left
                    new_img.paste(i, (0, y_offset))
                    y_offset += i.height
                img = new_img
                # Force processed flag implicitly by having a new img
            else:
                 img = Image.open(BytesIO(image_data))
                 if need_rotate_180:
                     img = img.transpose(Image.ROTATE_180)
                 # 如果 mode P/PA/CMYK 等非 RGB/L 需要转换，否则 saving as JPEG 会挂
                 if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                 orig_fmt = img.format
        else:
            img = Image.open(BytesIO(image_data))
            if need_rotate_180:
                img = img.transpose(Image.ROTATE_180)
            # 如果 mode P/PA/CMYK 等非 RGB/L 需要转换，否则 saving as JPEG 会挂
            if img.mode not in ("RGB", "L"):
               img = img.convert("RGB")
            orig_fmt = img.format

        if orig_fmt == 'JPEG':
            # 尝试完全加载以验证没有截断
            img.load()
            # 如果无需旋转/缩放，直接返回原数据，避免重编码损失
            # 但如果原图是CMYK等非RGB模式，可能后续还是得转
            
        rotate_q = (q_params.get("rotate") or h_params.get("X-Rotate") or "").strip()
        portrait_q = (q_params.get("portrait") or h_params.get("X-Portrait") or "0").strip()
        target_q = (q_params.get("target") or q_params.get("size") or h_params.get("X-Target-Size") or "").strip().lower()

        processed = False
        
        # portrait 优先：若为1且当前为横图，则转为竖图（顺时针90°）
        if portrait_q in ("1", "true", "yes"):
            if img.width > img.height:
                img = img.transpose(Image.ROTATE_270)  # 等价于顺时针90°
                processed = True

        # 显式旋转优先于 portrait 的兜底
        if rotate_q:
            rmap = {"90": Image.ROTATE_270, "-90": Image.ROTATE_90, "270": Image.ROTATE_90}
            r = rmap.get(rotate_q)
            if r is not None:
                img = img.transpose(r)
                processed = True

        # 已经在此函数最开头时统一做过 ROTATE_180，此处勿重复反转以免又倒回头
        # processed = True (保留状态，若之前已转则此处无需再转)

        # 解析目标尺寸，例如 600x800
        if target_q and "x" in target_q:
            try:
                tw, th = target_q.split("x", 1)
                tw = int(tw); th = int(th)
                if tw > 0 and th > 0 and (img.width != tw or img.height != th):
                    img = img.resize((tw, th), resample=Image.BILINEAR)
                    processed = True
            except Exception:
                pass
        
        # 即使没有旋转缩放，也强制转换为RGB并归一化为JPEG，确保兼容性
        # 如果你想保留原图，可以加个判断
        if img.mode != 'RGB':
            img = img.convert('RGB')
            processed = True
        
        # 优先尝试转成规范JPEG，失败则PNG兜底
        out = BytesIO()
        try:
            img.save(out, format="JPEG", quality=85, optimize=True)
            new_data = out.getvalue()
            return new_data, "image/jpeg", len(new_data), orig_fmt
        except Exception:
            # JPEG保存失败，尝试PNG
            out.seek(0)
            out.truncate(0)
            img.save(out, format="PNG", optimize=True)
            new_data = out.getvalue()
            return new_data, "image/png", len(new_data), orig_fmt
            
    except Exception as e:
        # 处理失败返回 None
        return None, None, 0, None


class VisionHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        # 初始化认证工具
        self.auth = AuthToken(config["server"]["auth_key"])
        # 初始化专用线程池，避免阻塞主线程或挤占默认池（默认池通常很小）
        # 视觉任务如果并发高，需要较大队列
        self.executor = ThreadPoolExecutor(max_workers=64, thread_name_prefix="VisionWorker")
        # 简易任务表（内存态）：task_id -> {status: pending|done|error, result: dict, created_at: float}
        # 注意：这是进程内短期缓存，进程重启会丢失，如需持久化可改为Redis/DB
        self.tasks = {}
        # 待拼接图片缓存：device_id -> PIL.Image
        self.pending_images = {}
        # 无需注入 WebSocketServer（通过文件持久化 + 工具执行器容错轮询实现回传）

    def _create_error_response(self, message: str) -> dict:
        """创建统一的错误响应格式"""
        return {"success": False, "message": message}

    def _verify_auth_token(self, request) -> Tuple[bool, Optional[str]]:
        """验证认证token"""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, None

        token = auth_header[7:]  # 移除"Bearer "前缀
        return self.auth.verify_token(token)

    async def handle_post(self, request):
        """处理 MCP Vision POST 请求"""
        response = None  # 初始化response变量
        saved_image_path = None
        saved_json_path = None
        saved_orig_path = None
        try:
            # 基础请求信息日志（不含敏感内容）
            ctype = request.headers.get("Content-Type", "")
            clen = request.headers.get("Content-Length", "")
            te = request.headers.get("Transfer-Encoding", "")
            self.logger.bind(tag=TAG).info(
                f"视觉POST到达: content_type={ctype}, content_length={clen}, transfer_encoding={te}"
            )
            # 验证token
            is_valid, token_device_id = self._verify_auth_token(request)
            if not is_valid:
                response = web.json_response(
                    self._create_error_response("无效的认证token或token已过期"),
                    status=401,
                )
                return response

            # 获取请求头信息
            device_id = request.headers.get("Device-Id", "")
            client_id = request.headers.get("Client-Id", "")
            if device_id != token_device_id:
                raise ValueError("设备ID与token不匹配")
            question: Optional[str] = None
            image_data: Optional[bytes] = None

            # 设备侧JPEG诊断头（用于比对裁剪、长度与MD5）
            jpeg_diag_trim = request.headers.get("X-JPEG-Trim", "")
            jpeg_diag_md5 = request.headers.get("X-JPEG-MD5", "")
            jpeg_diag_cl  = request.headers.get("X-JPEG-CL",  "")
            if jpeg_diag_trim or jpeg_diag_md5 or jpeg_diag_cl:
                self.logger.bind(tag=TAG).info(
                    f"设备JPEG诊断头: trim={jpeg_diag_trim}, md5={jpeg_diag_md5}, cl={jpeg_diag_cl}"
                )

            # 尝试从请求头获取学号（如果有）
            student_id = (
                request.headers.get("Student-Id")
                or request.headers.get("student-id")
                or request.headers.get("student_id")
                or ""
            ).strip()

            # 根据Content-Type分支处理
            ctype_lower = ctype.lower()
            # 记录最初上传的原始字节（用于后续校验/对比持久化）
            original_upload_bytes: Optional[bytes] = None
            if ctype_lower.startswith("multipart/form-data"):
                # 解析multipart/form-data请求（不依赖字段顺序，兼容多名称）
                reader = await request.multipart()
                while True:
                    field = await reader.next()
                    if field is None:
                        break
                    name = getattr(field, "name", None)
                    filename = getattr(field, "filename", None)
                    # 文本问题
                    if name == "question" and question is None:
                        question = await field.text()
                        continue
                    # 学号字段（如果客户端通过表单传递）
                    if name == "student_id" and not student_id:
                        try:
                            student_id = (await field.text()).strip()
                        except Exception:
                            pass
                        continue
                    # 图片文件，兼容多个字段名或者multipart检测到文件
                    if filename or name in {"image", "file", "photo"}:
                        if image_data is None:
                            image_data = await field.read()
                        else:
                            image_data += await field.read()
                        original_upload_bytes = image_data
                        continue
            else:
                # 兼容非multipart情况：
                # 1) application/json，包含 question 与 image_base64 / image 字段
                # 2) application/octet-stream，原始图片字节，question 从请求头 X-Question/Question 或 query 中获取
                try:
                    if "application/json" in ctype_lower:
                        body_json = await request.json()
                        if isinstance(body_json, dict):
                            question = body_json.get("question") or question
                            img_b64 = body_json.get("image_base64") or body_json.get("image")
                            if isinstance(img_b64, str) and len(img_b64) > 0:
                                try:
                                    image_data = base64.b64decode(img_b64)
                                    original_upload_bytes = image_data
                                except Exception:
                                    raise ValueError("JSON中的image_base64字段无法解析")
                    else:
                        # 原始字节：支持 Content-Length 或 chunked 传输
                        image_data = await request.read()
                        original_upload_bytes = image_data
                        question = (
                            request.headers.get("X-Question")
                            or request.headers.get("Question")
                            or request.query.get("question")
                            or question
                        )
                except Exception as je:
                    # 若解析失败，按原始字节兜底
                    if image_data is None:
                        image_data = await request.read()
                        original_upload_bytes = image_data

            if not question:
                # 放宽要求：若未提供问题，使用保守的默认提示文案，交由后续LLM结合上下文处理
                try:
                    question = "请结合这张照片进行分析和描述，若是试卷请判断答案是否正确。"
                except Exception:
                    question = "请描述这张照片。"
            if not image_data:
                raise ValueError("缺少图片文件")
            if len(image_data) == 0:
                raise ValueError("图片数据为空")

            # 记录一条可观测日志，方便确认是否收到请求
            self.logger.bind(tag=TAG).info(
                f"收到视觉请求: device={device_id}, client={client_id}, question_len={len(question)}, image_size={len(image_data)}"
            )

            # 通知活动连接：已收到请求
            target_conn = None
            try:
                # 优先精确匹配 client_id，避免多连接导致重复通知
                conns = find_connections(device_id=device_id)
                # target_conn = None  <-- Removed logic here to use outer var
                
                if conns:
                    # 1. 尝试筛选匹配 client_id 的连接
                    matched = [c for c in conns if c.headers.get("client-id") == client_id]
                    
                    if matched:
                        # 如果有多个匹配（例如旧连接未断开），取最后活跃时间最新的一个
                        try:
                            target_conn = max(matched, key=lambda c: getattr(c, "last_activity_time", 0))
                        except Exception:
                            target_conn = matched[-1]
                    else:
                        # 2. 兜底：如果没有精确匹配，取所有连接中最新的一个
                        try:
                            target_conn = max(conns, key=lambda c: getattr(c, "last_activity_time", 0))
                        except Exception:
                            target_conn = conns[-1]

                    if target_conn:
                        try:
                            # [Mod] Disable single notification to use animation loop inside pipeline
                            # if hasattr(target_conn, "notify_vision_started"):
                            #     target_conn.logger.bind(tag=TAG).info("VisionHandler 触发 notify_vision_started")
                            #     target_conn.notify_vision_started()
                            
                            # Just mark active and set flag
                            if hasattr(target_conn, "vision_request_received"):
                                target_conn.vision_request_received = True
                                target_conn._vision_final_sent = False
                                target_conn.mark_active()
                                try:
                                      real_q = getattr(target_conn, "last_user_query", None)
                                      if not real_q and hasattr(target_conn, "_get_last_user_content"):



                                        


                                        
                                          real_q = target_conn._get_last_user_content()
                                          
                                      if real_q and str(real_q).strip():
                                          # 对话练习模式：不覆盖question，保留专用的对话提取prompt
                                          _dp_session = getattr(target_conn, "dialogue_practice_session", None)
                                          if not (_dp_session and _dp_session.state == "awaiting_photo"):
                                              question = str(real_q).strip()

                                    # 如果请求中没有带student_id，从WebSocket连接中获取
                                      if not student_id and target_conn:
                                          if hasattr(target_conn, "student_id") and target_conn.student_id:
                                              student_id = str(target_conn.student_id).strip()
                                          else:
                                              # 退一步：如果还没有，将设备ID（通常显示在屏幕右上角）作为用户/学号标识
                                              if hasattr(target_conn, "device_id") and target_conn.device_id:
                                                  student_id = str(target_conn.device_id).strip()
                                              elif device_id:
                                                  student_id = str(device_id).strip()

                                except Exception:
                                    pass
                        except Exception:
                            pass
                else:
                    self.logger.bind(tag=TAG).warning(f"未找到活动连接用于通知 vision_started (device_id={device_id})")
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"触发 vision_started 通知失败: {e}")

            # 检查文件大小（支持通过配置调整）
            vision_cfg = (self.config.get("vision") or {})
            try:
                # 默认提升为10MB，具体上限仍可通过 data/.config.yaml 的 vision.max_upload_mb 配置
                max_mb = float(vision_cfg.get("max_upload_mb", 10))
            except Exception:
                max_mb = 10.0
            max_bytes = int(max_mb * 1024 * 1024)
            if len(image_data) > max_bytes:
                raise ValueError(
                    f"图片大小超过限制，最大允许{max_mb}MB"
                )

            # 检查文件格式（更加严格 + 可裁剪前导噪声）
            def _hex_head(data: bytes, n: int = 16) -> str:
                try:
                    return " ".join(f"{b:02X}" for b in data[:n])
                except Exception:
                    return ""

            def _detect_and_trim(data: bytes) -> Tuple[bytes, str]:
                """检测常见图片格式，并在允许范围内裁剪前导噪声。
                返回(裁剪后的数据, mime)；若无法识别则 mime 为 'unknown'。
                """
                if not data or len(data) < 4:
                    return data, "unknown"

                # PNG: 固定8字节签名，只接受出现在前64字节内，裁剪到签名位置
                sig_png = b"\x89PNG\r\n\x1a\n"
                k = data.find(sig_png, 0, 64)
                if k != -1:
                    return data[k:], "image/png"

                # GIF: 6字节签名，只接受出现在前64字节内
                for sig_gif in (b"GIF87a", b"GIF89a"):
                    k = data.find(sig_gif, 0, 64)
                    if k != -1:
                        return data[k:], "image/gif"

                # BMP: 'BM' 开头，允许在前64字节内
                k = data.find(b"BM", 0, 64)
                if k != -1:
                    return data[k:], "image/bmp"

                # TIFF: 'II*\x00' 或 'MM\x00*'，允许在前64字节内
                for sig_tiff in (b"II*\x00", b"MM\x00*"):
                    k = data.find(sig_tiff, 0, 64)
                    if k != -1:
                        return data[k:], "image/tiff"

                # WEBP: 'RIFF' + ... + 'WEBP'，通常应当从0开始，允许在前64字节内裁剪
                k = data.find(b"RIFF", 0, 64)
                if k != -1 and len(data) >= k + 16 and b"WEBP" in data[k:k+16]:
                    return data[k:], "image/webp"

                # JPEG: 查找SOI FFD8FF，允许在前1024字节内裁剪
                k = data.find(b"\xff\xd8\xff", 0, 1024)
                if k != -1:
                    trimmed = data[k:]
                    return trimmed, "image/jpeg"

                return data, "unknown"

            # 第一步：基于魔数识别并裁剪前导噪声
            # 在裁剪/修复前记录一份原始上传内容的MD5，便于排查“保存的图片有问题”的来源
            def _md5_hex(b: bytes) -> str:
                try:
                    import hashlib
                    m = hashlib.md5()
                    m.update(b)
                    return m.hexdigest()
                except Exception:
                    return ""
            if original_upload_bytes is None and image_data is not None:
                # 兜底：若上面未捕获到，确保 original_upload_bytes 至少有值
                original_upload_bytes = image_data

            orig_md5 = _md5_hex(original_upload_bytes or b"")
            image_data, initial_mime = _detect_and_trim(image_data)
            if initial_mime == "unknown":
                self.logger.bind(tag=TAG).warning(
                    f"图片魔数未识别，头16字节={_hex_head(image_data)}，拒绝继续处理"
                )
                raise ValueError(
                    "不支持的文件格式或数据损坏，请上传标准的 JPEG/PNG/GIF/BMP/TIFF/WEBP 图片"
                )

            # 统一重编码为规范JPEG，提升OpenAI兼容视觉模型的解析成功率
            #（部分设备上传的JPEG可能头部不规范或包含颜色空间/子采样差异，重编码可规避）
            
            # [Refactor] Async check moved here to allow full background processing
            async_requested = False
            try:
                q_async = request.query.get("async", "0")
                hdr_async = request.headers.get("X-Async", "0")
                async_requested = (str(q_async) == "1") or (str(hdr_async) == "1")
            except Exception:
                async_requested = False
            
            if device_id and async_requested:
                self.logger.bind(tag=TAG).info(f"Detected Async request (Device={device_id}). Will fork processing.")

            # Capture Context for thread safety
            req_query = dict(request.query)
            req_headers = {}
            try:
                for k, v in request.headers.items():
                    req_headers[k] = v
            except: pass

            # Define Pipeline Function
            async def _execute_inference_pipeline() -> dict:
                # Capture variables from closure
                current_image_data = image_data
                chosen_mime = "image/jpeg"
                orig_fmt = "Unknown"

                # Check multi flux
                is_multi_jpeg_stream = (current_image_data.count(b"\xff\xd8") > 1)
                try:
                    if not is_multi_jpeg_stream:
                        eoi = current_image_data.rfind(b"\xff\xd9")
                        if eoi != -1 and eoi + 2 < len(current_image_data):
                            cut_bytes = len(current_image_data) - (eoi + 2)
                            current_image_data = current_image_data[: eoi + 2]
                            self.logger.bind(tag=TAG).warning(f"检测到JPEG尾部疑似噪声，已截断 {cut_bytes} 字节")
                        elif current_image_data.startswith(b"\xff\xd8\xff") and eoi == -1:
                            current_image_data = current_image_data + b"\xff\xd9"
                            self.logger.bind(tag=TAG).warning("未检测到JPEG结束标记，已追加EOI(FFD9)")
                    else:
                        count_imgs = current_image_data.count(b'\xff\xd8')
                        self.logger.bind(tag=TAG).info(f"检测到多图JPEG流({count_imgs}张)，跳过EOI裁剪以完整保留数据")
                except Exception:
                    pass

                # Multi-page Stitching Logic (Supports N pages)
                try:
                    from io import BytesIO
                    from PIL import Image
                    from PIL import ImageFile
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    
                    with BytesIO(current_image_data) as _bio:
                        img = Image.open(_bio)
                        try: img.load()
                        except: pass
                    
                    orig_fmt = getattr(img, "format", "Unknown")
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")

                    # X-Device-Model 判断，如果属于4寸设备则翻转180度
                    device_model = req_headers.get("X-Device-Model", req_headers.get("x-device-model", "")).lower()
                    if "4" in device_model:
                        img = img.transpose(Image.ROTATE_180)

                    # 解析指令中的张数
                    q_lower = (question or "").lower().replace(" ", "")
                    target_count = 0
                    c_match = re.search(r"(\d+|[一二两三四五六七八九十])张", q_lower)
                    if c_match:
                        ns = c_match.group(1)
                        num_map = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
                        target_count = int(ns) if ns.isdigit() else num_map.get(ns, 0)
                    
                    force_disable_flow = is_multi_jpeg_stream
                    is_merge_intent = ("合并" in q_lower or "merge" in q_lower)
                    is_paged_intent = ("第" in q_lower and "张" in q_lower)

                    # 判定是否进入多张缓存流程
                    should_cache = (target_count > 1 or is_merge_intent or is_paged_intent) and not force_disable_flow
                    has_pending = device_id in self.pending_images

                    if should_cache or has_pending:
                        final_target = target_count if target_count > 1 else 2
                        
                        img_list = []
                        if has_pending:
                            exist_data = self.pending_images[device_id]
                            if isinstance(exist_data, list):
                                img_list = exist_data
                            else:
                                img_list = [exist_data] # 兼容旧数据
                        
                        img_list.append(img)
                        self.pending_images[device_id] = img_list
                        
                        current_count = len(img_list)
                        self.logger.bind(tag=TAG).info(f"Device {device_id} image stitching: {current_count}/{final_target}")

                        if current_count < final_target:
                            msg = f"已收到第{current_count}张图片，共需{final_target}张。请继续拍摄。"
                            resp_data = {
                                "success": True, "action": Action.RESPONSE.name,
                                "message": msg,
                                "response": msg
                            }
                            # Save notification file logic
                            try:
                                vision_cfg = self.config.get("vision", {}) or {}
                                root = vision_cfg.get("persist_dir", "data/vision_records")
                                day = datetime.now().strftime("%Y%m%d")
                                out_dir = os.path.join(root, day)
                                os.makedirs(out_dir, exist_ok=True)
                                ts = datetime.now().strftime("%H%M%S")
                                dev = (device_id or "").replace(":", "-")
                                cid = (client_id or "")[:8]
                                prefix = f"{ts}_{dev}_{cid}" if cid else f"{ts}_{dev}"
                                with open(os.path.join(out_dir, prefix + ".json"), "w", encoding="utf-8") as jf:
                                    jf.write(json.dumps(resp_data, ensure_ascii=False, indent=2))
                            except Exception: pass
                            return resp_data
                        else:
                            self.pending_images.pop(device_id)
                            max_width = max(i.width for i in img_list)
                            total_height = 0
                            resized_imgs = []
                            for im in img_list:
                                if im.width != max_width:
                                    ratio = max_width / im.width
                                    new_h = int(im.height * ratio)
                                    im = im.resize((max_width, new_h), Image.BILINEAR)
                                total_height += im.height
                                resized_imgs.append(im)
                            
                            new_img = Image.new('RGB', (max_width, total_height), (255, 255, 255))
                            y_offset = 0
                            for im in resized_imgs:
                                new_img.paste(im, (0, y_offset))
                                y_offset += im.height
                            img = new_img
                            self.logger.bind(tag=TAG).info(f"Merged {len(img_list)} images into {max_width}x{total_height}")
                            
                            out_merge = BytesIO()
                            img.save(out_merge, format="JPEG", quality=90)
                            current_image_data = out_merge.getvalue()
                except Exception as e:
                    self.logger.bind(tag=TAG).warning(f"Vision/Image Merge logic failed: {e}")

                # Image Processing (Rotate/Resize)
                try:
                    loop = asyncio.get_running_loop()
                    proc_img_data, proc_mime, proc_len, proc_fmt = await loop.run_in_executor(
                         self.executor, perform_image_processing, current_image_data, req_query, req_headers
                    )
                    if proc_img_data:
                        current_image_data = proc_img_data
                        chosen_mime = proc_mime
                        self.logger.bind(tag=TAG).info(f"图片已预处理: 原始fmt={proc_fmt}, 新MIME={chosen_mime}, size={proc_len}")
                    else:
                        chosen_mime = initial_mime or "image/jpeg"
                except Exception as _e:
                     self.logger.bind(tag=TAG).warning(f"图片预处理异常: {_e}")
                     chosen_mime = initial_mime or "image/jpeg"

                # Base64 Encode
                def _make_data_url(data_bytes, mime_type):
                    b64 = base64.b64encode(data_bytes).decode("utf-8")
                    return f"data:{mime_type};base64,{b64}", len(b64)
                
                data_url, b64_len = await asyncio.get_running_loop().run_in_executor(
                    self.executor, _make_data_url, current_image_data, chosen_mime
                )
                final_md5 = _md5_hex(current_image_data)
                self.logger.bind(tag=TAG).info(f"准备发送给VLLM: b64_len={b64_len}")

                # Config & VLLM
                current_config = copy.deepcopy(self.config)
                if current_config.get("read_config_from_api", False):
                    current_config = await asyncio.get_running_loop().run_in_executor(
                        None, get_private_config_from_api, current_config, device_id, client_id,
                    )
                
                select_vllm_module = current_config["selected_module"].get("VLLM")
                if not select_vllm_module: raise ValueError("您还未设置默认的视觉分析模块")
                vllm_cfg = current_config["VLLM"][select_vllm_module]
                vllm_type = select_vllm_module if "type" not in vllm_cfg else vllm_cfg["type"]
                if not vllm_type: raise ValueError(f"无法找到VLLM模块对应的供应器{vllm_type}")
                
                vllm = create_instance(vllm_type, vllm_cfg)
                vision_cfg = (self.config.get("vision") or {})
                vision_timeout = float((vision_cfg.get("timeout_seconds") or 300))

                # [Educational Prompt Injection]
                # Modifying prompt to support "Guide before Answer" execution mode for students
                edu_prompt_suffix = (
                    "\n\n【重要指令】：如果图片内容包含习题、试卷或作业题目："
                    "\n1. 首先观察题目区域是否为空白（即未作答状态）。"
                    "\n2. 如果题目是空白的，或者明显没有用户的作答痕迹，**请绝对不要直接给出最终答案**。"
                    "\n3. 请仅提供解题思路的引导，指出解题的关键点，或者反问用户对这道题的理解，鼓励用户自己思考。"
                    "\n4. 只有当用户提供了自己的作答（图片中有手写答案）时，或者用户明确表示已经做完请求批改时，才进行详细的分析、纠错和给出正确答案。"
                    "\n5. 请像一位耐心的老师一样，一步步引导学生自己解决问题，而不是直接告诉结果。"
                )

                # 英语对话练习：使用专用的对话提取prompt
                dialogue_session_active = False
                if target_conn:
                    try:
                        _session = getattr(target_conn, "dialogue_practice_session", None)
                        if _session and _session.state == "awaiting_photo":
                            dialogue_session_active = True
                    except Exception:
                        pass

                if dialogue_session_active:
                    final_question = (
                        "请仔细分析这张图片中的英语对话内容。"
                        "请完成以下任务：\n"
                        "1. 识别并列出对话中的所有角色名称\n"
                        "2. 按角色整理出完整的对话内容\n"
                        "3. 用中文回复，格式如下：\n"
                        "\"我已准备好，对话共有X个回合，角色有：1.角色A 2.角色B。"
                        "请告诉我你要扮演的角色编号或名字。\""
                    )
                    # 标记已处理，防止后续拍照仍用对话提取模式
                    target_conn.dialogue_practice_session = None
                else:
                    final_question = f"{question}{edu_prompt_suffix}"

                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(self.executor, vllm.response, final_question, data_url),
                    timeout=vision_timeout,
                )

                # Santize
                try:
                    from core.utils import textUtils as _txu
                    _resp = _txu.sanitize_for_device(result or "")
                except Exception: _resp = result

                if dialogue_session_active and target_conn:
                    if hasattr(target_conn, 'dialogue_practice'):
                        target_conn.dialogue_practice['content'] = result
                        target_conn.logger.bind(tag=TAG).info(f"保存了对话练习内容(长度:{len(result)})")

                return_json = {
                    "success": True, "action": Action.RESPONSE.name, "response": _resp,
                    "device_id": device_id,
                    "question": question,
                }
                
                jpeg_diag = {}
                if jpeg_diag_trim: jpeg_diag["device_trim"] = jpeg_diag_trim
                if jpeg_diag_md5: jpeg_diag["device_md5"] = jpeg_diag_md5
                if jpeg_diag_cl: jpeg_diag["device_cl"] = jpeg_diag_cl
                jpeg_diag["server_md5_orig"] = orig_md5
                jpeg_diag["server_md5_final"] = final_md5
                if jpeg_diag: return_json["jpeg_diag"] = jpeg_diag
                if student_id: return_json["student_id"] = student_id
                
                # Persistence
                if vision_cfg.get("persist", False) or student_id:
                    try:
                        root = vision_cfg.get("persist_dir", "data/vision_records")
                        await loop.run_in_executor(
                            self.executor, save_vision_record_task,
                            root, device_id, client_id, current_image_data, original_upload_bytes, return_json
                        )
                    except Exception as se:
                        self.logger.bind(tag=TAG).warning(f"视觉记录保存失败: {se}")
                
                return return_json

            # Wrapper for Animation
            async def _execute_with_animation():
                # 只发送 recognizing 状态，固件会在 lv_layer_top() 上显示全屏覆盖层动画
                # 不发送 tts start / sentence_start，避免在 content_ 层创建聊天气泡
                ws_ok = target_conn and target_conn.websocket and target_conn.ws_open
                if ws_ok:
                    try:
                        await target_conn.websocket.send(json.dumps({
                            "type": "image_generation_status",
                            "data": {
                                "status": "recognizing",
                                "message": "图片正在识别中，请耐心等待",
                            }
                        }, ensure_ascii=False))
                    except Exception:
                        pass

                return await _execute_inference_pipeline()

            # --- Branching ---
            if async_requested:
                task_id = uuid.uuid4().hex
                self.tasks[task_id] = {"status": "pending", "result": None}

                async def _bg_task_wrapper():
                    try:
                        res = await _execute_with_animation()
                        self.tasks[task_id] = {"status": "done", "result": res}
                        # WebSocket Bridge
                        try:
                            conns = find_connections(device_id=device_id, client_id=client_id)
                            if conns:
                                for _conn in conns:
                                    try:
                                        if hasattr(_conn, "handle_vision_bridge"):
                                            asyncio.create_task(_conn.handle_vision_bridge(res))
                                    except Exception: continue
                        except Exception: pass
                    except asyncio.TimeoutError:
                         self.tasks[task_id] = {"status": "error", "result": {"success": False, "message": "视觉分析超时"}}
                    except Exception as e:
                         self.tasks[task_id] = {"status": "error", "result": {"success": False, "message": f"任务失败: {e}"}}

                asyncio.create_task(_bg_task_wrapper())
                
                try: port = int(self.config["server"].get("http_port", 8003))
                except: port = 8003
                result_url = f"http://{get_local_ip()}:{port}/mcp/vision/result?id={task_id}"

                accept_body = {
                    "success": True, "accepted": True, "task_id": task_id,
                    "result_url": result_url,
                    "timeout_seconds": 120
                }
                body_bytes = json.dumps(accept_body, ensure_ascii=False).encode("utf-8")
                response = web.Response(body=body_bytes, content_type="application/json", status=202)
                response.headers["Connection"] = "close"
                return response
            else:
                # Sync Mode
                try:
                    loop = asyncio.get_running_loop()
                    result_json = await _execute_with_animation()
                except asyncio.TimeoutError:
                    raise ValueError(f"视觉分析超时")

                body_bytes = json.dumps(result_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                response = web.Response(body=body_bytes, content_type="application/json")
                try: response.headers["Connection"] = "close"
                except: pass
                
                # Optional Bridge also in Sync
                try:
                    conns = find_connections(device_id=device_id, client_id=client_id)
                    for _conn in conns:
                        if hasattr(_conn, "handle_vision_bridge"):
                            asyncio.create_task(_conn.handle_vision_bridge(result_json))
                except Exception: pass

                return response
        except ValueError as e:
            self.logger.bind(tag=TAG).error(f"MCP Vision POST请求异常: {e}")
            return_json = self._create_error_response(str(e))
            body_bytes = json.dumps(return_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            response = web.Response(body=body_bytes, content_type="application/json")
            try:
                response.headers["Connection"] = "close"
            except Exception:
                pass
        except Exception as e:
            # 针对连接中断的错误给出更清晰提示
            msg = str(e)
            if "Connection lost" in msg or "ConnectionResetError" in msg:
                msg = "上传过程中连接中断，可能是图片过大、网络不稳定或设备提前断开"
            self.logger.bind(tag=TAG).error(f"MCP Vision POST请求异常: {msg}")
            return_json = self._create_error_response("处理请求时发生错误")
            body_bytes = json.dumps(return_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            response = web.Response(body=body_bytes, content_type="application/json")
            try:
                response.headers["Connection"] = "close"
            except Exception:
                pass
        finally:
            if response:
                self._add_cors_headers(response)
            return response

    async def handle_get(self, request):
        """处理 MCP Vision GET 请求（精简实现，避免兼容性问题）"""
        vision_explain = None
        try:
            vision_explain = get_vision_url(self.config)
        except Exception:
            pass

        if vision_explain and len(str(vision_explain)) > 0 and str(vision_explain) != "null":
            message = f"MCP Vision 接口运行正常，视觉解释接口地址是：{vision_explain}"
            response = web.Response(text=message, content_type="text/plain")
        else:
            message = "MCP Vision 接口运行不正常，请打开data目录下的.config.yaml文件，找到【server.vision_explain】，设置好地址"
            response = web.Response(text=message, content_type="text/plain")

        self._add_cors_headers(response)
        return response

    async def handle_result(self, request):
        """异步任务结果查询: /mcp/vision/result?id=<task_id>"""
        try:
            task_id = request.query.get("id")
            if not task_id:
                raise ValueError("缺少id")
            task = self.tasks.get(task_id)
            if not task:
                return web.json_response({"success": False, "message": "任务不存在或已过期"}, status=404)
            status = task.get("status")
            if status == "pending":
                return web.json_response({"success": True, "status": "pending"}, status=200)
            elif status == "done":
                # 直接返回处理结果（与同步一致）
                return web.json_response(task.get("result") or {"success": False, "message": "未知状态"}, status=200)
            else:
                return web.json_response(task.get("result") or {"success": False, "message": "任务失败"}, status=200)
        except Exception as e:
            return web.json_response({"success": False, "message": str(e)}, status=400)

    def _add_cors_headers(self, response):
        """添加CORS头信息"""
        # 放宽预检允许的请求头，涵盖常见大小写写法
        response.headers["Access-Control-Allow-Headers"] = (
            "content-type, authorization, Authorization, client-id, Client-Id, device-id, Device-Id, student-id, Student-Id"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"

