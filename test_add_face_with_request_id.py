#!/usr/bin/env python3
import asyncio
import websockets
import json

async def test_add_face_with_request_id():
    """测试带有request_id的add_face请求"""
    uri = "ws://localhost:8000/xiaozhi/v1/?device-id=test-device&client-id=test-client"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("WebSocket 连接已建立")
            
            # 发送人脸添加请求 - 完全匹配用户提供的格式
            message = {
                "type": "face",
                "payload": {
                    "action": "add_face",
                    "person_name": "小护2025",
                    "image_path": "/home/xuqianjin/face_120066_149577570.jpg"
                },
                "request_id": "141128169_1163835400"
            }
            
            print(f"发送消息: {json.dumps(message, ensure_ascii=False, indent=2)}")
            await websocket.send(json.dumps(message))
            
            # 等待响应
            print("等待响应...")
            response = await asyncio.wait_for(websocket.recv(), timeout=60)
            print(f"收到响应: {response}")
            
            # 尝试解析JSON响应
            try:
                response_data = json.loads(response)
                print(f"解析后的响应: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                
                # 检查响应是否包含request_id
                if "request_id" in response_data:
                    print(f"✅ 响应包含request_id: {response_data['request_id']}")
                    if response_data["request_id"] == message["request_id"]:
                        print("✅ request_id匹配")
                    else:
                        print("❌ request_id不匹配")
                else:
                    print("❌ 响应中缺少request_id")
                    
            except json.JSONDecodeError:
                print("❌ 响应不是有效的JSON格式")
            
    except Exception as e:
        print(f"错误: {e}")

async def test_add_face_without_request_id():
    """测试不带request_id的add_face请求"""
    uri = "ws://localhost:8000/xiaozhi/v1/?device-id=test-device2&client-id=test-client2"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("\n" + "="*50)
            print("WebSocket 连接已建立 (测试不带request_id)")
            
            # 发送人脸添加请求 - 不包含request_id
            message = {
                "type": "face",
                "payload": {
                    "action": "add_face",
                    "person_name": "测试用户2025",
                    "image_path": "/home/xuqianjin/face_120066_149577570.jpg"
                }
            }
            
            print(f"发送消息: {json.dumps(message, ensure_ascii=False, indent=2)}")
            await websocket.send(json.dumps(message))
            
            # 等待响应
            print("等待响应...")
            response = await asyncio.wait_for(websocket.recv(), timeout=60)
            print(f"收到响应: {response}")
            
            # 尝试解析JSON响应
            try:
                response_data = json.loads(response)
                print(f"解析后的响应: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                
                # 检查响应是否不包含request_id
                if "request_id" not in response_data:
                    print("✅ 响应正确地不包含request_id")
                else:
                    print(f"❌ 响应意外包含request_id: {response_data['request_id']}")
                    
            except json.JSONDecodeError:
                print("❌ 响应不是有效的JSON格式")
            
    except Exception as e:
        print(f"错误: {e}")

async def main():
    print("开始测试add_face功能...")
    print("测试1: 带有request_id的请求")
    await test_add_face_with_request_id()
    
    print("\n测试2: 不带request_id的请求")
    await test_add_face_without_request_id()
    
    print("\n测试完成!")

if __name__ == "__main__":
    asyncio.run(main())
