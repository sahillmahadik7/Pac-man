# Simple test client for room-based multiplayer
import asyncio
import websockets
import json

async def test_client(client_name):
    """Test client that connects and sends some inputs"""
    try:
        async with websockets.connect("ws://localhost:8765") as websocket:
            print(f"[{client_name}] Connected to server")
            
            # Listen for initial messages
            try:
                while True:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(message)
                    
                    if data.get("type") == "room_assignment":
                        room_id = data.get("room_id")
                        print(f"[{client_name}] Assigned to room: {room_id}")
                        break
                    elif "room_id" in data:
                        room_id = data.get("room_id")
                        players = data.get("players", {})
                        print(f"[{client_name}] Room {room_id}: {len(players)} players")
                        
                        # Send some test inputs
                        if len(players) > 0:
                            await websocket.send(json.dumps({"key": "RIGHT", "action": "press"}))
                            await asyncio.sleep(0.1)
                            await websocket.send(json.dumps({"key": "RIGHT", "action": "release"}))
                            print(f"[{client_name}] Sent test input")
                        
                        await asyncio.sleep(1)
                    
            except asyncio.TimeoutError:
                print(f"[{client_name}] Timeout waiting for messages")
    
    except Exception as e:
        print(f"[{client_name}] Error: {e}")

async def test_multiple_clients():
    """Test multiple clients connecting simultaneously"""
    print("Testing multiple clients...")
    
    # Start multiple clients
    clients = [
        asyncio.create_task(test_client("Client1")),
        asyncio.create_task(test_client("Client2")),
        asyncio.create_task(test_client("Client3")),
        asyncio.create_task(test_client("Client4"))
    ]
    
    # Wait for all clients to finish (or timeout)
    try:
        await asyncio.wait_for(asyncio.gather(*clients), timeout=10)
    except asyncio.TimeoutError:
        print("Test completed (timeout)")
    
    print("✅ Multi-client test completed!")

if __name__ == "__main__":
    print("🧪 Testing Room-Based Multiplayer System")
    print("Make sure the server is running first!")
    print("==========================================")
    asyncio.run(test_multiple_clients())