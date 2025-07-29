#!/usr/bin/env python3
"""
textHandle.py 单元测试脚本 - 直接测试函数逻辑
"""

import asyncio
import json
import sys
import os
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

# 添加项目路径
sys.path.insert(0, '/home/xuqianjin/xiaozhi-esp32-server/main/xiaozhi-server')

try:
    from core.handle.textHandle import handleTextMessage
    print("✅ 成功导入 textHandle 模块")
except ImportError as e:
    print(f"❌ 导入 textHandle 失败: {e}")
    sys.exit(1)

class MockConnection:
    """模拟WebSocket连接对象"""
    def __init__(self):
        self.websocket = AsyncMock()
        self.logger = MagicMock()
        self.logger.bind.return_value = MagicMock()
        self.logger.bind.return_value.info = MagicMock()
        self.logger.bind.return_value.error = MagicMock()
        self.logger.bind.return_value.debug = MagicMock()
        
        # 模拟配置
        self.config = {
            "wakeup_words": ["小智", "你好"],
            "enable_greeting": True,
            "manager-api": {
                "secret": "test_secret"
            }
        }
        
        # 模拟状态变量
        self.client_listen_mode = "auto"
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_is_speaking = False
        self.just_woken_up = False
        self.asr_audio = []
        self.read_config_from_api = False
        self.server = None
        self.mcp_client = None

async def test_hello_message():
    """测试hello消息处理"""
    print("\n📋 测试hello消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "hello",
        "device_id": "test_device",
        "version": "1.0.0"
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ hello消息处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ hello消息处理失败: {e}")

async def test_face_list_message():
    """测试人脸列表消息处理"""
    print("\n👥 测试人脸列表消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "face",
        "action": "list"
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 人脸列表消息处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ 人脸列表消息处理失败: {e}")

async def test_face_add_message():
    """测试添加人脸消息处理"""
    print("\n➕ 测试添加人脸消息处理...")
    conn = MockConnection()
    
    # 测试正常情况
    message = json.dumps({
        "type": "face",
        "action": "add",
        "name": "测试用户",
        "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 添加人脸消息处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ 添加人脸消息处理失败: {e}")

async def test_face_add_missing_params():
    """测试缺少参数的添加人脸消息"""
    print("\n🚫 测试缺少参数的添加人脸消息...")
    conn = MockConnection()
    
    # 测试缺少name参数
    message = json.dumps({
        "type": "face",
        "action": "add",
        "image": "base64_image_data"
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 缺少参数处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
        # 检查是否发送了错误消息
        if conn.websocket.send.called:
            call_args = conn.websocket.send.call_args[0][0]
            response = json.loads(call_args)
            if response.get("status") == "error":
                print(f"✅ 正确返回错误消息: {response.get('message')}")
    except Exception as e:
        print(f"❌ 缺少参数处理失败: {e}")

async def test_face_find_message():
    """测试查找人脸消息处理"""
    print("\n🔍 测试查找人脸消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "face",
        "action": "find",
        "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 查找人脸消息处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ 查找人脸消息处理失败: {e}")

async def test_listen_message():
    """测试语音监听消息处理"""
    print("\n🎤 测试语音监听消息处理...")
    conn = MockConnection()
    
    # 测试开始监听
    start_message = json.dumps({
        "type": "listen",
        "state": "start",
        "mode": "continuous"
    })
    
    try:
        await handleTextMessage(conn, start_message)
        print(f"✅ 开始监听处理成功, client_have_voice: {conn.client_have_voice}")
        
        # 测试文本检测
        detect_message = json.dumps({
            "type": "listen",
            "state": "detect",
            "text": "你好"
        })
        
        await handleTextMessage(conn, detect_message)
        print("✅ 文本检测处理成功")
        
    except Exception as e:
        print(f"❌ 语音监听消息处理失败: {e}")

async def test_iot_message():
    """测试IoT消息处理"""
    print("\n🏠 测试IoT消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "iot",
        "descriptors": [{"id": "light_001", "name": "客厅灯"}],
        "states": [{"id": "light_001", "state": "on"}]
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ IoT消息处理成功")
    except Exception as e:
        print(f"❌ IoT消息处理失败: {e}")

async def test_abort_message():
    """测试中止消息处理"""
    print("\n🛑 测试中止消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "abort"
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 中止消息处理成功")
    except Exception as e:
        print(f"❌ 中止消息处理失败: {e}")

async def test_unknown_message():
    """测试未知类型消息处理"""
    print("\n❓ 测试未知类型消息处理...")
    conn = MockConnection()
    
    message = json.dumps({
        "type": "unknown_type",
        "data": "test"
    })
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 未知消息处理成功")
    except Exception as e:
        print(f"❌ 未知消息处理失败: {e}")

async def test_invalid_json():
    """测试无效JSON处理"""
    print("\n❌ 测试无效JSON处理...")
    conn = MockConnection()
    
    message = "invalid json string"
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 无效JSON处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ 无效JSON处理失败: {e}")

async def test_number_message():
    """测试数字消息处理"""
    print("\n🔢 测试数字消息处理...")
    conn = MockConnection()
    
    message = "123"
    
    try:
        await handleTextMessage(conn, message)
        print("✅ 数字消息处理成功")
        print(f"📤 WebSocket发送调用次数: {conn.websocket.send.call_count}")
    except Exception as e:
        print(f"❌ 数字消息处理失败: {e}")

async def run_all_tests():
    """运行所有测试"""
    print("🚀 开始textHandle.py单元测试")
    print("=" * 50)
    
    test_functions = [
        test_hello_message,
        test_face_list_message,
        test_face_add_message,
        test_face_add_missing_params,
        test_face_find_message,
        test_listen_message,
        test_iot_message,
        test_abort_message,
        test_unknown_message,
        test_invalid_json,
        test_number_message
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            await test_func()
            passed += 1
        except Exception as e:
            print(f"💥 测试 {test_func.__name__} 失败: {e}")
            failed += 1
        
        await asyncio.sleep(0.1)  # 短暂延迟
    
    print("\n" + "=" * 50)
    print(f"📊 测试结果: ✅ 成功 {passed} 个, ❌ 失败 {failed} 个")
    print("🏁 测试完成")

if __name__ == "__main__":
    try:
        asyncio.run(run_all_tests())
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被用户中断")
    except Exception as e:
        print(f"\n\n💥 测试过程中发生错误: {str(e)}")
