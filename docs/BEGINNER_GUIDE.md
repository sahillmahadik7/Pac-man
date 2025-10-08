# Pac‑Man Multiplayer — Beginner’s Guide (Simple, Practical, and Why We Chose It)

This guide explains the entire project in simple pointers so that anyone can understand what it is, how it works, and why we picked these designs over alternatives.


## 1) What is this project?
- A multiplayer Pac‑Man game where 2 players can play in the same room.
- Built with Python using:
  - websockets for real‑time networking
  - pygame for graphics on the client
- It scales horizontally (you can run many game servers) behind a WebSocket load balancer.
- You can host/join a room with a unique key (token).

Why we made this
- To learn and demonstrate real‑time networking + distributed systems patterns (load balancing, circuit breaker, backpressure) using a fun, approachable game.
- To create a minimal, scalable template for room‑based multiplayer games.
- To make "play with a friend" dead simple without accounts or heavy infrastructure.


## 2) The big picture
- Clients send inputs (UP/DOWN/LEFT/RIGHT) over WebSockets.
- A server updates the game state (players, pellets, ghosts) about 20 times per second.
- The server broadcasts the latest state to all players in the same room.
- A load balancer accepts all client connections and forwards them to backend servers.
- Rooms are isolated, so many rooms can run at the same time.

Why this design?
- WebSockets give low‑latency, bidirectional communication (great for games).
- Rooms cap complexity (2 players per room) and keep each game simple and independent.
- A balancer + multiple backends lets you handle more players without changing code.

Alternatives (and why not):
- HTTP polling/long‑polling: more overhead, slower, more complex to keep smooth gameplay.
- One giant server handling everyone in one room: code becomes complex and slow; rooms are simpler and safer.


## 3) Key parts of the code (simple)
- client/main.py — Draws the game, reads keys, talks to the server.
- server/main.py — Accepts WebSocket clients and assigns them to rooms.
- server/room_manager.py — Creates, tracks, and cleans up rooms.
- server/game_room.py — The game: maze, pellets, two players, ghosts, victory checks.
- server/load_balancer.py — The proxy that distributes clients to different backend servers.


## 4) Host/Join with a key (token)
- On the client, press H to host and get a 6‑character key.
- Share the key. Your friend presses J to join and types the key.
- The load balancer routes everyone with the same room key to the same backend.

Why tokens?
- Dead simple to share. No account system needed.
- Deterministic routing: the same key always reaches the same backend.

Alternatives (and why not):
- Full lobby UI + service: more code, more infra; overkill for a simple game.
- Random matchmaking: harder to play specifically with a friend.


## 5) Load balancer (how it works)
- Listens on ws://host:8765
- Uses “least‑connections” selection to pick a backend with fewer active players.
- Uses the room token to route consistently to the same backend (so friends meet).
- Autoscaling mode can launch new backends if existing ones get full.

Why least‑connections?
- It balances new connections better when backends are unevenly loaded.
- Simpler and often more effective than round‑robin for real‑time systems.

Alternatives (and why not):
- Pure round‑robin: can overload one backend if connections are “sticky”.
- Random: unpredictable; worse average balance.


## 6) Circuit breaker (resilience)
- If a backend fails to accept connections, we back off that backend for a short time.
- That prevents a “storm” of retries to a broken server.

Why a circuit breaker?
- Faster failure and safer recovery.

Alternatives (and why not):
- Retry repeatedly without backoff: creates more load and worse user experience.


## 7) Backpressure & Rate Limiting (stability)
- Rate limiting: each client can send a limited number of inputs per second (defaults are safe).
- Broadcast coalescing: if a client is slow, the server skips intermediate frames and sends the latest.

Why this?
- Keeps the server from lagging due to one spammy or slow client.
- Preserves smooth gameplay for everyone else.

Alternatives (and why not):
- Unbounded queues: memory blowups and lag spikes.
- Disconnect slow clients immediately: too harsh; coalescing is friendlier.


## 8) Ghost AI (simple classic behavior)
- Tile‑aware movement: turns at intersections, avoids reversing unless needed.
- Global modes: scatter (to corners) and chase (hunt players), alternating over time.
- Personalities:
  - Red (Blinky): chases the nearest player.
  - Purple (Pinky): aims a few tiles ahead of player movement.
  - Green (Inky): triangulates using Red + a point ahead of the player.
  - Orange (Clyde): chases when far, wanders when near.
- Frightened mode: when players eat a power pellet, ghosts try to flee.

Why this?
- Familiar, predictable, engaging behavior with minimal code.

