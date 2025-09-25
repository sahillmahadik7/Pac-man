# client/renderer.py
import pygame

WIDTH, HEIGHT = 640, 480

COLORS = {
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
}

def init():
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Distributed Pac-Man")
    players = []  # or some initial player objects
    return screen, players


def draw(screen, players):
    """Draw all players on the screen."""
    screen.fill((0, 0, 0))  # Clear screen
    for p in players:
        color = COLORS.get(p["color"], (255, 255, 255))
        pygame.draw.circle(screen, color, (int(p["x"]), int(p["y"])), 15)
    pygame.display.flip()
