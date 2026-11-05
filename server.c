/*
 *
 * Kompilacja:
 * gcc server.c -o server -lpthread -O2
 *
 * Uruchomienie:
 * ./server
 */

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <pthread.h>
#include <time.h>

/* ================================================================== */
#define MAX_CLIENTS   64
#define BUFFER_SIZE   8192
#define EVENT_ACTION_SIZE 131072
#define BASE_BUF_SIZE 131072
#define TRAIL_BUF_SIZE 32768
#define GRID_W        100
#define GRID_H        100
#define TICK_US       150000

/* ================================================================== */
/* Struktura klienta */
typedef struct {
    int  fd;
    int  id;
    int  active;
    int is_alive;
    int  x, y;
    char name[64];
    char base [BASE_BUF_SIZE];
    char trail[TRAIL_BUF_SIZE];
    pthread_mutex_t send_mutex;
} Client;

static Client       clients[MAX_CLIENTS];
static pthread_mutex_t clients_mutex = PTHREAD_MUTEX_INITIALIZER;

/* ================================================================== */
/* Kolejka zdarzeń */
typedef struct {
    int  client_id;
    char action[EVENT_ACTION_SIZE]; 
} Event;

#define QUEUE_SIZE 256
static Event            event_queue[QUEUE_SIZE];
static int              queue_head = 0, queue_tail = 0;
static pthread_mutex_t  queue_mutex = PTHREAD_MUTEX_INITIALIZER;

void print_server_ip();

/* ================================================================== */
static int alloc_client_slot(void) {
    for (int i = 0; i < MAX_CLIENTS; i++)
        if (!clients[i].active) return i;
    return -1;
}

/* Bezpieczna wysyłka do jednego klienta */
static void client_send(Client *c, const char *msg) {
    if (!c->active) return;
    pthread_mutex_lock(&c->send_mutex);
    send(c->fd, msg, strlen(msg), MSG_NOSIGNAL);
    pthread_mutex_unlock(&c->send_mutex);
}

/* Rozgłaszanie do wszystkich aktywnych klientów */
static void broadcast(const char *msg) {
    pthread_mutex_lock(&clients_mutex);
    for (int i = 0; i < MAX_CLIENTS; i++)
        if (clients[i].active)
            client_send(&clients[i], msg);
    pthread_mutex_unlock(&clients_mutex);
}

/* Rozgłaszanie z pominięciem jednego klienta */
static void broadcast_except(const char *msg, int skip_id) {
    pthread_mutex_lock(&clients_mutex);
    for (int i = 0; i < MAX_CLIENTS; i++)
        if (clients[i].active && i != skip_id)
            client_send(&clients[i], msg);
    pthread_mutex_unlock(&clients_mutex);
}

/* ================================================================== */
static void enqueue(int client_id, const char *action) {
    pthread_mutex_lock(&queue_mutex);
    int next = (queue_tail + 1) % QUEUE_SIZE;
    if (next != queue_head) {
        event_queue[queue_tail].client_id = client_id;
        strncpy(event_queue[queue_tail].action, action, EVENT_ACTION_SIZE - 1);
        event_queue[queue_tail].action[EVENT_ACTION_SIZE - 1] = '\0';
        queue_tail = next;
    }
    pthread_mutex_unlock(&queue_mutex);
}

/* ================================================================== */
/* POMOCNICZE FUNKCJE DO WYNIKÓW I ODBIERANIA PÓL */
/* ================================================================== */

/* Zlicza kafelki bazy (na podstawie średników), określając wynik */
static int get_client_score(const char *base) {
    int count = 0;
    if (!base || !*base) return 0;
    for (int i = 0; base[i] != '\0'; i++) {
        if (base[i] == ';') count++;
    }
    return count;
}

/* Usuwa podany kafelek (np. "10,20") z bazy danego gracza */
static void remove_cell_from_base(char *base, const char *cell) {
    if (!base || !*base || !cell || !*cell) return;
    size_t clen = strlen(cell);
    char *p = base;
    while ((p = strstr(p, cell)) != NULL) {
        if (p != base && p[-1] != ';') { p++; continue; }
        char after = p[clen];
        if (after != ';' && after != '\0') { p++; continue; }
        
        size_t delete_len = clen;
        if (after == ';') {
            delete_len++;
        }
        size_t rest_len = strlen(p + delete_len);
        memmove(p, p + delete_len, rest_len + 1);
    }
}

