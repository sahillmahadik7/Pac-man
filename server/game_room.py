# server/game_room.py
import asyncio
import copy
import random
import math
import json
import time
from collections import deque
import websockets

class GameRoom:
    """Manages a single game instance with max 2 players"""
    
    MAX_PLAYERS = 2
    
    # Grid constants
    CELL_SIZE = 40
    ROWS = 15
    COLS = 19
    PLAYER_SPEED = 0.2
    GHOST_SPEED = 0.08
    PLAYER_RADIUS = 15
    GHOST_RADIUS = 15
    PELLET_RADIUS = 4
    POWER_TIME = 200
    GRID_SNAP_THRESHOLD = 0.2
    
    # Original maze template for resetting
    ORIGINAL_MAZE = [
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [1,3,2,2,2,2,2,2,2,1,2,2,2,2,2,2,2,3,1],
        [1,2,1,1,2,1,1,1,2,1,2,1,1,1,2,1,1,2,1],
        [1,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,1],
        [1,2,1,1,2,1,2,1,1,1,1,1,2,1,2,1,1,2,1],
        [1,2,2,2,2,1,2,2,2,1,2,2,2,1,2,2,2,2,1],
        [1,1,1,1,2,1,1,1,0,1,0,1,1,1,2,1,1,1,1],
        [0,0,0,1,2,1,0,0,0,0,0,0,0,1,2,1,0,0,0],
        [1,1,1,1,2,1,0,1,1,0,1,1,0,1,2,1,1,1,1],
        [2,2,2,2,2,0,0,1,0,0,0,1,0,0,2,2,2,2,2],
        [1,1,1,1,2,1,0,1,1,1,1,1,0,1,2,1,1,1,1],
        [0,0,0,1,2,1,0,0,0,0,0,0,0,1,2,1,0,0,0],
        [1,1,1,1,2,1,1,1,0,1,0,1,1,1,2,1,1,1,1],
        [1,2,2,2,2,2,2,2,2,1,2,2,2,2,2,2,2,2,1],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
    ]
    
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}  # websocket -> player data
        self.clients = set()
        self.maze = copy.deepcopy(self.ORIGINAL_MAZE)
        self.ghosts = self._initialize_ghosts()
        self.game_tick = 0
        self.running = False
        self.game_loop_task = None
        self.created_at = time.time()
        
    def _initialize_ghosts(self):
        """Initialize ghosts for this room"""
        class Ghost:
            def __init__(self, x, y, behavior, color):
                self.x = float(x)
                self.y = float(y)
                self.target_x = float(x)
                self.target_y = float(y)
                self.dx = 0
                self.dy = 0
                self.behavior = behavior
                self.color = color
                self.mode_timer = 0
                self.home_x = x
                self.home_y = y
                self.path = deque()
                self.stuck_counter = 0
                self.last_positions = deque(maxlen=4)
                self.behavior_change_timer = 0
                self.current_behavior = behavior
                self.randomness_factor = random.uniform(0.3, 0.8)
                
            def snap_to_grid(self):
                grid_x = round(self.x)
                grid_y = round(self.y)
                
                if abs(self.x - grid_x) < GameRoom.GRID_SNAP_THRESHOLD:
                    self.x = float(grid_x)
                if abs(self.y - grid_y) < GameRoom.GRID_SNAP_THRESHOLD:
                    self.y = float(grid_y)
        
        return [
            Ghost(9, 7, "aggressive", "red"),
            Ghost(8, 9, "patrol", "orange"), 
            Ghost(10, 9, "ambush", "purple"),
            Ghost(9, 8, "random", "green")
        ]
    
    def is_full(self):
        """Check if room is at maximum capacity"""
        return len(self.players) >= self.MAX_PLAYERS
    
    def is_empty(self):
        """Check if room has no players"""
        return len(self.players) == 0
    
    async def add_player(self, websocket):
        """Add a player to this room"""
        if self.is_full():
            return False
        
        self.clients.add(websocket)
        player_id = id(websocket)
        
        # Better starting positions for 2 players
        start_positions = [(1.0, 1.0), (17.0, 13.0)]
        start_pos = start_positions[len(self.players) % len(start_positions)]
        
        self.players[player_id] = {
            "websocket": websocket,
            "x": start_pos[0], 
            "y": start_pos[1], 
            "target_x": start_pos[0],
            "target_y": start_pos[1],
            "keys": set(), 
            "score": 0, 
            "dead": False, 
            "power": 0, 
            "direction": None,
            "name": f"Player{len(self.players)}",
            "moving": False,
            "last_move_time": 0
        }
        
        # Start game loop if this is the first player
        if len(self.players) == 1 and not self.running:
            self.running = True
            self.game_loop_task = asyncio.create_task(self._game_loop())
        
        return True
    
    async def remove_player(self, websocket):
        """Remove a player from this room"""
        player_id = id(websocket)
        if player_id in self.players:
            del self.players[player_id]
        
        self.clients.discard(websocket)
        
        # Stop game loop if no players left
        if self.is_empty() and self.running:
            self.running = False
            if self.game_loop_task:
                self.game_loop_task.cancel()
    
    async def handle_input(self, websocket, message):
        """Handle input from a player in this room"""
        player_id = id(websocket)
        if player_id not in self.players:
            return
        
        try:
            data = json.loads(message)
            key = data.get("key")
            action = data.get("action", "press")
            
            if key in {"UP", "DOWN", "LEFT", "RIGHT", "RESTART"}:
                if action == "press":
                    if key == "RESTART":
                        if self.players[player_id]["dead"]:
                            await self._reset_player(player_id)
                    else:
                        self.players[player_id]["keys"].add(key)
                else:
                    self.players[player_id]["keys"].discard(key)
        except json.JSONDecodeError:
            pass
    
    def can_move(self, x, y):
        """Enhanced movement validation"""
        if not (0.3 <= x < self.COLS - 0.3 and 0.3 <= y < self.ROWS - 0.3):
            return False
        
        center_x = int(round(x))
        center_y = int(round(y))
        
        if 0 <= center_x < self.COLS and 0 <= center_y < self.ROWS:
            if self.maze[center_y][center_x] == 1:
                return False
        
        if abs(x - round(x)) > 0.3 or abs(y - round(y)) > 0.3:
            corners = [
                (int(x), int(y)),
                (int(x + 0.4), int(y)),
                (int(x), int(y + 0.4)),
                (int(x + 0.4), int(y + 0.4))
            ]
            
            for cx, cy in corners:
                if 0 <= cx < self.COLS and 0 <= cy < self.ROWS:
                    if self.maze[cy][cx] == 1:
                        return False
        
        return True
    
    def _update_players(self):
        """Update player positions and handle collisions"""
        for player in self.players.values():
            if player["dead"]: 
                continue
            
            current_x, current_y = player["x"], player["y"]
            target_x, target_y = current_x, current_y
            
            # Determine target based on input
            if "UP" in player["keys"]:
                target_y = current_y - self.PLAYER_SPEED
                player["direction"] = "UP"
            elif "DOWN" in player["keys"]:
                target_y = current_y + self.PLAYER_SPEED
                player["direction"] = "DOWN"
            elif "LEFT" in player["keys"]:
                target_x = current_x - self.PLAYER_SPEED
                player["direction"] = "LEFT"
            elif "RIGHT" in player["keys"]:
                target_x = current_x + self.PLAYER_SPEED
                player["direction"] = "RIGHT"
            
            # Apply movement if valid
            if target_x != current_x or target_y != current_y:
                new_x = max(0.4, min(self.COLS - 0.4, target_x))
                new_y = max(0.4, min(self.ROWS - 0.4, target_y))
                
                if self.can_move(new_x, new_y):
                    player["x"], player["y"] = new_x, new_y
            
            # Snap to grid when very close (for pellet collection)
            snap_threshold = 0.15
            if abs(player["x"] - round(player["x"])) < snap_threshold:
                player["x"] = float(round(player["x"]))
            if abs(player["y"] - round(player["y"])) < snap_threshold:
                player["y"] = float(round(player["y"]))
            
            # Pellet collection
            gx, gy = int(round(player["x"])), int(round(player["y"]))
            if 0 <= gy < self.ROWS and 0 <= gx < self.COLS:
                cell = self.maze[gy][gx]
                if cell == 2:
                    self.maze[gy][gx] = 0
                    player["score"] += 10
                elif cell == 3:
                    self.maze[gy][gx] = 0
                    player["score"] += 50
                    player["power"] = self.POWER_TIME
    
    def _update_ghosts(self):
        """Update ghost AI and movement"""
        for ghost in self.ghosts:
            self._update_ghost_behavior(ghost)
            
            new_x = ghost.x + ghost.dx * self.GHOST_SPEED
            new_y = ghost.y + ghost.dy * self.GHOST_SPEED
            
            new_x = max(0.4, min(self.COLS - 0.4, new_x))
            new_y = max(0.4, min(self.ROWS - 0.4, new_y))
            
            if self.can_move(new_x, new_y):
                ghost.x, ghost.y = new_x, new_y
            else:
                valid_dirs = self._get_valid_directions(ghost.x, ghost.y)
                if valid_dirs:
                    ghost.dx, ghost.dy, _ = random.choice(valid_dirs)
    
    def _update_ghost_behavior(self, ghost):
        """Enhanced ghost AI"""
        ghost.mode_timer += 1
        ghost.behavior_change_timer += 1
        ghost.snap_to_grid()
        
        ghost.last_positions.append((ghost.x, ghost.y))
        
        if not self.players:
            return
        
        alive_players = [p for p in self.players.values() if not p["dead"]]
        if not alive_players:
            return
        
        closest_player = min(alive_players, 
                           key=lambda p: self._distance(ghost.x, ghost.y, p["x"], p["y"]))
        
        players_powered = any(p.get("power", 0) > 0 for p in alive_players)
        
        if ghost.behavior_change_timer > random.randint(60, 180):
            ghost.behavior_change_timer = 0
            behaviors = ["aggressive", "patrol", "ambush", "random", "confused"]
            ghost.current_behavior = random.choice(behaviors)
            ghost.randomness_factor = random.uniform(0.4, 0.9)
        
        if random.random() < ghost.randomness_factor:
            ghost.current_behavior = "random"
        
        if players_powered:
            if random.random() < 0.7:
                corners = [(1, 1), (17, 1), (17, 13), (1, 13)]
                target = min(corners, key=lambda c: self._distance(ghost.x, ghost.y, c[0], c[1]))
                target_x, target_y = target
            else:
                target_x = random.randint(1, self.COLS-2)
                target_y = random.randint(1, self.ROWS-2)
        else:
            if ghost.current_behavior == "aggressive":
                if random.random() < 0.8:
                    target_x, target_y = closest_player["x"], closest_player["y"]
                else:
                    target_x = random.randint(1, self.COLS-2)
                    target_y = random.randint(1, self.ROWS-2)
            else:
                target_x = random.randint(1, self.COLS-2)
                target_y = random.randint(1, self.ROWS-2)
        
        # Simple movement towards target
        if ghost.mode_timer % random.randint(8, 20) == 0:
            valid_dirs = self._get_valid_directions(ghost.x, ghost.y)
            if valid_dirs:
                if random.random() < 0.7:
                    best_dir = None
                    best_dist = float('inf')
                    
                    for dx, dy, direction in valid_dirs:
                        test_x = ghost.x + dx * self.GHOST_SPEED
                        test_y = ghost.y + dy * self.GHOST_SPEED
                        dist = self._distance(test_x, test_y, target_x, target_y)
                        
                        if dist < best_dist:
                            best_dist = dist
                            best_dir = (dx, dy)
                    
                    if best_dir:
                        ghost.dx, ghost.dy = best_dir
                else:
                    ghost.dx, ghost.dy, _ = random.choice(valid_dirs)
    
    def _get_valid_directions(self, x, y):
        """Get valid movement directions"""
        directions = []
        moves = [(-1, 0, "LEFT"), (1, 0, "RIGHT"), (0, -1, "UP"), (0, 1, "DOWN")]
        
        for dx, dy, direction in moves:
            new_x = x + dx * self.GHOST_SPEED * 2
            new_y = y + dy * self.GHOST_SPEED * 2
            if self.can_move(new_x, new_y):
                directions.append((dx, dy, direction))
        
        return directions
    
    def _distance(self, x1, y1, x2, y2):
        """Calculate distance between two points"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    def _check_player_death(self):
        """Check for player-ghost collisions"""
        for player in self.players.values():
            if player["dead"]: 
                continue
                
            px, py = player["x"], player["y"]
            power = player.get("power", 0)
            
            for ghost in self.ghosts:
                gx, gy = ghost.x, ghost.y
                
                if self._distance(px, py, gx, gy) < 0.8:
                    if power > 0:
                        player["score"] += 200
                        # Reset ghost to home
                        ghost.x, ghost.y = ghost.home_x, ghost.home_y
                        ghost.dx, ghost.dy = 0, 0
                        ghost.path.clear()
                        ghost.mode_timer = 0
                        ghost.behavior_change_timer = 0
                        ghost.current_behavior = ghost.behavior
                    else:
                        player["dead"] = True
                        
            if power > 0:
                player["power"] -= 1
    
    def _check_victory(self):
        """Check for victory condition"""
        total_pellets = sum(row.count(2) + row.count(3) for row in self.maze)
        return total_pellets == 0
    
    async def _reset_player(self, player_id):
        """Reset a specific player when they die"""
        if player_id in self.players:
            start_positions = [(1.0, 1.0), (17.0, 13.0)]
            start_pos = start_positions[len(self.players) % len(start_positions)]
            
            player = self.players[player_id]
            player["x"] = start_pos[0]
            player["y"] = start_pos[1]
            player["target_x"] = start_pos[0]
            player["target_y"] = start_pos[1]
            player["score"] = 0
            player["dead"] = False
            player["power"] = 0
            player["direction"] = None
            player["keys"] = set()
            
            # Reset the maze for this room
            self.maze = copy.deepcopy(self.ORIGINAL_MAZE)
    
    async def _broadcast_game_state(self):
        """Broadcast game state to all clients in this room"""
        total_pellets = sum(row.count(2) + row.count(3) for row in self.maze)
        alive_players = sum(1 for p in self.players.values() if not p["dead"])
        victory = self._check_victory()
        
        # Prepare player data without websocket references
        players_data = {}
        for pid, player in self.players.items():
            players_data[pid] = {
                "x": round(player["x"], 2),
                "y": round(player["y"], 2),
                "score": player["score"],
                "dead": player["dead"],
                "power": player.get("power", 0),
                "name": player.get("name", f"Player{pid}"),
                "direction": player.get("direction")
            }
        
        payload = json.dumps({
            "room_id": self.room_id,
            "players": players_data,
            "ghosts": [
                {
                    "x": round(g.x, 2), 
                    "y": round(g.y, 2), 
                    "behavior": g.current_behavior,
                    "color": g.color
                } 
                for g in self.ghosts
            ],
            "maze": self.maze,
            "game_stats": {
                "total_pellets": total_pellets,
                "alive_players": alive_players,
                "total_players": len(self.players),
                "victory": victory,
                "game_tick": self.game_tick,
                "max_players": self.MAX_PLAYERS
            }
        })
        
        disconnected = set()
        for ws in list(self.clients):
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                disconnected.add(ws)
                
        for ws in disconnected:
            self.clients.discard(ws)
            await self.remove_player(ws)
    
    async def _game_loop(self):
        """Main game loop for this room"""
        try:
            while self.running and not self.is_empty():
                self.game_tick += 1
                
                self._update_players()
                self._update_ghosts()
                self._check_player_death()
                
                await self._broadcast_game_state()
                await asyncio.sleep(0.05)  # 20 FPS
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False