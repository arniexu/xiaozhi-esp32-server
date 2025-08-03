# Face Handle WebSocket API 文档 (更新版)

## 概述
Face Handle 是一个基于 WebSocket 的人脸识别接口，支持添加人员、查找人员、搜索人脸和列出所有人员功能。使用阿里云 Facebody 服务和 OSS 存储。

**更新**: 现在支持通过本地文件路径进行图片上传，而不是 base64 编码数据。

## WebSocket 连接
- **协议**: WebSocket
- **消息格式**: JSON
- **编码**: UTF-8

## 支持的操作

### 1. 添加人员 (add_face)
添加新的人员到人脸数据库

### 2. 查找人员 (find_face) 
查找最匹配的一个人员

### 3. 搜索人脸 (search_face)
高级搜索，支持返回多个匹配结果和置信度阈值过滤

### 4. 列出所有人员 (list_people)
列出数据库中的所有人员信息

## 详细 API 说明

### 1. 添加人员 (add_face)

#### 请求格式
```json
{
    "type": "face",
    "payload": {
        "action": "add_face",
        "person_name": "张三",
        "image_path": "/home/xuqianjin/face_20250804123456.jpg"
    }
}
```

**字段说明:**
- `type`: 必须为 "face"
- `payload.action`: 必须为 "add_face"
- `payload.person_name`: 人员姓名 (字符串)
- `payload.image_path`: 图片文件的绝对路径 (字符串)

#### 成功响应
```json
{
  "type": "face",
  "action": "add",
  "status": "success",
  "message": "成功添加人员: 张三",
  "data": {
    "name": "张三",
    "entity_id": "person_abc123",
    "oss_url": "https://faces-my-shanghai.oss-cn-shanghai.aliyuncs.com/faces/person_1691234567_person_abc123.jpg",
    "original_image_path": "/home/xuqianjin/face_20250804123456.jpg",
    "method": "alibaba_cloud_with_oss"
  }
}
```

#### 失败响应
```json
{
  "type": "face",
  "action": "add",
  "status": "error",
  "message": "图片文件不存在: /path/to/image.jpg"
}
```

**常见错误:**
- `"图片文件不存在: /path/to/image.jpg"` - 指定的文件路径不存在
- `"读取图片文件失败: Permission denied"` - 文件权限不足
- `"添加人员失败: OSS上传失败"` - OSS 服务异常

### 2. 查找人员 (find_face)

#### 请求格式
```json
{
    "type": "face",
    "payload": {
        "action": "find_face",
        "image_path": "/home/xuqianjin/search_face.jpg"
    }
}
```

**字段说明:**
- `type`: 必须为 "face"
- `payload.action`: 必须为 "find_face"
- `payload.image_path`: 图片文件的绝对路径 (字符串)

#### 成功响应 (找到匹配)
```json
{
  "type": "face",
  "action": "find",
  "status": "success",
  "message": "找到匹配的人员",
  "data": {
    "name": "张三",
    "entity_id": "person_abc123",
    "confidence": 0.95,
    "search_method": "alibaba_cloud_with_oss"
  }
}
```

#### 失败响应 (未找到匹配)
```json
{
  "type": "face",
  "action": "find",
  "status": "error",
  "message": "未找到匹配的人员",
  "data": {
    "search_method": "alibaba_cloud_with_oss"
  }
}
```

### 3. 搜索人脸 (search_face)

#### 请求格式
```json
{
    "type": "face",
    "payload": {
        "action": "search_face",
        "image_path": "/home/xuqianjin/search_20250804123456.jpg",
        "limit": 5,
        "threshold": 80.0
    }
}
```

**字段说明:**
- `type`: 必须为 "face"
- `payload.action`: 必须为 "search_face"
- `payload.image_path`: 图片文件的绝对路径 (字符串)
- `payload.limit`: 返回结果数量限制 (整数，可选，默认5)
- `payload.threshold`: 置信度阈值，0-100 (浮点数，可选，默认80.0)

