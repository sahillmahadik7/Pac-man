# server/main.py - Room-based multiplayer Pac-Man server
import asyncio
import websockets
import json
from room_manager import room_manager

async def handle_client(websocket):
    """Handle a new client connection"""
    print("Client connected")
    
    try:
        # Assign player to a room
        room_id = await room_manager.assign_player_to_room(websocket)
        if not room_id:
            await websocket.send(json.dumps({"error": "Failed to assign to room"}))
            return
        
        # Send initial room assignment message
        await websocket.send(json.dumps({
            "type": "room_assignment", 
            "room_id": room_id,
            "message": f"Assigned to room {room_id}"
        }))
        
        # Handle messages from the client
        async for message in websocket:
            try:
                await room_manager.handle_player_input(websocket, message)
            except json.JSONDecodeError:
                print("Invalid JSON received from client")
            except Exception as e:
                print(f"Error handling player input: {e}")
                
    except websockets.ConnectionClosedOK:
        print("Client disconnected normally")
    except websockets.ConnectionClosedError as e:
        print(f"Client disconnected with error: {e}")
    except Exception as e:
        print(f"Unexpected error in handle_client: {e}")
    finally:
        # Remove player from their room
        await room_manager.remove_player_from_room(websocket)
        print("Client connection cleaned up")

async def status_reporter():
    """Periodically report server status"""
    try:
        while True:
            await asyncio.sleep(30)  # Report every 30 seconds
            stats = room_manager.get_room_stats()
            if stats['total_players'] > 0:
                print(f"=== SERVER STATUS ===")
                print(f"Active Rooms: {stats['active_rooms']}")
                print(f"Total Players: {stats['total_players']}")
                for room in stats['rooms']:
                    if not room['is_empty']:
                        print(f"  Room {room['room_id']}: {room['players']}/{room['max_players']} players")
                print("====================")
    except asyncio.CancelledError:
        pass

async def main():
    """Main server function"""
    print("🎮 Room-Based Pac-Man Multiplayer Server")
    print("========================================")
    print("Features:")
    print("- Max 2 players per room")
    print("- Automatic room creation")
    print("- Simultaneous games")
    print("- Enhanced ghost AI")
    
    # Start the room manager
    await room_manager.start()
    
    # Start status reporter
    status_task = asyncio.create_task(status_reporter())
    
    try:
        # Start WebSocket server
        async with websockets.serve(handle_client, "0.0.0.0", 8765):
            print("\n✅ Server running on ws://localhost:8765")
            print("Players will be automatically assigned to rooms (max 2 per room)")
            print("Press Ctrl+C to stop the server\n")
            
            # Keep the server running
            await asyncio.Event().wait()  # Wait indefinitely
            
    except KeyboardInterrupt:
        print("\n🛑 Server shutdown requested")
    finally:
        # Cleanup
        status_task.cancel()
        await room_manager.stop()
        print("✅ Server stopped successfully")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped")
    except Exception as e:
        print(f"Fatal error: {e}")