import asyncio
from typing import Dict, Any

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from plugins_func.register import ActionResponse, Action

TAG = __name__


class CommandTextMessageHandler(TextMessageHandler):
    """通用命令消息处理器

    目前支持：
    - command == "device_take_photo_if_available" -> 优先调用设备端 MCP 的 self.camera.take_photo
    """

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.COMMAND

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        cmd = (msg_json.get("command") or "").strip().lower()
        reason = msg_json.get("reason")
        conn.logger.bind(tag=TAG).info(f"收到命令: {cmd}, reason={reason}")

        if cmd in ("device_take_photo_if_available", "take_photo", "camera_take_photo"):
            await self._handle_take_photo(conn)
        else:
            conn.logger.bind(tag=TAG).warning(f"未知命令: {cmd}")

    async def _handle_take_photo(self, conn) -> None:
        # 确认设备端MCP可用
        try:
            if not getattr(conn, "features", None) or not conn.features.get("mcp"):
                conn.logger.bind(tag=TAG).warning("客户端未声明支持MCP，忽略拍照命令")
                return
            if not hasattr(conn, "mcp_client") or conn.mcp_client is None:
                conn.logger.bind(tag=TAG).warning("MCP客户端未初始化，忽略拍照命令")
                return
            try:
                is_ready = await conn.mcp_client.is_ready()
            except Exception:
                is_ready = False
            if not is_ready:
                conn.logger.bind(tag=TAG).warning("MCP客户端未就绪，忽略拍照命令")
                return

            # 查找包含 take_photo 的设备工具（使用已清洗后的名称）
            cam_tool = None
            try:
                for name in (conn.mcp_client.tools or {}).keys():
                    if "take_photo" in str(name).lower():
                        cam_tool = name
                        break
            except Exception:
                cam_tool = None

            if not cam_tool:
                conn.logger.bind(tag=TAG).warning("未发现设备端拍照工具（*take_photo*），忽略命令")
                return

            # 通过统一工具管理器调用设备端MCP工具（异步调用，避免阻塞）
            async def _invoke():
                try:
                    result = await conn.func_handler.tool_manager.execute_tool(cam_tool, {})
                    if isinstance(result, ActionResponse):
                        if result.action in (Action.ERROR, Action.NOTFOUND):
                            conn.logger.bind(tag=TAG).warning(f"拍照命令执行返回: {result.action.name} {result.response or result.result}")
                        else:
                            conn.logger.bind(tag=TAG).info("拍照命令已下发（设备端保活与结果播报由执行器负责）")
                except Exception as e:
                    conn.logger.bind(tag=TAG).error(f"执行拍照工具失败: {e}")

            try:
                asyncio.create_task(_invoke())
            except Exception:
                await _invoke()
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"处理拍照命令异常: {e}")
