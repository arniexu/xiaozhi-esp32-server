#!/usr/bin/env python3
import asyncio
import websockets
import json

async def test_new_face_format():
    uri = "ws://localhost:8000/xiaozhi/v1/?device-id=test-device&client-id=test-client"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("WebSocket 连接已建立")
            
            # 发送新版人脸添加请求（包含request_id）
            message = {
                "type": "face",
                "payload": {
                    "action": "add_face",
                    "person_name": "小护2025",
                    "image_path": "/home/xuqianjin/face_990080_4100376205.jpg"
                },
                "request_id": "141128169_1163835400"
            }
            
            print(f"发送消息: {json.dumps(message, ensure_ascii=False, indent=2)}")
            await websocket.send(json.dumps(message))
            
            # 等待响应
            response = await asyncio.wait_for(websocket.recv(), timeout=60)
            print(f"收到响应: {response}")
            
            # 尝试解析JSON响应
            try:
                response_data = json.loads(response)
                print(f"解析后的响应: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
                
                # 检查响应是否包含request_id
                if "request_id" in response_data:
                    print(f"✅ 响应包含request_id: {response_data['request_id']}")
                else:
                    print("❌ 响应不包含request_id")
                    
            except json.JSONDecodeError:
                print("响应不是有效的JSON格式")
            
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    asyncio.run(test_new_face_format())