Alternatives (and why not):
- Full pathfinding (A*/BFS) per frame: more precise but heavier; not needed for fun.
- Pure random: too chaotic; feels unfair or boring.


## 9) Victory & Restart
- When pellets are gone, victory is set.
- A simple victory menu overlays scores.
- Press R to restart the room; ESC to quit.

Why a menu overlay?
- Familiar game flow. No need to restart the app to play again.


## 10) How to run (quick)
- Easiest way (client auto‑starts balancer/backends if needed):
  - In PowerShell: `python -m client.main`
- Or, run the balancer and backends yourself:
  - Backends: `python -m server.main --port 8766` and `--port 8767`
  - Balancer: `python -m server.load_balancer --port 8765 --backends ws://localhost:8766,ws://localhost:8767`
- Then `python -m client.main`


## 11) How to verify important behaviors (no code reading)
- Load balancing: Start two backends and the balancer, then open multiple clients.
  - Watch which backend prints “Client connected”.
  - Different room keys may map to different backends.
- Rate limiting: Hold keys down rapidly; server prints “Dropping input due to rate limit”.
- Coalescing: Make one client slow (CPU heavy). Others still play smoothly.
- Overload: Run the balancer with `--backend-capacity 1`. Second client gets a busy message.


## 12) Why these choices overall
- Simplicity first: Real‑time games need low latency more than fancy protocols.
- Isolation by room: Bugs and spikes are contained.
- Horizontal scale: One more backend is just another process and port.
- Friendly degradation: Backpressure and coalescing keep the game responsive.
- Predictable AI: Good gameplay without heavy compute.


## 13) Common alternatives and trade‑offs
- HTTP + polling: easier to debug, but poorer latency and more bandwidth.
- Full authoritative physics with rollback: more precise but complex.
- Central state store (Redis): useful for persistence; not needed here.
- Heavy pathfinding per ghost: looks smart, costs CPU; we kept it light for scale.


## 14) Terms (quick glossary)
- WebSocket: A two‑way, always‑on connection between client and server.
- Room: A small group of players isolated from others.
- Load balancer: A proxy that forwards client connections to different servers.
- Circuit breaker: Temporarily disables calls to a failing service.
- Backpressure: The system tells sources to slow down; limits overload.
- Coalescing: Drop old frames and send the latest state to keep up.


## 15) Where to look in the repo
- docs/FILE_REFERENCE.md — Per‑file explanations and a runtime checklist.
- CODE_DOCUMENTATION.txt — Architecture, networking, and distributed concepts.
- docs/POSTER.svg — A printable poster for the project.


## 16) What to build next
- Sticky sessions via hashing player IDs (even stickier routing).
- Sprite‑based graphics and sound effects.
- Matchmaking lobby or a list of active rooms.
- Cloud deploy (Docker + a lightweight reverse proxy).


## 17) Why these algorithms (distributed systems choices)
Below are the key algorithms/patterns we used, with plain‑English reasons and what we didn’t choose.

1) Load balancing: Least‑Connections (+ token‑consistent routing)
- Why: With long‑lived WebSockets, “how many connections” correlates with per‑backend load better than round‑robin.
- Token consistency: players using the same room key land on the same backend, ensuring they meet.
- Not chosen:
  - Round‑robin only: can be unfair when connections are long‑lived and uneven in cost.
  - Random: unstable distribution; swings happen under low counts.
  - Pure consistent hashing (no least‑connections): good for stickiness but blind to current load.

2) Circuit breaker: Exponential backoff with half‑open trials
- Why: Failing fast prevents “retry storms”. Exponential backoff quickly gives time for recovery while avoiding overload.
- Half‑open lets a few trial connections check recovery before fully closing the breaker.
- Not chosen:
  - Fixed/linear backoff: too slow to reduce pressure or too fast to restore.
  - Blind retries: can dog‑pile a sick backend and degrade user experience.

3) Rate limiting: Token bucket per client
- Why: Token bucket allows short bursts (feels responsive) but enforces an average rate, ideal for user inputs.
- Not chosen:
  - Leaky bucket: smooths output but doesn’t allow useful bursts from humans.
  - Fixed/sliding window counters: OK for APIs, but spiky UX for realtime input.

4) Backpressure for broadcasts: Coalescing (latest‑state wins)
- Why: Game state is idempotent — only the latest snapshot matters. Dropping older frames keeps the room smooth even if a client is slow.
- Not chosen:
  - Unbounded queues: memory growth, latency cliffs.
  - Drop‑tail only: can still accumulate stale frames under sustained slowness.
  - Strict blocking sends: a single slow client stalls everyone.

