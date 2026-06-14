import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.api.asr_http_handler import AsrHTTPHandler
from core.utils.monitor import monitor
from core.web.ui import WebUI

TAG = __name__


class SimpleHttpServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self.ota_handler = OTAHandler(config)
        self.vision_handler = VisionHandler(config)
        self.asr_http_handler = AsrHTTPHandler(config)
        self.web_ui = WebUI(config)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def start(self):
        server_config = self.config["server"]
        read_config_from_api = self.config.get("read_config_from_api", False)
        host = server_config.get("ip", "0.0.0.0")
        port = int(server_config.get("http_port", 8003))

        if port:
            # 提升上传体积上限，避免设备端上传图片时触发默认1MB限制导致连接中断
            # 默认改为20MB，如需更大请通过反向代理或data/.config.yaml的vision.max_upload_mb控制应用层限制
            app = web.Application(client_max_size=20 * 1024 * 1024)
            # 总是注册简单OTA接口，便于设备在任何模式下拉取服务器地址/配置
            app.add_routes(
                [
                    web.get("/xiaozhi/ota/", self.ota_handler.handle_get),
                    web.post("/xiaozhi/ota/", self.ota_handler.handle_post),
                    web.options("/xiaozhi/ota/", self.ota_handler.handle_post),
                ]
            )
            # 状态接口：监控当前连接与最近事件
            async def status_handler(request):
                limit = int(request.query.get("limit", 50))
                return web.json_response(monitor.snapshot(limit=limit))

            app.add_routes([web.get("/xiaozhi/status/", status_handler)])
            # 添加路由
            app.add_routes(
                [
                    web.get("/mcp/vision/explain", self.vision_handler.handle_get),
                    web.post("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.options("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.get("/mcp/vision/result", self.vision_handler.handle_result),
                    # Web UI ASR 转写接口
                    web.post("/web/asr/transcribe", self.asr_http_handler.handle_post),
                    web.options("/web/asr/transcribe", self.asr_http_handler.handle_options),
                    # Web UI 视觉聊天接口
                    web.post("/web/vision/chat", self.web_ui.vision_chat),
                    # Web UI 上传图片分析
                    web.get("/web/vision/upload", self.web_ui.upload_form),
                    web.post("/web/vision/upload", self.web_ui.upload_analyze),
                ]
            )

            # 简易 Web 页面与静态资源
            # 静态文件：映射 /static 到工作目录下 data 目录，便于直接访问保存的图片与 JSON
            async def static_handler(request):
                # 仅允许访问 data 下的文件
                # NOTE: 这里使用了 aiohttp 的 FileResponse 简化处理
                from aiohttp import web as _web
                import os as _os

                data_root = _os.path.abspath(_os.path.join(_os.getcwd(), "data"))
                tail = request.match_info.get("tail", "")
                abs_path = _os.path.abspath(_os.path.join(data_root, tail))
                if not abs_path.startswith(data_root + _os.sep) or not _os.path.isfile(abs_path):
                    raise _web.HTTPNotFound()
                return _web.FileResponse(abs_path)

            app.add_routes(
                [
                    web.get("/web", self.web_ui.index),
                    # 兼容带斜杠的访问路径 /web/
                    web.get("/web/", self.web_ui.index),
                    web.get("/web/vision", self.web_ui.vision_list),
                    web.get("/web/vision/present", self.web_ui.vision_present),
                    web.post("/web/vision/present/sync", self.web_ui.vision_present_sync),
                    web.post("/web/vision/delete", self.web_ui.vision_delete),
                    web.get("/web/generated", self.web_ui.generated_list),
                web.get("/web/generated/present", self.web_ui.generated_present),
                web.post("/web/generated/present/sync", self.web_ui.generated_present_sync),
                    web.post("/web/generated/delete", self.web_ui.generated_delete),
                    web.get("/web/generated/analyze", self.web_ui.generated_analyze),
                    web.post("/web/analysis/delete", self.web_ui.analysis_delete),
                    web.post("/web/vision/analyze", self.web_ui.re_analyze),
                    # 会话记录
                    web.get("/web/conversations", self.web_ui.conversations_page),
                    web.get("/web/conversations/view", self.web_ui.conversations_view),
                    web.post("/web/conversations/delete", self.web_ui.conversations_delete),
                    web.post("/web/conversations/analyze", self.web_ui.conversations_analyze),
                    web.post("/web/conversations/analyze_sids", self.web_ui.conversations_analyze_sids),
                    web.post("/web/conversations/analyze_selected", self.web_ui.conversations_analyze_selected),
                    web.get(r"/static/{tail:.*}", static_handler),
                ]
            )

            # 运行服务
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()

            # 保持服务运行
            while True:
                await asyncio.sleep(3600)  # 每隔 1 小时检查一次
