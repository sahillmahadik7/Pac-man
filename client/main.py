import asyncio
import sys
import pygame
import websockets
import json
import math
import time

CELL_SIZE = 40
PLAYER_RADIUS = 15
GHOST_RADIUS = 15
PELLET_RADIUS = 4

# Simple, reliable colors
COLORS = {
    'background': (0, 0, 0),
    'wall': (0, 0, 255),
    'pellet': (255, 255, 0),
    'power_pellet': (255, 255, 255),
    'player': (255, 255, 0),
    'player_dead': (100, 100, 0),
    'ghost_red': (255, 0, 0),
    'ghost_orange': (255, 165, 0),
    'ghost_purple': (255, 0, 255),
    'ghost_green': (0, 255, 0),
    'ui_text': (255, 255, 255),
    'ui_background': (50, 50, 50),
    'death_overlay': (255, 0, 0),
    'grid_line': (50, 50, 50)
}

class SimpleGameClient:
    def __init__(self):
        self.screen = None
        self.clock = pygame.time.Clock()
        self.last_data = {}
        self.current_player_id = None
        self.server_url = "ws://192.168.94.1:8765"
        self.room_id = None
        self.connection_status = "Connecting..."

    def init_display(self):
        """Initialize display"""
        try:
            pygame.init()
            pygame.font.init()
            
            if not pygame.display.get_init():
                raise pygame.error("No display available")
            
            self.screen = pygame.display.set_mode((CELL_SIZE * 19 + 250, CELL_SIZE * 15))
            pygame.display.set_caption("Pac-Man Multiplayer")
            return True
        except pygame.error as e:
            print(f"Display initialization failed: {e}")
            return False

    def draw_maze(self, surface, maze):
        """Draw simple maze"""
        for y, row in enumerate(maze):
            for x, cell in enumerate(row):
                px, py = x * CELL_SIZE, y * CELL_SIZE
                
                if cell == 1:  # Wall
                    pygame.draw.rect(surface, COLORS['wall'], (px, py, CELL_SIZE, CELL_SIZE))
                    
                elif cell == 2:  # Regular pellet
                    center_x = px + CELL_SIZE // 2
                    center_y = py + CELL_SIZE // 2
                    pygame.draw.circle(surface, COLORS['pellet'], (center_x, center_y), PELLET_RADIUS)
                    
                elif cell == 3:  # Power pellet
                    center_x = px + CELL_SIZE // 2
                    center_y = py + CELL_SIZE // 2
                    radius = PELLET_RADIUS * 2
                    pygame.draw.circle(surface, COLORS['power_pellet'], (center_x, center_y), radius)

    def draw_player(self, surface, player_data, player_id, is_current):
        """Draw simple player"""
        x = int(player_data['x'] * CELL_SIZE + CELL_SIZE // 2)
        y = int(player_data['y'] * CELL_SIZE + CELL_SIZE // 2)
        
        if player_data['dead']:
            # Dead player (gray)
            pygame.draw.circle(surface, COLORS['player_dead'], (x, y), PLAYER_RADIUS)
            return
        
        # Player colors
        player_colors = [
            (255, 255, 0),   # Yellow
            (0, 255, 255),   # Cyan
            (255, 0, 255),   # Magenta
            (0, 255, 0)      # Green
        ]
        color_idx = hash(str(player_id)) % len(player_colors)
        color = player_colors[color_idx]
        
        # Current player border
        if is_current:
            pygame.draw.circle(surface, (255, 255, 255), (x, y), PLAYER_RADIUS + 3, 2)
        
        # Player body
        pygame.draw.circle(surface, color, (x, y), PLAYER_RADIUS)
        
        # Power mode glow
        if player_data.get('power', 0) > 0:
            pygame.draw.circle(surface, (255, 255, 255), (x, y), PLAYER_RADIUS + 5, 2)
        
        # Eyes
        pygame.draw.circle(surface, (0, 0, 0), (x - 5, y - 3), 2)
        pygame.draw.circle(surface, (0, 0, 0), (x + 5, y - 3), 2)

    def draw_ghost(self, surface, ghost_data):
        """Draw simple ghost"""
        x = int(ghost_data['x'] * CELL_SIZE + CELL_SIZE // 2)
        y = int(ghost_data['y'] * CELL_SIZE + CELL_SIZE // 2)
        
        # Ghost colors
        color_map = {
            'red': COLORS['ghost_red'],
            'orange': COLORS['ghost_orange'],
            'purple': COLORS['ghost_purple'],
            'green': COLORS['ghost_green']
        }
        
        color = color_map.get(ghost_data.get('color', 'red'), COLORS['ghost_red'])
        
        # Ghost body
        pygame.draw.circle(surface, color, (x, y), GHOST_RADIUS)
        
        # Simple wavy bottom
        bottom_y = y + GHOST_RADIUS
        points = []
        for i in range(5):
            wave_x = x - GHOST_RADIUS + (i * GHOST_RADIUS // 2)
            wave_y = bottom_y + int(math.sin(time.time() * 5 + i) * 3)
            points.append((wave_x, wave_y))
        
        if len(points) >= 3:
            points = [(x - GHOST_RADIUS, bottom_y)] + points + [(x + GHOST_RADIUS, bottom_y)]
            pygame.draw.polygon(surface, color, points)
        
        # Eyes
        pygame.draw.circle(surface, (255, 255, 255), (x - 6, y - 5), 4)
        pygame.draw.circle(surface, (0, 0, 0), (x - 6, y - 5), 2)
        pygame.draw.circle(surface, (255, 255, 255), (x + 6, y - 5), 4)
        pygame.draw.circle(surface, (0, 0, 0), (x + 6, y - 5), 2)

    def draw_ui(self, surface, data):
        """Draw simple UI"""
        ui_x = CELL_SIZE * 19 + 10
        font_large = pygame.font.Font(None, 32)
        font_medium = pygame.font.Font(None, 24)
        font_small = pygame.font.Font(None, 18)
        
        # UI Background
        ui_rect = pygame.Rect(ui_x - 5, 0, 250, CELL_SIZE * 15)
        pygame.draw.rect(surface, COLORS['ui_background'], ui_rect)
        pygame.draw.rect(surface, COLORS['ui_text'], ui_rect, 2)
        
        y_offset = 20
        
        # Title
        title = font_large.render("PAC-MAN", True, COLORS['ui_text'])
        surface.blit(title, (ui_x, y_offset))
        y_offset += 40
        
        # Room Information
        if self.room_id:
            room_text = font_small.render(f"Room: {self.room_id}", True, COLORS['power_pellet'])
            surface.blit(room_text, (ui_x, y_offset))
        else:
            status_text = font_small.render(self.connection_status, True, COLORS['ui_text'])
            surface.blit(status_text, (ui_x, y_offset))
        y_offset += 25
        
        # Players
        players_title = font_medium.render("PLAYERS", True, COLORS['ui_text'])
        surface.blit(players_title, (ui_x, y_offset))
        y_offset += 30
        
        players = data.get('players', {})
        for i, (player_id, player_data) in enumerate(players.items()):
            # Player indicator
            player_colors = [(255, 255, 0), (0, 255, 255), (255, 0, 255), (0, 255, 0)]
            color_idx = hash(str(player_id)) % len(player_colors)
            color = player_colors[color_idx] if not player_data['dead'] else COLORS['player_dead']
            
            pygame.draw.circle(surface, color, (ui_x + 10, y_offset + 10), 6)
            
            # Player info
            name = player_data.get('name', f'Player {i+1}')
            score = player_data.get('score', 0)
            status = "DEAD" if player_data['dead'] else "ALIVE"
            power = player_data.get('power', 0)
            
            player_text = f"{name}: {score}"
            status_text = f"{status}"
            if power > 0:
                status_text += f" (POWER: {power})"
            
            text1 = font_small.render(player_text, True, COLORS['ui_text'])
            text2 = font_small.render(status_text, True, color)
            
            surface.blit(text1, (ui_x + 25, y_offset))
            surface.blit(text2, (ui_x + 25, y_offset + 15))
            y_offset += 40
        
        # Game Stats
        y_offset += 20
        stats_title = font_medium.render("GAME STATS", True, COLORS['ui_text'])
        surface.blit(stats_title, (ui_x, y_offset))
        y_offset += 30
        
        game_stats = data.get('game_stats', {})
        max_players = game_stats.get('max_players', 2)
        stats = [
            f"Pellets Left: {game_stats.get('total_pellets', 0)}",
            f"Players: {game_stats.get('alive_players', 0)}/{game_stats.get('total_players', 0)}",
            f"Room Capacity: {game_stats.get('total_players', 0)}/{max_players}",
            f"Game Tick: {game_stats.get('game_tick', 0)}"
        ]
        
        for stat in stats:
            stat_text = font_small.render(stat, True, COLORS['ui_text'])
            surface.blit(stat_text, (ui_x, y_offset))
            y_offset += 20
        
        # Victory message
        if game_stats.get('victory', False):
            y_offset += 30
            victory_text = font_large.render("VICTORY!", True, COLORS['power_pellet'])
            surface.blit(victory_text, (ui_x, y_offset))
        
        # Controls
        y_offset = CELL_SIZE * 15 - 100
        controls_title = font_small.render("CONTROLS:", True, COLORS['ui_text'])
        surface.blit(controls_title, (ui_x, y_offset))
        y_offset += 20
        
        controls = [
            "Arrow Keys: Move",
            "R: Restart (when dead)",
            "ESC: Exit"
        ]
        
        for control in controls:
            control_text = font_small.render(control, True, COLORS['ui_text'])
            surface.blit(control_text, (ui_x, y_offset))
            y_offset += 15

    def draw_death_overlay(self, surface, player_data):
        """Draw death overlay"""
        if not player_data or not player_data.get('dead', False):
            return
        
        # Semi-transparent overlay
        overlay = pygame.Surface((CELL_SIZE * 19, CELL_SIZE * 15))
        overlay.set_alpha(128)
        overlay.fill(COLORS['death_overlay'])
        surface.blit(overlay, (0, 0))
        
        # Death message
        font_large = pygame.font.Font(None, 48)
        font_medium = pygame.font.Font(None, 24)
        
        death_text = font_large.render("YOU DIED!", True, COLORS['ui_text'])
        restart_text = font_medium.render("Press R to restart", True, COLORS['ui_text'])
        score_text = font_medium.render(f"Score: {player_data.get('score', 0)}", True, COLORS['pellet'])
        
        # Center the text
        screen_center_x = (CELL_SIZE * 19) // 2
        screen_center_y = (CELL_SIZE * 15) // 2
        
        surface.blit(death_text, (screen_center_x - death_text.get_width() // 2, screen_center_y - 60))
        surface.blit(score_text, (screen_center_x - score_text.get_width() // 2, screen_center_y - 10))
        surface.blit(restart_text, (screen_center_x - restart_text.get_width() // 2, screen_center_y + 40))

    async def handle_input(self, websocket):
        """Handle input"""
        keys_held = set()
        
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return False
                    
                    key_map = {
                        pygame.K_UP: "UP",
                        pygame.K_DOWN: "DOWN",
                        pygame.K_LEFT: "LEFT",
                        pygame.K_RIGHT: "RIGHT",
                        pygame.K_r: "RESTART"
                    }
                    
                    if event.key in key_map:
                        key = key_map[event.key]
                        if key not in keys_held or key == "RESTART":
                            keys_held.add(key)
                            try:
                                await websocket.send(json.dumps({"key": key, "action": "press"}))
                            except websockets.ConnectionClosed:
                                return False
                
                elif event.type == pygame.KEYUP:
                    key_map = {
                        pygame.K_UP: "UP",
                        pygame.K_DOWN: "DOWN",
                        pygame.K_LEFT: "LEFT",
                        pygame.K_RIGHT: "RIGHT"
                    }
                    
                    if event.key in key_map:
                        key = key_map[event.key]
                        if key in keys_held:
                            keys_held.discard(key)
                            try:
                                await websocket.send(json.dumps({"key": key, "action": "release"}))
                            except websockets.ConnectionClosed:
                                return False
            
            await asyncio.sleep(1/60)

    async def game_loop(self, websocket):
        """Main game loop"""
        while True:
            try:
                # Receive game state
                message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                data = json.loads(message)
                
                # Handle room assignment messages
                if data.get("type") == "room_assignment":
                    self.room_id = data.get("room_id")
                    self.connection_status = f"Connected to room {self.room_id}"
                    print(f"Assigned to room: {self.room_id}")
                    continue
                
                self.last_data = data
            except asyncio.TimeoutError:
                data = self.last_data
            except websockets.ConnectionClosed:
                break
            except Exception as e:
                print(f"Game loop error: {e}")
                break
            
            # Clear screen
            self.screen.fill(COLORS['background'])
            
            # Draw game elements
            maze = data.get('maze', [])
            if maze:
                self.draw_maze(self.screen, maze)
            
            # Draw players
            players = data.get('players', {})
            for player_id, player_data in players.items():
                is_current = str(player_id) == str(self.current_player_id)
                self.draw_player(self.screen, player_data, player_id, is_current)
            
            # Draw ghosts
            ghosts = data.get('ghosts', [])
            for ghost_data in ghosts:
                self.draw_ghost(self.screen, ghost_data)
            
            # Draw UI
            self.draw_ui(self.screen, data)
            
            # Draw death overlay
            current_player = players.get(self.current_player_id)
            if current_player:
                self.draw_death_overlay(self.screen, current_player)
            
            # Update display
            pygame.display.flip()
            self.clock.tick(60)

    async def run(self):
        """Main run method"""
        if not self.init_display():
            return
        
        print(f"Connecting to {self.server_url}...")
        
        try:
            async with websockets.connect(self.server_url) as websocket:
                self.current_player_id = id(websocket)
                print(f"Connected to server!")
                
                # Start game tasks
                input_task = asyncio.create_task(self.handle_input(websocket))
                game_task = asyncio.create_task(self.game_loop(websocket))
                
                done, pending = await asyncio.wait(
                    [input_task, game_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                
        except ConnectionRefusedError:
            print(f"Could not connect to server at {self.server_url}")
        except OSError as e:
            print(f"Network error: {e}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            pygame.quit()
            print("Game ended.")

async def main():
    """Main function"""
    print("🎮 Pac-Man Multiplayer Client")
    print("============================")
    
    client = SimpleGameClient()
    
    if len(sys.argv) > 1:
        client.server_url = sys.argv[1]
    
    print(f"Server: {client.server_url}")
    print("Controls: Arrow keys to move, R to restart, ESC to exit")
    
    await client.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGame interrupted.")
    except Exception as e:
        print(f"Fatal error: {e}")