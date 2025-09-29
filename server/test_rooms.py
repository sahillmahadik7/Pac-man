# Test script for room system
import asyncio
import json
import websockets
from room_manager import room_manager

class MockWebSocket:
    def __init__(self, id_val):
        self._id = id_val
        
    def __hash__(self):
        return self._id
        
    def __eq__(self, other):
        return isinstance(other, MockWebSocket) and self._id == other._id

async def test_room_system():
    print("Testing room system...")
    
    # Start room manager
    await room_manager.start()
    
    # Create mock websockets (simulating players)
    ws1 = MockWebSocket(1)
    ws2 = MockWebSocket(2) 
    ws3 = MockWebSocket(3)
    ws4 = MockWebSocket(4)
    
    # Test room assignment
    print("\n1. Testing room assignment...")
    room1 = await room_manager.assign_player_to_room(ws1)
    print(f"Player 1 assigned to room: {room1}")
    
    room2 = await room_manager.assign_player_to_room(ws2)
    print(f"Player 2 assigned to room: {room2}")
    
    # Should be same room (room1 == room2)
    print(f"Same room? {room1 == room2}")
    
    # Third player should get new room
    room3 = await room_manager.assign_player_to_room(ws3)
    print(f"Player 3 assigned to room: {room3}")
    print(f"Different room? {room1 != room3}")
    
    # Fourth player should join room3
    room4 = await room_manager.assign_player_to_room(ws4)
    print(f"Player 4 assigned to room: {room4}")
    print(f"Same room as player 3? {room3 == room4}")
    
    # Check room stats
    print("\n2. Room statistics:")
    stats = room_manager.get_room_stats()
    print(f"Total rooms: {stats['total_rooms']}")
    print(f"Active rooms: {stats['active_rooms']}")
    print(f"Total players: {stats['total_players']}")
    
    for room_info in stats['rooms']:
        print(f"  Room {room_info['room_id']}: {room_info['players']}/{room_info['max_players']} players")
    
    # Test player removal
    print("\n3. Testing player removal...")
    await room_manager.remove_player_from_room(ws1)
    print("Removed player 1")
    
    stats = room_manager.get_room_stats()
    print(f"Total players after removal: {stats['total_players']}")
    
    # Stop room manager
    await room_manager.stop()
    print("\n✅ Room system test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_room_system())