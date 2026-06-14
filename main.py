#!/usr/bin/env python3
"""
NyaClicker — Advanced Auto-Clicker for Windows 10
github.com/xristos-dev/NyaClicker
"""

import os
import json
import time
import random
import threading
import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
from PIL import Image
import pyautogui
import keyboard

# ── Performance & safety ───────────────────────────────────────────────────────
pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0
try:
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP    = 0
except AttributeError:
    pass

APP_NAME    = "NyaClicker"
VERSION     = "1.0.0"
HOTKEY      = "f8"
HOTKEY_REC  = "f9"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ASSETS        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

class Action:
    TYPES   = ["Клик", "Двойной клик", "ПКМ", "Удержание", "Свайп", "Прокрутка"]
    BUTTONS = ["left", "right", "middle"]

    def __init__(self):
        self.action_type = "Клик"
        self.x           = 0
        self.y           = 0
        self.x2          = 0   # swipe end X  /  horizontal scroll clicks
        self.y2          = 0   # swipe end Y  /  vertical   scroll clicks
        self.delay_ms    = 50
        self.hold_ms     = 200
        self.button      = "left"
        self.repeat      = 1
        self.enabled     = True

    def to_dict(self):
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d):
        a = cls()
        a.__dict__.update(d)
        return a

    def label(self, idx: int) -> str:
        return self._fmt(idx, show_enabled=True)

    def rec_label(self, idx: int) -> str:
        return self._fmt(idx, show_enabled=False)

    def _fmt(self, idx: int, show_enabled: bool) -> str:
        icons = {
            "Клик": "🖱 ", "Двойной клик": "🖱🖱", "ПКМ": "🖱➡",
            "Удержание": "⏱ ", "Свайп": "↔ ", "Прокрутка": "🖱↕",
        }
        ico = icons.get(self.action_type, "● ")
        prefix = ("✓" if self.enabled else "✗") + " " if show_enabled else ""

        if self.action_type == "Свайп":
            detail = f"({self.x},{self.y}) → ({self.x2},{self.y2})  dur:{self.hold_ms}ms"
        elif self.action_type == "Удержание":
            detail = f"({self.x},{self.y})  hold:{self.hold_ms}ms"
        elif self.action_type == "Прокрутка":
            parts = []
            if self.y2: parts.append(f"↕{self.y2:+d}")
            if self.x2: parts.append(f"↔{self.x2:+d}")
            detail = f"({self.x},{self.y})  {'  '.join(parts) or '—'}"
        else:
            detail = f"({self.x},{self.y})  delay:{self.delay_ms}ms"

        rep = f"  ×{self.repeat}" if self.repeat > 1 else ""
        return f"  {prefix}{idx:3}. {ico} {self.action_type:<14}  {detail}{rep}"


# ──────────────────────────────────────────────────────────────────────────────
# Mouse Recorder
# ──────────────────────────────────────────────────────────────────────────────

