import asyncio
import websockets
import json
import random
import math
from collections import deque
import copy

# Connected clients
clients = set()

# Grid constants - Fixed for better movement
CELL_SIZE = 40
ROWS = 15
COLS = 19
PLAYER_SPEED = 0.2  # Increased for smoother movement
GHOST_SPEED = 0.08  # Significantly reduced ghost speed
PLAYER_RADIUS = 15
GHOST_RADIUS = 15
PELLET_RADIUS = 4
POWER_TIME = 200  # Reduced power time
GRID_SNAP_THRESHOLD = 0.2  # Increased for better grid alignment

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

# Current maze (will be modified during gameplay)
MAZE = copy.deepcopy(ORIGINAL_MAZE)

# Player states with enhanced tracking
players = {}

# Enhanced ghost AI with more unpredictable behavior
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
        self.randomness_factor = random.uniform(0.3, 0.8)  # Individual randomness
        
    def snap_to_grid(self):
        """Snap position to grid if close enough"""
        grid_x = round(self.x)
        grid_y = round(self.y)
        
        if abs(self.x - grid_x) < GRID_SNAP_THRESHOLD:
            self.x = float(grid_x)
        if abs(self.y - grid_y) < GRID_SNAP_THRESHOLD:
            self.y = float(grid_y)

# Initialize ghosts with enhanced properties
GHOSTS = [
    Ghost(9, 7, "aggressive", "red"),
    Ghost(8, 9, "patrol", "orange"), 
    Ghost(10, 9, "ambush", "purple"),
    Ghost(9, 8, "random", "green")
]

def can_move(x, y):
    """Enhanced movement validation with looser bounds checking"""
    if not (0.3 <= x < COLS - 0.3 and 0.3 <= y < ROWS - 0.3):
        return False
    
    # Check center point primarily
    center_x = int(round(x))
    center_y = int(round(y))
    
    if 0 <= center_x < COLS and 0 <= center_y < ROWS:
        if MAZE[center_y][center_x] == 1:
            return False
    
    # Check corners only if close to grid lines
    if abs(x - round(x)) > 0.3 or abs(y - round(y)) > 0.3:
        corners = [
            (int(x), int(y)),
            (int(x + 0.4), int(y)),
            (int(x), int(y + 0.4)),
            (int(x + 0.4), int(y + 0.4))
        ]
        
        for cx, cy in corners:
            if 0 <= cx < COLS and 0 <= cy < ROWS:
                if MAZE[cy][cx] == 1:
                    return False
    
    return True

def get_valid_directions(x, y):
    """Get valid movement directions with improved checking"""
    directions = []
    moves = [(-1, 0, "LEFT"), (1, 0, "RIGHT"), (0, -1, "UP"), (0, 1, "DOWN")]
    
    for dx, dy, direction in moves:
        new_x = x + dx * GHOST_SPEED * 2
        new_y = y + dy * GHOST_SPEED * 2
        if can_move(new_x, new_y):
            directions.append((dx, dy, direction))
    
    return directions

def find_path_bfs(start_x, start_y, target_x, target_y, max_depth=15):
    """Enhanced BFS pathfinding for ghosts"""
    if not can_move(target_x, target_y):
        return None
    
    queue = deque([(int(start_x), int(start_y), [])])
    visited = set()
    
    while queue and len(visited) < max_depth:
        x, y, path = queue.popleft()
        
        if (x, y) in visited:
            continue
        visited.add((x, y))
        
        if abs(x - target_x) < 2 and abs(y - target_y) < 2:
            return path
        
        for dx, dy, direction in [(-1, 0, "LEFT"), (1, 0, "RIGHT"), (0, -1, "UP"), (0, 1, "DOWN")]:
            new_x, new_y = x + dx, y + dy
            if can_move(new_x, new_y) and (new_x, new_y) not in visited:
                queue.append((new_x, new_y, path + [direction]))
    
    return None

