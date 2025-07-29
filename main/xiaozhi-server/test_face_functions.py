#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人脸识别功能测试用例
测试 add_person, find_person, list_people 三个功能
"""

import asyncio
import json
import base64
import os
import sys
from unittest.mock import Mock, AsyncMock
import tempfile

# 添加项目路径到系统路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.handle.faceHandle import add_person, find_person, list_people, _get_face_data, _save_face_data

class TestConnection:
    """模拟连接对象"""
    def __init__(self):
        self.websocket = AsyncMock()
        self.responses = []
        
    async def mock_send(self, message):
        """模拟websocket发送消息"""
        self.responses.append(json.loads(message))
        print(f"📤 发送响应: {message}")

def create_test_image_base64():
    """创建一个简单的测试图片（1x1像素的JPEG）"""
    # 这是一个最小的JPEG文件的base64编码（1x1像素，白色）
    jpeg_data = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xff\xd9'
    return base64.b64encode(jpeg_data).decode('utf-8')

def load_image_as_base64(image_path):
    """加载本地图片文件并转换为base64"""
    try:
        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
        else:
            print(f"⚠️  图片文件不存在: {image_path}")
            return None
    except Exception as e:
        print(f"❌ 读取图片失败: {str(e)}")
        return None

async def test_add_person():
    """测试添加人员功能"""
    print("\n" + "="*50)
    print("🧪 测试添加人员功能")
    print("="*50)
    
    conn = TestConnection()
    conn.websocket.send = conn.mock_send
    
    # 测试用例1：使用生成的测试图片
    print("\n📋 测试用例1: 添加人员 - 张三（使用生成的测试图片）")
    test_image = create_test_image_base64()
    await add_person(conn, "张三", test_image)
    
    # 检查响应
    if conn.responses and conn.responses[-1].get("status") == "success":
        print("✅ 测试用例1通过: 成功添加张三")
    else:
        print("❌ 测试用例1失败")
    
    # 测试用例2：尝试使用本地图片（如果存在）
    print("\n📋 测试用例2: 添加人员 - 李四（尝试使用本地图片）")
    
    # 尝试多个可能的图片路径
    possible_image_paths = [
        "../../docs/images/demo1.png",
        "docs/images/demo1.png", 
        "test_images/test1.jpg",
        "data/test_face.jpg"
    ]
    
    local_image = None
    for path in possible_image_paths:
        local_image = load_image_as_base64(path)
        if local_image:
            print(f"📷 使用本地图片: {path}")
            break
    
    if not local_image:
        print("📷 未找到本地图片，使用生成的测试图片")
        local_image = create_test_image_base64()
    
    await add_person(conn, "李四", local_image)
    
    if conn.responses and conn.responses[-1].get("status") == "success":
        print("✅ 测试用例2通过: 成功添加李四")
    else:
        print("❌ 测试用例2失败")
    
    # 测试用例3：测试异常情况（空图片）
    print("\n📋 测试用例3: 添加人员 - 异常情况（空图片）")
    await add_person(conn, "王五", "")
    
    if conn.responses and conn.responses[-1].get("status") == "error":
        print("✅ 测试用例3通过: 正确处理空图片错误")
    else:
        print("❌ 测试用例3失败")

async def test_list_people():
    """测试列出所有人员功能"""
    print("\n" + "="*50)
    print("🧪 测试列出所有人员功能")
    print("="*50)
    
    conn = TestConnection()
    conn.websocket.send = conn.mock_send
    
    print("\n📋 测试用例: 列出所有人员")
    await list_people(conn)
    
    if conn.responses and conn.responses[-1].get("status") == "success":
        people_data = conn.responses[-1].get("data", {})
        people_list = people_data.get("people", [])
        count = people_data.get("count", 0)
        
        print(f"✅ 测试通过: 成功列出 {count} 个人员")
        for i, person in enumerate(people_list, 1):
            print(f"   {i}. {person.get('name')} (ID: {person.get('entity_id')})")
    else:
        print("❌ 测试失败")

async def test_find_person():
    """测试查找人员功能"""
    print("\n" + "="*50)
    print("🧪 测试查找人员功能")
    print("="*50)
    
    conn = TestConnection()
    conn.websocket.send = conn.mock_send
    
    # 检查是否有人员数据
    face_data = _get_face_data()
    if not face_data:
        print("⚠️  数据库为空，先添加一个测试人员")
        await add_person(conn, "测试用户", create_test_image_base64())
    
    print("\n📋 测试用例1: 查找人员（使用测试图片）")
    test_image = create_test_image_base64()
    await find_person(conn, test_image)
    
    if conn.responses and conn.responses[-1].get("status") == "success":
        found_person = conn.responses[-1].get("data", {})
        print(f"✅ 测试通过: 找到人员 {found_person.get('name')} (ID: {found_person.get('entity_id')})")
    else:
        print("❌ 测试失败")
    
    print("\n📋 测试用例2: 查找人员（异常情况 - 空图片）")
    await find_person(conn, "")
    
    if conn.responses and conn.responses[-1].get("status") == "error":
        print("✅ 测试通过: 正确处理空图片错误")
    else:
        print("❌ 测试失败")

async def test_data_persistence():
    """测试数据持久化"""
    print("\n" + "="*50)
    print("🧪 测试数据持久化功能")
    print("="*50)
    
    # 保存当前数据
    current_data = _get_face_data()
    print(f"📊 当前数据库中有 {len(current_data)} 条记录")
    
    # 添加测试数据
    test_data = {
        "test_entity_123": {
            "name": "持久化测试用户",
            "entity_id": "test_entity_123",
            "image_path": "/tmp/test.jpg"
        }
    }
    
    updated_data = {**current_data, **test_data}
    _save_face_data(updated_data)
    print("💾 保存测试数据")
    
    # 重新读取数据
    reloaded_data = _get_face_data()
    
    if "test_entity_123" in reloaded_data:
        print("✅ 数据持久化测试通过")
        # 清理测试数据
        del reloaded_data["test_entity_123"]
        _save_face_data(reloaded_data)
        print("🧹 清理测试数据")
    else:
        print("❌ 数据持久化测试失败")

def create_test_images():
    """创建一些测试图片文件"""
    print("\n" + "="*50)
    print("🖼️  创建测试图片文件")
    print("="*50)
    
    # 创建测试图片目录
    test_dir = "test_images"
    os.makedirs(test_dir, exist_ok=True)
    
    # 创建几个不同的测试图片
    test_images = [
        ("test_face_1.jpg", "张三的测试照片"),
        ("test_face_2.jpg", "李四的测试照片"),
        ("test_face_3.jpg", "王五的测试照片")
    ]
    
    jpeg_data = create_test_image_base64()
    
    for filename, description in test_images:
        filepath = os.path.join(test_dir, filename)
        try:
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(jpeg_data))
            print(f"✅ 创建测试图片: {filepath} ({description})")
        except Exception as e:
            print(f"❌ 创建测试图片失败: {filepath} - {str(e)}")
    
    return test_dir

async def run_comprehensive_test():
    """运行综合测试"""
    print("🚀 开始人脸识别功能综合测试")
    print("=" * 60)
    
    # 创建测试图片
    test_dir = create_test_images()
    
    try:
        # 运行各项测试
        await test_data_persistence()
        await test_add_person()
        await test_list_people()
        await test_find_person()
        
        print("\n" + "="*60)
        print("📊 测试完成总结")
        print("="*60)
        
        # 显示最终数据库状态
        final_data = _get_face_data()
        print(f"📁 最终数据库中有 {len(final_data)} 条人员记录:")
        for entity_id, person_info in final_data.items():
            print(f"   - {person_info['name']} (ID: {entity_id})")
        
        print(f"\n📂 测试图片目录: {test_dir}")
        print("🎉 所有测试执行完毕!")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {str(e)}")
    
    finally:
        # 清理测试图片（可选）
        import shutil
        try:
            if os.path.exists(test_dir):
                # shutil.rmtree(test_dir)  # 取消注释以删除测试图片
                print(f"💡 提示: 测试图片保留在 {test_dir} 目录中")
        except:
            pass

if __name__ == "__main__":
    # 运行测试
    asyncio.run(run_comprehensive_test())
