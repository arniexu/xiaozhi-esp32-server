#!/usr/bin/env python3
"""
WebSocket测试脚本 - 测试textHandle.py的各种消息处理
"""

import asyncio
import websockets
import json
import base64
import os
import time

# 测试配置
WEBSOCKET_URL = "ws://172.17.110.229:8000/xiaozhi/v1/"  # 根据实际WebSocket服务地址调整

# 模拟base64图片数据（小的测试图片）
SAMPLE_IMAGE_BASE64 = """
/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k=
""".strip()

async def test_websocket_connection():
    """测试WebSocket连接"""
    try:
        print("🔗 尝试连接WebSocket服务器...")
        async with websockets.connect(WEBSOCKET_URL) as websocket:
            print("✅ WebSocket连接成功！")
            
            # 测试各种消息类型
            await test_hello_message(websocket)
            await asyncio.sleep(1)
            
            await test_face_list_message(websocket)
            await asyncio.sleep(1)
            
            await test_face_add_message(websocket)
            await asyncio.sleep(2)
            
            await test_face_find_message(websocket)
            await asyncio.sleep(1)
            
            await test_listen_message(websocket)
            await asyncio.sleep(1)
            
            await test_iot_message(websocket)
            await asyncio.sleep(1)
            
            await test_abort_message(websocket)
            
    except Exception as e:
        print(f"❌ WebSocket连接失败: {str(e)}")
        print("💡 提示: 请确保xiaozhi-server正在运行")

async def test_hello_message(websocket):
    """测试hello消息"""
    print("\n📋 测试hello消息...")
    hello_msg = {
        "type": "hello",
        "device_id": "test_device_001",
        "version": "1.0.0"
    }
    
    await websocket.send(json.dumps(hello_msg))
    print(f"📤 发送: {json.dumps(hello_msg, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_face_list_message(websocket):
    """测试人脸列表消息"""
    print("\n👥 测试人脸列表消息...")
    list_msg = {
        "type": "face",
        "action": "list"
    }
    
    await websocket.send(json.dumps(list_msg))
    print(f"📤 发送: {json.dumps(list_msg, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_face_add_message(websocket):
    """测试添加人脸消息"""
    print("\n➕ 测试添加人脸消息...")
    add_msg = {
        "type": "face",
        "action": "add",
        "name": f"测试用户_{int(time.time())}",
        "image": SAMPLE_IMAGE_BASE64
    }
    
    await websocket.send(json.dumps(add_msg))
    print(f"📤 发送: {json.dumps({**add_msg, 'image': '...[图片数据已省略]...'}, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_face_find_message(websocket):
    """测试查找人脸消息"""
    print("\n🔍 测试查找人脸消息...")
    find_msg = {
        "type": "face",
        "action": "find",
        "image": SAMPLE_IMAGE_BASE64
    }
    
    await websocket.send(json.dumps(find_msg))
    print(f"📤 发送: {json.dumps({**find_msg, 'image': '...[图片数据已省略]...'}, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_listen_message(websocket):
    """测试语音监听消息"""
    print("\n🎤 测试语音监听消息...")
    
    # 测试start
    listen_start_msg = {
        "type": "listen",
        "state": "start",
        "mode": "continuous"
    }
    
    await websocket.send(json.dumps(listen_start_msg))
    print(f"📤 发送: {json.dumps(listen_start_msg, ensure_ascii=False)}")
    
    # 测试detect with text
    await asyncio.sleep(0.5)
    listen_detect_msg = {
        "type": "listen",
        "state": "detect",
        "text": "你好，测试语音识别"
    }
    
    await websocket.send(json.dumps(listen_detect_msg))
    print(f"📤 发送: {json.dumps(listen_detect_msg, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_iot_message(websocket):
    """测试IoT消息"""
    print("\n🏠 测试IoT消息...")
    iot_msg = {
        "type": "iot",
        "descriptors": [
            {
                "id": "light_001",
                "name": "客厅灯",
                "type": "light"
            }
        ],
        "states": [
            {
                "id": "light_001",
                "state": "on",
                "brightness": 80
            }
        ]
    }
    
    await websocket.send(json.dumps(iot_msg))
    print(f"📤 发送: {json.dumps(iot_msg, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_abort_message(websocket):
    """测试中止消息"""
    print("\n🛑 测试中止消息...")
    abort_msg = {
        "type": "abort"
    }
    
    await websocket.send(json.dumps(abort_msg))
    print(f"📤 发送: {json.dumps(abort_msg, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_invalid_message(websocket):
    """测试无效消息"""
    print("\n❌ 测试无效消息...")
    
    # 测试未知类型
    invalid_msg = {
        "type": "unknown_type",
        "data": "test"
    }
    
    await websocket.send(json.dumps(invalid_msg))
    print(f"📤 发送: {json.dumps(invalid_msg, ensure_ascii=False)}")
    
    # 测试格式错误的JSON
    await websocket.send("invalid json")
    print("📤 发送: invalid json")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

async def test_face_error_cases(websocket):
    """测试人脸功能的错误情况"""
    print("\n🚫 测试人脸功能错误情况...")
    
    # 测试缺少参数的添加请求
    add_missing_params = {
        "type": "face",
        "action": "add",
        "name": "测试用户"
        # 缺少image参数
    }
    
    await websocket.send(json.dumps(add_missing_params))
    print(f"📤 发送(缺少image): {json.dumps(add_missing_params, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")
    
    await asyncio.sleep(0.5)
    
    # 测试缺少图片的查找请求
    find_missing_image = {
        "type": "face",
        "action": "find"
        # 缺少image参数
    }
    
    await websocket.send(json.dumps(find_missing_image))
    print(f"📤 发送(缺少image): {json.dumps(find_missing_image, ensure_ascii=False)}")
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        print(f"📥 响应: {response}")
    except asyncio.TimeoutError:
        print("⏰ 响应超时")

if __name__ == "__main__":
    print("🚀 开始WebSocket测试 - textHandle.py")
    print(f"📡 目标地址: {WEBSOCKET_URL}")
    print("=" * 50)
    
    try:
        asyncio.run(test_websocket_connection())
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被用户中断")
    except Exception as e:
        print(f"\n\n💥 测试过程中发生错误: {str(e)}")
    
    print("\n" + "=" * 50)
    print("🏁 测试完成")
