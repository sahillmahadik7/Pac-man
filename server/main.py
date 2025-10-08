# server/main.py - Room-based multiplayer Pac-Man server
import asyncio
import websockets
import json
import argparse
import os
from urllib.parse import urlparse, parse_qs
from .room_manager import room_manager

async def handle_client(websocket, path=None):
    """Handle a new client connection. Supports token-based room create/join via query params.
    Query:
      - action=create|join (optional; defaults to auto-assign)
      - room=<token>      (when action is provided)
    Compatible with websockets versions that pass either (websocket) or (websocket, path).
    """
    print("Client connected")
    
    try:
        # Parse query params for token-based routing
        room_id = None
        req_path = path or getattr(websocket, "path", "")
        action = None
        token = None
        action_source = "none"
        token_source = "none"
        if req_path:
            parsed = urlparse(req_path)
            qs = parse_qs(parsed.query)
            action = (qs.get("action", [None])[0] or "").lower()
            token = (qs.get("room", [None])[0] or "").strip()
            if action:
                action_source = "query"
            if token:
                token_source = "query"
        # Fallback to headers forwarded by the load balancer
        try:
            hdr_action = (websocket.request_headers.get("X-Pacman-Action") or "").lower().strip()
            hdr_token = (websocket.request_headers.get("X-Pacman-Room") or "").strip()
            if not action and hdr_action:
                action = hdr_action
                action_source = "header"
            if not token and hdr_token:
                token = hdr_token
                token_source = "header"
        except Exception:
            pass

        # Final fallback: try to read a small hello frame carrying action/token
        first_msg_buffer = None
        if not action or not token:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.75)
                try:
                    data = json.loads(raw)
                except Exception:
                    data = None
                if isinstance(data, dict) and data.get("type") == "hello":
                    if not action:
                        action = (data.get("action") or "").lower().strip() or None
                        if action:
                            action_source = "frame"
                    if not token:
                        token = (data.get("room") or "").strip() or None
                        if token:
                            token_source = "frame"
                else:
                    # Not a hello message; buffer it to replay after assignment
                    first_msg_buffer = raw
            except Exception:
                pass

        print(f"[SVR] new connection: action='{action or '-'}' ({action_source}), token='{token or '-'}' ({token_source})")
        if action in ("create", "join") and token:
            create_if_missing = (action == "create")
            force_new = False  # keep the token as-is for create
            print(f"[SVR] handling explicit {action} for token '{token}' (force_new={force_new})")

            if action == "join":
                # Wait briefly for the host to create the room on this backend
                max_wait = float(os.getenv("PACMAN_JOIN_WAIT_SECS", "12.0"))
                deadline = asyncio.get_event_loop().time() + max_wait
                room_id = None
                while True:
                    room_id = await room_manager.add_player_to_specific_room(
                        websocket, token, create_if_missing=False, force_new=False
                    )
                    if room_id:
                        break
                    # If room exists but is full, abort immediately
                    rm = room_manager.rooms.get(token)
                    if rm is not None and rm.is_full():
                        await websocket.send(json.dumps({"type": "error", "message": "Room is full."}))
                        return
                    if asyncio.get_event_loop().time() >= deadline:
                        await websocket.send(json.dumps({"type": "error", "message": "Room not found. Ask host to start, then retry Join."}))
                        return
                    await asyncio.sleep(0.25)
            else:
                room_id = await room_manager.add_player_to_specific_room(
                    websocket, token, create_if_missing=create_if_missing, force_new=force_new
                )
                if not room_id:
                    # Explicit create failed (should be rare): report error
                    await websocket.send(json.dumps({"type": "error", "message": "Could not create room. Try a different code."}))
                    return
        
        # Fallback: automatic assignment
        if not room_id:
            print("[SVR] no action/token => auto-assign path")
            room_id = await room_manager.assign_player_to_room(websocket)
        if not room_id:
            await websocket.send(json.dumps({"type": "error", "message": "Failed to assign to room"}))
            return
        
        # Send initial room assignment message
        await websocket.send(json.dumps({
            "type": "room_assignment", 
            "room_id": room_id,
            "message": f"Assigned to room {room_id}"
        }))

        # If we buffered a non-hello message before assignment, process it once
        if 'first_msg_buffer' in locals() and first_msg_buffer:
            try:
                await room_manager.handle_player_input(websocket, first_msg_buffer)
            except Exception:
                pass
        
