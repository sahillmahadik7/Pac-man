# Pac‑Man Multiplayer

Room‑based multiplayer Pac‑Man built in Python with websockets and pygame. This project supports horizontal scaling via a built‑in WebSocket load balancer and multiple backend game servers.

- Multiplayer: 2 players per room, many rooms per backend
- Realtime: WebSocket updates; server sim ~20 FPS, client render 60 FPS
- Scalable: Run many backends; load balancer uses least‑connections + circuit breaker

---

## Table of Contents
- Overview
- Architecture
- Requirements
- Installation
- Quick Start (Backends + Load Balancer + Client)
- Configuration
- Verifying Load Balancing (Runtime Checklist)
- Project Structure
- Documentation
- Troubleshooting

---

## Overview
This repository contains:
- A game server that manages rooms and authoritative game state
- A pygame client that renders the game and sends input
- A WebSocket load balancer that distributes clients across multiple backends

Use it locally to play with friends or as a reference for room‑based realtime games and simple distributed systems patterns.

---

## Architecture

High‑level flow:

```
Clients ──▶ Load Balancer (ws://localhost:8765) ──▶ Backend Servers (ws://localhost:8766, 8767, ...)
                 │                                         │
                 └────────────── JSON frames ──────────────┘
```

- Load Balancer: Layer‑7 WebSocket reverse proxy
  - Selection: least‑connections
  - Resilience: per‑backend exponential backoff (circuit breaker‑like cooldown)
- Backend Server: Creates/assigns rooms (2 players max), runs game loop, broadcasts state
- Client: pygame UI, connects via WebSocket, sends input and renders state

---

## Requirements
- Python 3.10+
- pip packages: websockets, pygame

Install deps:
- pip install websockets pygame

---

## Quick Start
Open three PowerShell windows.

1) Start two backend servers (different ports)
- python -m server.main --port 8766
- python -m server.main --port 8767

2) Start the load balancer (front port 8765)
- python -m server.load_balancer --port 8765 --backends ws://localhost:8766,ws://localhost:8767

3) Run the client (defaults to ws://localhost:8765)
- python -m client.main

Optional: connect to a specific server directly
- python -m client.main ws://localhost:8766

---

## Configuration
You can configure via flags or environment variables.

- Game server
  - Flag: --port
  - Env: PACMAN_SERVER_PORT
  - Example: set PACMAN_SERVER_PORT=9000; python -m server.main

- Load balancer
  - Flags: --port, --backends (comma‑separated)
  - Envs: PACMAN_LB_PORT, PACMAN_BACKENDS
  - Example: set PACMAN_LB_PORT=8765; set PACMAN_BACKENDS=ws://localhost:8766,ws://localhost:8767; python -m server.load_balancer

Client default endpoint is ws://localhost:8765 (load balancer). You can override by passing a WebSocket URL argument to client.main.

---

## Verifying Load Balancing (Runtime Checklist)
- Start two backends and the load balancer as shown above
- Launch Client 1 → one backend logs “Client connected”
- Launch Client 2 → the other backend logs “Client connected” (least‑connections)
- Stop one backend and start Client 3 → new clients route to the healthy backend; after cooldown and restart, balancing resumes across both

For deeper steps, see docs/FILE_REFERENCE.md (Runtime Verification section).

---

## Project Structure
```
Pac-man/
├─ client/
│  ├─ main.py           # pygame client (default ws://localhost:8765)
│  └─ renderer.py       # legacy/simple renderer (kept for reference)
├─ server/
│  ├─ main.py           # game server entry point (rooms, WebSocket handler)
│  ├─ load_balancer.py  # WebSocket reverse proxy (least‑connections + cooldown)
│  ├─ room_manager.py   # room lifecycle and assignment
│  ├─ game_room.py      # single‑room game logic + loop
│  ├─ protocol.py       # JSON encode/decode helpers
│  └─ state.py          # legacy simple state (not used by room system)
├─ utils/
│  ├─ logger.py         # reserved for logging utilities
│  └─ persistence.py    # reserved for persistence helpers
├─ docs/
│  └─ FILE_REFERENCE.md # detailed per‑file reference + verification guide
├─ CODE_DOCUMENTATION.txt # deep architecture + networking + LB + circuit breaker
└─ README.md
```

---

## Documentation
- docs/FILE_REFERENCE.md: file‑by‑file explanations and runtime verification guide
- CODE_DOCUMENTATION.txt: detailed architecture, data flow, and the new sections:
  - 10. Load Balancer Architecture
  - 11. Distributed Concept: Circuit Breaker Pattern

---

## Troubleshooting
- Client cannot connect
  - Ensure balancer is running on 8765 and at least one backend is up
  - Windows Firewall: allow Python through if ports are blocked
- Address already in use
  - Start each backend with a unique --port
- Unbalanced routing
  - Confirm the balancer was started with a correct --backends list that matches the actual backend ports

If you want sticky sessions or active health checks, open an issue or PR; the current design is intentionally minimal and easy to extend.
