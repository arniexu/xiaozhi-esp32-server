#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人脸识别功能单元测试
简化版本，专注于核心功能测试
"""

import asyncio
import json
import base64
import os
import sys
from unittest.mock import AsyncMock

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 测试用的最小JPEG图片数据（1x1像素）
SAMPLE_JPEG_BASE64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwA/8A"

class MockConnection:
    """模拟WebSocket连接"""
    def __init__(self):
        self.websocket = AsyncMock()
        self.sent_messages = []
        
    async def mock_send(self, message):
        """记录发送的消息"""
        self.sent_messages.append(json.loads(message))
        print(f"✉️  发送消息: {message}")

def print_test_header(test_name):
    """打印测试标题"""
    print(f"\n{'='*50}")
    print(f"🧪 {test_name}")
    print('='*50)

async def test_case_1_add_person():
    """测试用例1: 添加人员"""
    print_test_header("测试用例1: 添加人员功能")
    
    from core.handle.faceHandle import add_person
    
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    # 子测试1: 正常添加
    print("\n📋 子测试1.1: 正常添加人员")
    await add_person(conn, "测试用户1", SAMPLE_JPEG_BASE64)
    
    # 检查结果
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        print("✅ 子测试1.1 通过")
        entity_id = conn.sent_messages[-1].get("data", {}).get("entity_id")
        print(f"   生成的Entity ID: {entity_id}")
    else:
        print("❌ 子测试1.1 失败")
    
    # 子测试2: 空图片测试
    print("\n📋 子测试1.2: 空图片错误处理")
    await add_person(conn, "测试用户2", "")
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "error":
        print("✅ 子测试1.2 通过 - 正确处理空图片")
    else:
        print("❌ 子测试1.2 失败")

async def test_case_2_list_people():
    """测试用例2: 列出人员"""
    print_test_header("测试用例2: 列出人员功能")
    
    from core.handle.faceHandle import list_people
    
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    print("\n📋 测试: 列出所有人员")
    await list_people(conn)
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        data = conn.sent_messages[-1].get("data", {})
        count = data.get("count", 0)
        people = data.get("people", [])
        
        print(f"✅ 测试通过 - 找到 {count} 个人员")
        for i, person in enumerate(people[:3], 1):  # 只显示前3个
            print(f"   {i}. {person.get('name')} (ID: {person.get('entity_id', '')[:12]}...)")
        
        if count > 3:
            print(f"   ... 还有 {count - 3} 个人员")
    else:
        print("❌ 测试失败")

async def test_case_3_find_person():
    """测试用例3: 查找人员"""
    print_test_header("测试用例3: 查找人员功能")
    
    from core.handle.faceHandle import find_person, _get_face_data, add_person
    
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    # 确保有数据
    face_data = _get_face_data()
    if not face_data:
        print("📝 数据库为空，先添加测试数据...")
        await add_person(conn, "查找测试用户", SAMPLE_JPEG_BASE64)
        conn.sent_messages.clear()  # 清空之前的消息
    
    # 子测试1: 正常查找
    print("\n📋 子测试3.1: 正常查找人员")
    await find_person(conn, SAMPLE_JPEG_BASE64)
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        found_data = conn.sent_messages[-1].get("data", {})
        print(f"✅ 子测试3.1 通过 - 找到: {found_data.get('name')}")
    else:
        print("❌ 子测试3.1 失败")
    
    # 子测试2: 空图片查找
    print("\n📋 子测试3.2: 空图片错误处理")
    await find_person(conn, "")
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "error":
        print("✅ 子测试3.2 通过 - 正确处理空图片")
    else:
        print("❌ 子测试3.2 失败")

async def test_case_4_data_operations():
    """测试用例4: 数据操作"""
    print_test_header("测试用例4: 数据持久化测试")
    
    from core.handle.faceHandle import _get_face_data, _save_face_data
    
    print("\n📋 测试: 数据读写操作")
    
    # 读取当前数据
    original_data = _get_face_data()
    original_count = len(original_data)
    print(f"📊 当前数据库记录数: {original_count}")
    
    # 添加测试记录
    test_record = {
        "test_persist_123": {
            "name": "持久化测试",
            "entity_id": "test_persist_123",
            "image_path": "/tmp/test.jpg"
        }
    }
    
    # 保存数据
    new_data = {**original_data, **test_record}
    _save_face_data(new_data)
    print("💾 保存测试记录")
    
    # 重新读取
    reloaded_data = _get_face_data()
    
    if "test_persist_123" in reloaded_data:
        print("✅ 数据持久化测试通过")
        
        # 清理测试数据
        del reloaded_data["test_persist_123"]
        _save_face_data(reloaded_data)
        print("🧹 清理测试数据")
    else:
        print("❌ 数据持久化测试失败")

async def test_case_5_edge_cases():
    """测试用例5: 边界情况"""
    print_test_header("测试用例5: 边界情况测试")
    
    from core.handle.faceHandle import add_person, find_person
    
    conn = MockConnection()
    conn.websocket.send = conn.mock_send
    
    # 子测试1: 特殊字符名称
    print("\n📋 子测试5.1: 特殊字符名称")
    await add_person(conn, "测试用户-2023@#$%", SAMPLE_JPEG_BASE64)
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        print("✅ 子测试5.1 通过 - 支持特殊字符")
    else:
        print("❌ 子测试5.1 失败")
    
    # 子测试2: 长名称
    print("\n📋 子测试5.2: 长名称测试")
    long_name = "这是一个很长的名字" * 10  # 创建一个很长的名字
    await add_person(conn, long_name[:50], SAMPLE_JPEG_BASE64)  # 截断到50字符
    
    if conn.sent_messages and conn.sent_messages[-1].get("status") == "success":
        print("✅ 子测试5.2 通过 - 支持长名称")
    else:
        print("❌ 子测试5.2 失败")

def print_summary():
    """打印测试总结"""
    from core.handle.faceHandle import _get_face_data
    
    print("\n" + "="*60)
    print("📊 测试总结")
    print("="*60)
    
    # 显示数据库状态
    final_data = _get_face_data()
    print(f"📁 数据库状态: {len(final_data)} 条记录")
    
    if final_data:
        print("👥 数据库中的人员:")
        for i, (entity_id, info) in enumerate(list(final_data.items())[:5], 1):
            print(f"   {i}. {info['name']} (ID: {entity_id[:12]}...)")
        
        if len(final_data) > 5:
            print(f"   ... 还有 {len(final_data) - 5} 条记录")
    
    print(f"\n💾 数据文件位置: data/face_data.json")
    print("🎉 所有测试执行完毕!")

async def main():
    """主测试函数"""
    print("🚀 开始人脸识别功能测试")
    print("="*60)
    
    try:
        # 运行所有测试用例
        await test_case_1_add_person()
        await test_case_2_list_people()
        await test_case_3_find_person()
        await test_case_4_data_operations()
        await test_case_5_edge_cases()
        
        # 打印总结
        print_summary()
        
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # 运行测试
    asyncio.run(main())
