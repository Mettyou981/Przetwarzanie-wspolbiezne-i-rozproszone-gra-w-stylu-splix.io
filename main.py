import pygame
import sys
from enum import Enum

#Generalnie to mi służyło do testowania jak działa logika gry a dopiero potem robilem server

# LOGIKA GRY (MODEL)


class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)


class Player:
    def __init__(self, start_x, start_y):
        self.x = start_x
        self.y = start_y
        self.direction = Direction.RIGHT

        # Baza startowa - kwadrat 3x3 wokół punktu startowego
        self.base = set()
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                self.base.add((start_x + dx, start_y + dy))

        self.trail = []
        self.is_alive = True

    def set_direction(self, new_direction):
        curr_dx, curr_dy = self.direction.value
        new_dx, new_dy = new_direction.value
        if curr_dx + new_dx != 0 or curr_dy + new_dy != 0:
            self.direction = new_direction

    def move(self, world_width, world_height):
        if not self.is_alive:
            return

        # Zapisujemy starą pozycję
        old_x, old_y = self.x, self.y

        # Przesuwamy głowę
        dx, dy = self.direction.value
        self.x += dx
        self.y += dy

        # 1. Sprawdzenie kolizji ze ścianami
        if self.x < 0 or self.x >= world_width or self.y < 0 or self.y >= world_height:
            self.is_alive = False
            print("Śmierć: Uderzenie w ścianę!")
            return

        # 2. Sprawdzenie kolizji z własnym śladem
        if (self.x, self.y) in self.trail:
            self.is_alive = False
            print("Śmierć: Przeciąłeś własny ogon!")
            return

        # 3. Logika śladu (Trail)
        # Jeśli stara pozycja nie była w bazie, to znaczy, że jesteśmy w terenie
        if (old_x, old_y) not in self.base:
            self.trail.append((old_x, old_y))

        # 4. Powrót do bazy (Zamykanie obwodu)
        if (self.x, self.y) in self.base and len(self.trail) > 0:
            # Zamiast tylko dodawać kreskę, odpalamy nasz algorytm:
            self.fill_territory(world_width, world_height)

    def fill_territory(self, world_width, world_height):
        # 1. Tworzymy tymczasowy "mur", przez który woda nie przejdzie.
        # Składa się on z naszej obecnej bazy i nowo narysowanego ogona.
        new_boundary = self.base.copy()
        for tx, ty in self.trail:
            new_boundary.add((tx, ty))

        # 2. Zbiór 'outside' będzie trzymał wszystkie pola zalane wodą z zewnątrz mapy
        outside = set()
        queue = []  # Kolejka pól, z których woda będzie się dalej rozlewać

        # 3. Dodajemy wszystkie pola na brzegach mapy do kolejki startowej.
        # (Chyba że gracz ma swoją bazę na samym brzegu - tam woda nie wejdzie).
        for x in range(world_width):
            if (x, 0) not in new_boundary:
                queue.append((x, 0))
                outside.add((x, 0))
            if (x, world_height - 1) not in new_boundary:
                queue.append((x, world_height - 1))
                outside.add((x, world_height - 1))

        for y in range(1, world_height - 1):  # od 1 do height-1, żeby nie dublować rogów
            if (0, y) not in new_boundary:
                queue.append((0, y))
                outside.add((0, y))
            if (world_width - 1, y) not in new_boundary:
                queue.append((world_width - 1, y))
                outside.add((world_width - 1, y))

        # 4. ROZLEWANIE WODY (Algorytm BFS - Breadth-First Search)
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]  # góra, dół, lewo, prawo

        while queue:
            cx, cy = queue.pop(0)  # Pobieramy pole z kolejki

            for dx, dy in directions:  # Sprawdzamy 4 sąsiadujące pola
                nx, ny = cx + dx, cy + dy

                # Upewniamy się, że sąsiad mieści się na mapie
                if 0 <= nx < world_width and 0 <= ny < world_height:
                    # Jeśli woda tam jeszcze nie dotarła i nie jest to nasz mur...
                    if (nx, ny) not in outside and (nx, ny) not in new_boundary:
                        outside.add((nx, ny))  # Zalej to pole
                        queue.append((nx, ny))  # Dodaj do kolejki, żeby woda lała się stąd dalej

        # 5. ZAMKNIĘCIE TERYTORIUM
        # Każde pole na mapie, do którego NIE dotarła woda z zewnątrz (czyli nie ma
        # go w zbiorze 'outside'), jest otoczone naszym murem. Dodajemy je do bazy!
        for x in range(world_width):
            for y in range(world_height):
                if (x, y) not in outside:
                    self.base.add((x, y))

        # Na koniec czyścimy ślad, bo został wchłonięty
        self.trail = []