#### 成功响应 (找到多个匹配)
```json
{
  "type": "face",
  "action": "search",
  "status": "success",
  "message": "找到 3 个匹配的人员",
  "data": {
    "count": 3,
    "threshold": 80.0,
    "limit": 5,
    "results": [
      {
        "name": "张三",
        "entity_id": "person_abc123",
        "confidence": 95.2,
        "rank": 1
      },
      {
        "name": "李四",
        "entity_id": "person_def456",
        "confidence": 87.8,
        "rank": 2
      },
      {
        "name": "王五",
        "entity_id": "person_ghi789",
        "confidence": 82.1,
        "rank": 3
      }
    ],
    "search_method": "alibaba_cloud_with_oss"
  }
}
```

#### 失败响应 (未找到匹配)
```json
{
  "type": "face",
  "action": "search",
  "status": "error",
  "message": "未找到置信度 >= 80.0 的匹配人员",
  "data": {
    "threshold": 80.0,
    "limit": 5,
    "search_method": "alibaba_cloud_with_oss"
  }
}
```

### 4. 列出所有人员 (list_people)

#### 请求格式
```json
{
    "type": "face",
    "payload": {
        "action": "list_people"
    }
}
```

**字段说明:**
- `type`: 必须为 "face"
- `payload.action`: 必须为 "list_people"

#### 成功响应
```json
{
  "type": "face",
  "action": "list",
  "status": "success",
  "message": "共找到 2 个人员",
  "data": {
    "count": 2,
    "people": [
      {
        "name": "张三",
        "entity_id": "person_abc123",
        "created_at": 1691234567
      },
      {
        "name": "李四",
        "entity_id": "person_def456",
        "created_at": 1691234568
      }
    ]
  }
}
```

## 使用示例

### JavaScript WebSocket 客户端

```javascript
// 建立 WebSocket 连接
const ws = new WebSocket('ws://localhost:8000/xiaozhi/v1/');

ws.onopen = function() {
    console.log('WebSocket 连接已建立');
};

ws.onmessage = function(event) {
    const response = JSON.parse(event.data);
    console.log('收到响应:', response);
};

ws.onerror = function(error) {
    console.error('WebSocket 错误:', error);
};

// 添加人员
function addPerson(name, imagePath) {
    const message = {
        type: "face",
        payload: {
            action: "add_face",
            person_name: name,
            image_path: imagePath
        }
    };
    ws.send(JSON.stringify(message));
}

// 查找人员 (单个最佳匹配)
function findPerson(imagePath) {
    const message = {
        type: "face",
        payload: {
            action: "find_face",
            image_path: imagePath
        }
    };
    ws.send(JSON.stringify(message));
}

// 搜索人脸 (多个匹配结果，支持阈值)
function searchFace(imagePath, limit = 5, threshold = 80.0) {
    const message = {
        type: "face",
        payload: {
            action: "search_face",
            image_path: imagePath,
            limit: limit,
            threshold: threshold
        }
    };
    ws.send(JSON.stringify(message));
}

// 列出所有人员
function listPeople() {
    const message = {
        type: "face",
        payload: {
            action: "list_people"
        }
    };
    ws.send(JSON.stringify(message));
}

// 使用示例
addPerson("张三", "/home/xuqianjin/face_20250804123456.jpg");
findPerson("/home/xuqianjin/search_face.jpg");
searchFace("/home/xuqianjin/search_face.jpg", 10, 75.0);  // 搜索10个结果，置信度>=75%
listPeople();
```

### Python WebSocket 客户端