def distance(x1, y1, x2, y2):
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def reset_game():
    """Reset the entire game state"""
    global MAZE, players, GHOSTS
    
    # Reset maze
    MAZE.clear()
    for row in ORIGINAL_MAZE:
        MAZE.append(row[:])  # Deep copy each row
    
    # Reset all players
    start_positions = [(1.0, 1.0), (17.0, 1.0), (1.0, 13.0), (17.0, 13.0)]
    player_count = 0
    
    for player_id in players:
        start_pos = start_positions[player_count % len(start_positions)]
        players[player_id] = {
            "x": start_pos[0], 
            "y": start_pos[1], 
            "target_x": start_pos[0],
            "target_y": start_pos[1],
            "keys": set(), 
            "score": 0, 
            "dead": False, 
            "power": 0, 
            "direction": None,
            "name": f"Player{player_count + 1}",
            "moving": False,
            "last_move_time": 0
        }
        player_count += 1
    
    # Reset ghosts
    ghost_homes = [(9, 7), (8, 9), (10, 9), (9, 8)]
    for i, ghost in enumerate(GHOSTS):
        home = ghost_homes[i % len(ghost_homes)]
        ghost.x, ghost.y = float(home[0]), float(home[1])
        ghost.home_x, ghost.home_y = home[0], home[1]
        ghost.dx, ghost.dy = 0, 0
        ghost.path.clear()
        ghost.mode_timer = 0
        ghost.behavior_change_timer = 0
        ghost.current_behavior = ghost.behavior
        ghost.randomness_factor = random.uniform(0.3, 0.8)

def reset_player(player_id):
    """Reset a specific player when they die"""
    if player_id in players:
        start_positions = [(1.0, 1.0), (17.0, 1.0), (1.0, 13.0), (17.0, 13.0)]
        start_pos = start_positions[len(players) % len(start_positions)]
        
        # Reset player but keep their connection info
        player = players[player_id]
        player["x"] = start_pos[0]
        player["y"] = start_pos[1]
        player["target_x"] = start_pos[0]
        player["target_y"] = start_pos[1]
        player["score"] = 0
        player["dead"] = False
        player["power"] = 0
        player["direction"] = None
        player["keys"] = set()
        
        # Reset the maze for this player (restore all pellets)
        reset_game()

async def handle_client(ws):
    print("Client connected")
    clients.add(ws)
    player_id = id(ws)
    
    # Better starting positions
    start_positions = [(1.0, 1.0), (17.0, 1.0), (1.0, 13.0), (17.0, 13.0)]
    start_pos = start_positions[len(players) % len(start_positions)]
    
    players[player_id] = {
        "x": start_pos[0], 
        "y": start_pos[1], 
        "target_x": start_pos[0],
        "target_y": start_pos[1],
        "keys": set(), 
        "score": 0, 
        "dead": False, 
        "power": 0, 
        "direction": None,
        "name": f"Player{len(players)}",
        "moving": False,
        "last_move_time": 0
    }

    try:
        async for message in ws:
            data = json.loads(message)
            key = data.get("key")
            action = data.get("action", "press")
            
            if key in {"UP", "DOWN", "LEFT", "RIGHT", "RESTART"}:
                if action == "press":
                    if key == "RESTART":
                        # Reset this player when they die
                        if players[player_id]["dead"]:
                            reset_player(player_id)
                    else:
                        players[player_id]["keys"].add(key)
                else:
                    players[player_id]["keys"].discard(key)
    except websockets.ConnectionClosedOK:
        print("Client disconnected")
    finally:
        clients.discard(ws)
        players.pop(player_id, None)

def update_players():
    """Enhanced player movement with better grid alignment"""
    for player in players.values():
        if player["dead"]: 
            continue
        
        # Grid-based movement with smoother transitions
        current_x, current_y = player["x"], player["y"]
        target_x, target_y = current_x, current_y
        
        # Determine target based on input
        if "UP" in player["keys"]:
            target_y = current_y - PLAYER_SPEED
            player["direction"] = "UP"
        elif "DOWN" in player["keys"]:
            target_y = current_y + PLAYER_SPEED
            player["direction"] = "DOWN"
        elif "LEFT" in player["keys"]:
            target_x = current_x - PLAYER_SPEED
            player["direction"] = "LEFT"
        elif "RIGHT" in player["keys"]:
            target_x = current_x + PLAYER_SPEED
            player["direction"] = "RIGHT"
        
        # Apply movement if valid
        if target_x != current_x or target_y != current_y:
            # Ensure within bounds
            new_x = max(0.4, min(COLS - 0.4, target_x))
            new_y = max(0.4, min(ROWS - 0.4, target_y))
            
            if can_move(new_x, new_y):
                player["x"], player["y"] = new_x, new_y
        
        # Snap to grid when very close (for pellet collection)
        snap_threshold = 0.15
        if abs(player["x"] - round(player["x"])) < snap_threshold:
            player["x"] = float(round(player["x"]))
        if abs(player["y"] - round(player["y"])) < snap_threshold:
            player["y"] = float(round(player["y"]))
        
        # Pellet collection with better detection
        gx, gy = int(round(player["x"])), int(round(player["y"]))
        if 0 <= gy < ROWS and 0 <= gx < COLS:
            cell = MAZE[gy][gx]
            if cell == 2:
                MAZE[gy][gx] = 0
                player["score"] += 10
            elif cell == 3:
                MAZE[gy][gx] = 0
                player["score"] += 50
                player["power"] = POWER_TIME

