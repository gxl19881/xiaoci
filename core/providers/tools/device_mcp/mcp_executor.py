"""设备端MCP工具执行器"""

from typing import Dict, Any
import os
import json
import asyncio
from datetime import datetime, timedelta
from ..base import ToolType, ToolDefinition, ToolExecutor
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
from plugins_func.register import Action, ActionResponse
from .mcp_handler import call_mcp_tool, send_mcp_message, send_mcp_initialize_message
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class DeviceMCPExecutor(ToolExecutor):
    """设备端MCP工具执行器"""

    def __init__(self, conn):
        self.conn = conn

    async def execute(
        self, conn, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行设备端MCP工具"""
        if not hasattr(conn, "mcp_client") or not conn.mcp_client:
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未初始化",
            )

        # 检查是否就绪，对于相机类工具允许盲调（skip_check）
        is_ready = await conn.mcp_client.is_ready()
        skip_check = False
        
        lowered_name = tool_name.lower()
        is_camera_tool = (
            lowered_name.startswith("self.camera")
            or "take_photo" in lowered_name
            or "recognize_number" in lowered_name
        )

        if not is_ready:
            if is_camera_tool:
                # 允许相机工具在未就绪时尝试盲调
                skip_check = True
                try:
                    conn.logger.warning(f"MCP未就绪，尝试盲调相机工具: {tool_name}")
                    # 盲调前强制重发一次初始化消息，确保设备端已配置URL/Token
                    # 避免因首条初始化消息丢失或未处理导致 'Image explain URL or token is not set'
                    try:
                        asyncio.create_task(send_mcp_initialize_message(conn))
                        # 短暂等待让初始化消息先发出
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                return ActionResponse(
                    action=Action.ERROR,
                    response="设备端MCP客户端未准备就绪",
                )

        try:
            # 转换参数为JSON字符串
            import json

            args_str = json.dumps(arguments) if arguments else "{}"

            # 为相机/视觉类工具设置更长的默认超时（拍照、识别通常较慢）
            def _calc_timeout(name: str) -> int:
                try:
                    default_timeout = int(
                        conn.config.get("mcp_tool_timeout_default", 30)
                    )
                except Exception:
                    default_timeout = 30

                try:
                    camera_timeout = int(
                        conn.config.get("mcp_tool_timeout_camera", 90)
                    )
                except Exception:
                    camera_timeout = 90

                lowered = name.lower()
                if (
                    lowered.startswith("self.camera")
                    or "take_photo" in lowered
                    or "recognize_number" in lowered
                ):
                        return 300  # 将超时提升到300秒
                return default_timeout

            timeout = _calc_timeout(tool_name)

            # 对相机类工具采用“发送即轮询文件落地”的容错模式，避免设备未及时回传导致对话断开
            lowered = tool_name.lower()
            is_camera_tool = (
                lowered.startswith("self.camera")
                or "take_photo" in lowered
                or "recognize_number" in lowered
            )

            if is_camera_tool:
                # 标记工具运行中，避免连接空闲被关闭
                try:
                    conn._tool_running = True
                    # 重置收到请求标记
                    conn.vision_request_received = False
                except Exception:
                    pass
                # 启动独立保活任务（与轮询内保活解耦），确保即便轮询阻塞也能定期发送提示
                vision_cfg_bg = (conn.config.get("vision", {}) or {})
                keepalive_every_bg = int(vision_cfg_bg.get("keepalive_interval", 7))
                # 首次保活提前到 3 秒，避免前 7 秒完全静默（设备侧可能误判失联）
                first_keepalive_delay = int(vision_cfg_bg.get("keepalive_first_delay", 3))
                # 根据视觉超时动态计算保活次数（未显式配置时）
                try:
                    vision_timeout_cfg = int((vision_cfg_bg or {}).get("timeout_seconds", 45))
                except Exception:
                    vision_timeout_cfg = 45
                try:
                    keepalive_max_bg = int(vision_cfg_bg.get("keepalive_max"))
                except Exception:
                    # 至少能覆盖整个视觉超时窗口，多加余量3次
                    import math as _m
                    keepalive_max_bg = max(6, int(_m.ceil(vision_timeout_cfg / max(1, keepalive_every_bg)) + 3))
                # 用户要求移除“我还在分析...”这类干扰提示，这里默认置空
                keepalive_text_bg = ""
                # 若之前残留任务，先取消
                old_task = getattr(conn, "_vision_keepalive_task", None)
                if old_task and not old_task.done():
                    try:
                        old_task.cancel()
                    except Exception:
                        pass
                async def _vision_keepalive_loop():
                    sent = 0
                    loop_time = asyncio.get_event_loop().time()
                    last_sent = loop_time
                    first_sent_done = False
                    try:
                        while (not conn.stop_event.is_set()) and (not getattr(conn, "_vision_final_sent", False)) and sent < keepalive_max_bg:
                            nowt = asyncio.get_event_loop().time()
                            should_send = False
                            if not first_sent_done and (nowt - last_sent) >= first_keepalive_delay:
                                should_send = True
                                first_sent_done = True
                            elif first_sent_done and (nowt - last_sent) >= keepalive_every_bg:
                                should_send = True
                            if should_send:
                                try:
                                    if hasattr(conn, "tts") and conn.tts is not None:
                                        # 使用一次性单句TTS，确保立即合成并发送音频
                                        _text = keepalive_text_bg
                                        try:
                                            if _text and _text[-1] not in ["。","！","!","？","?","；",";","，",","]:
                                                _text = _text + "。"
                                        except Exception:
                                            pass
                                        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=_text)
                                        # 刷新活动时间戳，降低被动清理风险
                                        try:
                                            import time as _lt
                                            conn.last_activity_time = _lt.time() * 1000
                                        except Exception:
                                            pass
                                        sent += 1
                                        last_sent = nowt
                                        try:
                                            conn.logger.info(f"视觉保活提示已发送({sent}/{keepalive_max_bg})")
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            await asyncio.sleep(1.0)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                try:
                    conn._vision_keepalive_task = asyncio.create_task(_vision_keepalive_loop())
                except Exception:
                    pass
                # 1) 直接发送 tools/call，不注册等待future
                try:
                    tool_call_id = await conn.mcp_client.get_next_id()
                    actual_name = conn.mcp_client.name_mapping.get(tool_name, tool_name)
                    
                    # 构造参数，注入 timeoutMs 以防止设备端提前超时
                    call_args = json.loads(args_str)
                    if not isinstance(call_args, dict):
                        call_args = {}
                    
                    # [Fix] Extract operation type from arguments before using it
                    op_type = call_args.get("operation", "")

                    # 注入超时参数：使用计算出的 timeout (秒) * 1000，并增加一点余量
                    # 确保设备端等待时间略长于服务器端等待时间，避免设备端先断开
                    
                    payload = {
                        "jsonrpc": "2.0",
                        "id": tool_call_id,
                        "method": "tools/call",
                        "params": {
                            "name": actual_name, 
                            "arguments": call_args,
                            "timeoutMs": (timeout + 5) * 1000
                        },
                    }
                    
                    # ----------------------------------------------------
                    # 【修复】轮询重试逻辑：如果遇到 "System is busy" 则在 10s 内不断重试
                    # ----------------------------------------------------
                    import time as _tt
                    start_poll = _tt.time()
                    retry_count = 0
                    final_result = None
                    last_error_msg = ""
                    
                    # 初始化 MCP Future
                    fut = asyncio.get_event_loop().create_future()
                    await conn.mcp_client.register_call_result_future(tool_call_id, fut)

                    # 首次发送
                    await send_mcp_message(conn, payload)
                    
                    while True:
                        # [Added] 实时检查打断标记，确保语音介入时能立即终止轮询
                        if getattr(conn, "client_abort", False):
                            logger.bind(tag=TAG).info("检测到 client_abort，终止MCP轮询")
                            raise asyncio.CancelledError("Client aborted")

                        try:
                            # 每次等待较短时间
                            # [Modified] 对于合并拍照（长耗时任务），需要保持 Future 活跃，不轻易销毁
                            # 仅 wait_for 等待结果，不 shield，允许超时进入 except 分支
                            poll_res = await asyncio.wait_for(fut, timeout=2.0)
                            
                            # 检查结果
                            is_busy = False
                            if isinstance(poll_res, dict) and poll_res.get("success") is False:
                                msg = poll_res.get("message", "")
                                if "System is busy" in msg:
                                    is_busy = True
                            
                            if is_busy:
                                # [Modified] 延长重试窗口到 30s，并采用指数退避
                                if _tt.time() - start_poll < 30.0:
                                    retry_count += 1
                                    logger.bind(tag=TAG).info(f"设备忙，重试 ({retry_count})...")
                                    await conn.mcp_client.cleanup_call_result(tool_call_id)
                                    tool_call_id = await conn.mcp_client.get_next_id()
                                    payload["id"] = tool_call_id
                                    # [Fixed] 修复 id 更新后 payload 内的 id 未同步的问题
                                    fut = asyncio.get_event_loop().create_future()
                                    await conn.mcp_client.register_call_result_future(tool_call_id, fut)
                                    # 指数退避：1s, 2s, 3s... 最大 3s
                                    wait_time = min(3.0, 1.0 * retry_count)

                                    # [Fixed] 使用循环检查打断标记，实现快速响应，避免死等sleep
                                    for _ in range(int(wait_time * 10)):
                                        if getattr(conn, "client_abort", False) or (hasattr(conn, "stop_event") and conn.stop_event.is_set()):
                                            logger.bind(tag=TAG).info("检测到 client_abort，停止重试并终止")
                                            raise asyncio.CancelledError("Client aborted")
                                        await asyncio.sleep(0.1)
                                        
                                    await send_mcp_message(conn, payload)
                                    continue
                                else:
                                    final_result = poll_res
                                    break
                            else:
                                final_result = poll_res
                                
                                # [Added] 额外检查：如果是拍照相关指令且结果是空的或无效，但并非 busy，可能是设备发送了空响应
                                if is_camera_tool and isinstance(final_result, dict) and not final_result.get("content"):
                                    # 不立即退出，而是稍微等待或视为需要重试（视具体设备行为而定）
                                    # 但此处还是尊重返回结果
                                    pass
                                    
                                break
                                
                        except asyncio.TimeoutError:
                            # [Added] 每次轮询超时也检查是否已完成视觉发送，避免死等设备MCP响应
                            if getattr(conn, "_vision_final_sent", False):
                                logger.bind(tag=TAG).info("检测到视觉结果已发送，提前结束MCP轮询")
                                await conn.mcp_client.cleanup_call_result(tool_call_id)
                                return ActionResponse(action=Action.RESPONSE, response="")
                            
                            # [Added for Vision] 如果是 merge_and_analyze 操作，超时通常是因为用户拍摄耗时较长（300s以内）
                            # 此时不应视为失败，而是继续轮询，直到总超时
                            if op_type == "merge_and_analyze":
                                logger.bind(tag=TAG).debug("merge_and_analyze timeout, continuing poll...")
                                # 如果总时间未超，继续循环
                                continue

                            if _tt.time() - start_poll > timeout:
                                # [Added] 超时前最后一次检查，如果已经收到过图片（vision_handler），则不抛出异常
                                if getattr(conn, "_vision_final_sent", False):
                                     logger.bind(tag=TAG).info("检测到视觉结果已发送，忽略MCP执行超时")
                                     await conn.mcp_client.cleanup_call_result(tool_call_id)
                                     return ActionResponse(action=Action.RESPONSE, response="")
                                raise 
                            continue

                    await conn.mcp_client.cleanup_call_result(tool_call_id)
                    result = final_result

                    # ----------------------------------------------------
                    # 【修复】拦截 "System is busy" 或 "canceled by user" 并终止流程，防止后续无效轮询
                    # ----------------------------------------------------
                    _is_failed = False
                    _fail_msg = ""
                    
                    # 检查是否直接是 dict 且 success is False
                    if isinstance(result, dict) and result.get("success") is False:
                        _is_failed = True
                        _fail_msg = result.get("message", "")
                        
                    # 检查 content 内部是否包含 success: false 的 JSON 字符串
                    # result: {'content': [{'type': 'text', 'text': '{"success": false, "message": "canceled by user"}'}], 'isError': False}
                    if not _is_failed and isinstance(result, dict) and result.get("content"):
                        try:
                            content_list = result.get("content")
                            if isinstance(content_list, list) and len(content_list) > 0:
                                first_item = content_list[0]
                                if isinstance(first_item, dict) and first_item.get("type") == "text":
                                    text_val = first_item.get("text", "")
                                    if '"success": false' in text_val or '"success":false' in text_val:
                                        import json as _sub_json
                                        try:
                                            _inner = _sub_json.loads(text_val)
                                            if isinstance(_inner, dict) and _inner.get("success") is False:
                                                _is_failed = True
                                                _fail_msg = _inner.get("message", "")
                                        except Exception:
                                            pass
                        except Exception:
                            pass
                    
                    if _is_failed:
                         # 清理后台任务
                         try:
                            conn._tool_running = False
                            for attr in ["_vision_keepalive_task", "_vision_retry_task"]:
                                if hasattr(conn, attr):
                                    t = getattr(conn, attr)
                                    if t and not t.done():
                                        t.cancel()
                         except Exception:
                            pass
                         
                         # 若是忙碌，则尝试复位设备
                         if "System is busy" in _fail_msg:
                             try:
                                 asyncio.create_task(send_mcp_initialize_message(conn))
                             except Exception:
                                 pass

                         # 返回 Action.RESPONSE (非 ERROR)，终止 LLM 重试
                         logger.bind(tag=TAG).warning(f"设备返回失败，终止工具执行: {_fail_msg}")
                         
                         # 针对 canceled by user 优化提示
                         if "canceled" in _fail_msg.lower():
                             return ActionResponse(action=Action.RESPONSE, response="操作已取消")
                         
                         return ActionResponse(action=Action.RESPONSE, response=f"设备繁忙 ({_fail_msg})，请稍后再试")
                    
                    if result is None:
                         raise asyncio.TimeoutError("Polling finished without result")

                except Exception as _se:
                    if isinstance(_se, asyncio.TimeoutError):
                        raise _se 
                    return ActionResponse(action=Action.ERROR, response=f"MCP工具调用失败: {str(_se)}")

                # 1.1) 发送一次“处理中”提示
                try:
                    vision_cfg = conn.config.get("vision", {}) or {}
                    keepalive_hint = vision_cfg.get("keepalive_hint", True)
                    # 默认置空，不再播报"我在分析这...."
                    hint_text = vision_cfg.get("keepalive_text") or ""
                    if keepalive_hint and hint_text and hasattr(conn, "tts") and conn.tts is not None:
                        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=hint_text)
                        # 发送第一条保活提示时也刷新活跃时间
                        try:
                            import time as _t
                            conn.last_activity_time = _t.time() * 1000
                        except Exception:
                            pass
                        # 安排一个未收到照片的重试任务（仅一次），避免设备端未成功上传导致静默
                        async def _retry_if_no_photo():
                            try:
                                await asyncio.sleep(int(vision_cfg.get("no_photo_retry_seconds", 15)))
                                # 若此时仍未标记结果已发送且连接未关闭，则提示重新举起并再发一次工具调用
                                if not getattr(conn, "_vision_final_sent", False) and not conn.stop_event.is_set():
                                    # 关键检查：如果已经收到了视觉请求（正在处理中），则不要触发重试
                                    if getattr(conn, "vision_request_received", False):
                                        return

                                    try:
                                        retry_text = vision_cfg.get("no_photo_retry_text") or "还没有收到照片，请重新举起试卷，我再拍一次"
                                        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=retry_text)
                                        # 再次刷新活动时间
                                        try:
                                            import time as _t2
                                            conn.last_activity_time = _t2.time() * 1000
                                        except Exception:
                                            pass
                                        # 重新发起一次工具调用（限一次）
                                        if not getattr(conn, "_camera_tool_retried", False):
                                            conn._camera_tool_retried = True
                                            try:
                                                new_id = await conn.mcp_client.get_next_id()
                                                
                                                # 同样注入超时参数
                                                retry_args = json.loads(args_str)
                                                if not isinstance(retry_args, dict):
                                                    retry_args = {}
                                                
                                                retry_payload = {
                                                    "jsonrpc": "2.0",
                                                    "id": new_id,
                                                    "method": "tools/call",
                                                    "params": {
                                                        "name": actual_name, 
                                                        "arguments": retry_args,
                                                        "timeoutMs": (timeout + 5) * 1000
                                                    },
                                                }
                                                await send_mcp_message(conn, retry_payload)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        try:
                            conn._vision_retry_task = asyncio.create_task(_retry_if_no_photo())
                        except Exception:
                            pass
                except Exception:
                    pass

                # 2) 轮询 data/vision_records/<YYYYMMDD> 目录，查找包含 client_id 前8位的最新 .json
                try:
                    cid = (conn.headers.get("client-id", "") or "")[:8]
                    student_id = getattr(conn, "student_id", None) or ""
                    start_time = datetime.now()
                    vision_root = os.path.abspath(os.path.join(os.getcwd(), "data", "vision_records"))
                    day_dir = os.path.join(vision_root, start_time.strftime("%Y%m%d"))
                    # 以视觉配置的超时为准，适度上浮，最大不超过60秒
                    try:
                        vision_timeout = int((conn.config.get("vision", {}) or {}).get("timeout_seconds", 30))
                    except Exception:
                        vision_timeout = 30
                    poll_budget = min(max(vision_timeout + 10, 15), 60)
                    deadline = start_time + timedelta(seconds=poll_budget)

                    # 定期“保活提示”的参数（避免长时间静默被对端判定断开）
                    vision_cfg_local = (conn.config.get("vision", {}) or {})
                    # 再次缩短默认保活间隔为 7 秒，支持通过 vision.keepalive_interval 覆盖
                    keepalive_every = int(vision_cfg_local.get("keepalive_interval", 7))
                    # 增加保活次数上限，默认 6 次，支持 vision.keepalive_max 覆盖
                    try:
                        keepalive_max = int(vision_cfg_local.get("keepalive_max", 6))
                    except Exception:
                        keepalive_max = 6
                    keepalive_text2 = vision_cfg_local.get("keepalive_text2") or "我还在分析，请再等一下"
                    last_keepalive = start_time
                    keepalive_sent = 0

                    last_seen = None
                    # [Added] Double check before polling loop
                    if getattr(conn, "_vision_final_sent", False):
                        return ActionResponse(action=Action.RESPONSE, response="")

                    while datetime.now() < deadline:
                        # [Added] check inside polling loop
                        if getattr(conn, "_vision_final_sent", False):
                            return ActionResponse(action=Action.RESPONSE, response="")

                        try:
                            if not os.path.isdir(day_dir):
                                await asyncio.sleep(0.4)
                                continue
                            # 找到最新的匹配文件
                            candidates = [
                                f for f in os.listdir(day_dir)
                                if f.endswith('.json') and (cid == '' or cid in f)
                            ]
                            if candidates:
                                # 按修改时间排序
                                candidates.sort(key=lambda fn: os.path.getmtime(os.path.join(day_dir, fn)), reverse=True)
                                for fn in candidates[:5]:
                                    path = os.path.join(day_dir, fn)
                                    try:
                                        mtime = datetime.fromtimestamp(os.path.getmtime(path))
                                        if mtime + timedelta(seconds=2) < start_time:
                                            # 早于本次调用，跳过
                                            continue
                                        # 读取JSON并校验基本字段
                                        with open(path, "r", encoding="utf-8") as jf:
                                            data = json.load(jf)
                                        if not isinstance(data, dict):
                                            continue
                                        if data.get("success") is True and data.get("action") == Action.RESPONSE.name:
                                            # 学号匹配优先（若可用）
                                            if student_id and data.get("student_id") and data.get("student_id") != student_id:
                                                continue
                                            resp_txt = data.get("response") or ""
                                            if resp_txt:
                                                # 成功获取结果，取消重试任务并标记完成
                                                try:
                                                    conn._vision_final_sent = True
                                                    if hasattr(conn, "_vision_retry_task"):
                                                        rt = conn._vision_retry_task
                                                        if rt and not rt.done():
                                                            rt.cancel()
                                                except Exception:
                                                    pass

                                                # 找到结果后，额外等待2秒，确保设备端完成HTTP响应处理和状态复位
                                                # 避免连续调用时设备端报 "System is busy"
                                                await asyncio.sleep(2.0)
                                                return ActionResponse(action=Action.RESPONSE, response=resp_txt)
                                    except Exception:
                                        continue
                            await asyncio.sleep(0.3)
                        except Exception:
                            await asyncio.sleep(0.5)
                        # (已移除) 定期发送保活提示已移至 _vision_keepalive_loop 独立任务中统一处理，避免双重发送
                        pass
                    # 若轮询未命中，继续走标准等待（退回原逻辑）
                except Exception as e:
                    logger.bind(tag=TAG).error(f"视觉结果轮询异常: {e}")
                    pass

                # 3) 回退：缩短等待时间，尽快返回给用户可理解的错误信息
                # [Fix] 如果已经收到视觉请求（照片），绝对不要触发回退重试，直接等待处理结果即可
                if getattr(conn, "vision_request_received", False):
                    logger.bind(tag=TAG).info("已收到视觉请求，跳过MCP回退重试")
                    # 等待一下，让处理流程自然完成或超时
                    remaining = max(5, vision_timeout - 15)
                    await asyncio.sleep(remaining)
                    # 如果还是没拿到最终结果，可能是处理卡死，返回提示
                    if not getattr(conn, "_vision_final_sent", False):
                         return ActionResponse(action=Action.RESPONSE, response="照片正在处理中，请稍候...")
                    return ActionResponse(action=Action.RESPONSE, response="")

                fallback_wait = min(30, vision_timeout)
                try:
                    result = await call_mcp_tool(
                        conn, conn.mcp_client, tool_name, args_str, timeout=fallback_wait, skip_check=skip_check
                    )
                except Exception as _ce:
                    return ActionResponse(action=Action.ERROR, response=str(_ce))

                # 若返回的是{"success":false,...}这类JSON，直接转换为错误回复，避免再次REQLLM
                if isinstance(result, str):
                    try:
                        _tmp = json.loads(result)
                        if isinstance(_tmp, dict) and _tmp.get("success") is False:
                            msg = _tmp.get("message") or "视觉分析失败，请稍后重试"
                            return ActionResponse(action=Action.ERROR, response=msg)
                    except Exception:
                        pass
            else:
                # 非相机工具按原逻辑执行
                # 调用设备端MCP工具，遇到设备繁忙（Another tool is running）时短暂重试一次
                async def _invoke_once() -> str:
                    return await call_mcp_tool(
                        conn, conn.mcp_client, tool_name, args_str, timeout=timeout, skip_check=skip_check
                    )

                result = await _invoke_once()
                if isinstance(result, str) and "Another tool is running" in result:
                    try:
                        import asyncio as _asyncio
                        await _asyncio.sleep(2.0)
                        result = await _invoke_once()
                    except Exception:
                        pass

            resultJson = None
            if isinstance(result, str):
                try:
                    resultJson = json.loads(result)
                except Exception as e:
                    pass

            # 视觉大模型不经过二次LLM处理
            if (
                resultJson is not None
                and isinstance(resultJson, dict)
                and "action" in resultJson
            ):
                # 对视觉类工具的 Action.RESPONSE 采用分段播报，避免缺失 LAST
                action_name = resultJson.get("action")
                response_text = resultJson.get("response", "")
                if action_name == Action.RESPONSE.name and is_camera_tool and response_text:
                    try:
                        # ==========================================================
                        # 新增逻辑：如果字数大于100，则直接返回文本文字内容，不合成为语音
                        # ==========================================================
                        if len(response_text) > 100:
                            if conn.websocket and conn.ws_open:
                                try:
                                    import json as _json_mod
                                    asyncio.create_task(conn.websocket.send(_json_mod.dumps({"type": "tts", "state": "start"})))
                                    asyncio.create_task(conn.websocket.send(_json_mod.dumps({
                                        "type": "tts", 
                                        "state": "sentence_start", 
                                        "text": response_text
                                    }, ensure_ascii=False)))
                                    
                                    # [Fixed] 使用长延时 + 状态检查，确保设备有足够时间显示大段文本，避免Stop过快
                                    # 并防止重复播报逻辑被触发
                                    await asyncio.sleep(0.5)
                                    asyncio.create_task(conn.websocket.send(_json_mod.dumps({"type": "tts", "state": "stop"})))
                                    
                                    # [Critical] 一定要标记 vision_inflight 为 False，并标记 final_sent
                                    try:
                                        conn._vision_inflight = False
                                        conn._vision_final_sent = True
                                    except Exception:
                                        pass
                                        
                                    # [Critical] 一定要清除 resultJson 中的 action，防止上层把它当做 Action.RESPONSE 处理
                                    # 从而再次调用 conn._speak_vision_response 或其他逻辑
                                    resultJson["action"] = "HANDLED"
                                    
                                    # 同样需要写入对话历史，否则前端看不到
                                    try:
                                        from core.utils.dialogue import Message
                                        conn.dialogue.put(Message(role="assistant", content=response_text))
                                        conn._append_conversation_event(
                                            question=conn._get_last_user_content(),
                                            reply=response_text,
                                            source="realtime",
                                        )
                                    except Exception:
                                        pass
                                except Exception as e:
                                    pass
                        else:
                             conn._speak_vision_response(response_text)
                        # 播报完成，清理保活与运行标记
                        try:
                            if hasattr(conn, "_vision_keepalive_task"):
                                t = conn._vision_keepalive_task
                                if t and not t.done():
                                    t.cancel()
                        except Exception:
                            pass
                        try:
                            conn._tool_running = False
                        except Exception:
                            pass
                        # 结束后补一个 LAST 安全尾声（若 TTS 当前对话未发送 LAST）
                        try:
                            if hasattr(conn, "tts") and conn.tts:
                                conn.tts.tts_text_queue.put(
                                    TTSMessageDTO(
                                        sentence_id=getattr(conn, "sentence_id", conn.session_id),
                                        sentence_type=SentenceType.LAST,
                                        content_type=ContentType.ACTION,
                                    )
                                )
                        except Exception:
                            pass
                        return ActionResponse(action=Action.RESPONSE, response="")
                    except Exception:
                        # 失败则回退普通处理
                        pass
                
                # 如果 action 被篡改为 HANDLED，则返回 Action.NONE 或空 RESPONSE，避免上层朗读
                if resultJson.get("action") == "HANDLED":
                    return ActionResponse(action=Action.RESPONSE, response=None)

                return ActionResponse(
                    action=Action[action_name],
                    response=response_text,
                )

            return ActionResponse(action=Action.REQLLM, result=str(result))

        except ValueError as e:
            try:
                conn._tool_running = False
                if hasattr(conn, "_vision_keepalive_task"):
                    t = conn._vision_keepalive_task
                    if t and not t.done():
                        t.cancel()
            except Exception:
                pass
            return ActionResponse(action=Action.NOTFOUND, response=str(e))
        except TimeoutError as e:
            # 超时信息明确化，便于上层TTS提示
            try:
                conn._tool_running = False
                if hasattr(conn, "_vision_keepalive_task"):
                    t = conn._vision_keepalive_task
                    if t and not t.done():
                        t.cancel()
            except Exception:
                pass
            return ActionResponse(
                action=Action.ERROR,
                response=f"{str(e)}（工具: {tool_name}，已等待{timeout}s）",
            )
        except Exception as e:
            try:
                conn._tool_running = False
                if hasattr(conn, "_vision_keepalive_task"):
                    t = conn._vision_keepalive_task
                    if t and not t.done():
                        t.cancel()
            except Exception:
                pass
            return ActionResponse(action=Action.ERROR, response=str(e))

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return {}

        tools = {}
        mcp_tools = self.conn.mcp_client.get_available_tools()

        for tool in mcp_tools:
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")

            if tool_name:
                tools[tool_name] = ToolDefinition(
                    name=tool_name, description=tool, tool_type=ToolType.DEVICE_MCP
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return False

        return self.conn.mcp_client.has_tool(tool_name)