/* Sprawdza obecność kafelka w bazie danych gracza */
static int contains_cell(const char *haystack, const char *needle) {
    if (!haystack || !*haystack || !needle) return 0;
    const char *p = haystack;
    size_t nlen = strlen(needle);
    while ((p = strstr(p, needle)) != NULL) {
        if (p != haystack && p[-1] != ';') { p++; continue; }
        char after = p[nlen];
        if (after != '\0' && after != ';') { p++; continue; }
        return 1;
    }
    return 0;
}

/* ================================================================== */
/* Wątek obsługi jednego połączenia */
static void *connection_handler(void *arg) {
    int id = *(int *)arg;
    free(arg);

    Client *c = &clients[id];
    char buf[BUFFER_SIZE];
    char net_buf[EVENT_ACTION_SIZE * 2];
    int  net_len = 0;

    pthread_mutex_lock(&clients_mutex);
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (clients[i].active && clients[i].is_alive && i != id) {
            if (strlen(clients[i].base) > 0) {
                char base_msg[BASE_BUF_SIZE + 32];
                snprintf(base_msg, sizeof(base_msg), "BASE|%d|%s\n", i, clients[i].base);
                client_send(c, base_msg);
            }
            if (strlen(clients[i].trail) > 0) {
                char trail_msg[TRAIL_BUF_SIZE + 32];
                snprintf(trail_msg, sizeof(trail_msg), "TRAIL|%d|%s\n", i, clients[i].trail);
                client_send(c, trail_msg);
            }
        }
    }
    pthread_mutex_unlock(&clients_mutex);

    int read_size;
    while ((read_size = recv(c->fd, buf, sizeof(buf) - 1, 0)) > 0) {
        buf[read_size] = '\0';

        int remaining = (int)sizeof(net_buf) - net_len - 1;
        if (read_size > remaining) read_size = remaining;
        memcpy(net_buf + net_len, buf, read_size);
        net_len += read_size;
        net_buf[net_len] = '\0';

        char *line_start = net_buf;
        char *newline;
        while ((newline = memchr(line_start, '\n', net_buf + net_len - line_start)) != NULL) {
            *newline = '\0';
            if (newline > line_start)
                enqueue(id, line_start);
            line_start = newline + 1;
        }

        int leftover = (int)(net_buf + net_len - line_start);
        if (leftover > 0)
            memmove(net_buf, line_start, leftover);
        net_len = leftover;
    }

    pthread_mutex_lock(&clients_mutex);
    c->active = 0;
    c->is_alive = 0;
    c->base[0] = '\0';
    c->trail[0] = '\0';
    close(c->fd);
    pthread_mutex_unlock(&clients_mutex);

    char kill_msg[64];
    snprintf(kill_msg, sizeof(kill_msg), "KILL|%d\n", id);
    broadcast_except(kill_msg, id);

    printf("Gracz %d (%s) rozłączył się.\n", id, c->name);
    return NULL;
}

/* Buduje startową bazę 3x3 wokół (cx, cy) w formacie "x,y;x,y;..." */
static void build_start_base(char *buf, size_t bufsz, int cx, int cy) {
    buf[0] = '\0';
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            int bx = cx + dx, by = cy + dy;
            if (bx < 0 || bx >= GRID_W || by < 0 || by >= GRID_H) continue;
            char tmp[32];
            snprintf(tmp, sizeof(tmp), "%d,%d;", bx, by);
            strncat(buf, tmp, bufsz - strlen(buf) - 1);
        }
    }
    /* Usuń końcowy średnik jeśli istnieje */
    size_t len = strlen(buf);
    if (len > 0 && buf[len - 1] == ';') buf[len - 1] = '\0';
}

