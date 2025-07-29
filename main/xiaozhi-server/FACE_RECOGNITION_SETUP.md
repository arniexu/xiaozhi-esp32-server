# 人脸识别功能配置指南

## 1. 阿里云配置要求

### 1.1 获取阿里云访问密钥
1. 登录[阿里云控制台](https://ram.console.aliyun.com/manage/ak)
2. 创建AccessKey，获取以下信息：
   - `ALIBABA_CLOUD_ACCESS_KEY_ID`
   - `ALIBABA_CLOUD_ACCESS_KEY_SECRET`

### 1.2 设置环境变量

#### Linux/macOS 方式：
```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your_access_key_id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your_access_key_secret"
```

#### 永久设置（推荐）：
添加到 `~/.bashrc` 或 `~/.zshrc`：
```bash
echo 'export ALIBABA_CLOUD_ACCESS_KEY_ID="your_access_key_id"' >> ~/.bashrc
echo 'export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your_access_key_secret"' >> ~/.bashrc
source ~/.bashrc
```

### 1.3 验证配置
```bash
echo $ALIBABA_CLOUD_ACCESS_KEY_ID
echo $ALIBABA_CLOUD_ACCESS_KEY_SECRET
```

## 2. 功能说明

### 2.1 实现的功能
- ✅ **添加人员** (`add_person`): 添加新的人脸信息到数据库
- ✅ **查找人员** (`find_person`): 根据人脸图片查找已知人员
- ✅ **列出人员** (`list_people`): 列出所有已添加的人员

### 2.2 数据存储
- **本地存储**: `data/face_data.json` - 存储人员名称和entity_id映射
- **阿里云存储**: 人脸特征数据存储在阿里云Facebody服务中

## 3. API消息格式

### 3.1 添加人员
**发送格式:**
```json
{
    "type": "face",
    "action": "add",
    "name": "人员姓名",
    "image": "base64编码的图片数据"
}
```

**响应格式:**
```json
{
    "type": "face",
    "action": "add", 
    "status": "success",
    "message": "成功添加人员: 张三",
    "data": {
        "name": "张三",
        "entity_id": "person_abc123"
    }
}
```

### 3.2 查找人员
**发送格式:**
```json
{
    "type": "face",
    "action": "find",
    "image": "base64编码的图片数据"
}
```

**响应格式:**
```json
{
    "type": "face",
    "action": "find",
    "status": "success", 
    "message": "找到匹配的人员",
    "data": {
        "name": "张三",
        "entity_id": "person_abc123",
        "confidence": 0.95
    }
}
```

### 3.3 列出人员
**发送格式:**
```json
{
    "type": "face",
    "action": "list"
}
```

**响应格式:**
```json
{
    "type": "face",
    "action": "list",
    "status": "success",
    "message": "共找到 2 个人员",
    "data": {
        "people": [
            {"name": "张三", "entity_id": "person_abc123"},
            {"name": "李四", "entity_id": "person_def456"}
        ],
        "count": 2
    }
}
```

## 4. 测试指南

### 4.1 运行测试前的准备
1. 确保已安装所有依赖：
```bash
pip3 install -r requirements.txt
pip3 install alibabacloud-facebody20191230 alibabacloud-tea-openapi alibabacloud-darabonba-env alibabacloud-tea-console alibabacloud-darabonba-string alibabacloud-tea-util
```

2. 设置阿里云环境变量（见上文）

3. 准备测试图片（可选）：
```bash
# 将图片转换为base64（用于测试）
base64 -i your_face_image.jpg
```

### 4.2 运行测试
```bash
# 基础功能测试
python3 test_face_simple.py

# 完整测试（包含真实图片）
python3 test_face_functions.py

# 使用本地图片测试
python3 test_face_images.py
```

## 5. 故障排除

### 5.1 常见错误

**错误**: `Please set up the credentials correctly`
**解决**: 检查环境变量是否正确设置

**错误**: `Incorrect padding` 
**解决**: 检查base64图片数据格式是否正确

**错误**: `ModuleNotFoundError: No module named 'Tea'`
**解决**: 安装阿里云SDK依赖

### 5.2 调试技巧
1. 检查日志输出（所有操作都有详细日志）
2. 验证图片base64格式：
```python
import base64
try:
    base64.b64decode(your_base64_string)
    print("✅ Base64格式正确")
except:
    print("❌ Base64格式错误")
```

## 6. 性能优化建议

1. **图片大小**: 建议使用500KB以下的图片
2. **图片格式**: 支持JPG、PNG格式
3. **人脸要求**: 确保人脸清晰、正面、光线充足
4. **并发处理**: 可以并行处理多个人脸识别请求

## 7. 安全注意事项

1. **凭证安全**: 不要将AccessKey提交到代码仓库
2. **权限最小化**: 只授予必要的Facebody服务权限
3. **数据加密**: 敏感人脸数据应加密存储
4. **访问控制**: 限制人脸识别API的访问权限