class Recorder:
    DRAG_THRESHOLD  = 8     # px movement → Свайп
    HOLD_THRESHOLD  = 250   # ms held     → Удержание
    DC_THRESHOLD    = 350   # ms gap      → Двойной клик
    SCROLL_WINDOW   = 0.18  # sec         → accumulate scroll ticks

    def __init__(self, on_action, on_stopped):
        self._on_action  = on_action
        self._on_stopped = on_stopped
        self._listener   = None
        self._lock       = threading.Lock()
        self.recorded: list[Action] = []

        # click tracking
        self._last_t:    float = 0.0
        self._press_t:   float = 0.0
        self._press_pos        = (0, 0)
        self._press_btn: str   = "left"

        # double-click detection
        self._pending:       Action | None = None
        self._pending_timer               = None

        # scroll accumulation
        self._scroll_pos   = (0, 0)
        self._scroll_dx    = 0.0
        self._scroll_dy    = 0.0
        self._scroll_t:    float = 0.0
        self._scroll_delay: int  = 0
        self._scroll_timer       = None

    # ── public ────────────────────────────────────────────────────────────────

    def start(self):
        from pynput import mouse as pym

        self.recorded  = []
        self._last_t   = time.perf_counter()
        self._press_t  = 0.0
        self._pending  = None

        def on_click(x, y, button, pressed):
            t   = time.perf_counter()
            btn = button.name if hasattr(button, "name") else str(button)
            if pressed:
                self._press_t   = t
                self._press_pos = (int(x), int(y))
                self._press_btn = btn
            else:
                self._handle_release(int(x), int(y), t)

        def on_scroll(x, y, dx, dy):
            self._handle_scroll(int(x), int(y), dx, dy)

        self._listener = pym.Listener(on_click=on_click, on_scroll=on_scroll)
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
        # flush pending
        self._cancel_scroll_timer()
        self._flush_scroll_now()
        if self._pending_timer:
            self._pending_timer.cancel()
            self._pending_timer = None
        if self._pending:
            self._commit(self._pending)
            self._pending = None
        self._on_stopped()

    # ── click logic ───────────────────────────────────────────────────────────

    def _handle_release(self, rx: int, ry: int, t: float):
        if self._press_t == 0.0:
            return

        # flush any pending scroll so timing is accurate
        self._cancel_scroll_timer()
        self._flush_scroll_now()

        duration_ms = int((t - self._press_t) * 1000)
        delay_ms    = max(0, int((self._press_t - self._last_t) * 1000))
        self._last_t = t
        self._press_t = 0.0

        dx = abs(rx - self._press_pos[0])
        dy = abs(ry - self._press_pos[1])

        a = Action()
        a.delay_ms = delay_ms
        a.button   = self._press_btn
        a.x        = self._press_pos[0]
        a.y        = self._press_pos[1]

        if dx > self.DRAG_THRESHOLD or dy > self.DRAG_THRESHOLD:
            a.action_type = "Свайп"
            a.x2          = rx
            a.y2          = ry
            a.hold_ms     = duration_ms
            self._flush_pending()
            self._commit(a)

        elif duration_ms >= self.HOLD_THRESHOLD:
            a.action_type = "Удержание"
            a.hold_ms     = duration_ms
            self._flush_pending()
            self._commit(a)

        else:
            a.action_type = "Клик" if self._press_btn == "left" else "ПКМ"

            if (self._pending is not None
                    and self._pending.action_type == "Клик"
                    and self._press_btn == "left"
                    and abs(a.x - self._pending.x) < 12
                    and abs(a.y - self._pending.y) < 12
                    and delay_ms < self.DC_THRESHOLD):
                if self._pending_timer:
                    self._pending_timer.cancel()
                    self._pending_timer = None
                self._pending.action_type = "Двойной клик"
                self._commit(self._pending)
                self._pending = None
            else:
                self._flush_pending()
                if self._press_btn == "left":
                    self._pending = a
                    self._pending_timer = threading.Timer(
                        self.DC_THRESHOLD / 1000, self._flush_pending)
                    self._pending_timer.start()
                else:
                    self._commit(a)

    def _flush_pending(self):
        with self._lock:
            if self._pending_timer:
                self._pending_timer.cancel()
                self._pending_timer = None
            if self._pending:
                self._commit(self._pending)
                self._pending = None

    # ── scroll logic ──────────────────────────────────────────────────────────

    def _handle_scroll(self, x: int, y: int, dx: float, dy: float):
        t = time.perf_counter()

        same_pos = (abs(x - self._scroll_pos[0]) < 30 and
                    abs(y - self._scroll_pos[1]) < 30)
        within_window = (t - self._scroll_t) < self.SCROLL_WINDOW

        if self._scroll_timer is not None and same_pos and within_window:
            # accumulate
            with self._lock:
                self._scroll_dx += dx
                self._scroll_dy += dy
                self._scroll_t   = t
            self._cancel_scroll_timer()
            self._scroll_timer = threading.Timer(
                self.SCROLL_WINDOW, self._flush_scroll)
            self._scroll_timer.start()
        else:
            # commit previous, start fresh
            self._cancel_scroll_timer()
            self._flush_scroll_now()
            with self._lock:
                self._scroll_pos   = (x, y)
                self._scroll_dx    = dx
                self._scroll_dy    = dy
                self._scroll_t     = t
                self._scroll_delay = max(0, int((t - self._last_t) * 1000))
                self._last_t       = t
            self._scroll_timer = threading.Timer(
                self.SCROLL_WINDOW, self._flush_scroll)
            self._scroll_timer.start()

    def _cancel_scroll_timer(self):
        if self._scroll_timer:
            self._scroll_timer.cancel()
            self._scroll_timer = None

    def _flush_scroll(self):
        with self._lock:
            self._scroll_timer = None
        self._flush_scroll_now()

    def _flush_scroll_now(self):
        with self._lock:
            sdx = int(round(self._scroll_dx))
            sdy = int(round(self._scroll_dy))
            if sdx == 0 and sdy == 0:
                return
            a          = Action()
            a.action_type = "Прокрутка"
            a.x        = self._scroll_pos[0]
            a.y        = self._scroll_pos[1]
            a.x2       = sdx
            a.y2       = sdy
            a.delay_ms = self._scroll_delay
            self._scroll_dx   = 0.0
            self._scroll_dy   = 0.0
            self._scroll_delay = 0
        self._commit(a)

    # ── commit ────────────────────────────────────────────────────────────────

    def _commit(self, a: Action):
        self.recorded.append(a)
        self._on_action(a)


# ──────────────────────────────────────────────────────────────────────────────
# Action edit dialog
# ──────────────────────────────────────────────────────────────────────────────

