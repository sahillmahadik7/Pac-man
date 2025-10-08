# server/load_balancer.py - WebSocket reverse-proxy load balancer for Pac-Man
import asyncio
import argparse
import os
import subprocess
from typing import List, Optional
from urllib.parse import urlparse, parse_qs
import hashlib
import json

import websockets


class Backend:
    def __init__(self, url: str):
        self.url = url
        self.active = True
        self.active_connections = 0
        self.failures = 0
        self.cooldown_until: float = 0.0
        # autoscale/management fields
        self.managed: bool = False
        self.process: Optional[subprocess.Popen] = None
        self.last_active: float = 0.0
        # Room-based load balancing
        self.active_rooms: set = set()  # Track which rooms are hosted on this server
        self.room_player_counts: dict = {}  # room_id -> player_count

    def is_available(self, now: float) -> bool:
        return self.active and now >= self.cooldown_until

    def on_failure(self, now: float):
        self.failures += 1
        # Exponential backoff up to 30s
        cooldown = min(30, 2 ** min(self.failures, 4))
        self.cooldown_until = now + cooldown

    def on_success(self):
        self.failures = 0
        self.cooldown_until = 0.0


class BackendPool:
    def __init__(self, backends: List[str], capacity: int = 0):
        self.backends = [Backend(url) for url in backends]
        self._lock = asyncio.Lock()
        self.capacity = capacity
        # Room-to-backend mapping for consistent routing
        self.room_to_backend: dict = {}  # room_id -> Backend

    async def pick_backend(self) -> Optional[Backend]:
        """Least-connections selection across available backends."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            candidates = [b for b in self.backends if b.is_available(now)]
            if not candidates:
                return None
            # Choose backend with the fewest active connections (classic least-connections)
            # Tie-breaker by last_active to avoid sticking to index 0 on cold start
            chosen = min(candidates, key=lambda b: (b.active_connections, b.last_active))
            chosen.active_connections += 1
            chosen.last_active = now
            return chosen

    async def pick_backend_for_token(self, token: str, is_create: Optional[bool] = None) -> Optional[Backend]:
        """Sticky rooms + intent-aware selection.
        - If room already mapped: route there (join/create).
        - If creating: choose backend with the fewest active rooms and establish mapping.
        - If joining and no mapping exists: return None (room not found at LB).
        """
        async with self._lock:
            now = asyncio.get_event_loop().time()
            available = [b for b in self.backends if b.is_available(now)]
            if not available and not self.backends:
                return None
            
            # Existing mapping
            existing_backend = self.room_to_backend.get(token)
            if existing_backend and existing_backend in available:
                existing_backend.active_connections += 1
                existing_backend.last_active = now
                if token in existing_backend.room_player_counts:
                    existing_backend.room_player_counts[token] = existing_backend.room_player_counts.get(token, 0) + 1
                print(f"[LB] Room '{token}' exists on {existing_backend.url}, routing there")
                return existing_backend
            
            # Create new room: choose backend with least active rooms
            if is_create is True:
                if not available:
                    return None
                candidate = min(available, key=lambda b: len(b.active_rooms))
                candidate.active_connections += 1
                candidate.last_active = now
                self.room_to_backend[token] = candidate
                candidate.active_rooms.add(token)
                candidate.room_player_counts[token] = candidate.room_player_counts.get(token, 0) + 1
                print(f"[LB] New room '{token}' assigned to {candidate.url} (rooms: {len(candidate.active_rooms)})")
                return candidate
            
            # Join requested but we have no mapping for this token
            print(f"[LB] Join requested for unknown room '{token}'")
            return None

    async def release_backend(self, backend: Backend):
        async with self._lock:
            backend.active_connections = max(0, backend.active_connections - 1)
            backend.last_active = asyncio.get_event_loop().time()
    
    async def update_room_info(self, backend: Backend, room_id: str, player_count: int, room_active: bool):
        """Update room information from backend servers"""
        async with self._lock:
            if room_active and room_id not in backend.active_rooms:
                # New room detected
                backend.active_rooms.add(room_id)
                self.room_to_backend[room_id] = backend
                print(f"[LB] Room '{room_id}' started on {backend.url}")
            
            if room_active:
                backend.room_player_counts[room_id] = player_count
            elif room_id in backend.active_rooms:
                # Room ended or empty
                backend.active_rooms.discard(room_id)
                backend.room_player_counts.pop(room_id, None)
                self.room_to_backend.pop(room_id, None)
                print(f"[LB] Room '{room_id}' ended on {backend.url}")


async def bidirectional_proxy(client_ws: websockets.WebSocketClientProtocol, server_ws: websockets.WebSocketClientProtocol):
    async def c2s():
        async for msg in client_ws:
            await server_ws.send(msg)

    async def s2c():
        async for msg in server_ws:
            await client_ws.send(msg)

    # Run both directions until one side closes
    done, pending = await asyncio.wait({asyncio.create_task(c2s()), asyncio.create_task(s2c())}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()


async def handle_client(websocket: websockets.WebSocketServerProtocol, path: Optional[str], pool: BackendPool):
    # Extract token from query to choose a consistent backend for that room
    token = None
    # Prefer websocket.path (often includes query string) over handler's path argument
    req_path = getattr(websocket, "path", None) or path or ""
    # If handler path lacks query but websocket.path has it, the above covers it.
    if req_path:
        parsed = urlparse(req_path)
        qs = parse_qs(parsed.query)
        token = (qs.get("room", [None])[0] or "").strip() or None
    
    # Also parse 'action' if provided (for forwarding)
    action = None
    if req_path:
        try:
            parsed_tmp = urlparse(req_path)
            qs_tmp = parse_qs(parsed_tmp.query)
            action = (qs_tmp.get("action", [None])[0] or "").strip().lower() or None
        except Exception:
            action = None

    # Peek the first client frame to learn token/action if not present in URL
    first_msg = None
    if not token or not action:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=0.8)
            first_msg = raw
            try:
                data0 = None
                if isinstance(raw, (bytes, bytearray)):
                    try:
                        data0 = json.loads(raw.decode("utf-8", errors="ignore"))
                    except Exception:
                        data0 = None
                else:
                    data0 = json.loads(raw)
                if isinstance(data0, dict) and data0.get("type") == "hello":
                    if not token:
                        token = (data0.get("room") or "").strip() or None
                    if not action:
                        action = (data0.get("action") or "").strip().lower() or None
                    try:
                        print(f"[LB] learned from frame: action='{action or '-'}', token='{token or '-'}'")
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

    if token:
        is_create_flag = (action == "create") if action else None
        backend: Optional[Backend] = await pool.pick_backend_for_token(token, is_create=is_create_flag)
    else:
        backend: Optional[Backend] = await pool.pick_backend()
    if not backend:
        # No backend available or unknown room token
        try:
            if token and action == "join":
                await websocket.send('{"type": "error", "message": "Room not found."}')
            else:
                await websocket.send('{"type": "error", "message": "No backend available. Please try again later."}')
        finally:
            await websocket.close()
        return
    
    # Room-based overload check: if all available backends are at room capacity, return overload
    now = asyncio.get_event_loop().time()
    available = [b for b in pool.backends if b.is_available(now)]
    # Check if we're creating a new room and all servers are at room capacity
    max_rooms_per_server = pool.capacity // 2 if pool.capacity > 0 else 10  # Assume ~2 players per room
    if token and token not in pool.room_to_backend:  # New room
        if available and all(len(b.active_rooms) >= max_rooms_per_server for b in available):
            try:
                await websocket.send('{"type": "error", "message": "All servers are hosting maximum rooms. Please try again later."}')
            finally:
                await websocket.close()
            return

    # Debug/ops log: show routing decision
    try:
        room_info = f" (rooms: {len(backend.active_rooms)})" if hasattr(backend, 'active_rooms') else ""
        action = "joining existing room" if token and token in pool.room_to_backend else "creating new room" if token else "auto-assignment"
        print(f"[LB] {action} - path='{req_path}' token='{token or 'none'}' -> {backend.url}{room_info}")
    except Exception:
        pass

    try:
        # Attempt to connect to backend
        try:
            # Build destination URL preserving client's original path and query (e.g., ?action=join&room=TOKEN)
            dest_url = backend.url
            if req_path:
                if req_path.startswith("/"):
                    dest_url = f"{backend.url}{req_path}"
                else:
                    dest_url = f"{backend.url}/{req_path}"
            # Connect to backend. For maximum compatibility across websockets versions,
            # avoid passing extra headers here.
            async with websockets.connect(dest_url, open_timeout=5) as backend_ws:
                backend.on_success()
                # If we consumed a first client frame (e.g., hello), forward it to the backend first
                if first_msg is not None:
                    try:
                        await backend_ws.send(first_msg)
                    except Exception:
                        pass
                await bidirectional_proxy(websocket, backend_ws)
        except Exception as e:
            # Mark backend failure and close client
            backend.on_failure(asyncio.get_event_loop().time())
            try:
                print(f"[LB] Backend failure for token='{token or '-'}' url={backend.url}: {e}")
            except Exception:
                pass
            try:
                await websocket.send('{"type": "error", "message": "Selected backend became unavailable. Please reconnect."}')
            finally:
                await websocket.close()
    finally:
        # Decrease room player count if we know which room this was for
        if token and backend and token in backend.room_player_counts:
            backend.room_player_counts[token] = max(0, backend.room_player_counts[token] - 1)
            print(f"[LB] Player left room '{token}' on {backend.url} (remaining: {backend.room_player_counts[token]})")
        await pool.release_backend(backend)


async def main():
    parser = argparse.ArgumentParser(description="Pac-Man WebSocket Load Balancer")
    parser.add_argument("--port", type=int, default=int(os.getenv("PACMAN_LB_PORT", "8765")), help="Port for the load balancer to listen on")
    parser.add_argument("--backends", type=str, default=os.getenv("PACMAN_BACKENDS", ""), help="Comma-separated list of backend WebSocket URLs")
    parser.add_argument("--auto", action="store_true", help="Enable auto-start and autoscaling of local backend servers")
    parser.add_argument("--min-backends", type=int, default=int(os.getenv("PACMAN_LB_MIN_BACKENDS", "1")), help="Minimum number of backend servers when --auto is enabled")
    parser.add_argument("--max-backends", type=int, default=int(os.getenv("PACMAN_LB_MAX_BACKENDS", "3")), help="Maximum number of backend servers when --auto is enabled")
    parser.add_argument("--backend-base-port", type=int, default=int(os.getenv("PACMAN_LB_BACKEND_BASE_PORT", "8766")), help="Starting port for auto-launched backend servers")
    parser.add_argument("--backend-capacity", type=int, default=int(os.getenv("PACMAN_LB_BACKEND_CAPACITY", "20")), help="Approximate client capacity per backend before scaling up")
    parser.add_argument("--server-launch-cmd", type=str, default=os.getenv("PACMAN_LB_SERVER_LAUNCH_CMD", "python -m server.main --port {port}"), help="Command to launch a backend server; must include {port}")
    args = parser.parse_args()

    initial_backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    pool = BackendPool(initial_backends, capacity=args.backend_capacity)

    # spawning helpers
    async def spawn_backend_on_port(port: int):
        cmd = args.server_launch_cmd.format(port=port)
        print(f"Starting backend: {cmd}")
        proc = subprocess.Popen(cmd, shell=True)
        b = Backend(f"ws://localhost:{port}")
        b.managed = True
        b.process = proc
        pool.backends.append(b)

    async def ensure_min_backends():
        if not args.auto:
            return
        # Count existing
        existing_ports = set()
        for b in pool.backends:
            try:
                p = int(urlparse(b.url).port)
                existing_ports.add(p)
            except Exception:
                pass
        # Spawn until min-backends
        while len(pool.backends) < max(args.min_backends, len(initial_backends) or 0):
            # next port
            next_port = args.backend_base_port
            while next_port in existing_ports:
                next_port += 1
            await spawn_backend_on_port(next_port)
            existing_ports.add(next_port)

    async def autoscale_loop():
        if not args.auto:
            return
        try:
            while True:
                await asyncio.sleep(5)
                now = asyncio.get_event_loop().time()
                # Consider available backends
                available = [b for b in pool.backends if b.is_available(now)]
                if not available:
                    continue
                # Scale up if all available backends are hosting many rooms
                max_rooms_per_server = args.backend_capacity // 2 if args.backend_capacity > 0 else 10
                if all(len(b.active_rooms) >= max_rooms_per_server for b in available):
                    total = len(pool.backends)
                    if total < args.max_backends:
                        # find next free port
                        used_ports = set()
                        for b in pool.backends:
                            try:
                                used_ports.add(int(urlparse(b.url).port))
                            except Exception:
                                pass
                        next_port = args.backend_base_port
                        while next_port in used_ports:
                            next_port += 1
                        await spawn_backend_on_port(next_port)
                        print(f"Autoscale: launched backend on port {next_port}")
        except asyncio.CancelledError:
            pass

    async def room_monitor_loop():
        """Monitor backend servers for room state changes"""
        if not args.auto:
            return
        try:
            while True:
                await asyncio.sleep(10)  # Check every 10 seconds
                now = asyncio.get_event_loop().time()
                for backend in pool.backends:
                    if not backend.is_available(now):
                        continue
                    
                    try:
                        # Try to get room stats from backend server
                        # This would require a separate HTTP endpoint on game servers
                        # For now, we'll rely on connection patterns and timeouts
                        
                        # Clean up rooms that haven't been accessed recently
                        stale_rooms = []
                        for room_id in list(backend.active_rooms):
                            # If no connections to this room recently, mark as potentially stale
                            if backend.room_player_counts.get(room_id, 0) == 0:
                                stale_rooms.append(room_id)
                        
                        # Clean up stale rooms (this is a simplified approach)
                        for room_id in stale_rooms:
                            if backend.room_player_counts.get(room_id, 0) == 0:
                                backend.active_rooms.discard(room_id)
                                backend.room_player_counts.pop(room_id, None)
                                pool.room_to_backend.pop(room_id, None)
                                print(f"[LB] Cleaned up stale room '{room_id}' from {backend.url}")
                                
                    except Exception as e:
                        # Don't fail the entire monitor for one backend error
                        pass
                        
        except asyncio.CancelledError:
            pass

    print("⚖️  Pac-Man Load Balancer")
    print("==========================")
    print(f"Listening on ws://0.0.0.0:{args.port}")
    if initial_backends:
        print("Static Backends:")
        for b in initial_backends:
            print(f" - {b}")
    if args.auto:
        print(f"Autoscale enabled: min={args.min_backends}, max={args.max_backends}, base_port={args.backend_base_port}, capacity={args.backend_capacity}")

    await ensure_min_backends()

    async def _handler(ws, path=None):
        await handle_client(ws, path, pool)

    async with websockets.serve(_handler, "0.0.0.0", args.port):
        autoscale_task = asyncio.create_task(autoscale_loop())
        room_monitor_task = asyncio.create_task(room_monitor_loop())
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            autoscale_task.cancel()
            room_monitor_task.cancel()
            # Optional: stop managed backends
            for b in pool.backends:
                if b.managed and b.process and b.process.poll() is None:
                    try:
                        b.process.terminate()
                    except Exception:
                        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLoad balancer stopped")