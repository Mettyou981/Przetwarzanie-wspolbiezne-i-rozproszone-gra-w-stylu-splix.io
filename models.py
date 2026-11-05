from enum import Enum
from collections import deque
from settings import GRID_WIDTH, GRID_HEIGHT

"""Matematyka, enumy i logika obiektów"""

class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

class Enemy:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.base = set()
        self.trail = []

class Player:
    def __init__(self, start_x, start_y):
        self.reset(start_x, start_y)

    def reset(self, start_x, start_y):
        # Zabezpieczenie: upewnij się, że pozycja jest wewnątrz mapy z marginesem 1
        # (baza 3x3 wychodzi o 1 pole poza środek, więc potrzebujemy min 1 odstępu od krawędzi)
        start_x = max(1, min(GRID_WIDTH - 2, start_x))
        start_y = max(1, min(GRID_HEIGHT - 2, start_y))
        self.x, self.y = start_x, start_y
        self.direction = Direction.RIGHT
        self._next_dir = Direction.RIGHT
        self.base = {(start_x + dx, start_y + dy) for dx in [-1, 0, 1] for dy in [-1, 0, 1]}
        self.trail = []
        self.is_alive = True
        self.score = 0
        self.base_changed = True
        self.trail_changed = True

    def set_direction(self, new_dir: Direction):
        cx, cy = self.direction.value
        nx, ny = new_dir.value
        if cx + nx != 0 or cy + ny != 0:
            self._next_dir = new_dir

    def move(self):
        if not self.is_alive:
            return

        self.direction = self._next_dir
        old_x, old_y = self.x, self.y
        dx, dy = self.direction.value
        self.x += dx
        self.y += dy

        if not (0 <= self.x < GRID_WIDTH and 0 <= self.y < GRID_HEIGHT):
            self.is_alive = False
            return

        if (self.x, self.y) in self.trail:
            self.is_alive = False
            return

        if (old_x, old_y) not in self.base:
            self.trail.append((old_x, old_y))
            self.trail_changed = True

        if (self.x, self.y) in self.base and self.trail:
            self._fill_territory()

    def _fill_territory(self):
        boundary = self.base | set(self.trail)
        outside = set()
        queue = deque()

        for x in range(GRID_WIDTH):
            for y in [0, GRID_HEIGHT - 1]:
                if (x, y) not in boundary and (x, y) not in outside:
                    outside.add((x, y))
                    queue.append((x, y))
        for y in range(1, GRID_HEIGHT - 1):
            for x in [0, GRID_WIDTH - 1]:
                if (x, y) not in boundary and (x, y) not in outside:
                    outside.add((x, y))
                    queue.append((x, y))

        while queue:
            cx, cy = queue.popleft()
            for ddx, ddy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = cx + ddx, cy + ddy
                if 0 <= nx < GRID_WIDTH and 0 <= ny < GRID_HEIGHT:
                    if (nx, ny) not in outside and (nx, ny) not in boundary:
                        outside.add((nx, ny))
                        queue.append((nx, ny))

        captured = 0
        for x in range(GRID_WIDTH):
            for y in range(GRID_HEIGHT):
                if (x, y) not in outside:
                    if (x, y) not in self.base:
                        captured += 1
                    self.base.add((x, y))

        self.score += captured
        self.trail = []
        self.base_changed = True
        self.trail_changed = True