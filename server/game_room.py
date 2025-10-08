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
    GHOST_SPEED = 0.2  # Tile-oriented movement speed for smoother, classic behavior
    PLAYER_RADIUS = 15
    GHOST_RADIUS = 15
    PELLET_RADIUS = 4
    POWER_TIME = 200
    GRID_SNAP_THRESHOLD = 0.5

    # Original maze template for resetting
    ORIGINAL_MAZE = [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 3, 2, 2, 2, 1, 2, 2, 2, 1, 2, 2, 2, 1, 2, 2, 2, 3, 1],
        [1, 2, 1, 0, 2, 1, 2, 1, 0, 1, 0, 1, 2, 1, 2, 0, 1, 2, 1],
        [1, 2, 2, 2, 2, 2, 2, 2, 2, 0, 2, 2, 2, 2, 2, 2, 2, 2, 1],
        [1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 1, 1, 2, 1, 2, 1, 1, 2, 1],
        [1, 2, 2, 2, 2, 1, 2, 0, 2, 1, 2, 0, 2, 1, 2, 2, 2, 2, 1],
        [1, 1, 1, 1, 2, 1, 1, 1, 0, 1, 0, 1, 1, 1, 2, 1, 1, 1, 1],
        [0, 0, 0, 1, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0, 2, 1, 0, 0, 0],
        [1, 1, 1, 1, 2, 1, 0, 1, 1, 0, 1, 1, 0, 1, 2, 1, 1, 1, 1],
        [2, 2, 2, 2, 2, 0, 0, 1, 0, 0, 0, 1, 0, 0, 2, 2, 2, 2, 2],
        [1, 1, 1, 1, 2, 1, 0, 1, 1, 1, 1, 1, 0, 1, 2, 1, 1, 1, 1],
        [0, 0, 0, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 0, 0, 0],
        [1, 1, 1, 1, 2, 1, 1, 1, 0, 1, 0, 1, 1, 1, 2, 1, 1, 1, 1],
        [1, 2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 2, 2, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    ]

    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}  # websocket -> player data
        self.clients = set()
        # Deterministic per-room maze seed so everyone in the room sees the same grid
        self._maze_seed = int(abs(hash(room_id))) & 0xFFFFFFFF
        self.maze = self._generate_maze(self._maze_seed)
        # Track tile visit counts for exploration bias (helps ghosts roam the grid)
        self.visit_counts = [
            [0 for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self.ghosts = self._initialize_ghosts()
        self.game_tick = 0
        self.running = False
        self.game_loop_task = None
        self.created_at = time.time()
        # Global chase/scatter mode
        self.mode = "scatter"
        self.mode_timer = 0
        self.CHASE_STEPS = 7 * 20     # ~7 seconds at 20 FPS
        self.SCATTER_STEPS = 5 * 20   # ~5 seconds at 20 FPS

    def _generate_maze(self, seed: int):
        """Generate a random, solvable maze for this room using a deterministic seed.
        - Walls = 1, empty path = 0, pellets = 2, power pellets = 3
        - Guarantees open spawn tiles at (1,1) and (17,13)
        - Adds a horizontal wrap tunnel on the middle row if possible
        """
        rnd = random.Random(seed)
        rows, cols = self.ROWS, self.COLS
        # Start with all walls
        grid = [[1 for _ in range(cols)] for _ in range(rows)]
        # Carve passages on odd coordinates using DFS
        def carve(x, y):
            dirs = [(2,0), (-2,0), (0,2), (0,-2)]
            rnd.shuffle(dirs)
            for dx, dy in dirs:
                nx, ny = x + dx, y + dy
                if 1 <= nx < cols-1 and 1 <= ny < rows-1 and grid[ny][nx] == 1:
                    grid[y + dy//2][x + dx//2] = 0
                    grid[ny][nx] = 0
                    carve(nx, ny)
        # Pick a random odd start
        sx = rnd.randrange(1, cols-1, 2)
        sy = rnd.randrange(1, rows-1, 2)
        grid[sy][sx] = 0
        carve(sx, sy)
        # Ensure spawn tiles are open
        for (sx, sy) in [(1,1), (cols-2, rows-2)]:
            grid[sy][sx] = 0
        # Create wrap tunnel on middle row if possible
        mid = rows // 2
        grid[mid][0] = 0
        grid[mid][cols-1] = 0
        # Place pellets on open tiles; sprinkle a few power pellets
        for y in range(rows):
            for x in range(cols):
                if grid[y][x] == 0:
                    grid[y][x] = 2  # regular pellet
        # Keep spawn tiles empty (no pellets) for clarity
        grid[1][1] = 0
        grid[rows-2][cols-2] = 0
        # Power pellets: choose up to 4 far-apart corners if open
        candidates = [(1,1), (1,rows-2), (cols-2,1), (cols-2,rows-2)]
        rnd.shuffle(candidates)
        for i, (x,y) in enumerate(candidates[:4]):
            if grid[y][x] != 1:
                grid[y][x] = 3
        return grid

    def _initialize_ghosts(self):
        """Initialize ghosts for this room (ensure walkable spawns and initial direction)."""
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
                self.last_positions = deque(maxlen=8)
                self.last_grid = deque(maxlen=6)
                self.last_choice_tick = 0
                self.behavior_change_timer = 0
                self.current_behavior = behavior
                self.randomness_factor = random.uniform(0.3, 0.8)
                self.change_interval = random.randint(
                    10, 40)  # more frequent direction changes
                self.prev_tile = None

            def snap_to_grid(self):
                grid_x = round(self.x)
                grid_y = round(self.y)

                if abs(self.x - grid_x) < GameRoom.GRID_SNAP_THRESHOLD:
                    self.x = float(grid_x)
                if abs(self.y - grid_y) < GameRoom.GRID_SNAP_THRESHOLD:
                    self.y = float(grid_y)

        import random
        ghosts = [
            Ghost(9 + random.uniform(-0.2, 0.2), 7 + random.uniform(-0.2, 0.2), "aggressive", "red"),
            Ghost(8 + random.uniform(-0.2, 0.2), 9 + random.uniform(-0.2, 0.2), "patrol", "orange"),
            Ghost(10 + random.uniform(-0.2, 0.2), 9 + random.uniform(-0.2, 0.2), "ambush", "purple"),
            Ghost(9 + random.uniform(-0.2, 0.2), 8 + random.uniform(-0.2, 0.2), "random", "green")
        ]

        # Initialize ghosts with proper starting directions and scatter corners
        for i, ghost in enumerate(ghosts):
            # Ensure spawn is walkable; move to nearest path tile if needed
            gx, gy = int(round(ghost.x)), int(round(ghost.y))
            nearest = self._nearest_walkable(gx, gy, max_radius=6)
            if nearest:
                nx, ny = nearest
                ghost.x, ghost.y = float(nx), float(ny)
                ghost.home_x, ghost.home_y = float(nx), float(ny)
            # right, left, down, up
            directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            ghost.dx, ghost.dy = directions[i % 4]
            # If initial direction is blocked, pick a valid one
            valids = self._get_valid_directions_simple(int(round(ghost.x)), int(round(ghost.y)))
            if valids:
                ghost.dx, ghost.dy = random.choice(valids)
            ghost.mode_timer = i * 10  # Stagger behavior updates
            # Scatter targets (corners)
            top_left = (1, 1)
            top_right = (self.COLS - 2, 1)
            bottom_left = (1, self.ROWS - 2)
            bottom_right = (self.COLS - 2, self.ROWS - 2)
            if ghost.color == "red":  # Blinky
                ghost.scatter_x, ghost.scatter_y = top_right
            elif ghost.color == "purple":  # Pinky
                ghost.scatter_x, ghost.scatter_y = top_left
            elif ghost.color == "green":  # Inky
                ghost.scatter_x, ghost.scatter_y = bottom_right
            else:  # orange -> Clyde
                ghost.scatter_x, ghost.scatter_y = bottom_left

        return ghosts

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
                        # Allow restart when player is dead OR after victory
                        if self.players[player_id]["dead"]:
                            await self._reset_player(player_id)
                        elif self._check_victory():
                            await self._reset_room()
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
        """Tile-aware ghost movement with classic chase/scatter and frightened behavior"""
        # Determine if frightened mode is active (any player powered)
        frightened = any(p.get("power", 0) > 0 for p in self.players.values())

        # Update global mode timer when not frightened
        if not frightened:
            self.mode_timer += 1
            if self.mode == "scatter" and self.mode_timer >= self.SCATTER_STEPS:
                self.mode = "chase"
                self.mode_timer = 0
            elif self.mode == "chase" and self.mode_timer >= self.CHASE_STEPS:
                self.mode = "scatter"
                self.mode_timer = 0

        for ghost in self.ghosts:
            # Choose direction at tile centers or when blocked
            if self._at_tile_center(ghost.x, ghost.y):
                # Increment visit count at current tile
                vx, vy = int(round(ghost.x)), int(round(ghost.y))
                if 0 <= vy < self.ROWS and 0 <= vx < self.COLS:
                    self.visit_counts[vy][vx] = min(
                        self.visit_counts[vy][vx] + 1, 1_000_000)
                self._choose_ghost_direction(ghost, frightened)
                ghost.prev_tile = (vx, vy)

            # Move along current direction with mode-based speed tuning
            speed = self.GHOST_SPEED
            if frightened:
                speed = max(0.15, self.GHOST_SPEED * 0.85)
            elif self.mode == "chase":
                speed = min(0.28, self.GHOST_SPEED * 1.1)
            new_x = ghost.x + ghost.dx * speed
            new_y = ghost.y + ghost.dy * speed

            # Horizontal tunnel wrap if open
            gy = int(round(ghost.y))
            if 0 <= gy < self.ROWS:
                left_open = self.maze[gy][0] == 0
                right_open = self.maze[gy][self.COLS - 1] == 0
                if left_open and ghost.dx < 0 and new_x <= 0.4:
                    new_x = self.COLS - 0.6
                if right_open and ghost.dx > 0 and new_x >= self.COLS - 0.4:
                    new_x = 0.6

            # If ghost has no direction (e.g., after respawn), choose one now
            if ghost.dx == 0 and ghost.dy == 0:
                self._choose_ghost_direction(ghost, frightened, force=True)
                # Recompute tentative movement with picked direction
                new_x = ghost.x + ghost.dx * speed
                new_y = ghost.y + ghost.dy * speed

            # Apply movement if valid, else force a new direction (allow reverse as last resort)
            if self.can_move(new_x, new_y):
                ghost.x, ghost.y = new_x, new_y
            else:
                # pick new direction immediately
                self._choose_ghost_direction(ghost, frightened, force=True)
                new_x2 = ghost.x + ghost.dx * speed
                new_y2 = ghost.y + ghost.dy * speed
                if self.can_move(new_x2, new_y2):
                    ghost.x, ghost.y = new_x2, new_y2
                else:
                    # Strong fallback: snap to tile center and choose any valid non-wall direction
                    cx2, cy2 = int(round(ghost.x)), int(round(ghost.y))
                    ghost.x, ghost.y = float(cx2), float(cy2)
                    valids = self._get_valid_directions_simple(cx2, cy2)
                    if valids:
                        choice = random.choice(valids)
                        ghost.dx, ghost.dy = choice
                        new_x3 = ghost.x + ghost.dx * speed
                        new_y3 = ghost.y + ghost.dy * speed
                        if self.can_move(new_x3, new_y3):
                            ghost.x, ghost.y = new_x3, new_y3

            # Track grid transitions to fight oscillations and stuck
            gx2, gy2 = int(round(ghost.x)), int(round(ghost.y))
            ghost.last_grid.append((gx2, gy2))

            # Anti-stuck: if ghost barely moved for a while, randomize direction
            ghost.last_positions.append((round(ghost.x,2), round(ghost.y,2)))
            if len(ghost.last_positions) >= ghost.last_positions.maxlen:
                if len(set(ghost.last_positions)) <= 2:  # almost stationary
                    cx3, cy3 = int(round(ghost.x)), int(round(ghost.y))
                    valids = self._get_valid_directions_simple(cx3, cy3)
                    if valids:
                        choice = random.choice(valids)
                        if choice == (-ghost.dx, -ghost.dy) and len(valids) > 1:
                            choice = random.choice([d for d in valids if d != (-ghost.dx, -ghost.dy)])
                        ghost.dx, ghost.dy = choice
                        # Nudge movement after choosing to break inertia
                        nux = float(cx3) + ghost.dx * speed
                        nuy = float(cy3) + ghost.dy * speed
                        if self.can_move(nux, nuy):
                            ghost.x, ghost.y = nux, nuy
                        ghost.last_positions.clear()

            # Periodic re-evaluation: if going straight too long in chase, try a turn at intersections
            if self.mode == "chase" and (self.game_tick - getattr(ghost, 'last_choice_tick', 0)) > 40:
                if self._at_tile_center(ghost.x, ghost.y):
                    self._choose_ghost_direction(ghost, frightened, force=False)

    def _update_ghost_behavior(self, ghost):
        """Deprecated: direction choice handled in _choose_ghost_direction"""
        return

    def _get_valid_directions(self, x, y):
        """Get valid movement directions (legacy)"""
        directions = []
        moves = [(-1, 0, "LEFT"), (1, 0, "RIGHT"),
                 (0, -1, "UP"), (0, 1, "DOWN")]

        for dx, dy, direction in moves:
            new_x = x + dx * self.GHOST_SPEED * 2
            new_y = y + dy * self.GHOST_SPEED * 2
            if self.can_move(new_x, new_y):
                directions.append((dx, dy, direction))

        return directions

    def _get_grid_directions(self, grid_x, grid_y):
        """Get valid grid-based directions for ghosts"""
        directions = []
        moves = [(-1, 0, "LEFT"), (1, 0, "RIGHT"),
                 (0, -1, "UP"), (0, 1, "DOWN")]

        for dx, dy, direction in moves:
            new_x = grid_x + dx
            new_y = grid_y + dy
            if self.can_move(new_x, new_y):
                directions.append((dx, dy, direction))

        return directions

    def _get_valid_directions_simple(self, x, y):
        """Get valid movement directions for ghosts (immediate tile check)"""
        directions = []
        moves = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # LEFT, RIGHT, UP, DOWN
        cx, cy = int(round(x)), int(round(y))
        for dx, dy in moves:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < self.COLS and 0 <= ny < self.ROWS and self.maze[ny][nx] != 1:
                directions.append((dx, dy))
        return directions

    def _is_walkable_tile(self, x: int, y: int) -> bool:
        return 0 <= x < self.COLS and 0 <= y < self.ROWS and self.maze[y][x] != 1

    def _neighbors(self, x: int, y: int):
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if self._is_walkable_tile(nx, ny):
                yield nx, ny, dx, dy

    def _nearest_walkable(self, tx: int, ty: int, max_radius: int = 5):
        """Find the nearest walkable tile around (tx, ty) within a small radius."""
        if self._is_walkable_tile(tx, ty):
            return tx, ty
        for r in range(1, max_radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    nx, ny = tx + dx, ty + dy
                    if self._is_walkable_tile(nx, ny):
                        return nx, ny
        return None

    def _bfs_next_step(self, sx: int, sy: int, tx: int, ty: int, node_limit: int = 1200):
        """Return the first step (dx, dy) on a shortest path from (sx, sy) to (tx, ty) using BFS.
        If no path, return None. Limits explored nodes to keep it cheap.
        """
        if not self._is_walkable_tile(sx, sy):
            return None
        if not self._is_walkable_tile(tx, ty):
            nearest = self._nearest_walkable(tx, ty)
            if not nearest:
                return None
            tx, ty = nearest
        start = (sx, sy)
        target = (tx, ty)
        if start == target:
            return None
        q = deque([start])
        parents = {start: None}
        explored = 0
        while q and explored < node_limit:
            x0, y0 = q.popleft()
            explored += 1
            if (x0, y0) == target:
                break
            for nx, ny, _, _ in self._neighbors(x0, y0):
                if (nx, ny) not in parents:
                    parents[(nx, ny)] = (x0, y0)
                    q.append((nx, ny))
        if target not in parents:
            return None
        # backtrack to get next step from start
        cur = target
        while parents[cur] is not None and parents[cur] != start:
            cur = parents[cur]
        nx, ny = cur
        return (nx - sx, ny - sy)

    def _at_tile_center(self, x, y):
        return abs(x - round(x)) < 0.1 and abs(y - round(y)) < 0.1

    def _ghost_target_tile(self, ghost, frightened: bool):
        # Compute target tile based on mode and ghost type
        alive_players = [p for p in self.players.values() if not p["dead"]]
        if not alive_players:
            return (ghost.scatter_x, ghost.scatter_y)
        # choose primary target player (closest)
        closest = min(alive_players, key=lambda p: self._distance(
            ghost.x, ghost.y, p["x"], p["y"]))
        px, py = closest["x"], closest["y"]
        pdir = closest.get("direction")
        # frightened: run to scatter target opposite of player
        if frightened:
            # Flee away from nearest player
            fx = ghost.x + (ghost.x - px) * 2
            fy = ghost.y + (ghost.y - py) * 2
            return (int(round(fx)), int(round(fy)))
        # Scatter mode
        if self.mode == "scatter":
            return (ghost.scatter_x, ghost.scatter_y)
        # Chase mode behaviors
        if ghost.color == "red":  # Blinky - direct chase
            return (int(round(px)), int(round(py)))
        elif ghost.color == "purple":  # Pinky - aim 4 tiles ahead of player
            dx, dy = 0, 0
            if pdir == "UP":
                dx, dy = 0, -1
            elif pdir == "DOWN":
                dx, dy = 0, 1
            elif pdir == "LEFT":
                dx, dy = -1, 0
            elif pdir == "RIGHT":
                dx, dy = 1, 0
            return (int(round(px + 4*dx)), int(round(py + 4*dy)))
        elif ghost.color == "green":  # Inky - use vector from red to two tiles ahead of player
            red = next((g for g in self.ghosts if getattr(
                g, 'color', '') == 'red'), None)
            if red is None:
                return (int(round(px)), int(round(py)))
            # point two tiles ahead of player
            ax, ay = px, py
            if pdir == "UP":
                ay -= 2
            elif pdir == "DOWN":
                ay += 2
            elif pdir == "LEFT":
                ax -= 2
            elif pdir == "RIGHT":
                ax += 2
            vx = (ax - red.x) * 2
            vy = (ay - red.y) * 2
            return (int(round(red.x + vx)), int(round(red.y + vy)))
        else:  # orange - Clyde: chase when far, scatter when near
            dist = self._distance(ghost.x, ghost.y, px, py)
            if dist > 8:
                return (int(round(px)), int(round(py)))
            return (ghost.scatter_x, ghost.scatter_y)

    def _choose_ghost_direction(self, ghost, frightened: bool, force: bool = False):
        cx, cy = int(round(ghost.x)), int(round(ghost.y))
        valid_dirs = self._get_valid_directions_simple(cx, cy)
        if not valid_dirs:
            return
        reverse = (-ghost.dx, -ghost.dy)
        # Prefer not to reverse unless forced
        non_reverse = [d for d in valid_dirs if d != reverse]
        candidates = non_reverse or valid_dirs

        # Determine a target tile and plan via BFS
        tx, ty = self._ghost_target_tile(ghost, frightened)
        tx = int(max(0, min(self.COLS - 1, tx)))
        ty = int(max(0, min(self.ROWS - 1, ty)))
        step = self._bfs_next_step(cx, cy, tx, ty)

        # Oscillation breaker: avoid going straight back to the previous grid tile when we already did that
        prev_tile = ghost.prev_tile
        oscillation_penalty = {}
        if prev_tile is not None and len(ghost.last_grid) >= 2:
            # If last two grid positions were A,B then we are at B; discourage going back to A unless forced
            last = ghost.last_grid[-1]
            prev = ghost.last_grid[-2]
            if last == (cx, cy) and prev == prev_tile:
                for dx, dy in candidates:
                    nx, ny = cx + dx, cy + dy
                    if (nx, ny) == prev_tile:
                        oscillation_penalty[(dx, dy)] = 1000  # very high to discourage

        # At intersections, compute a score combining exploration (visit counts), BFS step preference, and oscillation penalty
        is_intersection = len(candidates) >= 3 or (
            len(candidates) == 2 and candidates[0] != (-candidates[1][0], -candidates[1][1]))
        if is_intersection or force:
            best_score = None
            best_dirs = []
            for dx, dy in candidates:
                nx, ny = cx + dx, cy + dy
                vis = self.visit_counts[ny][nx] if 0 <= ny < self.ROWS and 0 <= nx < self.COLS else 0
                score = vis
                # Prefer BFS step strongly
                if step is not None and (dx, dy) == step:
                    score -= 2
                # Penalty for oscillation
                score += oscillation_penalty.get((dx, dy), 0)
                # Mild randomness to diversify
                score += random.uniform(0, 0.25)
                if best_score is None or score < best_score:
                    best_score = score
                    best_dirs = [(dx, dy)]
                elif abs(score - best_score) < 1e-6:
                    best_dirs.append((dx, dy))
            choice = random.choice(best_dirs)
            if not force and choice == reverse and len(candidates) > 1:
                alt = [d for d in best_dirs if d != reverse] or [d for d in candidates if d != reverse]
                choice = random.choice(alt)
            ghost.dx, ghost.dy = choice
            ghost.last_choice_tick = self.game_tick
            return

        # Add small randomness to avoid repetitive patterns when not at intersections
        if random.random() < (0.10 if not frightened else 0.25):
            choice = random.choice(candidates)
            if not force and choice == reverse and len(candidates) > 1:
                choice = random.choice([d for d in candidates if d != reverse])
            ghost.dx, ghost.dy = choice
            ghost.last_choice_tick = self.game_tick
            return

        if step is not None and ((step in candidates) or force):
            ghost.dx, ghost.dy = step
            ghost.last_choice_tick = self.game_tick
            return

        # Fallback: choose the direction that gets closer to target (ties random)
        best_choices = []
        best_dist = None
        for dx, dy in candidates:
            nx, ny = cx + dx, cy + dy
            dist = self._distance(nx, ny, tx, ty)
            if best_dist is None or dist < best_dist:
                best_choices = [(dx, dy)]
                best_dist = dist
            elif abs(dist - best_dist) < 1e-6:
                best_choices.append((dx, dy))
        if best_choices:
            ghost.dx, ghost.dy = random.choice(best_choices)
            ghost.last_choice_tick = self.game_tick

    def _distance(self, x1, y1, x2, y2):
        """Calculate distance between two points"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    async def _reset_room(self):
        """Reset the entire room after victory or on demand"""
        # Reset maze and game tick (regenerate using the same seed for this room)
        self.maze = self._generate_maze(self._maze_seed)
        self.game_tick = 0
        self.mode = "scatter"
        self.mode_timer = 0
        # Reset ghosts
        self.ghosts = self._initialize_ghosts()
        # Reset all players to starting positions and clear status
        start_positions = [(1.0, 1.0), (17.0, 13.0)]
        for i, (pid, player) in enumerate(self.players.items()):
            start_pos = start_positions[i % len(start_positions)]
            player["x"] = start_pos[0]
            player["y"] = start_pos[1]
            player["target_x"] = start_pos[0]
            player["target_y"] = start_pos[1]
            player["score"] = 0
            player["dead"] = False
            player["power"] = 0
            player["direction"] = None
            player["keys"] = set()

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
                        # Reset ghost to home (nearest walkable) and clear direction; will pick next tick
                        nearest = self._nearest_walkable(int(round(ghost.home_x)), int(round(ghost.home_y)))
                        if nearest:
                            gx, gy = nearest
                            ghost.x, ghost.y = float(gx), float(gy)
                            ghost.home_x, ghost.home_y = float(gx), float(gy)
                        else:
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
            start_pos = start_positions[len(
                self.players) % len(start_positions)]

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

            # Reset the maze for this room (preserve per-room seed)
            self.maze = self._generate_maze(self._maze_seed)

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

        # Initialize in-flight tracking on first use
        if not hasattr(self, "_send_in_flight"):
            self._send_in_flight = {}

        disconnected = set()

        async def _send_one(ws):
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                disconnected.add(ws)
            finally:
                self._send_in_flight.pop(ws, None)

        for ws in list(self.clients):
            # Coalesce: if a previous send to this ws is still in flight, skip this frame for that ws
            inflight = self._send_in_flight.get(ws)
            if inflight and not inflight.done():
                # Drop this frame for this client
                # Optional: log occasionally
                # print("[Coalesce] Skipping frame for slow client")
                continue
            task = asyncio.create_task(_send_one(ws))
            self._send_in_flight[ws] = task

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
