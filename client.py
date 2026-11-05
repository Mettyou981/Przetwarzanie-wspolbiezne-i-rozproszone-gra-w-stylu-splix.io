import pygame
import sys
import socket
from enum import Enum
from settings import *
from models import Player, Enemy, Direction

class GameState(Enum):
    MENU = 1
    PLAYING = 2
    GAMEOVER = 3

def draw_text(screen, text, size, x, y, color=COLOR_TEXT, center=True):
    font = pygame.font.SysFont("Arial", size, bold=True)
    surf = font.render(text, True, color)
    rect = surf.get_rect()
    if center:
        rect.center = (x, y)
    else:
        rect.topleft = (x, y)
    screen.blit(surf, rect)

def cell_rect(cx, cy, off_x, off_y):
    return (cx * CELL_SIZE - off_x, cy * CELL_SIZE - off_y, CELL_SIZE, CELL_SIZE)

def main():
    SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    SERVER_PORT = 5000

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption(f"Splix.io – Multiplayer ({SERVER_IP})")
    clock = pygame.time.Clock()

    state = GameState.MENU
    player_name = ""
    player = Player(-100, -100)
    my_id = -1
    enemies: dict[int, Enemy] = {}

    print(f"Łączenie z serwerem: {SERVER_IP}:{SERVER_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((SERVER_IP, SERVER_PORT))
        sock.setblocking(False)
        print("Połączono!")
    except ConnectionRefusedError:
        print(f"Błąd: Serwer na {SERVER_IP} nie odpowiada!")
        pygame.quit()
        sys.exit()
        
    TICK_EVENT = pygame.USEREVENT + 1
    pygame.time.set_timer(TICK_EVENT, 150)

    net_buf = ""

    def send(msg: str):
        try:
            sock.setblocking(True)
            sock.sendall((msg + "\n").encode())
            sock.setblocking(False)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def process_server_line(line: str):
        nonlocal my_id, state

        if line == "DEAD":
            state = GameState.GAMEOVER
            player.is_alive = False
            player.base.clear()
            player.trail.clear()

        elif line.startswith("WELCOME|"):
            # Format: WELCOME|<id>:<x>,<y>
            parts = line[8:].split(":")
            my_id = int(parts[0])
            sx, sy = map(int, parts[1].split(","))
            player.reset(sx, sy)

            state = GameState.PLAYING  # Zmiana stanu następuje bezpiecznie DOPIERO TUTAJ!
            player.is_alive = True

        elif line.startswith("STATE|"):
            # POPRAWKA: Przetwarzanie pozycji wraz z autorytatywnym wynikiem z serwera
            # Format: STATE|<id>:<x>,<y>,<score>|<id>:<x>,<y>,<score>|...
            tokens = line[6:].split("|")
            seen_ids = set()
            for tok in tokens:
                if not tok:
                    continue
                pid_str, coord = tok.split(":")
                pid = int(pid_str)
                
                coord_parts = coord.split(",")
                if len(coord_parts) >= 3:
                    try:
                        ex, ey = int(coord_parts[0]), int(coord_parts[1])
                        escore = int(coord_parts[2])
                        
                        if pid == my_id:
                            player.score = escore  # Aktualizuj nasz wynik z serwera
                        else:
                            if pid not in enemies:
                                enemies[pid] = Enemy(ex, ey)
                            else:
                                enemies[pid].x, enemies[pid].y = ex, ey
                            seen_ids.add(pid)
                    except ValueError:
                        pass

            for dead in list(enemies.keys()):
                if dead not in seen_ids:
                    del enemies[dead]

        elif line.startswith("BASE|"):
            # POPRAWKA: Akceptujemy pakiety bazy również dla nas samych (synchronizacja po stracie pola)
            # Format: BASE|<pid>|<x>,<y>;<x>,<y>;...
            parts = line.split("|")
            pid = int(parts[1])
            valid_base = set()
            if len(parts) > 2:
                for c in parts[2].split(";"):
                    if c:
                        pair = c.split(",")
                        if len(pair) == 2:
                            try:
                                valid_base.add((int(pair[0]), int(pair[1])))
                            except ValueError:
                                pass
            
            if pid == my_id:
                player.base = valid_base  # Serwer nam uciął pole -> aktualizujemy nasz zestaw!
            elif pid in enemies:
                enemies[pid].base = valid_base

        elif line.startswith("TRAIL|"):
            parts = line.split("|")
            pid = int(parts[1])
            if pid in enemies and len(parts) > 2:
                valid_trail = []
                for c in parts[2].split(";"):
                    if c:
                        pair = c.split(",")
                        if len(pair) == 2:
                            try:
                                valid_trail.append((int(pair[0]), int(pair[1])))
                            except ValueError:
                                pass
                enemies[pid].trail = valid_trail

        elif line.startswith("KILL|"):
            victim = int(line[5:])
            if victim in enemies:
                del enemies[victim]

    # ================================================================== #
    running = True
    while running:

        try:
            data = sock.recv(65536).decode("utf-8", errors="ignore")
            net_buf += data
        except BlockingIOError:
            pass
        except Exception:
            pass

        while "\n" in net_buf:
            line, net_buf = net_buf.split("\n", 1)
            line = line.strip()
            if line:
                process_server_line(line)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if state == GameState.MENU:
                    if event.key == pygame.K_RETURN and player_name.strip():
                        send(f"JOIN|{player_name.strip()}")
                        # Usunięto: state = GameState.PLAYING (czekamy na WELCOME!)
                    elif event.key == pygame.K_BACKSPACE:
                        player_name = player_name[:-1]
                    elif len(player_name) < 16 and event.unicode.isprintable():
                        player_name += event.unicode

                elif state == GameState.PLAYING:
                    if event.key == pygame.K_UP or event.key == pygame.K_w:
                        player.set_direction(Direction.UP)
                    elif event.key == pygame.K_DOWN or event.key == pygame.K_s:
                        player.set_direction(Direction.DOWN)
                    elif event.key == pygame.K_LEFT or event.key == pygame.K_a:
                        player.set_direction(Direction.LEFT)
                    elif event.key == pygame.K_RIGHT or event.key == pygame.K_d:
                        player.set_direction(Direction.RIGHT)

                elif state == GameState.GAMEOVER:
                    if event.key == pygame.K_r:
                        send("RESET")
                    elif event.key == pygame.K_ESCAPE:
                        state = GameState.MENU

            elif event.type == TICK_EVENT and state == GameState.PLAYING:
                player.move()

                if not player.is_alive:
                    state = GameState.GAMEOVER

                send(f"MOVE {player.direction.name}")

                if player.base_changed:
                    b_str = ";".join(f"{x},{y}" for x, y in player.base)
                    send(f"MYBASE|{b_str}")
                    player.base_changed = False

                if player.trail_changed:
                    t_str = ";".join(f"{x},{y}" for x, y in player.trail)
                    send(f"MYTRAIL|{t_str}")
                    player.trail_changed = False

        # --- RYSOWANIE ---
        screen.fill(COLOR_BG)

        if state == GameState.MENU:
            for x in range(0, SCREEN_WIDTH, CELL_SIZE):
                pygame.draw.line(screen, COLOR_GRID, (x, 0), (x, SCREEN_HEIGHT))
            for y in range(0, SCREEN_HEIGHT, CELL_SIZE):
                pygame.draw.line(screen, COLOR_GRID, (0, y), (0 + SCREEN_WIDTH, y))

            draw_text(screen, "SPLIX.IO", 72, SCREEN_WIDTH // 2, 160, COLOR_BASE)
            draw_text(screen, "Multiplayer", 30, SCREEN_WIDTH // 2, 230, (100, 150, 220))

            box_rect = pygame.Rect(SCREEN_WIDTH // 2 - 180, 290, 360, 50)
            pygame.draw.rect(screen, (40, 40, 60), box_rect, border_radius=8)
            pygame.draw.rect(screen, COLOR_BASE, box_rect, 2, border_radius=8)
            display_name = player_name + ("_" if (pygame.time.get_ticks() // 500) % 2 == 0 else " ")
            draw_text(screen, display_name or "Wpisz nazwę...", 28,
                      SCREEN_WIDTH // 2, 316,
                      COLOR_TEXT if player_name else (80, 80, 100))

            draw_text(screen, "ENTER – dołącz do gry", 22, SCREEN_WIDTH // 2, 380, (150, 150, 200))
            draw_text(screen, "Sterowanie: strzałki lub WASD", 18, SCREEN_WIDTH // 2, 415, (100, 100, 150))

        elif state == GameState.PLAYING:
            off_x = player.x * CELL_SIZE - SCREEN_WIDTH // 2
            off_y = player.y * CELL_SIZE - SCREEN_HEIGHT // 2

            start_cx = max(0, off_x // CELL_SIZE)
            start_cy = max(0, off_y // CELL_SIZE)
            end_cx = min(GRID_WIDTH, (off_x + SCREEN_WIDTH) // CELL_SIZE + 2)
            end_cy = min(GRID_HEIGHT, (off_y + SCREEN_HEIGHT) // CELL_SIZE + 2)

            for gx in range(start_cx, end_cx):
                sx = gx * CELL_SIZE - off_x
                pygame.draw.line(screen, COLOR_GRID, (sx, 0), (sx, SCREEN_HEIGHT))
            for gy in range(start_cy, end_cy):
                sy = gy * CELL_SIZE - off_y
                pygame.draw.line(screen, COLOR_GRID, (0, sy), (SCREEN_WIDTH, sy))

            border_rect = (-off_x, -off_y, GRID_WIDTH * CELL_SIZE, GRID_HEIGHT * CELL_SIZE)
            pygame.draw.rect(screen, COLOR_BORDER, border_rect, 3)

            # --- 1. WARSTWA: BAZY ---
            for en in enemies.values():
                for bx, by in en.base:
                    r = cell_rect(bx, by, off_x, off_y)
                    if -CELL_SIZE < r[0] < SCREEN_WIDTH and -CELL_SIZE < r[1] < SCREEN_HEIGHT:
                        pygame.draw.rect(screen, COLOR_ENEMY_BASE, r)
                        
            for bx, by in player.base:
                r = cell_rect(bx, by, off_x, off_y)
                if -CELL_SIZE < r[0] < SCREEN_WIDTH and -CELL_SIZE < r[1] < SCREEN_HEIGHT:
                    pygame.draw.rect(screen, COLOR_BASE, r)
                    pygame.draw.rect(screen, (30, 100, 200), r, 1)

            # --- 2. WARSTWA: OGONY ---
            for en in enemies.values():
                for tx, ty in en.trail:
                    r = cell_rect(tx, ty, off_x, off_y)
                    if -CELL_SIZE < r[0] < SCREEN_WIDTH and -CELL_SIZE < r[1] < SCREEN_HEIGHT:
                        pygame.draw.rect(screen, COLOR_ENEMY_TRAIL, r)
                        
            for tx, ty in player.trail:
                r = cell_rect(tx, ty, off_x, off_y)
                if -CELL_SIZE < r[0] < SCREEN_WIDTH and -CELL_SIZE < r[1] < SCREEN_HEIGHT:
                    pygame.draw.rect(screen, COLOR_TRAIL, r)

            # --- 3. WARSTWA: GŁOWY ---
            for en in enemies.values():
                r = cell_rect(en.x, en.y, off_x, off_y)
                pygame.draw.rect(screen, COLOR_ENEMY_HEAD, r)
                
            in_base = (player.x, player.y) in player.base
            head_color = COLOR_HEAD_SAFE if in_base else COLOR_HEAD
            hr = cell_rect(player.x, player.y, off_x, off_y)
            pygame.draw.rect(screen, head_color, hr)

            # HUD (Wyświetla autorytatywny player.score przeliczony przez serwer)
            base_pct = int(len(player.base) / (GRID_WIDTH * GRID_HEIGHT) * 100)
            pygame.draw.rect(screen, (0, 0, 0, 160), (0, 0, SCREEN_WIDTH, 30))
            draw_text(screen,
                      f"Terytorium: {base_pct}%  |  Gracze online: {len(enemies) + 1}  |  Zdobyte: {player.score}",
                      20, 10, 15, COLOR_TEXT, center=False)

        elif state == GameState.GAMEOVER:
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((10, 10, 20, 200))
            screen.blit(overlay, (0, 0))

            draw_text(screen, "GAME OVER", 80, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 80, COLOR_BORDER)
            base_pct = int(len(player.base) / (GRID_WIDTH * GRID_HEIGHT) * 100)
            draw_text(screen, f"Terytorium: {base_pct}%   Zdobyte pola: {player.score}",
                      28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, COLOR_TEXT)
            draw_text(screen, "R – zagraj ponownie    ESC – menu",
                      22, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 60, (180, 180, 180))

        pygame.display.flip()
        clock.tick(60)

    sock.close()
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()