# INTERFEJS GRAFICZNY (PYGAME)

# Ustawienia okna i siatki
CELL_SIZE = 20
GRID_WIDTH = 30
GRID_HEIGHT = 30

# Kolory (RGB)
COLOR_BG = (30, 30, 30)  # Ciemnoszary
COLOR_BASE = (50, 150, 255)  # Niebieski
COLOR_TRAIL = (150, 200, 255)  # Jasnoniebieski
COLOR_HEAD = (255, 50, 50)  # Czerwony
COLOR_DEAD = (100, 100, 100)  # Szary po śmierci


def main():
    pygame.init()
    screen = pygame.display.set_mode((GRID_WIDTH * CELL_SIZE, GRID_HEIGHT * CELL_SIZE))
    pygame.display.set_caption("Splix.io - Prototyp")
    clock = pygame.time.Clock()

    # Tworzymy gracza na środku mapy
    player = Player(GRID_WIDTH // 2, GRID_HEIGHT // 2)

    # Zmienne do kontrolowania "tyknięć" logiki (np. 10 ruchów na sekundę)
    TICK_EVENT = pygame.USEREVENT + 1
    pygame.time.set_timer(TICK_EVENT, 150)  # 150 milisekund = prędkość gry

    running = True
    while running:
        # 1. OBSŁUGA ZDARZEŃ (Klawiatura itp.)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # Reakcja na strzałki
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    player.set_direction(Direction.UP)
                elif event.key == pygame.K_DOWN:
                    player.set_direction(Direction.DOWN)
                elif event.key == pygame.K_LEFT:
                    player.set_direction(Direction.LEFT)
                elif event.key == pygame.K_RIGHT:
                    player.set_direction(Direction.RIGHT)

            # Aktualizacja logiki gry (co 150ms)
            elif event.type == TICK_EVENT:
                player.move(GRID_WIDTH, GRID_HEIGHT)

        # 2. RYSOWANIE
        screen.fill(COLOR_BG)

        # Rysowanie bazy
        for bx, by in player.base:
            pygame.draw.rect(screen, COLOR_BASE, (bx * CELL_SIZE, by * CELL_SIZE, CELL_SIZE, CELL_SIZE))

        # Rysowanie śladu (ogona)
        for tx, ty in player.trail:
            pygame.draw.rect(screen, COLOR_TRAIL, (tx * CELL_SIZE, ty * CELL_SIZE, CELL_SIZE, CELL_SIZE))

        # Rysowanie głowy (zmienia kolor jak zginiesz)
        head_color = COLOR_HEAD if player.is_alive else COLOR_DEAD
        pygame.draw.rect(screen, head_color, (player.x * CELL_SIZE, player.y * CELL_SIZE, CELL_SIZE, CELL_SIZE))

        # Rysowanie siatki (opcjonalne, ale pomaga)
        for x in range(0, GRID_WIDTH * CELL_SIZE, CELL_SIZE):
            pygame.draw.line(screen, (50, 50, 50), (x, 0), (x, GRID_HEIGHT * CELL_SIZE))
        for y in range(0, GRID_HEIGHT * CELL_SIZE, CELL_SIZE):
            pygame.draw.line(screen, (50, 50, 50), (0, y), (GRID_WIDTH * CELL_SIZE, y))

        pygame.display.flip()
        clock.tick(60)  # 60 klatek na sekundę (dla płynności okna)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()