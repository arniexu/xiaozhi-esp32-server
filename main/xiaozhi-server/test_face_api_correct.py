#!/usr/bin/env python3
"""
WebSocket Face API Test - Using image_path format
"""
import asyncio
import websockets
import json
import uuid

async def test_face_add_with_path():
    """Test face add API via WebSocket using image_path"""
    # Add required query parameters: device-id and client-id
    uri = "ws://localhost:8000/xiaozhi/v1/?device-id=test-device-001&client-id=test-client-001"
    
    # Use absolute path for server local image
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    test_image_path = os.path.join(current_dir, "data/test_face.jpg")  # Absolute path
    
    try:
        print(f"Connecting to WebSocket server: {uri}")
        async with websockets.connect(uri) as websocket:
            print("WebSocket connected successfully")
            
            # Generate request ID
            request_id = str(uuid.uuid4())
            
            # Correct face add request format with payload structure
            add_face_request = {
                "type": "face",
                "payload": {
                    "action": "add_face",
                    "person_name": "TestUser", 
                    "image_path": test_image_path
                },
                "request_id": request_id
            }
            
            print(f"Sending face add request (request_id: {request_id})")
            print(f"   - action: {add_face_request['payload']['action']}")
            print(f"   - person_name: {add_face_request['payload']['person_name']}")
            print(f"   - image_path: {add_face_request['payload']['image_path']}")
            
            # Send request
            request_json = json.dumps(add_face_request, ensure_ascii=True)
            print(f"Request JSON: {request_json}")
            
            await websocket.send(request_json)
            
            # Wait for response with timeout
            timeout = 60  # Increased timeout for OSS upload + face recognition
            
            try:
                print(f"Waiting for server response (timeout: {timeout}s)...")
                print("Note: This includes time for OSS upload + face recognition")
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
                        print("✅ Face add successful!")
                        return True
                    else:
                        print(f"❌ Face add failed: {response_data.get('message', 'Unknown error')}")
                        return False
                        
                except json.JSONDecodeError as e:
                    print(f"❌ JSON parse failed: {e}")
                    print(f"Raw response content: {response}")
                    return False
                    
            except asyncio.TimeoutError:
                print(f"⏰ Request timeout ({timeout}s)")
                return False
                
    except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
        print(f"❌ Connection error: {e}")
        print("💡 Please ensure xiaozhi-server is running on port 8000")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

async def test_list_people():
    """Test list people API"""
    # Add required query parameters: device-id and client-id
    uri = "ws://localhost:8000/xiaozhi/v1/?device-id=test-device-001&client-id=test-client-001"
    
    try:
        async with websockets.connect(uri) as websocket:
            request_id = str(uuid.uuid4())
            
            # List people request
            list_request = {
                "type": "face",
                "payload": {
                    "action": "list_people"
                },
                "request_id": request_id
            }
            
            print(f"\nSending list people request (request_id: {request_id})")
            await websocket.send(json.dumps(list_request, ensure_ascii=True))
            
            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            print(f"List people response:")
            print(json.dumps(response_data, indent=2, ensure_ascii=False))
            
            return response_data.get("status") == "success"
            
    except Exception as e:
        print(f"❌ List people failed: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 Starting WebSocket Face API Test (image_path format)")
    print("=" * 60)
    
    # Test 1: Face add with image_path
    print("\n📋 Test 1: Face Add (using image_path)")
    add_success = asyncio.run(test_face_add_with_path())
    
    if add_success:
        # Test 2: List people
        print("\n📋 Test 2: List People")
        list_success = asyncio.run(test_list_people())
    else:
        list_success = False
    
    # Test summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary:")
    print(f"  - Face Add: {'✅ SUCCESS' if add_success else '❌ FAILED'}")
    print(f"  - List People: {'✅ SUCCESS' if list_success else '❌ FAILED'}")
    
    if add_success and list_success:
        print("\n🎉 All tests passed!")
        return True
    else:
        print("\n💥 Some tests failed!")
        print("\n💡 Expected flow:")
        print("   1. Server receives WebSocket message with image_path")
        print("   2. Server reads local image file")
        print("   3. Server uploads image to OSS")
        print("   4. Server calls Alibaba Face Recognition API with OSS URL")
        print("   5. Server returns success/error response")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