def update_ghost_behavior(ghost):
    """Enhanced ghost AI with much more unpredictable behavior"""
    ghost.mode_timer += 1
    ghost.behavior_change_timer += 1
    ghost.snap_to_grid()
    
    # Track positions to detect stuck state
    ghost.last_positions.append((ghost.x, ghost.y))
    
    if not players:
        return
    
    # Find closest alive player
    alive_players = [p for p in players.values() if not p["dead"]]
    if not alive_players:
        return
    
    closest_player = min(alive_players, 
                        key=lambda p: distance(ghost.x, ghost.y, p["x"], p["y"]))
    
    # Check if any player has power
    players_powered = any(p.get("power", 0) > 0 for p in alive_players)
    
    # Add much more randomness - change behavior frequently
    if ghost.behavior_change_timer > random.randint(60, 180):  # Change every 2-6 seconds
        ghost.behavior_change_timer = 0
        behaviors = ["aggressive", "patrol", "ambush", "random", "confused"]
        ghost.current_behavior = random.choice(behaviors)
        ghost.randomness_factor = random.uniform(0.4, 0.9)
    
    # Add random chance to ignore current behavior
    if random.random() < ghost.randomness_factor:
        ghost.current_behavior = "random"
    
    if players_powered:
        # Flee behavior - but with some randomness
        if random.random() < 0.7:  # 70% chance to actually flee
            corners = [(1, 1), (17, 1), (17, 13), (1, 13)]
            target = min(corners, key=lambda c: distance(ghost.x, ghost.y, c[0], c[1]))
            target_x, target_y = target
        else:
            # Sometimes move randomly even when player has power
            target_x = random.randint(1, COLS-2)
            target_y = random.randint(1, ROWS-2)
    else:
        # Normal behavior but much more unpredictable
        if ghost.current_behavior == "aggressive":
            if random.random() < 0.8:  # 80% chance to chase
                target_x, target_y = closest_player["x"], closest_player["y"]
            else:
                # Sometimes go to a random location instead
                target_x = random.randint(1, COLS-2)
                target_y = random.randint(1, ROWS-2)
            
        elif ghost.current_behavior == "patrol":
            if ghost.mode_timer % random.randint(100, 400) == 0 or not hasattr(ghost, 'patrol_target'):
                patrol_points = [(3, 3), (15, 3), (15, 11), (3, 11), (9, 7), (5, 8), (13, 8)]
                ghost.patrol_target = random.choice(patrol_points)
            target_x, target_y = ghost.patrol_target
            
        elif ghost.current_behavior == "ambush":
            # More unpredictable ambush - sometimes predict, sometimes not
            if random.random() < 0.6:
                target_x, target_y = closest_player["x"], closest_player["y"]
                predict_distance = random.randint(2, 6)  # Random prediction distance
                if closest_player["direction"] == "UP":
                    target_y -= predict_distance
                elif closest_player["direction"] == "DOWN":
                    target_y += predict_distance
                elif closest_player["direction"] == "LEFT":
                    target_x -= predict_distance
                elif closest_player["direction"] == "RIGHT":
                    target_x += predict_distance
            else:
                # Sometimes just move randomly
                target_x = random.randint(1, COLS-2)
                target_y = random.randint(1, ROWS-2)
            
        elif ghost.current_behavior == "confused":
            # New behavior - move in random directions frequently
            if ghost.mode_timer % random.randint(30, 80) == 0:
                target_x = random.randint(1, COLS-2)
                target_y = random.randint(1, ROWS-2)
            else:
                target_x, target_y = ghost.x, ghost.y
            
        else:  # random or fallback
            if ghost.mode_timer % random.randint(50, 150) == 0:
                valid_dirs = get_valid_directions(ghost.x, ghost.y)
                if valid_dirs:
                    ghost.dx, ghost.dy, _ = random.choice(valid_dirs)
            return  # Skip pathfinding for pure random movement
    
    # Enhanced pathfinding with more randomness
    if ghost.mode_timer % random.randint(8, 20) == 0:  # Random update interval
        path = find_path_bfs(ghost.x, ghost.y, target_x, target_y)
        if path and random.random() < 0.8:  # Sometimes ignore the path
            ghost.path = deque(path[:random.randint(1, 4)])  # Random path length
        else:
            # Sometimes just move randomly
            valid_dirs = get_valid_directions(ghost.x, ghost.y)
            if valid_dirs:
                ghost.dx, ghost.dy, _ = random.choice(valid_dirs)
    
    # Execute movement with random delays
    if ghost.path and random.random() < 0.9:  # Sometimes skip movement
        next_move = ghost.path[0]
        move_map = {"LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, -1), "DOWN": (0, 1)}
        
        if next_move in move_map:
            dx, dy = move_map[next_move]
            new_x = ghost.x + dx * GHOST_SPEED
            new_y = ghost.y + dy * GHOST_SPEED
            
            if can_move(new_x, new_y):
                ghost.x, ghost.y = new_x, new_y
                ghost.dx, ghost.dy = dx, dy
                
                # Remove completed move
                if abs(ghost.x - round(ghost.x)) < GRID_SNAP_THRESHOLD and \
                   abs(ghost.y - round(ghost.y)) < GRID_SNAP_THRESHOLD:
                    if ghost.path:
                        ghost.path.popleft()
            else:
                # Clear path if blocked
                ghost.path.clear()
    
    # Fallback movement with more randomness
    if not ghost.path or random.random() < 0.1:  # 10% chance to change direction randomly
        valid_dirs = get_valid_directions(ghost.x, ghost.y)
        if valid_dirs:
            if random.random() < 0.7:  # 70% chance to move towards target
                best_dir = None
                best_dist = float('inf')
                
                for dx, dy, direction in valid_dirs:
                    test_x = ghost.x + dx * GHOST_SPEED
                    test_y = ghost.y + dy * GHOST_SPEED
                    dist = distance(test_x, test_y, target_x, target_y)
                    
                    if dist < best_dist:
                        best_dist = dist
                        best_dir = (dx, dy)
                
                if best_dir:
                    ghost.dx, ghost.dy = best_dir
            else:  # 30% chance to move randomly
                ghost.dx, ghost.dy, _ = random.choice(valid_dirs)

def update_ghosts():
    """Update all ghosts with enhanced collision detection"""
    for ghost in GHOSTS:
        update_ghost_behavior(ghost)
        
        new_x = ghost.x + ghost.dx * GHOST_SPEED
        new_y = ghost.y + ghost.dy * GHOST_SPEED
        
        # Enhanced bounds checking
        new_x = max(0.4, min(COLS - 0.4, new_x))
        new_y = max(0.4, min(ROWS - 0.4, new_y))
        
        if can_move(new_x, new_y):
            ghost.x, ghost.y = new_x, new_y
        else:
            # Try alternative directions
            valid_dirs = get_valid_directions(ghost.x, ghost.y)
            if valid_dirs:
                ghost.dx, ghost.dy, _ = random.choice(valid_dirs)

def check_player_death():
    """Enhanced collision detection"""
    for player in players.values():
        if player["dead"]: 
            continue
            
        px, py = player["x"], player["y"]
        power = player.get("power", 0)
        
        for ghost in GHOSTS:
            gx, gy = ghost.x, ghost.y
            
            # More precise collision detection
            if distance(px, py, gx, gy) < 0.8:
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

def check_victory():
    """Check for victory condition"""
    total_pellets = sum(row.count(2) + row.count(3) for row in MAZE)
    return total_pellets == 0

async def broadcast_game_state():
    game_tick = 0
    while True:
        game_tick += 1
        
        update_players()
        update_ghosts()
        check_player_death()
        
        # Game statistics
        total_pellets = sum(row.count(2) + row.count(3) for row in MAZE)
        alive_players = sum(1 for p in players.values() if not p["dead"])
        victory = check_victory()
        
        payload = json.dumps({
            "players": {
                pid: {
                    "x": round(p["x"], 2), 
                    "y": round(p["y"], 2), 
                    "score": p["score"], 
                    "dead": p["dead"], 
                    "power": p.get("power", 0),
                    "name": p.get("name", f"Player{pid}"),
                    "direction": p.get("direction")
                } 
                for pid, p in players.items()
            },
            "ghosts": [
                {
                    "x": round(g.x, 2), 
                    "y": round(g.y, 2), 
                    "behavior": g.current_behavior,  # Use current behavior
                    "color": g.color
                } 
                for g in GHOSTS
            ],
            "maze": MAZE,
            "game_stats": {
                "total_pellets": total_pellets,
                "alive_players": alive_players,
                "total_players": len(players),
                "victory": victory,
                "game_tick": game_tick
            }
        })
        
        disconnected = set()
        for ws in list(clients):
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                disconnected.add(ws)
                
        for ws in disconnected:
            clients.discard(ws)
            
        await asyncio.sleep(0.05)  # Reduced to 20 FPS for smoother ghost movement

async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        print("Fixed Enhanced Pac-Man Server running on ws://localhost:8765")
        print("Features: Slower ghosts, Better collision, Auto-restart, Unpredictable AI")
        await broadcast_game_state()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped")