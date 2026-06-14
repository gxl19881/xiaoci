import asyncio
import websockets
from config.logger import setup_logging
from core.connection import ConnectionHandler
from core.conn_registry import register as _connreg_register, unregister as _connreg_unregister
from config.config_loader import get_config_from_api
from core.utils.modules_initialize import initialize_modules
from core.utils.util import check_vad_update, check_asr_update
from core.utils.monitor import monitor

TAG = __name__


class WebSocketServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self.config_lock = asyncio.Lock()
        modules = initialize_modules(
            self.logger,
            self.config,
            "VAD" in self.config["selected_module"],
            "ASR" in self.config["selected_module"],
            "LLM" in self.config["selected_module"],
            False,
            "Memory" in self.config["selected_module"],
            "Intent" in self.config["selected_module"],
        )
        self._vad = modules["vad"] if "vad" in modules else None
        self._asr = modules["asr"] if "asr" in modules else None
        self._llm = modules["llm"] if "llm" in modules else None
        self._intent = modules["intent"] if "intent" in modules else None
        self._memory = modules["memory"] if "memory" in modules else None

        self.active_connections = set()

    async def start(self):
        server_config = self.config["server"]
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("port", 8000))

        # 设备端（ESP32 等）在拍照/上传期间可能无法及时响应 WebSocket 控制帧（ping/pong），
        # 为避免因未收到 pong 而提前断开，这里关闭库级 ping（依赖连接层的应用层保活与空闲超时逻辑）。
        async with websockets.serve(
            self._handle_connection,
            host,
            port,
            process_request=self._http_response,
            ping_interval=None,
            ping_timeout=None,
        ):
            await asyncio.Future()

    async def _handle_connection(self, websocket):
        """处理新连接，每次创建独立的ConnectionHandler"""
        try:
            # 尝试获取远端地址信息（websockets >=10 提供 .remote_address）
            remote = None
            if hasattr(websocket, "remote_address"):
                try:
                    remote = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
                except Exception:
                    remote = str(websocket.remote_address)
            monitor.on_connected(remote)
            # 记录连接建立日志并输出活跃连接数
            try:
                snap = monitor.snapshot(limit=0)
                active = snap.get("active", "?")
                total = snap.get("total_accepted", "?")
                self.logger.bind(tag=TAG).info(
                    f"新连接: {remote} | 当前活跃: {active} | 累计接入: {total}"
                )
            except Exception:
                pass
        except Exception:
            pass
        # 创建ConnectionHandler时传入当前server实例
        handler = ConnectionHandler(
            self.config,
            self._vad,
            self._asr,
            self._llm,
            self._memory,
            self._intent,
            self,  # 传入server实例
        )
        self.active_connections.add(handler)
        
        try:
            await handler.handle_connection(websocket)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理连接时出错: {e}")
        finally:
            # 确保从活动连接集合中移除
            self.active_connections.discard(handler)
            # 从全局注册表移除
            try:
                _connreg_unregister(handler)
            except Exception:
                pass
            # 强制关闭连接（如果还没有关闭的话）
            try:
                # 安全地检查WebSocket状态并关闭
                if hasattr(websocket, "closed") and not websocket.closed:
                    await websocket.close()
                elif hasattr(websocket, "state") and websocket.state.name != "CLOSED":
                    await websocket.close()
                else:
                    # 如果没有closed属性，直接尝试关闭
                    await websocket.close()
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"服务器端强制关闭连接时出错: {close_error}"
                )
            try:
                monitor.on_closed(remote, reason="server_cleanup")
                # 记录连接关闭日志并输出活跃/累计信息
                try:
                    snap = monitor.snapshot(limit=0)
                    active = snap.get("active", "?")
                    total_closed = snap.get("total_closed", "?")
                    self.logger.bind(tag=TAG).info(
                        f"连接关闭: {remote} | 原因: server_cleanup | 当前活跃: {active} | 累计关闭: {total_closed}"
                    )
                except Exception:
                    pass
            except Exception:
                pass

    async def _http_response(self, websocket, request_headers):
        # 检查是否为 WebSocket 升级请求
        if request_headers.headers.get("connection", "").lower() == "upgrade":
            # 如果是 WebSocket 请求，返回 None 允许握手继续
            return None
        else:
            # 如果是普通 HTTP 请求，返回 "server is running"
            return websocket.respond(200, "Server is running\n")

    async def update_config(self) -> bool:
        """更新服务器配置并重新初始化组件

        Returns:
            bool: 更新是否成功
        """
        try:
            async with self.config_lock:
                # 重新获取配置
                new_config = get_config_from_api(self.config)
                if new_config is None:
                    self.logger.bind(tag=TAG).error("获取新配置失败")
                    return False
                self.logger.bind(tag=TAG).info(f"获取新配置成功")
                # 检查 VAD 和 ASR 类型是否需要更新
                update_vad = check_vad_update(self.config, new_config)
                update_asr = check_asr_update(self.config, new_config)
                self.logger.bind(tag=TAG).info(
                    f"检查VAD和ASR类型是否需要更新: {update_vad} {update_asr}"
                )
                # 更新配置
                self.config = new_config
                # 重新初始化组件
                modules = initialize_modules(
                    self.logger,
                    new_config,
                    update_vad,
                    update_asr,
                    "LLM" in new_config["selected_module"],
                    False,
                    "Memory" in new_config["selected_module"],
                    "Intent" in new_config["selected_module"],
                )

                # 更新组件实例
                if "vad" in modules:
                    self._vad = modules["vad"]
                if "asr" in modules:
                    self._asr = modules["asr"]
                if "llm" in modules:
                    self._llm = modules["llm"]
                if "intent" in modules:
                    self._intent = modules["intent"]
                if "memory" in modules:
                    self._memory = modules["memory"]
                self.logger.bind(tag=TAG).info(f"更新配置任务执行完毕")
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新服务器配置失败: {str(e)}")
            return False