5) Autoscaling: Connection‑count threshold
- Why: Simple, visible signal that correlates with capacity for a WebSocket game. Easy to reason about and tune.
- Not chosen (yet):
  - CPU/latency‑driven autoscaling: more precise but needs metrics plumbing and hysteresis tuning.
  - Queue‑length based: we already coalesce; queue depth is intentionally small/unreliable as a signal.

6) Token rooms: Simple keys + consistent routing
- Why: Zero account system, immediate “play with a friend”, deterministic routing by key.
- Not chosen:
  - Central lobby service: heavier infra, more moving parts for a small game.
  - Pure random matchmaking: doesn’t guarantee friends end up together.

7) Transport: WebSockets (vs HTTP polling)
- Why: Full‑duplex, low latency, low overhead for frequent updates.
- Not chosen:
  - Long‑polling/Server‑Sent Events: possible, but more overhead and trickier backpressure.

Putting it together: these choices favor smooth gameplay, predictable scaling, and minimal complexity. They also give you clear upgrade paths: add metrics and hysteresis for smarter autoscaling; add BFS pathing for ghosts; or swap in consistent hashing for sticky sessions at larger scale.

## 18) Distributed systems concepts used (summary)
- WebSockets for full‑duplex, low‑latency messaging
- Load balancing: least‑connections selection + token‑consistent routing
- Circuit breaker with exponential backoff and half‑open trials
- Rate limiting: per‑client token bucket
- Backpressure: output coalescing (latest‑state wins)
- Autoscaling: connection‑count thresholds
- Room isolation: per‑room authoritative state to reduce blast radius
- Idempotent state broadcasting for eventual visual consistency
- Health‑aware routing: cooldown/backoff on failing backends
- Stateless front door (balancer) with sticky routing via tokens

## 19) Tricky questions (with answers)
1) Why is least‑connections better than round‑robin for WebSockets here?
- WebSocket connections are long‑lived and uneven in cost. Least‑connections reflects current load; round‑robin can overload a backend that ends up with more heavy rooms.

2) If we add consistent hashing for stickiness, what trade‑off do we introduce vs least‑connections?
- Strong stickiness but blindness to instantaneous load. Mitigate by combining hashing for affinity with a secondary least‑connections choice among a small candidate set.

3) What failure mode does the circuit breaker protect against, and what happens if cooldown is too aggressive?
- It prevents retry storms against a sick backend. Over‑aggressive cooldown delays recovery; tune half‑open probes and backoff caps.

4) How does broadcast coalescing preserve correctness?
- Game state is idempotent for rendering: only the latest snapshot matters. Dropping stale frames maintains smooth gameplay; visual artifacts are brief but state remains correct.

5) How do we detect a backend that is slow (degraded) but not failing outright?
- Track moving averages of send latency and queue depth; apply partial backoff/weight reduction or route new rooms elsewhere until metrics recover.

6) How do tokens ensure friends meet even after autoscaling (backends added/removed)?
- Use deterministic routing (e.g., consistent hashing) based on the token over the active backend set; keep the mapping stable by updating the hash ring carefully when membership changes.

7) What if two backends both believe they own the same room key (split‑brain)?
- Enforce single ownership at the balancer or via a lightweight registry/lease. Use atomic registration (CAS) and heartbeat expiry to prevent duplicates.

8) Why not use a central state store (e.g., Redis) for rooms?
- Not needed for ephemeral matches; adds latency/complexity. It’s useful for persistence/match recovery at the cost of operational overhead.

9) What’s the worst case for token‑bucket rate limiting with a spammy client?
- A short burst is allowed then inputs drop, which can feel like lost presses. Tune bucket size/refill rate to human input patterns and provide client feedback.

10) If we upgrade ghost AI to A* per frame, which scaling signal matters most?
- CPU time per tick becomes dominant. Connection‑count autoscaling may be insufficient; you’ll likely need CPU/latency‑based scaling and hysteresis.

11) How do we keep the game fair when one client has high latency?
- Keep the server authoritative, coalesce outputs, and optionally add client‑side interpolation/extrapolation; never block the room on the slowest client.

12) How can we add sticky sessions without hurting balancing too much?
- Two‑step: hash the token to a small candidate set, then pick by least‑connections; or use weighted consistent hashing informed by backend load.

You now understand why each piece exists, how it fits, and why we traded complexity for smoothness and stability. Have fun playing—and feel free to extend it!
