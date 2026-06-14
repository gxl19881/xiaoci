import json
import asyncio
from core.providers.tools.device_mcp.mcp_handler import send_mcp_initialize_message

TAG = __name__


async def handleAbortMessage(conn):
    conn.logger.bind(tag=TAG).info("Abort message received")
    # 设置成打断状态，会自动打断llm、tts任务
    conn.client_abort = True

    # ==========================================================
    # 深度清理：停止多模态任务、MCP轮询、释放设备端资源
    # ==========================================================
    try:
        # 1. 标记工具停止运行
        conn._tool_running = False
        
        # 2. 取消视觉保活/重试任务
        for attr in ["_vision_keepalive_task", "_vision_retry_task"]:
            if hasattr(conn, attr):
                t = getattr(conn, attr)
                if t and not t.done():
                    t.cancel()
        
        # 3. 如果有 MCP 客户端，发送初始化/重置消息以释放设备端内存和状态
        # (这会重置设备端的 Camera/Audio 状态机)
        if hasattr(conn, "mcp_client") and conn.mcp_client:
             asyncio.create_task(send_mcp_initialize_message(conn))

    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"Error cleaning up MCP/Device tasks: {e}")

    # 取消兜底静默触发任务，避免未await协程告警与误触发
    try:
        old = getattr(conn, "_silence_trigger_task", None)
        if old and not old.done():
            old.cancel()
    except Exception:
        pass
    conn.clear_queues()
    # 打断客户端说话状态
    try:
        await conn.websocket.send(
            json.dumps({"type": "tts", "state": "stop", "session_id": conn.session_id})
        )
    except Exception:
        pass

    conn.clearSpeakStatus()
    conn.logger.bind(tag=TAG).info("Abort message received-end")
