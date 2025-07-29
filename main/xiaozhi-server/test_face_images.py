#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用真实图片文件测试人脸识别功能
支持多种图片格式：jpg, jpeg, png, bmp
"""

import asyncio
import json
import base64
import os
import sys
from unittest.mock import AsyncMock

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class MockConnection:
    """模拟WebSocket连接"""
    def __init__(self):
        self.websocket = AsyncMock()
        self.sent_messages = []
        
    async def mock_send(self, message):
        """记录发送的消息"""
        self.sent_messages.append(json.loads(message))
        print(f"📤 响应: {json.loads(message).get('message', 'Unknown')}")

def find_image_files(directories):
    """在指定目录中查找图片文件"""
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']
    found_images = []
    
    for directory in directories:
        if os.path.exists(directory):
            print(f"🔍 搜索目录: {directory}")
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in image_extensions):
                        filepath = os.path.join(root, file)
                        file_size = os.path.getsize(filepath)
                        found_images.append({
                            'path': filepath,
                            'name': file,
                            'size': file_size
                        })
        else:
            print(f"⚠️  目录不存在: {directory}")
    
    return found_images

def load_image_as_base64(image_path):
    """加载图片文件并转换为base64"""
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
            base64_str = base64.b64encode(image_data).decode('utf-8')
            print(f"📷 加载图片: {image_path} ({len(image_data)} bytes)")
            return base64_str
    except Exception as e:
        print(f"❌ 加载图片失败: {image_path} - {str(e)}")
        return None

async def test_with_real_images():
    """使用真实图片测试"""
    print("🖼️  使用真实图片测试人脸识别功能")
    print("="*60)
    
    from core.handle.faceHandle import add_person, find_person, list_people
    
    # 搜索可能的图片目录
    search_directories = [
        "../../docs/images",
        "docs/images",
        "test_images",
        "data",
        "images",
        "/tmp",
        "."
    ]
    
    # 查找图片文件
    print("🔍 搜索本地图片文件...")
    image_files = find_image_files(search_directories)
    
    if not image_files:
        print("⚠️  未找到任何图片文件")
        print("💡 提示: 请将测试图片放在以下目录之一:")
        for directory in search_directories[:4]:
            print(f"   - {directory}")
        return
    
    # 显示找到的图片
    print(f"\n📸 找到 {len(image_files)} 个图片文件:")
    for i, img in enumerate(image_files[:10], 1):  # 只显示前10个
        size_kb = img['size'] / 1024
        print(f"   {i}. {img['name']} ({size_kb:.1f} KB)")
    
    if len(image_files) > 10:
        print(f"   ... 还有 {len(image_files) - 10} 个文件")
    
    # 选择前几个图片进行测试
    test_images = image_files[:3]  # 使用前3张图片
    
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    # 测试添加人员
    print(f"\n🧪 测试添加人员 (使用 {len(test_images)} 张图片)")
    print("-" * 40)
    
    test_names = ["张三", "李四", "王五"]
    
    for i, (img_info, name) in enumerate(zip(test_images, test_names), 1):
        print(f"\n📋 测试 {i}: 添加 {name}")
        
        # 加载图片
        image_base64 = load_image_as_base64(img_info['path'])
        if not image_base64:
            continue
        
        # 添加人员
        await add_person(conn, name, image_base64)
        
        # 检查结果
        if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
            entity_id = conn.sent_messages[-1].get("data", {}).get("entity_id", "")
            print(f"✅ 成功添加 {name} (ID: {entity_id[:12]}...)")
        else:
            print(f"❌ 添加 {name} 失败")
    
    # 测试列出人员
    print(f"\n🧪 测试列出所有人员")
    print("-" * 40)
    
    await list_people(conn)
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        data = conn.sent_messages[-1].get("data", {})
        count = data.get("count", 0)
        people = data.get("people", [])
        
        print(f"✅ 找到 {count} 个人员:")
        for person in people:
            print(f"   - {person.get('name')} (ID: {person.get('entity_id', '')[:12]}...)")
    
    # 测试查找人员
    print(f"\n🧪 测试查找人员")
    print("-" * 40)
    
    if test_images:
        print(f"使用第一张图片进行查找测试: {test_images[0]['name']}")
        
        search_image = load_image_as_base64(test_images[0]['path'])
        if search_image:
            await find_person(conn, search_image)
            
            if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
                found_data = conn.sent_messages[-1].get("data", {})
                search_method = found_data.get("search_method", "unknown")
                print(f"✅ 查找成功，找到: {found_data.get('name')} (方法: {search_method})")
            else:
                print("❌ 查找失败")

def create_sample_images():
    """创建一些示例图片文件"""
    print("\n📁 创建示例图片文件")
    print("-" * 40)
    
    # 创建测试目录
    test_dir = "test_images"
    os.makedirs(test_dir, exist_ok=True)
    
    # 不同颜色的1x1像素PNG图片数据
    sample_images = {
        "red_1x1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
        "green_1x1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "blue_1x1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChAGA4tEiEAAAAABJRU5ErkJggg=="
    }
    
    created_files = []
    
    for filename, base64_data in sample_images.items():
        filepath = os.path.join(test_dir, filename)
        try:
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(base64_data))
            created_files.append(filepath)
            print(f"✅ 创建: {filepath}")
        except Exception as e:
            print(f"❌ 创建失败: {filepath} - {str(e)}")
    
    if created_files:
        print(f"\n💡 创建了 {len(created_files)} 个示例图片，可用于测试")
        return test_dir
    else:
        return None

async def test_specific_image():
    """测试指定的图片文件"""
    print("�️  测试指定图片: /home/xuqianjin/1.jpg")
    print("="*60)
    
    from core.handle.faceHandle import add_person, find_person, list_people
    
    # 指定的图片路径
    image_path = "/home/xuqianjin/1.jpg"
    search_image_path = "/home/xuqianjin/2.jpg"  # 用于搜索的图片
    
    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"❌ 图片文件不存在: {image_path}")
        return
        
    if not os.path.exists(search_image_path):
        print(f"❌ 搜索图片文件不存在: {search_image_path}")
        return
    
    # 加载图片
    print(f"📷 加载图片: {image_path}")
    image_base64 = load_image_as_base64(image_path)
    
    print(f"📷 加载搜索图片: {search_image_path}")
    search_image_base64 = load_image_as_base64(search_image_path)
    
    if not image_base64:
        print("❌ 图片加载失败")
        return
        
    if not search_image_base64:
        print("❌ 搜索图片加载失败")
        return
    
    # 创建模拟连接
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    # 添加人员到数据库
    person_name = "用户1"  # 可以修改为任意名称
    print(f"\n🧪 添加人员: {person_name}")
    print("-" * 40)
    
    await add_person(conn, person_name, image_base64)
    
    # 检查添加结果
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        entity_id = conn.sent_messages[-1].get("data", {}).get("entity_id", "")
        print(f"✅ 成功添加 {person_name} (ID: {entity_id[:12]}...)")
    else:
        print(f"❌ 添加 {person_name} 失败")
    
    # 测试查找功能 - 使用不同的图片进行搜索
    print(f"\n🧪 测试查找功能 (使用 2.jpg 搜索)")
    print("-" * 40)
    
    await find_person(conn, search_image_base64)
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        found_data = conn.sent_messages[-1].get("data", {})
        confidence = found_data.get("confidence", 0)
        search_method = found_data.get("search_method", "unknown")
        print(f"✅ 查找成功，找到: {found_data.get('name')} (置信度: {confidence}, 方法: {search_method})")
    else:
        print("❌ 查找失败")
    
    # 列出所有人员
    print(f"\n🧪 列出所有人员")
    print("-" * 40)
    
    await list_people(conn)
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        data = conn.sent_messages[-1].get("data", {})
        count = data.get("count", 0)
        people = data.get("people", [])
        
        print(f"✅ 数据库中共有 {count} 个人员:")
        for person in people:
            print(f"   - {person.get('name')} (ID: {person.get('entity_id', '')[:12]}...)")

async def main():
    """主函数"""
    print("🚀 人脸数据库插入测试")
    print("="*60)
    
    try:
        # 测试指定的图片文件
        await test_specific_image()
        
        # 显示最终状态
        print(f"\n📊 测试完成")
        print("-" * 40)
        
        from core.handle.faceHandle import _get_face_data
        final_data = _get_face_data()
        print(f"数据库中共有 {len(final_data)} 条人员记录")
        
        if final_data:
            print("人员列表:")
            for entity_id, info in final_data.items():
                print(f"   - {info['name']} (ID: {entity_id[:12]}...)")
        
        print("\n💡 说明:")
        print("   - 图片已加载并处理")
        print("   - 人员信息已保存到本地数据库")
        print("   - 阿里云API调用需要正确的访问密钥配置")
        
        print("\n💡 说明:")
        print("   - 图片已加载并处理")
        print("   - 人员信息已保存到本地数据库")
        print("   - 阿里云API调用需要正确的访问密钥配置")
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
