# server/load_balancer.py - WebSocket reverse-proxy load balancer for Pac-Man
import asyncio
import argparse
import os
import subprocess
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

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

    async def pick_backend(self) -> Optional[Backend]:
        """Least-connections selection among available backends"""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            candidates = [b for b in self.backends if b.is_available(now)]
            if not candidates:
                return None
            # Least connections; tie-breaker: original order
            chosen = min(candidates, key=lambda b: b.active_connections)
            chosen.active_connections += 1
            chosen.last_active = now
            return chosen

    async def pick_backend_for_token(self, token: str) -> Optional[Backend]:
        """Consistent selection based on token; falls back to least-connections if candidate unavailable."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            available = [b for b in self.backends if b.is_available(now)]
            if not available:
                return None
            # Deterministic index by token hash
            idx = (hash(token) % len(self.backends)) if self.backends else 0
            preferred = self.backends[idx]
            candidate = preferred if preferred in available else min(available, key=lambda b: b.active_connections)
            candidate.active_connections += 1
            candidate.last_active = now
            return candidate

    async def release_backend(self, backend: Backend):
        async with self._lock:
            backend.active_connections = max(0, backend.active_connections - 1)
            backend.last_active = asyncio.get_event_loop().time()


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
    req_path = path or getattr(websocket, "path", "")
    if req_path:
        parsed = urlparse(req_path)
        qs = parse_qs(parsed.query)
        token = (qs.get("room", [None])[0] or "").strip() or None
    
    if token:
        backend: Optional[Backend] = await pool.pick_backend_for_token(token)
    else:
        backend: Optional[Backend] = await pool.pick_backend()
    if not backend:
        # No backend available; inform client
        try:
            await websocket.send('{"error": "No backend available. Please try again later."}')
        finally:
            await websocket.close()
        return
    
    # Overload check: if all available backends are at/over capacity, return overload
    now = asyncio.get_event_loop().time()
    available = [b for b in pool.backends if b.is_available(now)]
    if pool.capacity and available and all(b.active_connections >= pool.capacity for b in available):
        try:
            await websocket.send('{"error": "All servers are busy. Please try again in a moment."}')
        finally:
            await websocket.close()
        return

    try:
        # Attempt to connect to backend
        try:
            async with websockets.connect(backend.url, open_timeout=5) as backend_ws:
                backend.on_success()
                await bidirectional_proxy(websocket, backend_ws)
        except Exception:
            # Mark backend failure and close client
            backend.on_failure(asyncio.get_event_loop().time())
            try:
                await websocket.send('{"error": "Selected backend became unavailable. Please reconnect."}')
            finally:
                await websocket.close()
    finally:
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
                # Scale up if all available backends are at/over capacity
                if all(b.active_connections >= args.backend_capacity for b in available):
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
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            autoscale_task.cancel()
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