/* ================================================================== */
static void *game_loop(void *arg) {
    (void)arg;

    while (1) {
        /* --- Przetwarzanie kolejki zdarzeń --- */
        pthread_mutex_lock(&queue_mutex);
        while (queue_head != queue_tail) {
            Event ev = event_queue[queue_head];
            queue_head = (queue_head + 1) % QUEUE_SIZE;
            pthread_mutex_unlock(&queue_mutex);

            int id = ev.client_id;
            pthread_mutex_lock(&clients_mutex);
            if (!clients[id].active) {
                pthread_mutex_unlock(&clients_mutex);
                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            if (!clients[id].is_alive && strcmp(ev.action, "RESET") !=0 && strncmp(ev.action, "JOIN|",5) !=0){
                pthread_mutex_unlock(&clients_mutex);
                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            /* Ruch */
            if      (strcmp(ev.action, "MOVE UP")    == 0) clients[id].y--;
            else if (strcmp(ev.action, "MOVE DOWN")  == 0) clients[id].y++;
            else if (strcmp(ev.action, "MOVE LEFT")  == 0) clients[id].x--;
            else if (strcmp(ev.action, "MOVE RIGHT") == 0) clients[id].x++;

            /* Granice mapy */
            if (clients[id].x < 0 || clients[id].x >= GRID_W || clients[id].y < 0 || clients[id].y >= GRID_H) {
                clients[id].is_alive = 0;
                /* Cofnij gracza do bezpiecznej pozycji w środku mapy,
                   żeby stan był spójny zanim przyjdzie RESET od klienta */
                clients[id].x = GRID_W / 2;
                clients[id].y = GRID_H / 2;
                clients[id].base[0] = '\0';
                clients[id].trail[0] = '\0';

                client_send(&clients[id], "DEAD\n");

                char kill_msg[64];
                snprintf(kill_msg, sizeof(kill_msg), "KILL|%d\n", id);
                for (int k = 0; k < MAX_CLIENTS; k++) {
                    if (clients[k].active && k != id)
                        client_send(&clients[k], kill_msg);
                }

                printf("Gracz %d (%s) rozbił się o ścianę i został usunięty z mapy.\n", id, clients[id].name);
                pthread_mutex_unlock(&clients_mutex);
                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            /* POPRAWIONA LOGIKA: Baza gracza oraz odbieranie pól przeciwnikom */
            /* POPRAWKA BŁĘDU: Ultraszybki algorytm obsługi pól i kradzieży terytoriów O(N) */
            else if (strncmp(ev.action, "MYBASE|", 7) == 0) {
                strncpy(clients[id].base, ev.action + 7, BASE_BUF_SIZE - 1);
                clients[id].base[BASE_BUF_SIZE - 1] = '\0';

                // 1. Zbuduj mapę 2D zajętych pól przez tego gracza, by uniknąć setek tysięcy przeszukiwań stringa
                int agg_grid[GRID_W][GRID_H] = {0};
                const char *p = clients[id].base;

                while (*p) {
                    int x = atoi(p);
                    while (*p && *p != ',') p++;
                    if (*p == ',') p++;
                    int y = atoi(p);
                    while (*p && *p != ';') p++;
                    if (*p == ';') p++;

                    if (x >= 0 && x < GRID_W && y >= 0 && y < GRID_H) {
                        agg_grid[x][y] = 1;
                    }
                }

                int updated_others[MAX_CLIENTS] = {0};

                // 2. Przeskanuj bazy innych graczy w jednym przejściu
                for (int k = 0; k < MAX_CLIENTS; k++) {
                    if (clients[k].active && clients[k].is_alive && k != id) {
                        if (strlen(clients[k].base) == 0) continue;

                        char new_base[BASE_BUF_SIZE];
                        char *dest = new_base;
                        int updated = 0;

                        const char *rp = clients[k].base;
                        while (*rp) {
                            const char *start = rp;
                            int x = atoi(rp);
                            while (*rp && *rp != ',') rp++;
                            if (*rp == ',') rp++;
                            int y = atoi(rp);
                            while (*rp && *rp != ';') rp++;
                            if (*rp == ';') rp++;

                            int tlen = rp - start;

                            if (x >= 0 && x < GRID_W && y >= 0 && y < GRID_H && agg_grid[x][y]) {
                                // To pole leży na siatce agresora! Pomijamy kopiowanie (czyli kradniemy je ofierze).
                                updated = 1;
                            } else {
                                // Bezpieczne pole, przepisz do nowej bazy
                                memcpy(dest, start, tlen);
                                dest += tlen;
                            }
                        }
                        *dest = '\0';

                        if (updated) {
                            strcpy(clients[k].base, new_base);
                            updated_others[k] = 1;
                        }
                    }
                }

                char base_msg[BASE_BUF_SIZE + 32];
                snprintf(base_msg, sizeof(base_msg), "BASE|%d|%s\n", id, clients[id].base);
                pthread_mutex_unlock(&clients_mutex);

                broadcast_except(base_msg, id);

                for (int k = 0; k < MAX_CLIENTS; k++) {
                    if (updated_others[k]) {
                        char other_base_msg[BASE_BUF_SIZE + 32];
                        pthread_mutex_lock(&clients_mutex);
                        snprintf(other_base_msg, sizeof(other_base_msg), "BASE|%d|%s\n", k, clients[k].base);
                        pthread_mutex_unlock(&clients_mutex);
                        broadcast(other_base_msg);
                    }
                }

                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            /* Obsługa ogona gracza (MYTRAIL) */
            else if (strncmp(ev.action, "MYTRAIL|", 8) == 0) {
                strncpy(clients[id].trail, ev.action + 8, TRAIL_BUF_SIZE - 1);
                clients[id].trail[TRAIL_BUF_SIZE - 1] = '\0';

                char trail_msg[TRAIL_BUF_SIZE + 32];
                snprintf(trail_msg, sizeof(trail_msg),
                         "TRAIL|%d|%s\n", id, clients[id].trail);

                pthread_mutex_unlock(&clients_mutex);
                broadcast_except(trail_msg, id);
                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            /* Dołączenie (nazwa gracza) - WEJŚCIE Z MENU DO GRY */
            else if (strncmp(ev.action, "JOIN|", 5) == 0) {
                strncpy(clients[id].name, ev.action + 5, 63);
                clients[id].name[63] = '\0';
                printf("Gracz %d dołączył z menu jako \"%s\"\n", id, clients[id].name);

                clients[id].is_alive = 1;
                clients[id].x = (rand() % (GRID_W - 40)) + 20;
                clients[id].y = (rand() % (GRID_H - 40)) + 20;
                memset(clients[id].trail, 0, TRAIL_BUF_SIZE);
                memset(clients[id].base,  0, BASE_BUF_SIZE);
                build_start_base(clients[id].base, BASE_BUF_SIZE,
                                 clients[id].x, clients[id].y);

                char welcome[128];
                snprintf(welcome, sizeof(welcome),
                         "WELCOME|%d:%d,%d\n", id, clients[id].x, clients[id].y);

                char base_init[BASE_BUF_SIZE + 32];
                snprintf(base_init, sizeof(base_init), "BASE|%d|%s\n", id, clients[id].base);

                pthread_mutex_unlock(&clients_mutex);
                client_send(&clients[id], welcome);

                broadcast(base_init);

                char empty_trail[64];
                snprintf(empty_trail, sizeof(empty_trail), "TRAIL|%d|\n", id);
                broadcast_except(empty_trail, id);

                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            /* Reset po śmierci */
            else if (strcmp(ev.action, "RESET") == 0) {
                clients[id].is_alive = 1;
                clients[id].x = (rand() % (GRID_W - 40)) + 20;
                clients[id].y = (rand() % (GRID_H - 40)) + 20;
                memset(clients[id].trail, 0, TRAIL_BUF_SIZE);
                memset(clients[id].base,  0, BASE_BUF_SIZE);
                build_start_base(clients[id].base, BASE_BUF_SIZE,
                                 clients[id].x, clients[id].y);

                char welcome[128];
                snprintf(welcome, sizeof(welcome),
                         "WELCOME|%d:%d,%d\n", id, clients[id].x, clients[id].y);

                char base_init[BASE_BUF_SIZE + 32];
                snprintf(base_init, sizeof(base_init), "BASE|%d|%s\n", id, clients[id].base);

                pthread_mutex_unlock(&clients_mutex);
                client_send(&clients[id], welcome);

                broadcast(base_init);

                char empty_trail[64];
                snprintf(empty_trail, sizeof(empty_trail), "TRAIL|%d|\n", id);
                broadcast_except(empty_trail, id);

                pthread_mutex_lock(&queue_mutex);
                continue;
            }

            pthread_mutex_unlock(&clients_mutex);
            pthread_mutex_lock(&queue_mutex);
        }
        pthread_mutex_unlock(&queue_mutex);

        /* --- Detekcja kolizji --- */
        pthread_mutex_lock(&clients_mutex);
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (!clients[i].active || !clients[i].is_alive) continue;

            char head[32];
            snprintf(head, sizeof(head), "%d,%d", clients[i].x, clients[i].y);

            for (int j = 0; j < MAX_CLIENTS; j++) {
                if (!clients[j].active || !clients[j].is_alive) continue;
                if (strlen(clients[j].trail) == 0) continue;

                if (contains_cell(clients[j].trail, head)) {
                    clients[j].is_alive = 0;
                    clients[j].base[0] = '\0';
                    clients[j].trail[0] = '\0';

                    client_send(&clients[j], "DEAD\n");

                    char kill_msg[64];
                    snprintf(kill_msg, sizeof(kill_msg), "KILL|%d\n", j);
                    for (int k = 0; k < MAX_CLIENTS; k++)
                        if (clients[k].active)
                            client_send(&clients[k], kill_msg);

                    printf("Gracz %d (%s) zginął od ataku gracza %d (%s)\n",
                           j, clients[j].name, i, clients[i].name);
                    if (i == j) break;
                }
            }
        }
        pthread_mutex_unlock(&clients_mutex);

        /* --- Rozgłaszanie stanu (Z UWZGLĘDNIENIEM WYNIKU Z SERWERA) --- */
        {
            char *state_msg = malloc(MAX_CLIENTS * 48 + 16);
            if (state_msg) {
                strcpy(state_msg, "STATE|");
                pthread_mutex_lock(&clients_mutex);
                for (int i = 0; i < MAX_CLIENTS; i++) {
                    if (!clients[i].active || !clients[i].is_alive) continue;
                    
                    char temp[48];
                    int score = get_client_score(clients[i].base); // Serwer sam liczy punkty
                    snprintf(temp, sizeof(temp), "%d:%d,%d,%d|", i, clients[i].x, clients[i].y, score);
                    strcat(state_msg, temp);
                }
                pthread_mutex_unlock(&clients_mutex);
                strcat(state_msg, "\n");
                broadcast(state_msg);
                free(state_msg);
            }
        }

        usleep(TICK_US);
    }
    return NULL;
}

/* ================================================================== */
int main(void) {
    srand((unsigned)time(NULL));

    for (int i = 0; i < MAX_CLIENTS; i++) {
        memset(&clients[i], 0, sizeof(clients[i]));
        pthread_mutex_init(&clients[i].send_mutex, NULL);
        clients[i].id = i;
    }

    int listenfd = socket(AF_INET, SOCK_STREAM, 0);
    if (listenfd < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(listenfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(5000),
        .sin_addr.s_addr = htonl(INADDR_ANY)
    };
    if (bind(listenfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); return 1;
    }
    listen(listenfd, 16);

    print_server_ip();

    pthread_t game_tid;
    pthread_create(&game_tid, NULL, game_loop, NULL);

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);
        int conn = accept(listenfd, (struct sockaddr *)&client_addr, &addr_len);
        if (conn < 0) continue;

        pthread_mutex_lock(&clients_mutex);
        int slot = alloc_client_slot();
        if (slot < 0) {
            pthread_mutex_unlock(&clients_mutex);
            send(conn, "FULL\n", 5, 0);
            close(conn);
            continue;
        }

        clients[slot].fd     = conn;
        clients[slot].active = 1;
        clients[slot].is_alive = 0;
        memset(clients[slot].name,  0, sizeof(clients[slot].name));
        memset(clients[slot].base,  0, BASE_BUF_SIZE);
        memset(clients[slot].trail, 0, TRAIL_BUF_SIZE);
        snprintf(clients[slot].name, sizeof(clients[slot].name), "Gracz%d", slot);
        pthread_mutex_unlock(&clients_mutex);

        printf("Nowy gracz: slot %d, IP %s\n", slot, inet_ntoa(client_addr.sin_addr));

        int *id_ptr = malloc(sizeof(int));
        *id_ptr = slot;
        pthread_t tid;
        pthread_create(&tid, NULL, connection_handler, id_ptr);
        pthread_detach(tid);
    }

    return 0;
}

void print_server_ip() {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) return;

    struct sockaddr_in serv;
    memset(&serv, 0, sizeof(serv));
    serv.sin_family = AF_INET;
    serv.sin_addr.s_addr = inet_addr("8.8.8.8");
    serv.sin_port = htons(53);

    int err = connect(sock, (const struct sockaddr*)&serv, sizeof(serv));
    if (err == 0) {
        struct sockaddr_in name;
        socklen_t namelen = sizeof(name);
        err = getsockname(sock, (struct sockaddr*)&name, &namelen);
        if (err == 0) {
            printf("\n========================================================\n");
            printf("  SERWER SPLIX.IO JEST GOTOWY!\n");
            printf("  python client.py %s\n", inet_ntoa(name.sin_addr));
            printf("========================================================\n\n");
        }
    } else {
        printf("Serwer nasłuchuje na porcie 5000...\n");
    }
    close(sock);
}