```python
import asyncio
import websockets
import json

async def face_client():
    uri = "ws://localhost:8000/xiaozhi/v1/"
    
    async with websockets.connect(uri) as websocket:
        print("WebSocket 连接已建立")
        
        # 添加人员
        add_message = {
            "type": "face",
            "payload": {
                "action": "add_face",
                "person_name": "张三",
                "image_path": "/home/xuqianjin/face_20250804123456.jpg"
            }
        }
        await websocket.send(json.dumps(add_message))
        response = await websocket.recv()
        print("添加人员响应:", json.loads(response))
        
        # 查找人员 (单个最佳匹配)
        find_message = {
            "type": "face",
            "payload": {
                "action": "find_face",
                "image_path": "/home/xuqianjin/search_face.jpg"
            }
        }
        await websocket.send(json.dumps(find_message))
        response = await websocket.recv()
        print("查找人员响应:", json.loads(response))
        
        # 搜索人脸 (多个匹配结果，支持阈值)
        search_message = {
            "type": "face",
            "payload": {
                "action": "search_face",
                "image_path": "/home/xuqianjin/search_face.jpg",
                "limit": 10,
                "threshold": 75.0
            }
        }
        await websocket.send(json.dumps(search_message))
        response = await websocket.recv()
        print("搜索人脸响应:", json.loads(response))
        
        # 列出所有人员
        list_message = {
            "type": "face",
            "payload": {
                "action": "list_people"
            }
        }
        await websocket.send(json.dumps(list_message))
        response = await websocket.recv()
        print("列出人员响应:", json.loads(response))

# 运行客户端
asyncio.run(face_client())
```

## 技术实现

### 文件处理流程
1. **验证**: 检查图片文件路径是否存在
2. **读取**: 读取本地图片文件为二进制数据
3. **转换**: 将二进制数据转换为 base64 编码
4. **上传**: 上传到阿里云 OSS 获取公开 URL
5. **识别**: 使用 OSS URL 调用阿里云 Facebody API
6. **记录**: 将人员信息保存到本地 JSON 数据库

### 支持的图片格式
- 自动检测文件扩展名 (.jpg, .jpeg, .png, .gif, .webp)
- 保留原始文件扩展名用于 OSS 存储
- 人脸必须清晰、正面、无遮挡

### 数据存储增强
本地 JSON 数据库现在包含以下字段：
```json
{
  "person_abc123": {
    "name": "张三",
    "entity_id": "person_abc123",
    "oss_url": "https://...",
    "filename": "person_1691234567_person_abc123.jpg",
    "original_image_path": "/home/xuqianjin/face_20250804123456.jpg",
    "created_at": 1691234567
  }
}
```

## 配置要求

### 文件权限
- 确保应用有读取图片文件的权限
- 图片文件路径必须是绝对路径
- 建议使用 644 (rw-r--r--) 或 755 (rwxr-xr-x) 权限

### 环境变量
```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your_access_key_id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your_access_key_secret"
```

### 阿里云服务
1. **开通 Facebody 服务** (人体识别)
2. **创建 OSS Bucket**: `faces-my-shanghai` (cn-shanghai 区域)
3. **设置 Bucket 权限**: 公共读权限 (用于图片访问)

## 迁移指南

### 从旧版本 API 迁移

**旧格式 (base64):**
```json
{
  "type": "face",
  "action": "add",
  "name": "张三",
  "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
}
```

**新格式 (文件路径):**
```json
{
    "type": "face",
    "payload": {
        "action": "add_face",
        "person_name": "张三",
        "image_path": "/home/xuqianjin/face_20250804123456.jpg"
    }
}
```

### 主要变更
1. **消息结构**: 增加了 `payload` 包装层
2. **操作名称**: 
   - `add` → `add_face`
   - `find` → `find_face` 
   - `list` → `list_people`
   - 新增 `search_face` (高级搜索功能)
3. **参数名称**: `name` → `person_name`, `image` → `image_path`
4. **数据格式**: base64 字符串 → 本地文件路径
5. **新功能**: `search_face` 支持多结果返回和置信度阈值过滤

## 错误处理

### 文件相关错误
- **FileNotFoundError**: 图片文件不存在
- **PermissionError**: 文件权限不足
- **OSError**: 文件读取失败

### 网络相关错误
- **OSS 连接失败**: 检查网络连接和 OSS 配置
- **阿里云 API 错误**: 检查访问密钥和服务状态

### 建议的错误处理策略
1. **客户端**: 发送请求前验证文件是否存在
2. **服务端**: 提供详细的错误信息和错误码
3. **重试机制**: 对于网络错误实现指数退避重试