# Rate limiting config
        RATE = float(os.getenv("PACMAN_INPUT_RPS", "30"))
        BURST = float(os.getenv("PACMAN_INPUT_BURST", "10"))
        tokens = BURST
        last_refill = asyncio.get_event_loop().time()
        warn_cooldown = 0.0

        # Handle messages from the client
        async for message in websocket:
            try:
                # Refill token bucket
                now = asyncio.get_event_loop().time()
                elapsed = now - last_refill
                last_refill = now
                tokens = min(BURST, tokens + elapsed * RATE)
                if tokens >= 1.0:
                    tokens -= 1.0
                    await room_manager.handle_player_input(websocket, message)
                else:
                    # Drop excess input and occasionally warn
                    if now >= warn_cooldown:
                        print("[RateLimit] Dropping input from client due to rate limit")
                        try:
                            await websocket.send(json.dumps({"type": "rate_limit", "message": "Too many inputs; slowing down."}))
                        except Exception:
                            pass
                        warn_cooldown = now + 1.0  # warn at most once per second
            except json.JSONDecodeError:
                print("Invalid JSON received from client")
            except Exception as e:
                print(f"Error handling player input: {e}")
                
    except websockets.ConnectionClosedOK:
        print("Client disconnected normally")
    except websockets.ConnectionClosedError as e:
        print(f"Client disconnected with error: {e}")
    except Exception as e:
        print(f"Unexpected error in handle_client: {e}")
    finally:
        # Remove player from their room
        await room_manager.remove_player_from_room(websocket)
        print("Client connection cleaned up")

async def status_reporter():
    """Periodically report server status"""
    try:
        while True:
            await asyncio.sleep(30)  # Report every 30 seconds
            stats = room_manager.get_room_stats()
            if stats['total_players'] > 0:
                print(f"=== SERVER STATUS ===")
                print(f"Active Rooms: {stats['active_rooms']}")
                print(f"Total Players: {stats['total_players']}")
                for room in stats['rooms']:
                    if not room['is_empty']:
                        print(f"  Room {room['room_id']}: {room['players']}/{room['max_players']} players")
                print("====================")
    except asyncio.CancelledError:
        pass

async def main(port: int = 8765):
    """Main server function"""
    print("🎮 Room-Based Pac-Man Multiplayer Server")
    print("========================================")
    print("Features:")
    print("- Max 2 players per room")
    print("- Automatic room creation")
    print("- Simultaneous games")
    print("- Enhanced ghost AI")
    
    # Start the room manager
    await room_manager.start()
    
    # Start status reporter
    status_task = asyncio.create_task(status_reporter())
    
    try:
        # Start WebSocket server
        async with websockets.serve(handle_client, "0.0.0.0", port):
            print(f"\n✅ Server running on ws://localhost:{port}")
            print("Players will be automatically assigned to rooms (max 2 per room)")
            print("Press Ctrl+C to stop the server\n")
            
            # Keep the server running
            await asyncio.Event().wait()  # Wait indefinitely
            
    except KeyboardInterrupt:
        print("\n🛑 Server shutdown requested")
    finally:
        # Cleanup
        status_task.cancel()
        await room_manager.stop()
        print("✅ Server stopped successfully")

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Room-Based Pac-Man Server")
        parser.add_argument("--port", type=int, default=int(os.getenv("PACMAN_SERVER_PORT", "8765")), help="Port to bind the game server on")
        args = parser.parse_args()
        asyncio.run(main(port=args.port))
    except KeyboardInterrupt:
        print("\nServer stopped")
    except Exception as e:
        print(f"Fatal error: {e}")