class ActionDialog(ctk.CTkToplevel):
    def __init__(self, parent, action: Action = None):
        super().__init__(parent)
        self.title("✏  Настройка действия")
        self.geometry("510x550")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus()

        self.result: Action = None
        src = action or Action()

        self.tv  = tk.StringVar(value=src.action_type)
        self.xv  = tk.StringVar(value=str(src.x))
        self.yv  = tk.StringVar(value=str(src.y))
        self.x2v = tk.StringVar(value=str(src.x2))
        self.y2v = tk.StringVar(value=str(src.y2))
        self.dv  = tk.StringVar(value=str(src.delay_ms))
        self.hv  = tk.StringVar(value=str(src.hold_ms))
        self.rv  = tk.StringVar(value=str(src.repeat))
        self.bv  = tk.StringVar(value=src.button)
        self.ev  = tk.BooleanVar(value=src.enabled)
        self._src = src

        self._build()

    def _build(self):
        s = self._section("Тип действия")
        r = ctk.CTkFrame(s, fg_color="transparent")
        r.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkOptionMenu(r, values=Action.TYPES, variable=self.tv, width=210).pack(side="left")
        ctk.CTkCheckBox(r, text=" Включено", variable=self.ev).pack(side="left", padx=20)

        s = self._section("Начальная точка  (X, Y)")
        self._coord_row(s, self.xv, self.yv, self._cap_start)

        s = self._section("Конечная точка  (X2, Y2)  ← Свайп  |  Прокрутка ↔↕ тики")
        self._coord_row_manual(s, "X2 / H.scroll:", self.x2v, "Y2 / V.scroll:", self.y2v)

        s = self._section("Тайминг")
        trow = ctk.CTkFrame(s, fg_color="transparent")
        trow.pack(fill="x", padx=10, pady=(0, 6))
        for lbl, var in [
            ("Задержка\n(мс)", self.dv),
            ("Удержание /\nДлина свайпа (мс)", self.hv),
            ("Повторений", self.rv),
        ]:
            f = ctk.CTkFrame(trow, fg_color="transparent")
            f.pack(side="left", padx=10)
            ctk.CTkLabel(f, text=lbl, font=ctk.CTkFont(size=11), text_color="#aaa").pack(anchor="w")
            ctk.CTkEntry(f, textvariable=var, width=110).pack()

        brow = ctk.CTkFrame(s, fg_color="transparent")
        brow.pack(fill="x", padx=10, pady=(4, 8))
        ctk.CTkLabel(brow, text="Кнопка мыши:").pack(side="left")
        ctk.CTkOptionMenu(brow, values=Action.BUTTONS, variable=self.bv, width=130).pack(side="left", padx=8)

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=(8, 14))
        ctk.CTkButton(bf, text="✓  Сохранить", width=145, height=38,
                      fg_color="#2ecc71", hover_color="#27ae60", command=self._ok).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="✗  Отмена", width=145, height=38,
                      fg_color="#555", hover_color="#444", command=self.destroy).pack(side="left", padx=8)

    def _section(self, title):
        f = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=8)
        f.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#FF6B9D").pack(anchor="w", padx=10, pady=(8, 3))
        return f

    def _coord_row(self, parent, xv, yv, cap_fn):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))
        for lbl, var in [("X:", xv), ("Y:", yv)]:
            ctk.CTkLabel(row, text=lbl, width=24).pack(side="left")
            ctk.CTkEntry(row, textvariable=var, width=82).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="📍 Захват", width=95, height=28,
                      fg_color="#e94560", hover_color="#c0392b", command=cap_fn).pack(side="left", padx=6)

    def _coord_row_manual(self, parent, lx, xv, ly, yv):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(row, text=lx, width=90).pack(side="left")
        ctk.CTkEntry(row, textvariable=xv, width=80).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(row, text=ly, width=90).pack(side="left")
        ctk.CTkEntry(row, textvariable=yv, width=80).pack(side="left")

    def _capture(self, xv, yv):
        self.iconify()
        def _run():
            time.sleep(0.5)
            captured = []
            try:
                from pynput import mouse as pym
                def on_click(x, y, button, pressed):
                    if pressed:
                        captured.append((int(x), int(y)))
                        return False
                with pym.Listener(on_click=on_click) as listener:
                    listener.join()
            except Exception:
                pos = pyautogui.position()
                captured.append((pos.x, pos.y))
            if captured:
                xv.set(str(captured[0][0]))
                yv.set(str(captured[0][1]))
            self.after(0, lambda: (self.deiconify(), self.focus()))
        threading.Thread(target=_run, daemon=True).start()

    def _cap_start(self): self._capture(self.xv, self.yv)

    def _ok(self):
        try:
            a = self._src
            a.action_type = self.tv.get()
            a.x           = int(self.xv.get())
            a.y           = int(self.yv.get())
            a.x2          = int(self.x2v.get())
            a.y2          = int(self.y2v.get())
            a.delay_ms    = max(0, int(self.dv.get()))
            a.hold_ms     = max(0, int(self.hv.get()))
            a.repeat      = max(1, int(self.rv.get()))
            a.button      = self.bv.get()
            a.enabled     = self.ev.get()
            self.result   = a
            self.destroy()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


# ──────────────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────────────

