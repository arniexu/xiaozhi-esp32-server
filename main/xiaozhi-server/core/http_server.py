import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.api.image_handler import ImageUploadHandler
from core.api.agent_approval_handler import AgentApprovalHandler

TAG = __name__


class SimpleHttpServer:
    def __init__(self, config: dict, ws_server=None):
        self.config = config
        self.logger = setup_logging()
        self.ota_handler = OTAHandler(config)
        self.vision_handler = VisionHandler(config)
        self.image_upload_handler = ImageUploadHandler(config)
        # 授权端点需要 WebSocketServer.active_connections 找到在线设备
        self.agent_approval_handler = AgentApprovalHandler(config, ws_server)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址"""
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def _handle_root(self, request):
        """处理根路径请求"""
        response = web.Response(text="xiaozhi-server is running with image upload support")
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    async def _handle_cors_preflight(self, request):
        """处理CORS预检请求"""
        response = web.Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Max-Age'] = '86400'
        return response

    async def start(self):
        try:
            server_config = self.config["server"]
            host = server_config.get("ip", "0.0.0.0")
            port = int(server_config.get("http_port", 8003))

            self.logger.bind(tag=TAG).info(f"正在启动HTTP服务器 {host}:{port}")

            if port:
                app = web.Application()

                read_config_from_api = server_config.get("read_config_from_api", False)

                # 添加基础路由
                routes = []
                
                # 根路径
                routes.append(web.get("/", self._handle_root))
                
                # Vision相关路由
                routes.extend([
                    web.get("/mcp/vision/explain", self.vision_handler.handle_get),
                    web.post("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.options("/mcp/vision/explain", self._handle_cors_preflight),
                ])
                
                # 图片上传路由
                routes.extend([
                    web.post("/api/upload/image", self.image_upload_handler.handle_post),
                    web.get("/api/upload/image", self.image_upload_handler.handle_get),
                    web.options("/api/upload/image", self.image_upload_handler.handle_options),
                ])

                # 设备授权中继路由（authentication/xiaozhi-relay v2）
                routes.extend([
                    web.post("/api/agent/approval", self.agent_approval_handler.handle_post),
                    web.post("/api/agent/approval/cancel", self.agent_approval_handler.handle_cancel),
                    web.options("/api/agent/approval", self.agent_approval_handler.handle_options),
                    web.options("/api/agent/approval/cancel", self.agent_approval_handler.handle_options),
                ])

                if not read_config_from_api:
                    # OTA路由
                    routes.extend([
                        web.get("/xiaozhi/ota/", self.ota_handler.handle_get),
                        web.post("/xiaozhi/ota/", self.ota_handler.handle_post),
                        web.options("/xiaozhi/ota/", self._handle_cors_preflight),
                    ])

                # 添加所有路由
                app.add_routes(routes)
                
                # 添加静态文件服务 - 用于访问上传的图片
                try:
                    upload_dir = self.image_upload_handler.upload_dir
                    app.router.add_static('/uploads/', upload_dir, name='uploads')
                    self.logger.bind(tag=TAG).info(f"静态文件目录配置成功: {upload_dir}")
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"静态文件服务配置失败: {e}")

                # 运行服务
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, host, port)
                await site.start()
                
                self.logger.bind(tag=TAG).info(f"✅ HTTP服务器启动成功: http://{host}:{port}")
                self.logger.bind(tag=TAG).info(f"📤 图片上传接口: http://{host}:{port}/api/upload/image")
                self.logger.bind(tag=TAG).info(f"📁 静态文件访问: http://{host}:{port}/uploads/")

                # 保持服务运行
                try:
                    while True:
                        await asyncio.sleep(3600)
                except KeyboardInterrupt:
                    self.logger.bind(tag=TAG).info("服务器正在关闭...")
                    await runner.cleanup()
                    
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"HTTP服务器启动失败: {e}")
            raise e