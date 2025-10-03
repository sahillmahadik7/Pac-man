# Project File Reference and Runtime Verification Guide

This document explains what each file in the project does and provides a hands-on checklist to verify the load balancer and multi-backend setup while executing the project.

## Runtime Verification (Windows PowerShell)

Prerequisites:
- Python 3.10+
- Dependencies: `pip install websockets pygame`

1) Start two backend servers (on different ports)
- Window A:
  - `python -m server.main --port 8766`
  - Expect: prints “Server running on ws://localhost:8766”, “Room Manager started”
- Window B:
  - `python -m server.main --port 8767`
  - Expect: prints “Server running on ws://localhost:8767”

2) Start the load balancer on 8765 with both backends
- Window C:
  - `python -m server.load_balancer --port 8765 --backends ws://localhost:8766,ws://localhost:8767`
  - Expect: lists the two backends and “Listening on ws://0.0.0.0:8765”

3) Run client(s) and observe distribution
- Client 1:
  - `python -m client.main`
  - Expect: connects via ws://localhost:8765 by default; one backend window logs “Client connected”.
- Client 2:
  - `python -m client.main`
  - Expect: should connect to the other backend (least-connections strategy). You’ll see the other backend log “Client connected”.
- Client 3 (optional):
  - `python -m client.main`
  - Expect: routes back to the backend with fewer active connections at that moment.

4) Verify port configurability
- Stop a backend and restart on a new port, e.g. 9000:
  - `python -m server.main --port 9000`
- Restart or re-run the load balancer with the updated backends list:
  - `python -m server.load_balancer --port 8765 --backends ws://localhost:8766,ws://localhost:9000`
- Launch clients again and observe successful connections.

5) Verify circuit breaker behavior (resilience)
- With the balancer and both backends running, stop one backend (Ctrl+C on its window).
- Start a new client while that backend is down:
  - If the balancer selects the failing backend initially, the client may get an error and close.
  - Subsequent new clients should route to the healthy backend while the failing backend is in cooldown.
- Restart the stopped backend; after cooldown expires, the balancer will resume distributing connections across both.

6) Optional direct connect (sanity check)
- To bypass the balancer and hit a specific backend directly:
  - `python -m client.main ws://localhost:8766`

7) Documentation checks
- CODE_DOCUMENTATION.txt: contains sections “10. LOAD BALANCER ARCHITECTURE” and “11. DISTRIBUTED CONCEPT: CIRCUIT BREAKER PATTERN”.
- README.md: contains “Quick Start” with 2 backends + load balancer.


## File-by-File Reference

### Root
- README.md
  - Quick start and configuration for running backends, load balancer, and client.
- CODE_DOCUMENTATION.txt
  - Deep dive into architecture, game mechanics, networking protocol, and now the load balancer and circuit breaker sections.

### server/
- server/load_balancer.py
  - Purpose: WebSocket Layer-7 reverse proxy that accepts client connections and forwards them to one of several backend game servers.
  - Key components:
    - Backend: Tracks a single backend’s URL, connection count, failure count, and cooldown.
    - BackendPool: Chooses a backend using least-connections among available (not in cooldown) backends.
    - bidirectional_proxy: Pipes messages in both directions between client and backend WebSocket connections until one side closes.
    - handle_client: Picks a backend, connects to it, and starts the proxy. On backend errors, triggers exponential backoff cooldown.
    - main: CLI runner with flags `--port` (default 8765) and `--backends` (comma-separated URLs). Also supports env vars PACMAN_LB_PORT and PACMAN_BACKENDS.
  - Resilience: Lightweight circuit breaker via exponential backoff per failing backend.

- server/main.py
  - Purpose: The actual game server entry point. Listens on a configurable port and manages player connections.
  - Functions:
    - handle_client(websocket): Assigns the connecting client to a room, forwards inputs to the correct room, and cleans up on disconnect.
    - status_reporter(): Prints periodic stats about rooms and players.
    - main(port): Starts the room manager, launches the WebSocket server at the given port, and runs until interrupted.
  - Config: `--port` flag or PACMAN_SERVER_PORT.

- server/room_manager.py
  - Purpose: Creates, tracks, and cleans up game rooms. Assigns players to rooms (max 2 per room).
  - Responsibilities:
    - assign_player_to_room(websocket): Finds a non-full room or creates a new one and adds the player.
    - remove_player_from_room(websocket): Removes player; schedules cleanup if room becomes empty.
    - handle_player_input(websocket, message): Routes messages to the correct GameRoom instance.
    - get_room_stats(): Summarizes room and player counts for reporting.
    - _cleanup_loop(): Periodically removes old, empty rooms.

- server/game_room.py
  - Purpose: Encapsulates a single game instance (max 2 players) including the maze, ghosts, player states, and the game loop.
  - Notable constants: MAX_PLAYERS=2, grid size (ROWS=15, COLS=19), PLAYER_SPEED, GHOST_SPEED, POWER_TIME, etc.
  - Core methods:
    - add_player/remove_player: Manage players joining/leaving and start/stop the room’s game loop.
    - handle_input: Update a player’s pressed keys.
    - _update_players/_update_ghosts/_update_ghost_behavior: Movement and AI logic per frame.
    - _check_player_death: Collision detection with ghosts and power mode effects.
    - _broadcast_game_state: Sends game state to all clients in the room.
    - _game_loop: Runs at a fixed tick rate, updating state and broadcasting.

- server/protocol.py
  - Purpose: Tiny utility for JSON encode/decode of messages.

- server/state.py
  - Purpose: Legacy/alternate simple game state implementation (not used by the current room-based game loop). Kept for reference.

### client/
- client/main.py
  - Purpose: Pygame client that connects to the server (or the load balancer), renders the maze, players, and ghosts, and sends user input.
  - Highlights:
    - Default server URL: `ws://localhost:8765` (the load balancer).
    - handle_input: Reads keyboard events and sends JSON messages.
    - game_loop: Receives game state snapshots and renders at 60 FPS.
    - draw_maze, draw_player, draw_ghost, draw_ui, draw_death_overlay: Rendering utilities for a classic Pac-Man look.

- client/renderer.py
  - Purpose: Legacy/simple renderer kept for compatibility; draws basic circles for players.

### utils/
- utils/logger.py
  - Purpose: Reserved for logging utilities (not actively used in the current runtime paths).

- utils/persistence.py
  - Purpose: Reserved for persistence/storage helpers (not actively used in the current runtime paths).

### Packaging/markers
- server/__init__.py, client/__init__.py
  - Mark packages to enable `python -m server.main` and `python -m client.main` execution.


## Tips for Troubleshooting
- If clients cannot connect, ensure the load balancer is running and at least one backend is listening.
- Firewall: On Windows, allow Python through the firewall if ports are blocked.
- Port conflicts: Start backends on different ports using `--port`.
- Balancer targets: Keep the `--backends` list in sync with the actual backend ports.