class NyaClicker(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"🐱  {APP_NAME}  v{VERSION}")
        self.geometry("990x700")
        self.minsize(820, 580)

        self.actions: list[Action] = []
        self.running   = False
        self._thread   = None
        self._hotkey   = HOTKEY

        self._recorder: Recorder | None = None
        self._recording = False
        self._rec_hotkey = HOTKEY_REC

        self._load_neko()
        self._build_ui()
        self._load_settings()
        self._register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._tick()

    # ── assets ──────────────────────────────────────────────────────────────────

    def _load_neko(self):
        try:
            img = Image.open(os.path.join(ASSETS, "neko.png"))
            self._neko_sm = ctk.CTkImage(img.resize((90, 90),   Image.LANCZOS), size=(90, 90))
            self._neko_lg = ctk.CTkImage(img.resize((160, 160), Image.LANCZOS), size=(160, 160))
        except Exception:
            self._neko_sm = self._neko_lg = None

    # ── settings persistence ──────────────────────────────────────────────────────

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                s = json.load(f)
            self._sv_loops.set(s.get("loops", "0"))
            self._sv_gdelay.set(s.get("gdelay", "0"))
            self._sv_variance.set(s.get("variance", "0"))
            self._sv_move_dur.set(s.get("move_dur", "0"))
            self._sv_smooth.set(s.get("smooth", False))
            self._sv_stop_err.set(s.get("stop_err", True))
            if s.get("hotkey"):
                self._hotkey = s["hotkey"]
                self._sv_hotkey.set(s["hotkey"].upper())
                self._start_btn.configure(text=f"▶  Старт  [{s['hotkey'].upper()}]")
            if s.get("rec_hotkey"):
                self._rec_hotkey = s["rec_hotkey"]
                self._sv_rec_hotkey.set(s["rec_hotkey"].upper())
                self._rec_toggle_btn.configure(
                    text=f"🔴  Начать запись  [{s['rec_hotkey'].upper()}]")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_settings(self):
        try:
            s = {
                "loops":    self._sv_loops.get(),
                "gdelay":   self._sv_gdelay.get(),
                "variance": self._sv_variance.get(),
                "move_dur": self._sv_move_dur.get(),
                "smooth":   self._sv_smooth.get(),
                "stop_err": self._sv_stop_err.get(),
                "hotkey":   self._hotkey,
                "rec_hotkey": self._rec_hotkey,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── UI ───────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── sidebar ──────────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=192, corner_radius=0, fg_color="#14142b")
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(9, weight=1)

        if self._neko_sm:
            ctk.CTkLabel(sb, image=self._neko_sm, text="").grid(
                row=0, column=0, pady=(22, 4), padx=51)
        ctk.CTkLabel(sb, text=APP_NAME,
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color="#FF6B9D").grid(row=1, column=0, pady=(0, 2))
        ctk.CTkLabel(sb, text=f"v{VERSION}",
                     font=ctk.CTkFont(size=10), text_color="#555").grid(row=2, column=0, pady=(0, 14))

        def nav(row, text, cmd):
            b = ctk.CTkButton(sb, text=text, width=170, anchor="w",
                              fg_color="transparent", hover_color="#2a2a4e",
                              font=ctk.CTkFont(size=13), command=cmd)
            b.grid(row=row, column=0, padx=10, pady=2)
            return b

        nav(3, "⚡  Действия",    lambda: self._show("actions"))
        nav(4, "🔴  Запись",      lambda: self._show("record"))
        nav(5, "⚙  Настройки",   lambda: self._show("settings"))
        nav(6, "ℹ  О программе",  lambda: self._show("about"))

        # Play-recording button
        self._play_rec_btn = ctk.CTkButton(
            sb, text="▶  Воспроизвести запись",
            width=170, height=36,
            fg_color="#16a085", hover_color="#1abc9c",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._rec_play
        )
        self._play_rec_btn.grid(row=10, column=0, padx=10, pady=(4, 4))

        # Start/stop button
        self._start_btn = ctk.CTkButton(
            sb, text=f"▶  Старт  [{HOTKEY.upper()}]",
            width=170, height=44,
            fg_color="#2ecc71", hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle
        )
        self._start_btn.grid(row=11, column=0, padx=10, pady=(0, 22))

        # ── main area ────────────────────────────────────────────────────────────
        self._main = ctk.CTkFrame(self, corner_radius=0, fg_color="#16213e")
        self._main.grid(row=0, column=1, sticky="nsew")
        self._main.grid_columnconfigure(0, weight=1)
        self._main.grid_rowconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkBaseClass] = {}
        self._build_actions_tab()
        self._build_record_tab()
        self._build_settings_tab()
        self._build_about_tab()
        self._show("actions")

        self._status = ctk.CTkLabel(
            self, text="● Готов", anchor="w", padx=12, height=26,
            fg_color="#0b0b1a", text_color="#666", font=ctk.CTkFont(size=11))
        self._status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _show(self, name: str):
        for t in self._tabs.values():
            t.grid_forget()
        self._tabs[name].grid(row=0, column=0, sticky="nsew")

    # ── actions tab ──────────────────────────────────────────────────────────────

    def _build_actions_tab(self):
        f = ctk.CTkFrame(self._main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        self._tabs["actions"] = f

        tb = ctk.CTkFrame(f, fg_color="#1a1a2e", height=54)
        tb.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 5))
        tb.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tb, text="⚡  Список действий",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#FF6B9D").grid(row=0, column=0, padx=14, sticky="w")

        bf = ctk.CTkFrame(tb, fg_color="transparent")
        bf.grid(row=0, column=1, padx=8)
        for label, color, cmd in [
            ("+ Добавить", "#e94560", self._add),
            ("✏ Изменить", "#2980b9", self._edit),
            ("🗑 Удалить",  "#555",    self._delete),
        ]:
            ctk.CTkButton(bf, text=label, width=102, height=30,
                          fg_color=color, command=cmd).pack(side="left", padx=3, pady=12)

        lf = ctk.CTkFrame(f, fg_color="#111124")
        lf.grid(row=1, column=0, sticky="nsew", padx=14, pady=3)
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(0, weight=1)

        self._lb = tk.Listbox(
            lf, bg="#0d0d20", fg="#ddd",
            selectbackground="#e94560", selectforeground="#fff",
            borderwidth=0, highlightthickness=0,
            font=("Consolas", 11), activestyle="none")
        self._lb.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        sb2 = ctk.CTkScrollbar(lf, command=self._lb.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self._lb.configure(yscrollcommand=sb2.set)
        self._lb.bind("<Double-Button-1>", lambda _: self._edit())

        bb = ctk.CTkFrame(f, fg_color="#1a1a2e", height=46)
        bb.grid(row=2, column=0, sticky="ew", padx=14, pady=(3, 12))
        for label, cmd in [("⬆ Вверх", self._up), ("⬇ Вниз", self._down)]:
            ctk.CTkButton(bb, text=label, width=90, height=30,
                          fg_color="#2c3e50", command=cmd).pack(side="left", padx=5, pady=8)
        ctk.CTkButton(bb, text="📂 Загрузить", width=115, height=30,
                      fg_color="#2980b9", command=self._load).pack(side="right", padx=5)
        ctk.CTkButton(bb, text="💾 Сохранить", width=115, height=30,
                      fg_color="#8e44ad", command=self._save).pack(side="right", padx=5)

    # ── record tab ───────────────────────────────────────────────────────────────

    def _build_record_tab(self):
        f = ctk.CTkFrame(self._main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)
        self._tabs["record"] = f

        hdr = ctk.CTkFrame(f, fg_color="#1a1a2e", height=54)
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 5))
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="🔴  Запись и воспроизведение",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#FF6B9D").grid(row=0, column=0, padx=14, sticky="w")
        ctk.CTkLabel(hdr, text=f"[{HOTKEY_REC.upper()}] — Старт/Стоп записи",
                     font=ctk.CTkFont(size=11), text_color="#666").grid(
            row=0, column=1, padx=12, sticky="e")

        badge = ctk.CTkFrame(f, fg_color="#1a1a2e", corner_radius=10)
        badge.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))
        badge.grid_columnconfigure(1, weight=1)

        self._rec_dot = ctk.CTkLabel(badge, text="⚫", font=ctk.CTkFont(size=20))
        self._rec_dot.grid(row=0, column=0, padx=(14, 6), pady=10)

        self._rec_status_lbl = ctk.CTkLabel(
            badge, text="Ожидание  —  нажмите кнопку или F9 для начала записи",
            font=ctk.CTkFont(size=13), text_color="#aaa", anchor="w")
        self._rec_status_lbl.grid(row=0, column=1, padx=4, pady=10, sticky="w")

        self._rec_count_lbl = ctk.CTkLabel(
            badge, text="0 событий",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#666")
        self._rec_count_lbl.grid(row=0, column=2, padx=14, pady=10)

        lf = ctk.CTkFrame(f, fg_color="#111124")
        lf.grid(row=2, column=0, sticky="nsew", padx=14, pady=3)
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(0, weight=1)

        self._rec_lb = tk.Listbox(
            lf, bg="#0d0d20", fg="#ddd",
            selectbackground="#e94560", selectforeground="#fff",
            borderwidth=0, highlightthickness=0,
            font=("Consolas", 11), activestyle="none")
        self._rec_lb.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        sb3 = ctk.CTkScrollbar(lf, command=self._rec_lb.yview)
        sb3.grid(row=0, column=1, sticky="ns")
        self._rec_lb.configure(yscrollcommand=sb3.set)

        bb = ctk.CTkFrame(f, fg_color="#1a1a2e", height=54)
        bb.grid(row=3, column=0, sticky="ew", padx=14, pady=(3, 12))

        self._rec_toggle_btn = ctk.CTkButton(
            bb, text=f"🔴  Начать запись  [{HOTKEY_REC.upper()}]",
            width=210, height=38, fg_color="#e94560", hover_color="#c0392b",
            font=ctk.CTkFont(size=13, weight="bold"), command=self._toggle_rec)
        self._rec_toggle_btn.pack(side="left", padx=8, pady=8)

        ctk.CTkButton(bb, text="🗑 Очистить", width=100, height=38,
                      fg_color="#555", hover_color="#444",
                      command=self._rec_clear).pack(side="left", padx=3)

        ctk.CTkButton(bb, text="▶ Воспроизвести", width=145, height=38,
                      fg_color="#2ecc71", hover_color="#27ae60",
                      command=self._rec_play).pack(side="left", padx=3)

        ctk.CTkButton(bb, text="📂 Загрузить", width=110, height=38,
                      fg_color="#2980b9", command=self._rec_load).pack(side="right", padx=8)
        ctk.CTkButton(bb, text="💾 Сохранить", width=110, height=38,
                      fg_color="#8e44ad", command=self._rec_save).pack(side="right", padx=3)
        ctk.CTkButton(bb, text="➕ В список действий", width=155, height=38,
                      fg_color="#16a085", hover_color="#1abc9c",
                      command=self._rec_add_to_actions).pack(side="right", padx=3)

    # ── settings tab ─────────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        f = ctk.CTkScrollableFrame(self._main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self._tabs["settings"] = f

        ctk.CTkLabel(f, text="⚙  Настройки",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#FF6B9D").grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        def card(row, title):
            c = ctk.CTkFrame(f, fg_color="#1a1a2e", corner_radius=8)
            c.grid(row=row, column=0, sticky="ew", padx=14, pady=5)
            c.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color="#aaa").grid(row=0, column=0, columnspan=3,
                                                  padx=14, pady=(10, 4), sticky="w")
            return c

        def row(parent, r, label, var):
            ctk.CTkLabel(parent, text=label, anchor="w").grid(
                row=r, column=0, padx=14, pady=7, sticky="w")
            ctk.CTkEntry(parent, textvariable=var, width=110).grid(
                row=r, column=1, padx=14, pady=7, sticky="w")

        g = card(1, "Глобальные")
        self._sv_loops    = tk.StringVar(value="0")
        self._sv_gdelay   = tk.StringVar(value="0")
        self._sv_variance = tk.StringVar(value="0")
        row(g, 1, "Повторений цикла (0 = ∞):", self._sv_loops)
        row(g, 2, "Доп. задержка между действиями (мс):", self._sv_gdelay)
        row(g, 3, "Случайный разброс задержки (±мс):", self._sv_variance)
        self._sv_stop_err = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(g, text="Остановить при ошибке",
                        variable=self._sv_stop_err).grid(
            row=4, column=0, columnspan=2, padx=14, pady=(4, 12), sticky="w")

        m = card(2, "Мышь")
        self._sv_move_dur = tk.StringVar(value="0")
        row(m, 1, "Длительность движения курсора (сек, 0 = мгновенно):", self._sv_move_dur)
        self._sv_smooth = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(m, text="Плавное движение (easeInOutQuad)",
                        variable=self._sv_smooth).grid(
            row=2, column=0, columnspan=2, padx=14, pady=(4, 12), sticky="w")

        h = card(3, "Горячие клавиши")
        self._sv_hotkey     = tk.StringVar(value=HOTKEY.upper())
        self._sv_rec_hotkey = tk.StringVar(value=HOTKEY_REC.upper())
        ctk.CTkLabel(h, text="Старт / Стоп воспроизведения:").grid(
            row=1, column=0, padx=14, pady=7, sticky="w")
        ctk.CTkEntry(h, textvariable=self._sv_hotkey, width=90).grid(
            row=1, column=1, padx=14, sticky="w")
        ctk.CTkButton(h, text="Применить", width=90, height=28, fg_color="#8e44ad",
                      command=self._apply_hotkey).grid(row=1, column=2, padx=8, pady=(4, 4))
        ctk.CTkLabel(h, text="Старт / Стоп записи:").grid(
            row=2, column=0, padx=14, pady=7, sticky="w")
        ctk.CTkEntry(h, textvariable=self._sv_rec_hotkey, width=90).grid(
            row=2, column=1, padx=14, sticky="w")
        ctk.CTkButton(h, text="Применить", width=90, height=28, fg_color="#8e44ad",
                      command=self._apply_rec_hotkey).grid(row=2, column=2, padx=8, pady=(0, 12))

        ctk.CTkButton(
            f, text="💾  Сохранить настройки", width=210,
            fg_color="#8e44ad", hover_color="#7d3c98",
            command=self._apply_settings
        ).grid(row=4, column=0, padx=16, pady=14, sticky="w")

    # ── about tab ────────────────────────────────────────────────────────────────

    def _build_about_tab(self):
        f = ctk.CTkFrame(self._main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)
        self._tabs["about"] = f

        c = ctk.CTkFrame(f, fg_color="transparent")
        c.place(relx=.5, rely=.5, anchor="center")

        if self._neko_lg:
            ctk.CTkLabel(c, image=self._neko_lg, text="").pack(pady=(0, 12))

        ctk.CTkLabel(c, text=APP_NAME,
                     font=ctk.CTkFont(size=32, weight="bold"),
                     text_color="#FF6B9D").pack()
        ctk.CTkLabel(c, text=f"Версия {VERSION}",
                     font=ctk.CTkFont(size=12), text_color="#666").pack(pady=2)
        ctk.CTkLabel(c, text="Продвинутый автокликер для Windows 10",
                     text_color="#999").pack(pady=4)

        info = ctk.CTkFrame(c, fg_color="#1a1a2e", corner_radius=8)
        info.pack(pady=10, padx=10, fill="x")
        ctk.CTkLabel(info, text="🎮  Горячие клавиши",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#FF6B9D").pack(pady=(10, 2))
        ctk.CTkLabel(info,
                     text="[F8]  —  Старт / Стоп воспроизведения\n"
                          "[F9]  —  Старт / Стоп записи\n"
                          "[📍 Захват]  —  Кликни по экрану в диалоге\n"
                          "Угол (0, 0)  —  Аварийная остановка (FailSafe)",
                     text_color="#ccc", justify="center").pack(pady=(0, 10))

        ctk.CTkLabel(c, text="github.com/xristos-dev/NyaClicker",
                     text_color="#444", font=ctk.CTkFont(size=10)).pack(pady=8)

    # ── actions list ─────────────────────────────────────────────────────────────

    def _refresh(self):
        self._lb.delete(0, tk.END)
        for i, a in enumerate(self.actions, 1):
            self._lb.insert(tk.END, a.label(i))

    def _sel(self) -> int | None:
        s = self._lb.curselection()
        return s[0] if s else None

    def _add(self):
        d = ActionDialog(self)
        self.wait_window(d)
        if d.result:
            self.actions.append(d.result)
            self._refresh()

    def _edit(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo("", "Выберите действие", parent=self)
            return
        d = ActionDialog(self, self.actions[i])
        self.wait_window(d)
        if d.result:
            self.actions[i] = d.result
            self._refresh()

    def _delete(self):
        i = self._sel()
        if i is None:
            return
        if messagebox.askyesno("Удалить?", f"Удалить действие #{i + 1}?", parent=self):
            self.actions.pop(i)
            self._refresh()

    def _up(self):
        i = self._sel()
        if i is None or i == 0:
            return
        self.actions[i - 1], self.actions[i] = self.actions[i], self.actions[i - 1]
        self._refresh()
        self._lb.selection_set(i - 1)

    def _down(self):
        i = self._sel()
        if i is None or i >= len(self.actions) - 1:
            return
        self.actions[i], self.actions[i + 1] = self.actions[i + 1], self.actions[i]
        self._refresh()
        self._lb.selection_set(i + 1)

    def _save(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            title="Сохранить список действий")
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump([a.to_dict() for a in self.actions], fh,
                          ensure_ascii=False, indent=2)
            self._status.configure(text=f"● Сохранено: {os.path.basename(p)}")

    def _load(self):
        p = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            title="Загрузить список действий")
        if p:
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.actions = [Action.from_dict(d) for d in data]
                self._refresh()
                self._status.configure(text=f"● Загружено: {os.path.basename(p)}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    # ── settings apply ───────────────────────────────────────────────────────────

    def _apply_settings(self):
        self._save_settings()
        self._status.configure(text="● Настройки сохранены")

    # ── hotkeys ──────────────────────────────────────────────────────────────────

    def _register_hotkeys(self):
        try:
            keyboard.add_hotkey(self._hotkey,     self._toggle)
            keyboard.add_hotkey(self._rec_hotkey, self._toggle_rec)
        except Exception:
            pass

    def _apply_hotkey(self):
        new = self._sv_hotkey.get().strip().lower()
        if not new:
            return
        try:
            keyboard.remove_hotkey(self._hotkey)
        except Exception:
            pass
        self._hotkey = new
        keyboard.add_hotkey(self._hotkey, self._toggle)
        self._start_btn.configure(text=f"▶  Старт  [{new.upper()}]")
        self._save_settings()
        self._status.configure(text=f"● Горячая клавиша воспр.: {new.upper()}")

    def _apply_rec_hotkey(self):
        new = self._sv_rec_hotkey.get().strip().lower()
        if not new:
            return
        try:
            keyboard.remove_hotkey(self._rec_hotkey)
        except Exception:
            pass
        self._rec_hotkey = new
        keyboard.add_hotkey(self._rec_hotkey, self._toggle_rec)
        self._rec_toggle_btn.configure(
            text=f"🔴  Начать запись  [{new.upper()}]")
        self._save_settings()
        self._status.configure(text=f"● Горячая клавиша записи: {new.upper()}")

    # ── recording ────────────────────────────────────────────────────────────────

    def _toggle_rec(self):
        if self._recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        if self.running:
            messagebox.showwarning("", "Остановите воспроизведение перед записью")
            return
        self._recording = True
        self._recorder  = Recorder(
            on_action  = self._rec_action_cb,
            on_stopped = self._rec_stopped_cb)
        self._recorder.start()
        self._rec_toggle_btn.configure(
            text=f"⏹  Остановить запись  [{self._rec_hotkey.upper()}]",
            fg_color="#c0392b", hover_color="#a93226")
        self._rec_dot.configure(text="🔴")
        self._rec_status_lbl.configure(
            text="ЗАПИСЬ ИДЁТ...  клики, свайпы, прокрутка — всё записывается",
            text_color="#e74c3c")

    def _stop_rec(self):
        if self._recorder:
            threading.Thread(target=self._recorder.stop, daemon=True).start()

    def _rec_action_cb(self, action: Action):
        def _upd():
            if not self._recording:
                return
            n = len(self._recorder.recorded) if self._recorder else 0
            self._rec_lb.insert(tk.END, action.rec_label(n))
            self._rec_lb.see(tk.END)
            self._rec_count_lbl.configure(text=f"{n} событий")
        self.after(0, _upd)

    def _rec_stopped_cb(self):
        def _upd():
            self._recording = False
            n = len(self._recorder.recorded) if self._recorder else 0
            self._rec_toggle_btn.configure(
                text=f"🔴  Начать запись  [{self._rec_hotkey.upper()}]",
                fg_color="#e94560", hover_color="#c0392b")
            self._rec_dot.configure(text="⚫")
            self._rec_status_lbl.configure(
                text=f"Запись остановлена  —  {n} событий захвачено",
                text_color="#aaa")
            self._status.configure(
                text=f"⚫  Запись остановлена  |  {n} событий",
                text_color="#666")
        self.after(0, _upd)

    def _rec_clear(self):
        if self._recording:
            messagebox.showwarning("", "Остановите запись перед очисткой")
            return
        self._rec_lb.delete(0, tk.END)
        if self._recorder:
            self._recorder.recorded.clear()
        self._rec_count_lbl.configure(text="0 событий")
        self._rec_status_lbl.configure(
            text="Очищено  —  нажмите кнопку для новой записи", text_color="#aaa")

    def _rec_play(self):
        if not self._recorder or not self._recorder.recorded:
            messagebox.showwarning("Пусто", "Нет записанных действий для воспроизведения")
            return
        if self._recording:
            messagebox.showwarning("", "Остановите запись")
            return
        if self.running:
            messagebox.showwarning("", "Воспроизведение уже идёт")
            return
        saved = self.actions[:]
        self.actions = [Action.from_dict(a.to_dict()) for a in self._recorder.recorded]
        self.running  = True
        self._start_btn.configure(
            text=f"⏹  Стоп  [{self._hotkey.upper()}]",
            fg_color="#e74c3c", hover_color="#c0392b")
        def _done():
            self.actions = saved
            self._refresh()
        self._thread = threading.Thread(
            target=self._run_loop_once, args=(_done,), daemon=True)
        self._thread.start()

    def _rec_add_to_actions(self):
        if not self._recorder or not self._recorder.recorded:
            messagebox.showwarning("Пусто", "Нет записанных действий")
            return
        n = len(self._recorder.recorded)
        for a in self._recorder.recorded:
            self.actions.append(Action.from_dict(a.to_dict()))
        self._refresh()
        self._show("actions")
        self._status.configure(text=f"● Добавлено {n} действий из записи")

    def _rec_save(self):
        if not self._recorder or not self._recorder.recorded:
            messagebox.showwarning("Пусто", "Нет записанных действий")
            return
        p = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump([a.to_dict() for a in self._recorder.recorded], fh,
                          ensure_ascii=False, indent=2)
            self._status.configure(text=f"● Запись сохранена: {os.path.basename(p)}")

    def _rec_load(self):
        p = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if p:
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                if self._recorder is None:
                    self._recorder = Recorder(
                        on_action=self._rec_action_cb,
                        on_stopped=self._rec_stopped_cb)
                self._recorder.recorded = [Action.from_dict(d) for d in data]
                self._rec_lb.delete(0, tk.END)
                for i, a in enumerate(self._recorder.recorded, 1):
                    self._rec_lb.insert(tk.END, a.rec_label(i))
                n = len(self._recorder.recorded)
                self._rec_count_lbl.configure(text=f"{n} событий")
                self._rec_status_lbl.configure(
                    text=f"Загружено {n} событий из файла", text_color="#aaa")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    # ── playback ─────────────────────────────────────────────────────────────────

    def _toggle(self):
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        if not self.actions:
            messagebox.showwarning("Нет действий", "Добавьте хотя бы одно действие!")
            return
        self.running = True
        self._start_btn.configure(
            text=f"⏹  Стоп  [{self._hotkey.upper()}]",
            fg_color="#e74c3c", hover_color="#c0392b")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _stop(self):
        self.running = False
        self._start_btn.configure(
            text=f"▶  Старт  [{self._hotkey.upper()}]",
            fg_color="#2ecc71", hover_color="#27ae60")

    def _run_loop(self):
        try:
            max_loops = int(self._sv_loops.get())
            g_delay   = int(self._sv_gdelay.get()) / 1000
            variance  = int(self._sv_variance.get()) / 1000
            move_dur  = float(self._sv_move_dur.get())
            smooth    = self._sv_smooth.get()
            stop_err  = self._sv_stop_err.get()
        except Exception:
            max_loops, g_delay, variance, move_dur, smooth, stop_err = 0, 0.0, 0.0, 0.0, False, True

        loop = 0
        while self.running:
            for action in self.actions:
                if not self.running:
                    break
                if not action.enabled:
                    continue
                self._execute(action, move_dur, smooth, stop_err)
                if g_delay > 0 or variance > 0:
                    delay = g_delay + (random.uniform(-variance, variance)
                                       if variance > 0 else 0)
                    _precise_sleep(max(0.0, delay))
            loop += 1
            if max_loops > 0 and loop >= max_loops:
                break
        self.after(0, self._stop)

    def _run_loop_once(self, on_done):
        try:
            move_dur = float(self._sv_move_dur.get())
            smooth   = self._sv_smooth.get()
            stop_err = self._sv_stop_err.get()
        except Exception:
            move_dur, smooth, stop_err = 0.0, False, True
        for action in self.actions:
            if not self.running:
                break
            if not action.enabled:
                continue
            self._execute(action, move_dur, smooth, stop_err)
        self.after(0, self._stop)
        self.after(0, on_done)

    def _execute(self, a: Action, move_dur: float, smooth: bool, stop_err: bool):
        tween = pyautogui.easeInOutQuad if (smooth and move_dur > 0) else pyautogui.linear
        try:
            if a.delay_ms > 0:
                _precise_sleep(a.delay_ms / 1000)

            for _ in range(a.repeat):
                if not self.running:
                    return

                if a.action_type == "Клик":
                    pyautogui.click(a.x, a.y, button=a.button,
                                    duration=move_dur, tween=tween)

                elif a.action_type == "Двойной клик":
                    pyautogui.doubleClick(a.x, a.y,
                                          duration=move_dur, tween=tween)

                elif a.action_type == "ПКМ":
                    pyautogui.rightClick(a.x, a.y,
                                         duration=move_dur, tween=tween)

                elif a.action_type == "Удержание":
                    pyautogui.moveTo(a.x, a.y, duration=move_dur, tween=tween)
                    pyautogui.mouseDown(button=a.button)
                    _precise_sleep(max(0.0, a.hold_ms / 1000))
                    pyautogui.mouseUp(button=a.button)

                elif a.action_type == "Свайп":
                    dur = max(0.05, a.hold_ms / 1000)
                    pyautogui.moveTo(a.x, a.y, duration=move_dur, tween=tween)
                    pyautogui.dragTo(a.x2, a.y2, duration=dur,
                                     button=a.button, tween=tween)

                elif a.action_type == "Прокрутка":
                    if move_dur > 0:
                        pyautogui.moveTo(a.x, a.y, duration=move_dur, tween=tween)
                    if a.y2:
                        pyautogui.scroll(a.y2, x=a.x, y=a.y)
                    if a.x2:
                        pyautogui.hscroll(a.x2, x=a.x, y=a.y)

        except pyautogui.FailSafeException:
            self.running = False
        except Exception:
            if stop_err:
                self.running = False

    # ── status ticker ────────────────────────────────────────────────────────────

    def _tick(self):
        if not self._recording:
            n = len(self.actions)
            if self.running:
                self._status.configure(
                    text=f"🔴  ВОСПРОИЗВОДИТСЯ  |  действий: {n}  |  [{self._hotkey.upper()}] — стоп",
                    text_color="#e74c3c")
            else:
                self._status.configure(
                    text=f"⚫  Готов  |  действий: {n}  |  F8 — старт  |  F9 — запись",
                    text_color="#666")
        self.after(400, self._tick)

    def _close(self):
        self.running    = False
        self._recording = False
        self._save_settings()
        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.destroy()


# ── Precise sleep (avoids OS scheduler jitter for short waits) ─────────────────

def _precise_sleep(seconds: float):
    if seconds <= 0:
        return
    if seconds < 0.002:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            pass
    else:
        time.sleep(seconds)


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = NyaClicker()
    app.mainloop()
