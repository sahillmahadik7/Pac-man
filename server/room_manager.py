# server/room_manager.py
import asyncio
import time
import uuid
import websockets
from typing import Dict, Optional, Set
from .game_room import GameRoom

class RoomManager:
    """Manages multiple game rooms and assigns players to available rooms"""
    
    def __init__(self):
        self.rooms: Dict[str, GameRoom] = {}
        self.player_to_room: Dict[int, str] = {}  # player_id -> room_id
        self.cleanup_interval = 60  # seconds
        self._cleanup_task = None
        
    async def start(self):
        """Start the room manager"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        print("Room Manager started")
    
    async def stop(self):
        """Stop the room manager and all rooms"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        # Stop all rooms
        for room in list(self.rooms.values()):
            await self._cleanup_room(room.room_id)
        
        print("Room Manager stopped")
    
    async def assign_player_to_room(self, websocket) -> Optional[str]:
        """Assign a player to an available room, creating a new one if necessary"""
        player_id = id(websocket)
        
        # Check if player is already in a room
        if player_id in self.player_to_room:
            return self.player_to_room[player_id]
        
        # Find an available room (not full)
        available_room = None
        for room in self.rooms.values():
            if not room.is_full():
                available_room = room
                break
        
        # Create a new room if no available room found
        if available_room is None:
            room_id = str(uuid.uuid4())[:8]  # Short room ID
            available_room = GameRoom(room_id)
            self.rooms[room_id] = available_room
            print(f"Created new room: {room_id}")
        
        # Add player to the room
        success = await available_room.add_player(websocket)
        if success:
            self.player_to_room[player_id] = available_room.room_id
            print(f"Player {player_id} assigned to room {available_room.room_id}")
            print(f"Room {available_room.room_id} now has {len(available_room.players)} players")
            return available_room.room_id
        
        return None

    async def add_player_to_specific_room(self, websocket, room_id: str, create_if_missing: bool = True) -> Optional[str]:
        """Add a player to a specific room by ID. Optionally create if missing.
        Returns room_id on success, None on failure (e.g., room full or not found and create disabled).
        """
        player_id = id(websocket)
        
        # If already tracked, return existing room
        if player_id in self.player_to_room:
            return self.player_to_room[player_id]
        
        room = self.rooms.get(room_id)
        if room is None and create_if_missing:
            room = GameRoom(room_id)
            self.rooms[room_id] = room
            print(f"Created room with token: {room_id}")
        
        if room is None:
            return None
        
        if room.is_full():
            print(f"Room {room_id} is full")
            return None
        
        success = await room.add_player(websocket)
        if success:
            self.player_to_room[player_id] = room.room_id
            print(f"Player {player_id} joined room {room.room_id}")
            print(f"Room {room.room_id} now has {len(room.players)} players")
            return room.room_id
        return None
    
    async def remove_player_from_room(self, websocket):
        """Remove a player from their room"""
        player_id = id(websocket)
        
        if player_id not in self.player_to_room:
            return
        
        room_id = self.player_to_room[player_id]
        room = self.rooms.get(room_id)
        
        if room:
            await room.remove_player(websocket)
            print(f"Player {player_id} removed from room {room_id}")
            print(f"Room {room_id} now has {len(room.players)} players")
            
            # Schedule room cleanup if empty
            if room.is_empty():
                asyncio.create_task(self._schedule_room_cleanup(room_id))
        
        del self.player_to_room[player_id]
    
    async def handle_player_input(self, websocket, message):
        """Forward player input to their room"""
        player_id = id(websocket)
        
        if player_id not in self.player_to_room:
            return
        
        room_id = self.player_to_room[player_id]
        room = self.rooms.get(room_id)
        
        if room:
            await room.handle_input(websocket, message)
    
    def get_room_for_player(self, websocket) -> Optional[GameRoom]:
        """Get the room that a player is in"""
        player_id = id(websocket)
        
        if player_id not in self.player_to_room:
            return None
        
        room_id = self.player_to_room[player_id]
        return self.rooms.get(room_id)
    
    def get_room_stats(self) -> Dict:
        """Get statistics about all rooms"""
        total_rooms = len(self.rooms)
        total_players = sum(len(room.players) for room in self.rooms.values())
        active_rooms = sum(1 for room in self.rooms.values() if not room.is_empty())
        
        room_details = []
        for room_id, room in self.rooms.items():
            room_details.append({
                "room_id": room_id,
                "players": len(room.players),
                "max_players": room.MAX_PLAYERS,
                "is_full": room.is_full(),
                "is_empty": room.is_empty(),
                "running": room.running,
                "created_at": room.created_at,
                "game_tick": room.game_tick
            })
        
        return {
            "total_rooms": total_rooms,
            "active_rooms": active_rooms,
            "total_players": total_players,
            "rooms": room_details
        }
    
    async def _schedule_room_cleanup(self, room_id: str, delay: float = 30.0):
        """Schedule a room for cleanup after a delay"""
        await asyncio.sleep(delay)
        
        room = self.rooms.get(room_id)
        if room and room.is_empty():
            await self._cleanup_room(room_id)
    
    async def _cleanup_room(self, room_id: str):
        """Clean up a specific room"""
        if room_id not in self.rooms:
            return
        
        room = self.rooms[room_id]
        
        # Remove all players from tracking
        players_to_remove = []
        for player_id, tracked_room_id in self.player_to_room.items():
            if tracked_room_id == room_id:
                players_to_remove.append(player_id)
        
        for player_id in players_to_remove:
            del self.player_to_room[player_id]
        
        # Stop the room's game loop if running
        if room.running and room.game_loop_task:
            room.game_loop_task.cancel()
        
        # Remove the room
        del self.rooms[room_id]
        print(f"Cleaned up room: {room_id}")
    
    async def _cleanup_loop(self):
        """Periodic cleanup of empty rooms"""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                
                # Find empty rooms older than 5 minutes
                current_time = time.time()
                rooms_to_cleanup = []
                
                for room_id, room in self.rooms.items():
                    if room.is_empty() and (current_time - room.created_at) > 300:  # 5 minutes
                        rooms_to_cleanup.append(room_id)
                
                # Clean up old empty rooms
                for room_id in rooms_to_cleanup:
                    await self._cleanup_room(room_id)
                
                # Log stats periodically
                if len(self.rooms) > 0:
                    stats = self.get_room_stats()
                    print(f"Room Stats - Active: {stats['active_rooms']}, Total: {stats['total_rooms']}, Players: {stats['total_players']}")
                    
        except asyncio.CancelledError:
            pass

# Global room manager instance
room_manager = RoomManager()