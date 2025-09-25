# server/state.py

class GameState:
    """Authoritative world state for the 2-player Pac-Man game."""

    WIDTH = 640
    HEIGHT = 480
    SPEED = 5

    def __init__(self):
        # { websocket : {"x":.., "y":.., "vx":.., "vy":.., "color":..} }
        self.players = {}
        self.colors = ["yellow", "cyan"]

    async def add_player(self, ws):
        """Register a new player and assign a colour."""
        if not self.colors:
            return False
        color = self.colors.pop(0)
        self.players[ws] = {
            "x": 100 if color == "yellow" else 300,
            "y": 200,
            "vx": 0,
            "vy": 0,
            "color": color,
        }
        return True

    async def remove_player(self, ws):
        if ws in self.players:
            color = self.players[ws]["color"]
            self.players.pop(ws)
            self.colors.insert(0, color)

    async def handle_input(self, ws, action):
        """Process a keypress from a client."""
        p = self.players.get(ws)
        if not p:
            return
        if action == "UP":
            p["vx"], p["vy"] = 0, -self.SPEED
        elif action == "DOWN":
            p["vx"], p["vy"] = 0, self.SPEED
        elif action == "LEFT":
            p["vx"], p["vy"] = -self.SPEED, 0
        elif action == "RIGHT":
            p["vx"], p["vy"] = self.SPEED, 0

    def update(self):
        """Move players each tick, keeping them inside bounds."""
        for p in self.players.values():
            p["x"] = max(0, min(self.WIDTH, p["x"] + p["vx"]))
            p["y"] = max(0, min(self.HEIGHT, p["y"] + p["vy"]))

    def snapshot(self):
        """Return a serializable snapshot of the game world."""
        return {
            "type": "snapshot",
            "players": [
                {"x": p["x"], "y": p["y"], "color": p["color"]}
                for p in self.players.values()
            ],
        }
