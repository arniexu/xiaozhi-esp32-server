# Face Handle API JSON 示例

本文档包含了人脸识别 API 的所有请求和响应 JSON 结构示例，方便开发和测试时参考使用。

## 1. 添加人员 API

### 1.1 添加人员 - 请求示例
```json
{
  "type": "face",
  "action": "add",
  "name": "张三",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD..."
}
```

### 1.2 添加人员 - 成功响应示例
```json
{
  "type": "face",
  "action": "add", 
  "status": "success",
  "message": "成功添加人员: 张三",
  "data": {
    "name": "张三",
    "entity_id": "person_abc12345",
    "oss_url": "https://faces-my-shanghai.oss-cn-shanghai.aliyuncs.com/faces/person_1640995200_abc12345.jpg",
    "method": "alibaba_cloud_with_oss"
  }
}
```

### 1.3 添加人员 - 失败响应示例
```json
{
  "type": "face",
  "action": "add",
  "status": "error",
  "message": "添加人员失败: 图片格式不支持"
}
```

### 1.4 添加人员 - 参数验证错误响应示例
```json
{
  "type": "face",
  "status": "error",
  "message": "缺少参数"
}
```

## 2. 查找人员 API

### 2.1 查找人员 - 请求示例
```json
{
  "type": "face",
  "action": "find",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD..."
}
```

### 2.2 查找人员 - 找到匹配人员响应示例
```json
{
  "type": "face",
  "action": "find",
  "status": "success",
  "message": "找到匹配的人员",
  "data": {
    "name": "张三",
    "entity_id": "person_abc12345",
    "confidence": 0.95,
    "search_method": "alibaba_cloud_with_oss"
  }
}
```

### 2.3 查找人员 - 未找到匹配人员响应示例
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

### 2.4 查找人员 - 查找失败响应示例
```json
{
  "type": "face",
  "action": "find",
  "status": "error",
  "message": "查找人员失败: 网络连接超时"
}
```

### 2.5 查找人员 - 参数验证错误响应示例
```json
{
  "type": "face",
  "status": "error",
  "message": "缺少图片数据"
}
```

## 3. 列出所有人员 API

### 3.1 列出所有人员 - 请求示例
```json
{
  "type": "face",
  "action": "list"
}
```

### 3.2 列出所有人员 - 成功响应示例
```json
{
  "type": "face",
  "action": "list",
  "status": "success",
  "message": "共找到 3 个人员",
  "data": {
    "count": 3,
    "people": [
      {
        "name": "张三",
        "entity_id": "person_abc12345",
        "created_at": 1640995200
      },
      {
        "name": "李四", 
        "entity_id": "person_def67890",
        "created_at": 1640995300
      },
      {
        "name": "王五",
        "entity_id": "person_ghi11111",
        "created_at": 1640995400
      }
    ]
  }
}
```

### 3.3 列出所有人员 - 空列表响应示例
```json
{
  "type": "face",
  "action": "list",
  "status": "success",
  "message": "共找到 0 个人员",
  "data": {
    "count": 0,
    "people": []
  }
}
```

### 3.4 列出所有人员 - 失败响应示例
```json
{
  "type": "face",
  "action": "list",
  "status": "error",
  "message": "列出人员失败: 数据库连接失败"
}
```

## 4. 通用错误响应

### 4.1 缺少操作类型参数错误示例
```json
{
  "type": "face",
  "status": "error", 
  "message": "缺少操作类型参数"
}
```

### 4.2 未知操作类型错误示例
```json
{
  "type": "face",
  "status": "error",
  "message": "未知操作类型：delete"
}
```

## 5. 测试用完整 JSON 示例

### 5.1 测试添加人员完整示例
```json
{
  "type": "face",
  "action": "add",
  "name": "测试用户001",
  "image": "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
}
```

### 5.2 测试查找人员完整示例
```json
{
  "type": "face",
  "action": "find",
  "image": "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
}
```

### 5.3 测试列出所有人员完整示例
```json
{
  "type": "face",
  "action": "list"
}
```

## 6. 字段说明

### 6.1 请求字段说明
- `type`: 固定为 "face" - 标识这是人脸相关的请求
- `action`: 操作类型，可选值："add"(添加), "find"(查找), "list"(列出)
- `name`: 人员姓名，仅在 add 操作时必需
- `image`: base64 编码的图片数据，在 add 和 find 操作时必需

### 6.2 响应字段说明
- `type`: 固定为 "face" - 标识这是人脸相关的响应
- `action`: 回显请求的操作类型
- `status`: 操作状态，"success" 表示成功，"error" 表示失败
- `message`: 操作结果的文字描述
- `data`: 具体的返回数据，仅在成功时包含

### 6.3 数据字段说明
- `entity_id`: 阿里云人脸库中的唯一标识符，格式为 "person_xxxxxxxx"
- `confidence`: 人脸匹配置信度，范围 0.0-1.0，值越高表示匹配度越高
- `oss_url`: 图片在阿里云 OSS 上的存储地址
- `created_at`: Unix 时间戳，表示人员添加时间
- `method/search_method`: 使用的技术方案标识，当前为 "alibaba_cloud_with_oss"
- `count`: 人员总数
- `people`: 人员列表数组

## 7. 使用说明

1. **图片格式**: 支持 JPEG、PNG 等常见格式，建议使用 JPEG 格式以减少数据传输量
2. **图片大小**: 建议图片尺寸不超过 2MB，人脸清晰可见
3. **Base64 编码**: 图片需要进行 base64 编码后传输，可包含 data URL 前缀
4. **置信度阈值**: 一般认为 confidence > 0.8 为较好的匹配结果
5. **错误处理**: 所有错误都会通过 status="error" 和 message 字段返回详细信息
