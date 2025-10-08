# Pac‑Man Multiplayer — Simple File-by-File Explainer (Panel-Friendly)

Goal: Explain every file clearly. For each, first say what the main class/function does, then briefly explain important sub-functions inside it. Keep it crisp and on-point.


Root
- README.md
  - What: Project overview and how to run it.
  - Why: Keep this as your quick start and reference.


server/
- server/load_balancer.py
  - What (main idea): WebSocket reverse proxy that sends players to one of many backend game servers. It balances load and handles failures.
  - Main classes/functions:
    - Backend (class): Represents one backend server.
      - url: WebSocket URL of the backend (e.g., ws://localhost:8766)
      - active_connections: How many clients are currently on it.
      - failures, cooldown_until: Used for short “cooldown” after failures (circuit-breaker style).
      - on_failure(now): Increases backoff/cooldown.
      - on_success(): Clears cooldown and failures.
    - BackendPool (class): Chooses which backend to use.
      - pick_backend(): Least-connections. Picks the backend with the fewest active connections among healthy ones.
      - pick_backend_for_token(token): Deterministic choice using the token’s hash (keeps friends together), falling back to least-connections if needed.
      - release_backend(backend): Decrements the active count when a client leaves.
    - bidirectional_proxy(client_ws, server_ws): Pipes messages both ways until one side closes.
    - handle_client(websocket, path, pool): Entry for new client connections to the LB.
      - Reads ?room=<token> for sticky routing.
      - Picks a backend via pool (token or least-connections).
      - Connects to that backend and starts bidirectional_proxy.
      - On backend error, applies cooldown and informs the client.
    - main(): Starts the load balancer process.
      - Flags: --port, --backends, and autoscale options (--auto, --min-backends, --max-backends, etc.).

- server/main.py
  - What (main idea): The actual game server. Accepts clients, assigns them to rooms, enforces per-client input rate limiting, and reports status.
  - Main functions:
    - handle_client(websocket, path=None): Handles one client from connect to disconnect.
      - Parses optional query (?action=create|join&room=<token>).
      - If provided, joins/creates that room; else auto-assigns.
      - Sends { type: "room_assignment", room_id } to the client.
      - Applies input rate limiting (token bucket via PACMAN_INPUT_RPS/BURST) and forwards valid input to RoomManager.
    - status_reporter(): Every 30s, prints how many rooms and players are active.
    - main(port): Bootstraps the server, starts RoomManager, runs the WebSocket server, and keeps it alive.

- server/room_manager.py
  - What (main idea): Creates rooms, assigns players, routes their inputs, and cleans up empty rooms.
  - Main class: RoomManager
    - assign_player_to_room(ws) -> room_id: Finds a non-full room or creates a new one and adds the player.
    - add_player_to_specific_room(ws, room_id, create_if_missing=True) -> room_id: For tokens (create/join a specific room).
    - remove_player_from_room(ws): Removes player; schedules cleanup if the room becomes empty.
    - handle_player_input(ws, message): Forwards input to that player’s GameRoom.
    - get_room_stats() -> dict: Counts active rooms/players for status_reporter().
    - _schedule_room_cleanup(room_id, delay=30s): Waits, then deletes if still empty.
    - _cleanup_room(room_id): Cancels loop and deletes the room safely.
    - _cleanup_loop(): Periodically removes old empty rooms.

- server/game_room.py
  - What (main idea): One live game (max 2 players). Updates players/ghosts ~20 FPS and broadcasts snapshots to clients.
  - Main class: GameRoom
    - Key constants: MAX_PLAYERS=2, ROWS=15, COLS=19, PLAYER_SPEED, GHOST_SPEED, POWER_TIME, ORIGINAL_MAZE grid.
    - add_player(ws): Adds a player, sets spawn point, starts game loop if first player.
    - remove_player(ws): Removes a player; stops loop if room becomes empty.
    - handle_input(ws, message): Reads { key, action } and updates that player’s keys/power/restart.
    - can_move(x, y): Checks walls/bounds to validate movement.
    - _update_players(): Moves players based on held keys, snaps to grid, collects pellets/power pellets, updates score/power.
    - _update_ghosts(): Classic behavior with global scatter/chase modes; frightened mode if any player has power.
    - _choose_ghost_direction(ghost, frightened, force=False): Picks direction at tile centers (don’t reverse unless needed), aims toward a target tile.
    - _ghost_target_tile(ghost, frightened): Target logic by ghost type:
      - red: chase closest player directly
      - purple (pinky): aim a few tiles ahead
      - green (inky): vector using red + ahead-of-player point
      - orange (clyde): chase when far, scatter when near
    - _check_player_death(): Detects collisions; if player powered, they eat ghost (score + reset ghost). Otherwise player dies.
    - _check_victory(): True when all pellets are eaten.
    - _reset_player(player_id): Resets a dead player to start.
    - _reset_room(): Resets maze, ghosts, timers, and all players (e.g., after victory).
    - _broadcast_game_state(): Sends { room_id, players, ghosts, maze, game_stats } to all clients; coalesces frames for slow clients.
    - _game_loop(): Repeats: update players, update ghosts, check collisions/victory, broadcast, tick.
    - _initialize_ghosts(): Creates ghosts with scatter corners and initial directions.

- server/protocol.py
  - What: Tiny JSON helpers.
  - Functions:
    - encode(dict) -> str: json.dumps wrapper.
    - decode(str) -> dict: json.loads wrapper.

- server/state.py (legacy, not used by room system)
  - What: Older simple state engine kept for reference.
  - Main class: GameState
    - add_player(ws): Adds a player with color and starting position.
    - remove_player(ws): Removes player and frees their color.
    - handle_input(ws, action): Updates velocity for UP/DOWN/LEFT/RIGHT.
    - update(): Applies velocity and clamps to bounds.
    - snapshot(): Returns a simplified state dict for rendering.


client/
- client/main.py
  - What (main idea): Pygame client. Connects over WebSocket, sends keys, renders the maze/players/ghosts/UI, and shows victory/death overlays.
  - Main class: SimpleGameClient
    - init_display(): Initializes pygame window safely.
    - draw_maze(maze): Draws walls and pellets (regular + power).
    - draw_player(player, id, is_current): Draws Pac-Man with direction-based mouth; power glow; dead styling.
      - _draw_pacman(...): Helper to draw Pac-Man body + mouth + eye.
    - draw_ghost(ghost, frightened, velocity): Draws classic ghost; blue when frightened; eye pupils follow velocity.
      - _draw_classic_ghost(...): Helper for ghost shape and eyes.
    - draw_ui(data): Sidebar with room id, players, scores, and stats.
    - draw_death_overlay(player): Red tint overlay + restart hint.
    - draw_victory_menu(data): Victory screen with scores and restart/exit options.
    - handle_input(websocket): Reads keyboard; sends JSON like {"key":"UP","action":"press"}.
    - game_loop(websocket): Receives snapshots and renders at 60 FPS; shows overlays.
    - _gen_token(length): Generates room tokens like ABC123.
    - _menu_loop(): Simple menu to Host (generate token) or Join (enter token).
    - run(): Brings it all together. Shows menu, builds URL (?action=create|join&room=<token>), connects, starts input+render loops. If connect fails, tries to auto-start the load balancer once, then reconnects.
  - Module-level main(): Creates and runs SimpleGameClient. You can pass a WebSocket URL as argv[1] to override the default.

- client/renderer.py (legacy/simple)
  - What: Minimal renderer that draws players as colored circles.
  - Functions:
    - init(): Creates a window and returns (screen, players).
    - draw(screen, players): Clears, draws circles, flips the display.


utils/
- utils/logger.py
  - What: Placeholder for future logging utilities.

- utils/persistence.py
  - What: Placeholder for future persistence (e.g., save rooms/leaderboards).


packages
- server/__init__.py and client/__init__.py
  - What: Mark these folders as Python packages so `python -m server.main` and `python -m client.main` work.


That’s it — each file, what it does, and what the key functions inside do. This is tuned for quick explaining to a panel.
