#!/usr/bin/env python3
"""
模拟WebSocket请求测试人脸识别API
"""
import asyncio
import websockets
import json
import base64
import uuid
import os
from pathlib import Path

def load_image_as_base64(image_path):
    """加载图片并转换为base64"""
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
            base64_data = base64.b64encode(image_data).decode('utf-8')
            return base64_data
    except Exception as e:
        print(f"❌ 加载图片失败: {e}")
        return None

async def test_websocket_face_api():
    """测试WebSocket人脸识别API"""
    # WebSocket服务器地址
    uri = "ws://localhost:8000/xiaozhi/v1/"
    
    # 测试图片路径
    current_dir = Path(__file__).parent
    test_image_path = current_dir / "data" / "test_face.jpg"
    
    # 检查测试图片是否存在
    if not test_image_path.exists():
        print(f"❌ 测试图片不存在: {test_image_path}")
        print("💡 请在data目录下放置一张名为test_face.jpg的测试图片")
        return False
    
    # 加载测试图片
    print(f"📸 加载测试图片: {test_image_path}")
    image_base64 = load_image_as_base64(test_image_path)
    if not image_base64:
        return False
    
    try:
        print(f"🔗 连接到WebSocket服务器: {uri}")
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket连接成功")
            
            # 生成请求ID
            request_id = str(uuid.uuid4())
            
            # 构造人脸添加请求（只使用英文）
            add_face_request = {
                "action": "add_face",
                "person_id": "test_person_001",
                "person_name": "Test_User",
                "image_base64": image_base64,
                "request_id": request_id
            }
            
            print(f"📤 发送人脸添加请求 (request_id: {request_id})")
            print(f"   - person_id: {add_face_request['person_id']}")
            print(f"   - person_name: {add_face_request['person_name']}")
            print(f"   - image_base64 长度: {len(image_base64)} 字符")
            
            # 发送请求
            await websocket.send(json.dumps(add_face_request))
            
            # 设置超时时间
            timeout = 30  # 30秒超时
            
            try:
                # 等待响应
                print(f"⏳ 等待服务器响应 (超时: {timeout}秒)...")
                response = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                
                print(f"📥 原始响应: {repr(response)}")
                
                # 检查响应是否为空
                if not response or response.strip() == "":
                    print("❌ 服务器返回空响应")
                    return False
                
                # 解析响应
                try:
                    response_data = json.loads(response)
                    print(f"📥 解析后的响应:")
                    print(json.dumps(response_data, indent=2, ensure_ascii=False))
                except json.JSONDecodeError as e:
                    print(f"❌ JSON解析失败: {e}")
                    print(f"原始响应内容: {response}")
                    return False
                
                # 检查响应状态
                if response_data.get("status") == "success":
                    print("✅ 人脸添加成功!")
                    return True
                else:
                    print(f"❌ 人脸添加失败: {response_data.get('message', '未知错误')}")
                    return False
                    
            except asyncio.TimeoutError:
                print(f"⏰ 请求超时 ({timeout}秒)")
                return False
                
    except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError):
        print("❌ 无法连接到WebSocket服务器")
        print("💡 请确保xiaozhi-server服务正在运行 (端口8000)")
        return False
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False

async def test_list_people():
    """测试获取人员列表"""
    uri = "ws://localhost:8000/xiaozhi/v1/"
    
    try:
        async with websockets.connect(uri) as websocket:
            # 构造获取人员列表请求
            list_request = {
                "action": "list_people",
                "request_id": str(uuid.uuid4())
            }
            
            print(f"📤 发送获取人员列表请求")
            await websocket.send(json.dumps(list_request))
            
            # 等待响应
            response = await asyncio.wait_for(websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            print(f"📥 人员列表响应:")
            print(json.dumps(response_data, indent=2, ensure_ascii=False))
            
            return response_data.get("status") == "success"
            
    except Exception as e:
        print(f"❌ 获取人员列表失败: {e}")
        return False

def main():
    """主测试函数"""
    print("🚀 开始WebSocket人脸识别API测试")
    print("=" * 50)
    
    # 测试1: 人脸添加
    print("\n📋 测试1: 人脸添加")
    add_success = asyncio.run(test_websocket_face_api())
    
    if add_success:
        # 测试2: 获取人员列表
        print("\n📋 测试2: 获取人员列表")
        list_success = asyncio.run(test_list_people())
    else:
        list_success = False
    
    # 测试结果总结
    print("\n" + "=" * 50)
    print("📊 测试结果总结:")
    print(f"  - 人脸添加: {'✅ 成功' if add_success else '❌ 失败'}")
    print(f"  - 人员列表: {'✅ 成功' if list_success else '❌ 失败'}")
    
    if add_success and list_success:
        print("\n🎉 所有测试通过!")
        return True
    else:
        print("\n💥 部分测试失败!")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
