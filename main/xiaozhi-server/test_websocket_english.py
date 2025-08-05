#!/usr/bin/env python3
"""
Simple WebSocket Face API Test - English Only
"""
import asyncio
import websockets
import json
import uuid

def main():
    """Main test function"""
    print("Starting WebSocket Face API Test (English Only)")
    print("=" * 50)
    
    # Test: Face add
    print("\nTest: Face Add")
    success = asyncio.run(test_face_add())
    
    # Test summary
    print("\n" + "=" * 50)
    print("Test Results:")
    print(f"  - Face Add: {'SUCCESS' if success else 'FAILED'}")
    
    if success:
        print("\nAll tests passed!")
        return True
    else:
        print("\nSome tests failed!")
        return False

async def test_face_add():
    """Test face add API via WebSocket"""
    uri = "ws://localhost:8000/xiaozhi/v1/"
    
    # Test image path on server
    test_image_path = "data/test_face.jpg"  # 服务器本地路径
    
    try:
        print(f"Connecting to WebSocket server: {uri}")
        async with websockets.connect(uri) as websocket:
            print("WebSocket connected successfully")
            
            # Generate request ID
            request_id = str(uuid.uuid4())
            
            # Face add request - using image_path (server local path)
            add_face_request = {
                "type": "face",
                "payload": {
                    "action": "add_face",
                    "image_path": test_image_path,
                    "person_name": "TestUser",
                    "person_id": "test_person_001"
                },
                "request_id": request_id
            }
            
            print(f"Sending face add request (request_id: {request_id})")
            print(f"   - action: {add_face_request['payload']['action']}")
            print(f"   - image_path: {add_face_request['payload']['image_path']}")
            print(f"   - person_name: {add_face_request['payload']['person_name']}")
            print(f"   - person_id: {add_face_request['payload']['person_id']}")
            
            # Send request
            request_json = json.dumps(add_face_request, ensure_ascii=True)
            print(f"Request JSON: {request_json}")
            
            await websocket.send(request_json)
            
            # Wait for response with timeout
            timeout = 30
            
            try:
                print(f"Waiting for server response (timeout: {timeout}s)...")
                response = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                
                print(f"Raw response: {repr(response)}")
                
                # Check if response is empty
                if not response or response.strip() == "":
                    print("Server returned empty response")
                    return False
                
                # Try to parse JSON response
                try:
                    response_data = json.loads(response)
                    print(f"Parsed response:")
                    print(json.dumps(response_data, indent=2, ensure_ascii=False))
                    
                    # Check response status
                    if response_data.get("status") == "success":
                        print("Face add successful!")
                        return True
                    else:
                        print(f"Face add failed: {response_data.get('message', 'Unknown error')}")
                        return False
                        
                except json.JSONDecodeError as e:
                    print(f"JSON parse failed: {e}")
                    print(f"Raw response content: {response}")
                    return False
                    
            except asyncio.TimeoutError:
                print(f"Request timeout ({timeout}s)")
                return False
                
    except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
        print(f"Connection error: {e}")
        print("Please ensure xiaozhi-server is running on port 8000")
        return False
    except Exception as e:
        print(f"Test error: {e}")
        return False

def main():
    """Main test function"""
    print("Starting WebSocket Face API Test (English Only)")
    print("=" * 50)
    
    # Test: Face add
    print("\nTest: Face Add")
    success = asyncio.run(test_face_add())
    
    # Test summary
    print("\n" + "=" * 50)
    print("Test Results:")
    print(f"  - Face Add: {'SUCCESS' if success else 'FAILED'}")
    
    if success:
        print("\nAll tests passed!")
        return True
    else:
        print("\nSome tests failed!")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
