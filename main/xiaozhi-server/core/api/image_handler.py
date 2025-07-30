import os
import json
import base64
import time
import mimetypes
from datetime import datetime
from aiohttp import web
from core.api.base_handler import BaseHandler
from core.utils.util import get_local_ip

TAG = __name__


class ImageUploadHandler(BaseHandler):
    def __init__(self, config: dict):
        super().__init__(config)
        self.max_file_size = 5 * 1024 * 1024  # 5MB
        self.allowed_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
        
        # 设置本地存储路径
        self.upload_dir = self._get_upload_directory()
        self._ensure_upload_directory()

    def _get_upload_directory(self):
        """获取上传目录路径"""
        server_config = self.config.get("server", {})
        upload_dir = server_config.get("upload_dir", "uploads")
        
        # 如果是相对路径，则相对于项目根目录
        if not os.path.isabs(upload_dir):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            upload_dir = os.path.join(project_root, upload_dir)
        
        return upload_dir

    def _ensure_upload_directory(self):
        """确保上传目录存在"""
        try:
            os.makedirs(self.upload_dir, exist_ok=True)
            date_dir = os.path.join(self.upload_dir, datetime.now().strftime('%Y-%m-%d'))
            os.makedirs(date_dir, exist_ok=True)
            self.logger.bind(tag=TAG).info(f"上传目录已准备: {self.upload_dir}")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"创建上传目录失败: {e}")
            raise e

    def _get_file_url(self, relative_path):
        """生成文件访问URL"""
        server_config = self.config.get("server", {})
        local_ip = get_local_ip()
        port = int(server_config.get("port", 8000))
        http_port = server_config.get("http_port", port + 3)
        
        return f"http://{local_ip}:{http_port}/uploads/{relative_path}"

    async def handle_post(self, request):
        """处理图片上传 POST 请求"""
        try:
            self.logger.bind(tag=TAG).info("收到图片上传请求")
            self.logger.bind(tag=TAG).debug(f"请求头: {dict(request.headers)}")
            
            content_type = request.content_type
            self.logger.bind(tag=TAG).debug(f"Content-Type: {content_type}")

            if content_type == 'application/json':
                return await self._handle_base64_upload(request)
            elif content_type and content_type.startswith('multipart/form-data'):
                return await self._handle_multipart_upload(request)
            else:
                return self._error_response("不支持的内容类型，请使用 multipart/form-data 或 application/json", 400)

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"图片上传异常: {e}")
            return self._error_response(f"上传失败: {str(e)}", 500)

    async def handle_get(self, request):
        """处理图片上传 GET 请求"""
        try:
            local_ip = get_local_ip()
            server_config = self.config.get("server", {})
            http_port = server_config.get("http_port", 8003)
            
            info = {
                "service": "Image Upload API",
                "version": "1.0.0",
                "storage": "local",
                "upload_directory": self.upload_dir,
                "endpoints": {
                    "upload": {
                        "method": "POST",
                        "url": f"http://{local_ip}:{http_port}/api/upload/image",
                        "supported_formats": ["multipart/form-data", "application/json (base64)"],
                        "max_file_size": "5MB",
                        "allowed_types": list(self.allowed_extensions)
                    },
                    "access": {
                        "method": "GET",
                        "url": f"http://{local_ip}:{http_port}/uploads/{{filename}}",
                        "description": "访问上传的图片"
                    }
                },
                "examples": {
                    "multipart": f"curl -X POST -F 'image=@image.jpg' http://{local_ip}:{http_port}/api/upload/image",
                    "json": f"curl -X POST -H 'Content-Type: application/json' -d '{{\"image\":\"base64data\",\"filename\":\"test.jpg\"}}' http://{local_ip}:{http_port}/api/upload/image"
                }
            }
            
            response = web.json_response(info)
            self._add_cors_headers(response)
            return response
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"GET请求异常: {e}")
            return self._error_response("接口信息获取失败", 500)

    async def _handle_base64_upload(self, request):
        """处理 base64 格式的图片上传"""
        try:
            body = await request.json()
            self.logger.bind(tag=TAG).debug("处理 base64 格式上传")
            
            if 'image' not in body:
                return self._error_response("缺少图片数据", 400)

            image_data = body['image']
            filename = body.get('filename', f'upload_{int(time.time())}.jpg')
            
            if image_data.startswith('data:image'):
                image_data = image_data.split(',')[1]
            
            try:
                image_bytes = base64.b64decode(image_data)
                self.logger.bind(tag=TAG).debug(f"base64 解码成功，图片大小: {len(image_bytes)} bytes")
            except Exception as e:
                return self._error_response("无效的 base64 图片数据", 400)

            validation_result = self._validate_image(image_bytes, filename)
            if validation_result is not True:
                return validation_result

            return await self._save_to_local(image_bytes, filename)

        except json.JSONDecodeError:
            return self._error_response("无效的 JSON 格式", 400)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"base64 上传处理异常: {e}")
            return self._error_response(f"处理失败: {str(e)}", 500)

    async def _handle_multipart_upload(self, request):
        """处理 multipart/form-data 格式的图片上传"""
        try:
            self.logger.bind(tag=TAG).debug("处理 multipart 格式上传")
            reader = await request.multipart()
            
            async for part in reader:
                if part.name == 'image':
                    filename = part.filename or f'upload_{int(time.time())}.jpg'
                    self.logger.bind(tag=TAG).debug(f"接收文件: {filename}")
                    
                    image_bytes = await part.read()
                    self.logger.bind(tag=TAG).debug(f"文件大小: {len(image_bytes)} bytes")

                    validation_result = self._validate_image(image_bytes, filename)
                    if validation_result is not True:
                        return validation_result

                    return await self._save_to_local(image_bytes, filename)

            return self._error_response("未找到图片文件，请确保字段名为 'image'", 400)

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"multipart 上传处理异常: {e}")
            return self._error_response(f"处理失败: {str(e)}", 500)

    def _validate_image(self, image_bytes, filename):
        """验证图片文件"""
        if len(image_bytes) > self.max_file_size:
            return self._error_response(f"文件大小超过限制 ({self.max_file_size // (1024*1024)}MB)", 400)

        file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
        if file_extension not in self.allowed_extensions:
            return self._error_response(f"不支持的文件格式，支持的格式: {', '.join(self.allowed_extensions)}", 400)

        if not self._is_valid_image_header(image_bytes):
            return self._error_response("无效的图片文件", 400)

        return True

    def _is_valid_image_header(self, image_bytes):
        """验证是否为有效的图片文件头"""
        if len(image_bytes) < 12:
            return False
            
        if image_bytes.startswith(b'\xff\xd8\xff'):  # JPEG
            return True
        elif image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
            return True
        elif image_bytes.startswith(b'GIF8'):  # GIF
            return True
        elif image_bytes.startswith(b'RIFF') and b'WEBP' in image_bytes[:12]:  # WebP
            return True
        
        return False

    async def _save_to_local(self, image_bytes, filename):
        """保存图片到本地"""
        try:
            timestamp = int(time.time())
            file_extension = filename.split('.')[-1] if '.' in filename else 'jpg'
            safe_filename = f"{timestamp}_{filename}"
            
            date_str = datetime.now().strftime('%Y-%m-%d')
            date_dir = os.path.join(self.upload_dir, date_str)
            os.makedirs(date_dir, exist_ok=True)
            
            file_path = os.path.join(date_dir, safe_filename)
            relative_path = f"{date_str}/{safe_filename}"
            
            with open(file_path, 'wb') as f:
                f.write(image_bytes)
            
            self.logger.bind(tag=TAG).info(f"图片保存成功: {file_path}")
            
            file_url = self._get_file_url(relative_path)
            
            return_json = {
                "status": "success",
                "message": "图片上传成功",
                "data": {
                    "filename": filename,
                    "saved_filename": safe_filename,
                    "file_path": file_path,
                    "relative_path": relative_path,
                    "file_url": file_url,
                    "upload_time": datetime.now().isoformat(),
                    "file_size": len(image_bytes),
                    "mime_type": mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                }
            }
            
            response = web.json_response(return_json)
            self._add_cors_headers(response)
            return response
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"本地保存失败: {e}")
            return self._error_response(f"本地保存失败: {str(e)}", 500)

    def _error_response(self, message, status=400):
        """创建错误响应"""
        return_json = {
            "status": "error",
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        
        response = web.json_response(return_json, status=status)
        self._add_cors_headers(response)
        return response

    def _add_cors_headers(self, response):
        """添加 CORS 头"""
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

    async def handle_options(self, request):
        """处理 CORS 预检请求"""
        response = web.Response()
        self._add_cors_headers(response)
        response.headers['Access-Control-Max-Age'] = '86400'
        return response