import flet as ft
import sqlite3
import random
import time
import threading
import os
from datetime import datetime

# ============================================================
# БАЗА ДАННЫХ
# ============================================================

# ✅ Абсолютный путь — база всегда рядом со скриптом (работает и на GitHub)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zing.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS friendships (id TEXT PRIMARY KEY, user1 TEXT NOT NULL, user2 TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS friend_requests (id TEXT PRIMARY KEY, from_id TEXT NOT NULL, from_name TEXT NOT NULL, to_id TEXT NOT NULL, status TEXT DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_by TEXT NOT NULL, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS group_members (group_id TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY (group_id, user_id));
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, from_id TEXT NOT NULL, sender_name TEXT, text TEXT NOT NULL, timestamp INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL, from_id TEXT NOT NULL, sender_name TEXT, text TEXT NOT NULL, timestamp INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS contact_names (owner_id TEXT NOT NULL, contact_id TEXT NOT NULL, custom_name TEXT NOT NULL, PRIMARY KEY (owner_id, contact_id));
    CREATE TABLE IF NOT EXISTS user_settings (user_id TEXT PRIMARY KEY, font_size REAL DEFAULT 14, compact INTEGER DEFAULT 0, accent TEXT DEFAULT 'violet', notifications INTEGER DEFAULT 1);
    """)
    c.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in c.fetchall()]
    if "password" not in columns:
        c.execute("ALTER TABLE users ADD COLUMN password TEXT DEFAULT ''")
    conn.commit()
    conn.close()

def gen_six_digit():
    return str(random.randint(100000, 999999))

def create_unique_id(conn):
    for _ in range(50):
        uid = gen_six_digit()
        cur = conn.execute("SELECT 1 FROM users WHERE id=?", (uid,))
        if not cur.fetchone():
            return uid
    raise Exception("Нет свободных ID")

def friendship_id(a, b):
    return f"{a}_{b}" if a < b else f"{b}_{a}"

def chat_id(a, b):
    return f"{a}_{b}" if a < b else f"{b}_{a}"

def now_ms():
    return int(time.time() * 1000)

# ============================================================
# ЦВЕТА / СТИЛЬ (ОРИГИНАЛ)
# ============================================================

BG = "#0a0a0a"
SIDEBAR_BG = "#121212"
PANEL_BG = "#181818"
CARD_BG = "#1a1a1a"
CARD_BORDER = "#2a2a2a"
INPUT_BG = "#1e1e1e"
INPUT_BORDER = "#2e2e2e"
TEXT = "#e0e0e0"
MUTED = "#9ca3af"
ACCENT_1 = "#667eea"
ACCENT_2 = "#764ba2"
GREEN = "#10b981"
RED = "#dc2626"
RED_LIGHT = "#ef4444"
BLUE = "#3b82f6"
PURPLE_LIGHT = "#a5b4fc"
PURPLE_2 = "#c084fc"

GLASS_HI = "#ffffff14"
GLASS_BORDER = "#ffffff1f"

ACCENTS = {
    "violet": ("#667eea", "#764ba2"),
    "blue":   ("#3b82f6", "#06b6d4"),
    "green":  ("#10b981", "#059669"),
    "pink":   ("#ec4899", "#8b5cf6"),
    "orange": ("#f97316", "#ef4444"),
}

def gradient(a1=None, a2=None):
    a1 = a1 or ACCENT_1
    a2 = a2 or ACCENT_2
    return ft.LinearGradient(
        begin=ft.alignment.top_left,
        end=ft.alignment.bottom_right,
        colors=[a1, a2],
    )

# ============================================================
# ПРИЛОЖЕНИЕ
# ============================================================

def main(page: ft.Page):
    page.title = "Zing Messenger"
    page.bgcolor = BG
    page.padding = 0
    page.window_width = 1000
    page.window_height = 720

    def is_mobile():
        try:
            return (page.width or 1000) < 720
        except Exception:
            return False

    state = {
        "user": None,
        "current_chat": None,
        "contact_names": {},
        "editing_group_id": None,
        "editing_contact": None,
        "hash_friends": None,
        "hash_requests": None,
        "hash_groups": None,
        "settings": {"font_size": 14, "compact": 0, "accent": "violet", "notifications": 1},
        "show_settings": False,
        "mobile_view": "sidebar",
    }
    poller_token = {"n": 0}
    poll_state = {"last_ts": 0, "last_key": None}

    conn = get_db()
    init_db()

    # ========================================================
    # ЭКРАН АВТОРИЗАЦИИ
    # ========================================================

    username_input = ft.TextField(
        hint_text="Ваше имя", bgcolor=INPUT_BG, border_color=INPUT_BORDER,
        color="white", border_radius=16, text_size=16, content_padding=14,
    )
    password_input = ft.TextField(
        hint_text="Пароль", password=True, can_reveal_password=True,
        bgcolor=INPUT_BG, border_color=INPUT_BORDER, color="white",
        border_radius=16, text_size=16, content_padding=14,
    )
    warning_text = ft.Text("", color="white", size=13, visible=False)

    def show_warning(msg):
        warning_text.value = msg
        warning_text.visible = True
        page.update()
        def hide():
            time.sleep(3)
            warning_text.visible = False
            try: page.update()
            except Exception: pass
        threading.Thread(target=hide, daemon=True).start()

    def do_login(e):
        name = (username_input.value or "").strip()
        password = (password_input.value or "").strip()
        if len(name) < 2:
            show_warning("Введите имя (минимум 2 символа)!")
            return
        if len(password) < 3:
            show_warning("Введите пароль (минимум 3 символа)!")
            return
        try:
            row = conn.execute("SELECT id, password FROM users WHERE name=?", (name,)).fetchone()
            if row is None:
                uid = create_unique_id(conn)
                conn.execute("INSERT INTO users(id,name,password) VALUES(?,?,?)", (uid, name, password))
                conn.commit()
                user_id = uid
            else:
                db_password = row["password"] or ""
                if db_password == "":
                    conn.execute("UPDATE users SET password=? WHERE id=?", (password, row["id"]))
                    conn.commit()
                elif db_password != password:
                    show_warning("Неверный пароль!")
                    return
                user_id = row["id"]

            state["user"] = {"id": user_id, "name": name}
            rows = conn.execute("SELECT contact_id, custom_name FROM contact_names WHERE owner_id=?", (user_id,)).fetchall()
            state["contact_names"] = {r["contact_id"]: r["custom_name"] for r in rows}

            srow = conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
            if srow:
                state["settings"] = {
                    "font_size": srow["font_size"], "compact": srow["compact"],
                    "accent": srow["accent"], "notifications": srow["notifications"],
                }
            else:
                conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (user_id,))
                conn.commit()
            show_main_screen()
        except Exception as ex:
            show_warning("Ошибка: " + str(ex))

    auth_screen = ft.Container(
        expand=True, bgcolor=BG, alignment=ft.alignment.center,
        content=ft.Container(
            width=360, bgcolor=PANEL_BG,
            border=ft.border.all(1, "#2d2d2d"),
            border_radius=28,
            padding=ft.padding.symmetric(vertical=40, horizontal=24),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=18,
                controls=[
                    ft.Icon(ft.Icons.CHAT_BUBBLE_ROUNDED, size=40, color=PURPLE_LIGHT),
                    ft.Text("Zing Messenger", size=26, weight=ft.FontWeight.BOLD, color=PURPLE_LIGHT),
                    username_input,
                    password_input,
                    ft.Container(
                        bgcolor=gradient(), border_radius=40,
                        padding=ft.padding.symmetric(vertical=14),
                        alignment=ft.alignment.center, width=340,
                        on_click=do_login,
                        content=ft.Text("Войти / Зарегистрироваться", color="white", weight=ft.FontWeight.BOLD, size=16),
                    ),
                    warning_text,
                ],
            ),
        ),
    )

    # ========================================================
    # ГЛАВНЫЙ ЭКРАН
    # ========================================================

    main_screen = ft.Container(expand=True, visible=False)

    profile_name_text = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=PURPLE_LIGHT)
    profile_id_text = ft.Text("", size=12, color=MUTED, font_family="monospace")

    def do_logout(e):
        poller_token["n"] += 1
        poll_state["last_ts"] = 0
        poll_state["last_key"] = None
        state["user"] = None
        state["current_chat"] = None
        state["contact_names"] = {}
        state["hash_friends"] = None
        state["hash_requests"] = None
        state["hash_groups"] = None
        state["show_settings"] = False
        main_screen.visible = False
        auth_screen.visible = True
        username_input.value = ""
        password_input.value = ""
        page.update()

    def open_settings(e):
        state["show_settings"] = True
        render_settings()
        apply_layout()
        page.update()

    profile_card = ft.Container(
        bgcolor=PANEL_BG, padding=16,
        content=ft.Column(spacing=8, controls=[
            profile_name_text,
            ft.Container(
                bgcolor=INPUT_BG, border_radius=40,
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                content=profile_id_text,
            ),
            ft.Row(spacing=8, controls=[
                ft.Container(
                    expand=True, bgcolor="#2a2a2a", border_radius=40,
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    on_click=lambda e: open_edit_my_name(),
                    content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=4, controls=[
                        ft.Icon(ft.Icons.EDIT_ROUNDED, size=12, color="#aaa"),
                        ft.Text("Имя", size=12, color="#aaa"),
                    ]),
                ),
                ft.Container(
                    expand=True, bgcolor="#2a2a2a", border_radius=40,
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    on_click=open_settings,
                    content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=4, controls=[
                        ft.Icon(ft.Icons.SETTINGS_ROUNDED, size=12, color="#aaa"),
                        ft.Text("Настройки", size=12, color="#aaa"),
                    ]),
                ),
            ]),
        ]),
    )

    # ---------- поиск ----------
    search_input = ft.TextField(
        hint_text="000000", max_length=6,
        bgcolor=INPUT_BG, border_color=INPUT_BORDER, color="white",
        border_radius=28, text_size=16, text_align=ft.TextAlign.CENTER,
        expand=True, content_padding=10,
    )
    search_result_box = ft.Container(visible=False, bgcolor=CARD_BG, border_radius=20, padding=10)

    def do_search(e):
        sid = (search_input.value or "").strip()
        if len(sid) != 6:
            show_notification("Введите 6 цифр")
            return
        if sid == state["user"]["id"]:
            show_notification("Это вы")
            return
        row = conn.execute("SELECT name FROM users WHERE id=?", (sid,)).fetchone()
        if not row:
            search_result_box.content = ft.Row(spacing=6, controls=[
                ft.Icon(ft.Icons.ERROR_OUTLINE_ROUNDED, size=16, color=RED_LIGHT),
                ft.Text("Не найден", color=TEXT),
            ])
            search_result_box.visible = True
            page.update()
            return
        real_name = row["name"]
        fid = friendship_id(state["user"]["id"], sid)
        is_friend = conn.execute("SELECT 1 FROM friendships WHERE id=?", (fid,)).fetchone() is not None
        if is_friend:
            search_result_box.content = ft.Row(spacing=6, controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=16, color=GREEN),
                ft.Text("Уже в друзьях", color=TEXT),
            ])
        else:
            search_result_box.content = ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(spacing=0, controls=[
                        ft.Text(real_name, weight=ft.FontWeight.BOLD, color=TEXT),
                        ft.Text(sid, size=10, color=MUTED),
                    ]),
                    ft.Container(
                        bgcolor=BLUE, border_radius=40,
                        padding=ft.padding.symmetric(horizontal=14, vertical=6),
                        on_click=lambda e, sid=sid: send_friend_request(sid),
                        content=ft.Row(spacing=4, controls=[
                            ft.Icon(ft.Icons.PERSON_ADD_ROUNDED, size=14, color="white"),
                            ft.Text("Добавить", color="white", size=12),
                        ]),
                    ),
                ],
            )
        search_result_box.visible = True
        page.update()

    def send_friend_request(to_id):
        u = state["user"]
        exists = conn.execute(
            "SELECT 1 FROM friend_requests WHERE from_id=? AND to_id=? AND status='pending'",
            (u["id"], to_id),
        ).fetchone()
        if exists:
            show_notification("Заявка уже отправлена")
            return
        rid = f"{now_ms()}_{random.randint(1000, 9999)}"
        try:
            conn.execute(
                "INSERT INTO friend_requests(id,from_id,from_name,to_id,status) VALUES(?,?,?,?,?)",
                (rid, u["id"], u["name"], to_id, "pending"),
            )
            conn.commit()
        except Exception as ex:
            show_notification("Ошибка: " + str(ex))
            return
        show_notification("Заявка отправлена")
        search_result_box.visible = False
        search_input.value = ""
        page.update()

    search_section = ft.Container(
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        content=ft.Column(spacing=8, controls=[
            ft.Row(spacing=6, controls=[
                ft.Icon(ft.Icons.SEARCH_ROUNDED, size=14, color=MUTED),
                ft.Text("Найти друга по ID", size=13, color=MUTED),
            ]),
            ft.Row(spacing=8, controls=[
                search_input,
                ft.Container(
                    bgcolor=GREEN, border_radius=28,
                    padding=ft.padding.symmetric(horizontal=16, vertical=10),
                    on_click=do_search,
                    content=ft.Icon(ft.Icons.SEARCH_ROUNDED, size=18, color="white"),
                ),
            ]),
            search_result_box,
        ]),
    )

    # ---------- вкладки ----------
    friends_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    groups_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    requests_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    tab_content_chats = ft.Container(content=friends_list, visible=True, expand=True, padding=12)
    tab_content_groups = ft.Container(visible=False, expand=True, padding=12)
    tab_content_requests = ft.Container(content=requests_list, visible=False, expand=True, padding=12)

    def make_tab_btn(icon, label, key):
        return ft.Container(
            expand=True, padding=ft.padding.symmetric(vertical=8),
            alignment=ft.alignment.center,
            on_click=lambda e, k=key: switch_tab(k),
            content=ft.Column(spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(icon, size=16, color=MUTED),
                ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=MUTED),
            ]),
        )

    tab_btn_chats = make_tab_btn(ft.Icons.CHAT_ROUNDED, "Чаты", "chats")
    tab_btn_groups = make_tab_btn(ft.Icons.GROUPS_ROUNDED, "Группы", "groups")
    tab_btn_requests = make_tab_btn(ft.Icons.MAIL_ROUNDED, "Заявки", "requests")
    tabs_header = ft.Row(spacing=4, controls=[tab_btn_chats, tab_btn_groups, tab_btn_requests])

    def switch_tab(key):
        tab_content_chats.visible = key == "chats"
        tab_content_groups.visible = key == "groups"
        tab_content_requests.visible = key == "requests"
        for btn, k in [(tab_btn_chats, "chats"), (tab_btn_groups, "groups"), (tab_btn_requests, "requests")]:
            c = PURPLE_LIGHT if k == key else MUTED
            btn.content.controls[0].color = c
            btn.content.controls[1].color = c
        page.update()

    switch_tab("chats")

    def open_create_group(e):
        open_group_modal(edit_id=None)

    create_group_btn = ft.Container(
        bgcolor=gradient(), border_radius=40, padding=10,
        alignment=ft.alignment.center, on_click=open_create_group,
        content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=6, controls=[
            ft.Icon(ft.Icons.ADD_ROUNDED, size=14, color="white"),
            ft.Text("Создать группу", color="white", weight=ft.FontWeight.BOLD, size=13),
        ]),
    )

    tab_content_groups.content = ft.Column(spacing=8, controls=[create_group_btn, groups_list], expand=True)

    sidebar = ft.Container(
        width=320, bgcolor=SIDEBAR_BG,
        border=ft.border.only(right=ft.BorderSide(1, "#2a2a2a")),
        content=ft.Column(spacing=0, expand=True, controls=[
            profile_card, search_section,
            ft.Container(bgcolor=SIDEBAR_BG, padding=ft.padding.only(left=12, right=12, top=8), content=tabs_header),
            ft.Container(expand=True, content=ft.Stack(expand=True, controls=[
                tab_content_chats, tab_content_groups, tab_content_requests,
            ])),
        ]),
    )

    # ========================================================
    # СПИСКИ
    # ========================================================

    def make_friend_item(fid, real_name, display):
        return ft.Container(
            bgcolor=CARD_BG, border=ft.border.all(1, CARD_BORDER),
            border_radius=16, padding=ft.padding.symmetric(horizontal=14, vertical=12),
            on_click=lambda e: open_private_chat(fid, display),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Column(spacing=3, controls=[
                        ft.Text(display, weight=ft.FontWeight.BOLD, size=14, color=TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(fid, size=10, color=MUTED),
                    ], expand=True),
                    ft.Row(spacing=0, controls=[
                        ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, icon_size=14, icon_color=PURPLE_LIGHT,
                                      on_click=lambda e, fid=fid, rn=real_name: open_edit_contact(fid, rn), tooltip="Ред."),
                        ft.IconButton(icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_size=14, icon_color="#f87171",
                                      on_click=lambda e, fid=fid, dn=display: delete_friend(fid, dn), tooltip="Удалить"),
                    ]),
                ],
            ),
        )

    def hash_friends_now():
        u = state["user"]
        rows = conn.execute("SELECT * FROM friendships WHERE user1=? OR user2=?", (u["id"], u["id"])).fetchall()
        ids = [r["user2"] if r["user1"] == u["id"] else r["user1"] for r in rows]
        return tuple(sorted(ids))

    def load_friends():
        u = state["user"]
        rows = conn.execute("SELECT * FROM friendships WHERE user1=? OR user2=?", (u["id"], u["id"])).fetchall()
        friend_ids = [r["user2"] if r["user1"] == u["id"] else r["user1"] for r in rows]
        friends_list.controls.clear()
        if not friend_ids:
            friends_list.controls.append(ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=6, controls=[
                ft.Icon(ft.Icons.PEOPLE_OUTLINE_ROUNDED, size=16, color="#6b7280"),
                ft.Text("Нет друзей", color="#6b7280"),
            ]))
        for fid in friend_ids:
            r = conn.execute("SELECT name FROM users WHERE id=?", (fid,)).fetchone()
            real_name = r["name"] if r else fid
            display = state["contact_names"].get(fid, real_name)
            friends_list.controls.append(make_friend_item(fid, real_name, display))
        try: page.update()
        except Exception: pass

    def delete_friend(fid, display):
        fid_pair = friendship_id(state["user"]["id"], fid)
        conn.execute("DELETE FROM friendships WHERE id=?", (fid_pair,))
        cid = chat_id(state["user"]["id"], fid)
        conn.execute("DELETE FROM messages WHERE chat_id=?", (cid,))
        conn.commit()
        if state["current_chat"] and state["current_chat"]["type"] == "private" and state["current_chat"]["id"] == fid:
            close_chat()
        show_notification("Контакт удален")
        state["hash_friends"] = None
        load_friends()

    def hash_requests_now():
        u = state["user"]
        rows = conn.execute("SELECT * FROM friend_requests WHERE to_id=? AND status='pending'", (u["id"],)).fetchall()
        return tuple(sorted((r["id"], r["from_name"]) for r in rows))

    def load_requests():
        u = state["user"]
        rows = conn.execute("SELECT * FROM friend_requests WHERE to_id=? AND status='pending'", (u["id"],)).fetchall()
        requests_list.controls.clear()
        if not rows:
            requests_list.controls.append(ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=6, controls=[
                ft.Icon(ft.Icons.MAIL_OUTLINE_ROUNDED, size=16, color="#6b7280"),
                ft.Text("Нет входящих заявок", color="#6b7280"),
            ]))
        for r in rows:
            requests_list.controls.append(ft.Container(
                bgcolor=CARD_BG, border=ft.border.all(1, CARD_BORDER),
                border_radius=16, padding=ft.padding.symmetric(horizontal=14, vertical=12),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(spacing=0, controls=[
                            ft.Text(r["from_name"], weight=ft.FontWeight.BOLD, size=14, color=TEXT),
                            ft.Text(r["from_id"], size=10, color=MUTED),
                        ]),
                        ft.Row(spacing=6, controls=[
                            ft.Container(bgcolor=GREEN, border_radius=30,
                                         padding=ft.padding.symmetric(horizontal=12, vertical=5),
                                         on_click=lambda e, rid=r["id"], f=r["from_id"], fn=r["from_name"]: accept_request(rid, f, fn),
                                         content=ft.Text("Принять", color="white", size=11, weight=ft.FontWeight.BOLD)),
                            ft.Container(bgcolor=RED_LIGHT, border_radius=30,
                                         padding=ft.padding.symmetric(horizontal=12, vertical=5),
                                         on_click=lambda e, rid=r["id"]: reject_request(rid),
                                         content=ft.Text("Отклонить", color="white", size=11, weight=ft.FontWeight.BOLD)),
                        ]),
                    ],
                ),
            ))
        try: page.update()
        except Exception: pass

    def accept_request(rid, from_id, from_name):
        conn.execute("UPDATE friend_requests SET status='accepted' WHERE id=?", (rid,))
        fid = friendship_id(state["user"]["id"], from_id)
        a, b = sorted([state["user"]["id"], from_id])
        conn.execute("INSERT OR IGNORE INTO friendships(id,user1,user2) VALUES(?,?,?)", (fid, a, b))
        conn.commit()
        show_notification(f"Друзья с {from_name}")
        state["hash_requests"] = None
        state["hash_friends"] = None
        load_requests()
        load_friends()

    def reject_request(rid):
        conn.execute("UPDATE friend_requests SET status='rejected' WHERE id=?", (rid,))
        conn.commit()
        state["hash_requests"] = None
        load_requests()

    def hash_groups_now():
        u = state["user"]
        rows = conn.execute(
            """SELECT g.id, g.name, (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id=g.id) AS cnt
               FROM groups g JOIN group_members m ON m.group_id=g.id WHERE m.user_id=?""",
            (u["id"],),
        ).fetchall()
        return tuple(sorted((g["id"], g["name"], g["cnt"]) for g in rows))

    def load_groups():
        u = state["user"]
        rows = conn.execute(
            """SELECT g.*, (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id=g.id) AS cnt
               FROM groups g JOIN group_members m ON m.group_id=g.id WHERE m.user_id=?""",
            (u["id"],),
        ).fetchall()
        groups_list.controls.clear()
        if not rows:
            groups_list.controls.append(ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=6, controls=[
                ft.Icon(ft.Icons.GROUPS_OUTLINE_ROUNDED, size=16, color="#6b7280"),
                ft.Text("Нет групп", color="#6b7280"),
            ]))
        for g in rows:
            groups_list.controls.append(ft.Container(
                bgcolor=CARD_BG, border=ft.border.all(1, CARD_BORDER),
                border_radius=16, padding=ft.padding.symmetric(horizontal=14, vertical=12),
                on_click=lambda e, gid=g["id"], gn=g["name"]: open_group_chat(gid, gn),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Column(spacing=3, controls=[
                            ft.Text(g["name"], weight=ft.FontWeight.BOLD, size=14, color=TEXT),
                            ft.Text(f"{g['cnt']} уч.", size=10, color=MUTED),
                        ], expand=True),
                        ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, icon_size=14, icon_color=PURPLE_LIGHT,
                                      on_click=lambda e, gid=g["id"], gn=g["name"]: open_group_modal(edit_id=(gid, gn))),
                    ],
                ),
            ))
        try: page.update()
        except Exception: pass

    # ========================================================
    # ОБЛАСТЬ ЧАТА
    # ========================================================

    chat_header_text = ft.Text("Выберите чат", size=16, weight=ft.FontWeight.BOLD, color=TEXT)
    edit_contact_btn = ft.IconButton(icon=ft.Icons.EDIT_ROUNDED, icon_size=18, icon_color=PURPLE_2,
                                      visible=False, tooltip="Ред.",
                                      on_click=lambda e: open_edit_contact_from_chat())
    group_members_btn = ft.IconButton(icon=ft.Icons.GROUPS_ROUNDED, icon_size=18, icon_color=PURPLE_2,
                                       visible=False, tooltip="Участники",
                                       on_click=lambda e: show_group_members())
    back_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_size=20, icon_color=PURPLE_LIGHT,
                              visible=False, tooltip="Назад",
                              on_click=lambda e: go_back_to_sidebar())

    def go_back_to_sidebar():
        state["mobile_view"] = "sidebar"
        apply_layout()
        page.update()

    chat_header = ft.Container(
        bgcolor=SIDEBAR_BG,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border=ft.border.only(bottom=ft.BorderSide(1, "#2a2a2a")),
        content=ft.Row(spacing=12, controls=[
            back_btn, chat_header_text, ft.Container(expand=True),
            group_members_btn, edit_contact_btn,
        ]),
    )

    messages_col = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
    empty_messages = ft.Column(
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
        controls=[
            ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, size=48, color="#3a3a4a"),
            ft.Text("Выберите чат", color="#6b7280", size=14),
        ],
    )
    messages_area = ft.Container(expand=True, bgcolor="#0f0f0f", padding=16, content=empty_messages)

    msg_input = ft.TextField(
        hint_text="Сообщение...",
        bgcolor=INPUT_BG, border_color=INPUT_BORDER, color="white",
        border_radius=40, text_size=14, expand=True,
        content_padding=ft.padding.symmetric(horizontal=16, vertical=10),
        shift_enter=True,
    )

    def on_msg_keyboard(e: ft.KeyboardEvent):
        if e.key == "Enter" and not e.shift:
            send_message()
    msg_input.on_keyboard = on_msg_keyboard

    def do_send(e):
        send_message()

    msg_input_area = ft.Container(
        visible=False, bgcolor=SIDEBAR_BG,
        padding=ft.padding.symmetric(horizontal=16, vertical=10),
        border=ft.border.only(top=ft.BorderSide(1, "#2a2a2a")),
        content=ft.Row(spacing=10, controls=[
            msg_input,
            ft.Container(
                width=44, height=44, border_radius=22,
                bgcolor=gradient(), alignment=ft.alignment.center,
                on_click=do_send,
                content=ft.Icon(ft.Icons.SEND_ROUNDED, size=20, color="white"),
            ),
        ]),
    )

    chat_area = ft.Container(
        expand=True, bgcolor="#0f0f0f",
        content=ft.Column(spacing=0, expand=True, controls=[chat_header, messages_area, msg_input_area]),
    )

    def append_message(msg, is_group):
        is_sent = msg["from_id"] == state["user"]["id"]
        t = datetime.fromtimestamp(msg["timestamp"] / 1000).strftime("%H:%M")
        font_size = state["settings"]["font_size"]

        if is_group and not is_sent:
            sender = msg.get("sender_name") or msg["from_id"]
            text_ctrl = ft.RichText(spans=[
                ft.TextSpan(f"{sender}: ", style=ft.TextStyle(size=font_size - 3, weight=ft.FontWeight.BOLD)),
                ft.TextSpan(msg["text"], style=ft.TextStyle(size=font_size)),
            ])
        else:
            text_ctrl = ft.Text(msg["text"], size=font_size)

        bubble = ft.Container(
            bgcolor=gradient() if is_sent else "#202020",
            border=ft.border.all(1, "#ffffff22" if is_sent else GLASS_BORDER),
            border_radius=ft.border_radius.only(
                top_left=20, top_right=20,
                bottom_left=20 if is_sent else 4,
                bottom_right=4 if is_sent else 20,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            width=min(380, (page.width or 600) * 0.72),
            content=ft.Column(spacing=4, controls=[
                text_ctrl,
                ft.Text(t, size=8, color="white" if is_sent else MUTED),
            ]),
        )
        wrapper = ft.Row(
            alignment=ft.MainAxisAlignment.END if is_sent else ft.MainAxisAlignment.START,
            controls=[bubble],
        )
        messages_col.controls.append(wrapper)
        messages_col.auto_scroll = True

    def show_empty_messages(text="Нет сообщений"):
        messages_col.controls.clear()
        messages_col.controls.append(ft.Row(alignment=ft.MainAxisAlignment.CENTER,
                                              controls=[ft.Text(text, color="#6b7280")]))

    def close_chat():
        state["current_chat"] = None
        poll_state["last_key"] = None
        poll_state["last_ts"] = 0
        chat_header_text.value = "Выберите чат"
        edit_contact_btn.visible = False
        group_members_btn.visible = False
        msg_input_area.visible = False
        messages_col.controls.clear()
        messages_area.content = empty_messages
        page.update()

    def open_private_chat(fid, display_name):
        state["current_chat"] = {"type": "private", "id": fid, "name": display_name}
        chat_header_text.value = display_name
        edit_contact_btn.visible = True
        group_members_btn.visible = False
        msg_input_area.visible = True
        messages_area.content = messages_col
        messages_col.controls.clear()
        cid = chat_id(state["user"]["id"], fid)
        rows = conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp", (cid,)).fetchall()
        if not rows:
            show_empty_messages("Нет сообщений")
        else:
            for r in rows:
                append_message(dict(r), is_group=False)
        poll_state["last_key"] = ("private", fid)
        poll_state["last_ts"] = now_ms()
        if is_mobile():
            state["mobile_view"] = "chat"
            apply_layout()
        page.update()

    def open_group_chat(gid, gname):
        state["current_chat"] = {"type": "group", "id": gid, "name": gname}
        chat_header_text.value = gname
        edit_contact_btn.visible = False
        group_members_btn.visible = True
        msg_input_area.visible = True
        messages_area.content = messages_col
        messages_col.controls.clear()
        rows = conn.execute("SELECT * FROM group_messages WHERE group_id=? ORDER BY timestamp", (gid,)).fetchall()
        if not rows:
            show_empty_messages("Нет сообщений")
        else:
            for r in rows:
                append_message(dict(r), is_group=True)
        poll_state["last_key"] = ("group", gid)
        poll_state["last_ts"] = now_ms()
        if is_mobile():
            state["mobile_view"] = "chat"
            apply_layout()
        page.update()

    def send_message():
        chat = state["current_chat"]
        if not chat:
            return
        text = (msg_input.value or "").strip()
        if not text:
            return
        u = state["user"]
        ts = now_ms()
        if chat["type"] == "private":
            cid = chat_id(u["id"], chat["id"])
            conn.execute(
                "INSERT INTO messages(chat_id,from_id,sender_name,text,timestamp) VALUES(?,?,?,?,?)",
                (cid, u["id"], u["name"], text, ts),
            )
        else:
            conn.execute(
                "INSERT INTO group_messages(group_id,from_id,sender_name,text,timestamp) VALUES(?,?,?,?,?)",
                (chat["id"], u["id"], u["name"], text, ts),
            )
        conn.commit()
        msg_input.value = ""

        msg = {"from_id": u["id"], "sender_name": u["name"], "text": text, "timestamp": ts}
        append_message(msg, is_group=(chat["type"] == "group"))

        poll_state["last_ts"] = max(poll_state["last_ts"], ts)
        poll_state["last_key"] = (chat["type"], chat["id"])

        page.update()

    # ========================================================
    # ГРУППЫ
    # ========================================================

    group_name_input = ft.TextField(hint_text="Название", bgcolor="#2c2c2e",
                                     border_color="#3a3a3c", color="white", border_radius=24)
    group_members_select = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, height=200)
    group_modal_title = ft.Text("Создать группу", size=18, weight=ft.FontWeight.BOLD, color=TEXT)

    def close_group_modal():
        group_modal.visible = False
        state["editing_group_id"] = None
        page.update()

    def open_group_modal(edit_id=None):
        if edit_id:
            gid, gname = edit_id
            state["editing_group_id"] = gid
            group_modal_title.value = "Редактировать группу"
            group_name_input.value = gname
            group_members_select.controls = [ft.Text("Измените название и сохраните", color="#6b7280")]
        else:
            state["editing_group_id"] = None
            group_modal_title.value = "Создать группу"
            group_name_input.value = ""
            u = state["user"]
            rows = conn.execute("SELECT * FROM friendships WHERE user1=? OR user2=?", (u["id"], u["id"])).fetchall()
            friend_ids = [r["user2"] if r["user1"] == u["id"] else r["user1"] for r in rows]
            group_members_select.controls.clear()
            group_members_select.controls.append(ft.Text("Выберите друзей:", size=12, color=MUTED))
            if not friend_ids:
                group_members_select.controls.append(ft.Text("Нет друзей для добавления", color="#6b7280"))
            for fid in friend_ids:
                r = conn.execute("SELECT name FROM users WHERE id=?", (fid,)).fetchone()
                name = r["name"] if r else fid
                group_members_select.controls.append(ft.Checkbox(label=f"{name} ({fid})", value=False, data=fid))
        group_modal.visible = True
        page.update()

    def save_group(e):
        name = (group_name_input.value or "").strip()
        if not name:
            show_notification("Введите название")
            return
        u = state["user"]
        if state["editing_group_id"]:
            conn.execute("UPDATE groups SET name=? WHERE id=?", (name, state["editing_group_id"]))
            conn.commit()
            show_notification("Группа обновлена")
            if state["current_chat"] and state["current_chat"]["type"] == "group" and state["current_chat"]["id"] == state["editing_group_id"]:
                chat_header_text.value = name
            state["hash_groups"] = None
        else:
            gid = f"g{now_ms()}_{random.randint(100, 999)}"
            conn.execute("INSERT INTO groups(id,name,created_by,created_at) VALUES(?,?,?,?)", (gid, name, u["id"], now_ms()))
            conn.execute("INSERT INTO group_members(group_id,user_id) VALUES(?,?)", (gid, u["id"]))
            for c in group_members_select.controls:
                if isinstance(c, ft.Checkbox) and c.value:
                    conn.execute("INSERT OR IGNORE INTO group_members(group_id,user_id) VALUES(?,?)", (gid, c.data))
            conn.commit()
            show_notification("Группа создана")
            state["hash_groups"] = None
        close_group_modal()
        load_groups()

    group_modal = ft.Container(
        visible=False, expand=True, bgcolor="#000000cc", alignment=ft.alignment.center,
        content=ft.Container(
            width=340, bgcolor="#1c1c1e", border_radius=28, padding=24,
            content=ft.Column(spacing=16, controls=[
                group_modal_title, group_name_input, group_members_select,
                ft.Row(spacing=10, controls=[
                    ft.Container(expand=True, bgcolor=GREEN, border_radius=60, padding=10, alignment=ft.alignment.center,
                                 on_click=save_group,
                                 content=ft.Text("Создать", color="white", weight=ft.FontWeight.BOLD)),
                    ft.Container(expand=True, bgcolor=RED, border_radius=60, padding=10, alignment=ft.alignment.center,
                                 on_click=lambda e: close_group_modal(),
                                 content=ft.Text("Отмена", color="white", weight=ft.FontWeight.BOLD)),
                ]),
            ]),
        ),
    )

    def show_group_members():
        chat = state["current_chat"]
        if not chat or chat["type"] != "group":
            return
        rows = conn.execute("SELECT user_id FROM group_members WHERE group_id=?", (chat["id"],)).fetchall()
        lines = ["Участники:"]
        for r in rows:
            uid = r["user_id"]
            urow = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
            nm = urow["name"] if urow else uid
            suf = " (Вы)" if uid == state["user"]["id"] else ""
            lines.append(f"• {nm} ({uid}){suf}")
        show_notification(" | ".join(lines))

    # ========================================================
    # РЕДАКТИРОВАНИЕ ИМЕНИ
    # ========================================================

    edit_name_input = ft.TextField(bgcolor="#2c2c2e", border_color="#3a3a3c", color="white", border_radius=24)
    edit_modal_title = ft.Text("Редактировать", size=18, weight=ft.FontWeight.BOLD, color=TEXT)

    def close_edit_modal():
        edit_modal.visible = False
        page.update()

    def open_edit_my_name():
        state["editing_contact"] = None
        edit_modal_title.value = "Ваше имя"
        edit_name_input.value = state["user"]["name"]
        edit_modal.visible = True
        page.update()

    def open_edit_contact(fid, real_name):
        state["editing_contact"] = fid
        edit_modal_title.value = "Имя контакта"
        edit_name_input.value = state["contact_names"].get(fid, real_name)
        edit_modal.visible = True
        page.update()

    def open_edit_contact_from_chat():
        chat = state["current_chat"]
        if not chat or chat["type"] != "private":
            return
        r = conn.execute("SELECT name FROM users WHERE id=?", (chat["id"],)).fetchone()
        real = r["name"] if r else chat["id"]
        open_edit_contact(chat["id"], real)

    def save_name(e):
        new_name = (edit_name_input.value or "").strip()
        if not new_name:
            return
        u = state["user"]
        if state["editing_contact"] is None:
            conn.execute("UPDATE users SET name=? WHERE id=?", (new_name, u["id"]))
            conn.commit()
            u["name"] = new_name
            profile_name_text.value = new_name
            show_notification("Имя обновлено")
        else:
            cid = state["editing_contact"]
            state["contact_names"][cid] = new_name
            conn.execute("INSERT OR REPLACE INTO contact_names(owner_id,contact_id,custom_name) VALUES(?,?,?)",
                         (u["id"], cid, new_name))
            conn.commit()
            if state["current_chat"] and state["current_chat"]["type"] == "private" and state["current_chat"]["id"] == cid:
                chat_header_text.value = new_name
            state["hash_friends"] = None
            load_friends()
            show_notification("Имя контакта обновлено")
        close_edit_modal()

    edit_modal = ft.Container(
        visible=False, expand=True, bgcolor="#000000cc", alignment=ft.alignment.center,
        content=ft.Container(
            width=340, bgcolor="#1c1c1e", border_radius=28, padding=24,
            content=ft.Column(spacing=16, controls=[
                edit_modal_title, edit_name_input,
                ft.Row(spacing=10, controls=[
                    ft.Container(expand=True, bgcolor=GREEN, border_radius=60, padding=10, alignment=ft.alignment.center,
                                 on_click=save_name,
                                 content=ft.Text("Сохранить", color="white", weight=ft.FontWeight.BOLD)),
                    ft.Container(expand=True, bgcolor=RED, border_radius=60, padding=10, alignment=ft.alignment.center,
                                 on_click=lambda e: close_edit_modal(),
                                 content=ft.Text("Отмена", color="white", weight=ft.FontWeight.BOLD)),
                ]),
            ]),
        ),
    )

    # ========================================================
    # НАСТРОЙКИ
    # ========================================================

    settings_panel = ft.Container(visible=False, expand=True, bgcolor=BG)

    def save_settings_to_db():
        u = state["user"]
        if not u: return
        s = state["settings"]
        conn.execute("""INSERT OR REPLACE INTO user_settings(user_id,font_size,compact,accent,notifications)
                        VALUES(?,?,?,?,?)""",
                     (u["id"], s["font_size"], s["compact"], s["accent"], s["notifications"]))
        conn.commit()

    def rerender_messages():
        chat = state["current_chat"]
        if not chat: return
        messages_col.controls.clear()
        if chat["type"] == "private":
            cid = chat_id(state["user"]["id"], chat["id"])
            rows = conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp", (cid,)).fetchall()
            for r in rows: append_message(dict(r), is_group=False)
        else:
            rows = conn.execute("SELECT * FROM group_messages WHERE group_id=? ORDER BY timestamp", (chat["id"],)).fetchall()
            for r in rows: append_message(dict(r), is_group=True)

    def render_settings():
        s = state["settings"]

        def set_font(v):
            state["settings"]["font_size"] = int(v)
            save_settings_to_db()
            rerender_messages()
            page.update()

        def set_compact(e):
            state["settings"]["compact"] = 1 if e.control.value else 0
            save_settings_to_db()
            page.update()

        def set_accent(key):
            state["settings"]["accent"] = key
            save_settings_to_db()
            render_settings()
            page.update()

        def set_notifications(e):
            state["settings"]["notifications"] = 1 if e.control.value else 0
            save_settings_to_db()
            page.update()

        accent_buttons = []
        for key, colors in ACCENTS.items():
            is_sel = s["accent"] == key
            accent_buttons.append(ft.Container(
                width=40, height=40, border_radius=20,
                bgcolor=ft.LinearGradient(begin=ft.alignment.top_left,
                                          end=ft.alignment.bottom_right,
                                          colors=list(colors)),
                border=ft.border.all(3, "#ffffff" if is_sel else "#00000000"),
                on_click=lambda e, k=key: set_accent(k),
                alignment=ft.alignment.center,
                content=ft.Icon(ft.Icons.CHECK_ROUNDED, size=18, color="white") if is_sel else None,
            ))

        settings_panel.content = ft.Container(
            expand=True, padding=16,
            content=ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True, controls=[
                ft.Row(spacing=8, controls=[
                    ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_size=20, icon_color=PURPLE_LIGHT,
                                  on_click=lambda e: close_settings()),
                    ft.Text("Настройки", size=20, weight=ft.FontWeight.BOLD, color=TEXT),
                ]),
                ft.Container(bgcolor=PANEL_BG, border_radius=16, padding=16, content=ft.Column(spacing=8, controls=[
                    ft.Row(spacing=6, controls=[
                        ft.Icon(ft.Icons.PERSON_ROUNDED, size=16, color=PURPLE_LIGHT),
                        ft.Text("Аккаунт", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
                    ]),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Column(spacing=0, controls=[
                            ft.Text(state["user"]["name"], size=14, color=TEXT, weight=ft.FontWeight.BOLD),
                            ft.Text(f"ID: {state['user']['id']}", size=11, color=MUTED, font_family="monospace"),
                        ]),
                        ft.Container(bgcolor="#2a2a2a", border_radius=30,
                                     padding=ft.padding.symmetric(horizontal=12, vertical=6),
                                     on_click=lambda e: open_edit_my_name(),
                                     content=ft.Text("Изменить", size=12, color="#aaa")),
                    ]),
                ])),
                ft.Container(bgcolor=PANEL_BG, border_radius=16, padding=16, content=ft.Column(spacing=12, controls=[
                    ft.Row(spacing=6, controls=[
                        ft.Icon(ft.Icons.PALETTE_ROUNDED, size=16, color=PURPLE_LIGHT),
                        ft.Text("Внешний вид", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
                    ]),
                    ft.Column(spacing=6, controls=[
                        ft.Text("Акцентный цвет", size=12, color=MUTED),
                        ft.Row(spacing=8, controls=accent_buttons, wrap=True),
                    ]),
                    ft.Column(spacing=2, controls=[
                        ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                            ft.Text("Размер шрифта", size=12, color=MUTED),
                            ft.Text(str(int(s["font_size"])) + "px", size=12, color=PURPLE_LIGHT, weight=ft.FontWeight.BOLD),
                        ]),
                        ft.Slider(min=10, max=22, divisions=12, value=s["font_size"],
                                  active_color=ACCENT_1, inactive_color=INPUT_BG,
                                  on_change=lambda e: set_font(e.control.value)),
                    ]),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Text("Компактный режим", size=12, color=MUTED),
                        ft.Switch(value=bool(s["compact"]), active_color=ACCENT_1, on_change=set_compact),
                    ]),
                ])),
                ft.Container(bgcolor=PANEL_BG, border_radius=16, padding=16, content=ft.Column(spacing=12, controls=[
                    ft.Row(spacing=6, controls=[
                        ft.Icon(ft.Icons.NOTIFICATIONS_ROUNDED, size=16, color=PURPLE_LIGHT),
                        ft.Text("Уведомления", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
                    ]),
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Text("Показывать уведомления", size=12, color=MUTED),
                        ft.Switch(value=bool(s["notifications"]), active_color=ACCENT_1, on_change=set_notifications),
                    ]),
                ])),
                ft.Container(bgcolor=RED, border_radius=40,
                             padding=ft.padding.symmetric(vertical=12),
                             alignment=ft.alignment.center, on_click=do_logout,
                             content=ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=6, controls=[
                                 ft.Icon(ft.Icons.LOGOUT_ROUNDED, size=16, color="white"),
                                 ft.Text("Выйти из аккаунта", color="white", weight=ft.FontWeight.BOLD, size=13),
                             ])),
            ]),
        )

    def close_settings():
        state["show_settings"] = False
        apply_layout()
        page.update()

    # ========================================================
    # АДАПТИВНЫЙ LAYOUT
    # ========================================================

    layout_stack = ft.Stack(expand=True)

    def apply_layout():
        mobile = is_mobile()
        if mobile:
            sidebar.width = None
            sidebar.border = None
            sidebar.expand = True
            back_btn.visible = state["mobile_view"] == "chat"
            if state["show_settings"]:
                layout_stack.controls = [settings_panel]
            elif state["mobile_view"] == "chat":
                layout_stack.controls = [chat_area]
            else:
                layout_stack.controls = [sidebar]
        else:
            sidebar.width = 320
            sidebar.expand = False
            sidebar.border = ft.border.only(right=ft.BorderSide(1, "#2a2a2a"))
            back_btn.visible = False
            if state["show_settings"]:
                layout_stack.controls = [settings_panel]
            else:
                layout_stack.controls = [ft.Row(expand=True, spacing=0, controls=[sidebar, chat_area])]
        try: page.update()
        except Exception: pass

    def on_resize(e):
        apply_layout()

    page.on_resize = on_resize

    # ========================================================
    # УВЕДОМЛЕНИЯ
    # ========================================================

    def show_notification(text):
        if not state["settings"].get("notifications", 1):
            return
        try:
            page.open(ft.SnackBar(content=ft.Text(text, color="white"), bgcolor="#2c2c2e", duration=2000))
        except Exception:
            pass

    # ========================================================
    # АВТООБНОВЛЕНИЕ (каждую секунду, отдельное соединение)
    # ========================================================

    def start_auto_refresh():
        poller_token["n"] += 1
        my_token = poller_token["n"]

        def loop():
            poll_conn = get_db()
            while poller_token["n"] == my_token:
                time.sleep(1)
                if not state["user"]:
                    continue

                chat = state["current_chat"]

                # --- сообщения ---
                try:
                    if chat:
                        key = (chat["type"], chat["id"])
                        if key != poll_state["last_key"]:
                            poll_state["last_key"] = key
                            poll_state["last_ts"] = now_ms()

                        if chat["type"] == "private":
                            cid = chat_id(state["user"]["id"], chat["id"])
                            rows = poll_conn.execute(
                                "SELECT * FROM messages WHERE chat_id=? AND timestamp>? ORDER BY timestamp",
                                (cid, poll_state["last_ts"]),
                            ).fetchall()
                        else:
                            rows = poll_conn.execute(
                                "SELECT * FROM group_messages WHERE group_id=? AND timestamp>? ORDER BY timestamp",
                                (chat["id"], poll_state["last_ts"]),
                            ).fetchall()

                        if rows:
                            if messages_area.content is not messages_col:
                                messages_area.content = messages_col
                            for r in rows:
                                append_message(dict(r), is_group=(chat["type"] == "group"))
                                poll_state["last_ts"] = max(poll_state["last_ts"], r["timestamp"])
                            try:
                                page.update()
                            except Exception:
                                pass
                    else:
                        poll_state["last_key"] = None
                except Exception:
                    pass

                # --- заявки ---
                try:
                    if state["user"]:
                        rows = poll_conn.execute(
                            "SELECT * FROM friend_requests WHERE to_id=? AND status='pending'",
                            (state["user"]["id"],),
                        ).fetchall()
                        h = tuple(sorted((r["id"], r["from_name"]) for r in rows))
                        if h != state["hash_requests"]:
                            state["hash_requests"] = h
                            load_requests()
                            page.update()
                except Exception:
                    pass

                # --- друзья ---
                try:
                    if state["user"]:
                        rows = poll_conn.execute(
                            "SELECT * FROM friendships WHERE user1=? OR user2=?",
                            (state["user"]["id"], state["user"]["id"]),
                        ).fetchall()
                        ids = [r["user2"] if r["user1"] == state["user"]["id"] else r["user1"] for r in rows]
                        h = tuple(sorted(ids))
                        if h != state["hash_friends"]:
                            state["hash_friends"] = h
                            load_friends()
                            page.update()
                except Exception:
                    pass

                # --- группы ---
                try:
                    if state["user"]:
                        rows = poll_conn.execute(
                            """SELECT g.id, g.name,
                                      (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id=g.id) AS cnt
                               FROM groups g JOIN group_members m ON m.group_id=g.id WHERE m.user_id=?""",
                            (state["user"]["id"],),
                        ).fetchall()
                        h = tuple(sorted((g["id"], g["name"], g["cnt"]) for g in rows))
                        if h != state["hash_groups"]:
                            state["hash_groups"] = h
                            load_groups()
                            page.update()
                except Exception:
                    pass

                try:
                    poll_conn.close()
                except Exception:
                    pass
                poll_conn = get_db()

        threading.Thread(target=loop, daemon=True).start()

    # ========================================================
    # ЗАПУСК
    # ========================================================

    def show_main_screen():
        u = state["user"]
        profile_name_text.value = u["name"]
        profile_id_text.value = f"ID: {u['id']}"
        auth_screen.visible = False
        main_screen.visible = True

        state["hash_friends"] = hash_friends_now()
        state["hash_requests"] = hash_requests_now()
        state["hash_groups"] = hash_groups_now()

        load_friends()
        load_requests()
        load_groups()
        switch_tab("chats")
        apply_layout()
        start_auto_refresh()
        page.update()

    main_screen.content = ft.Stack(expand=True, controls=[layout_stack, group_modal, edit_modal])
    page.add(ft.Stack(expand=True, controls=[auth_screen, main_screen]))
    layout_stack.controls = [ft.Row(expand=True, spacing=0, controls=[sidebar, chat_area])]

if __name__ == "__main__":
    ft.app(target=main)