#!/usr/bin/env python3
"""
NyaClicker — Advanced Auto-Clicker for Windows 10
github.com/xristos-dev/NyaClicker
"""

import sys
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

# ── Safety ─────────────────────────────────────────────────────────────────────
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0

APP_NAME = "NyaClicker"
VERSION  = "1.0.0"
HOTKEY   = "f8"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

class Action:
    TYPES   = ["Клик", "Двойной клик", "ПКМ", "Удержание", "Свайп"]
    BUTTONS = ["left", "right", "middle"]

    def __init__(self):
        self.action_type  = "Клик"
        self.x            = 0
        self.y            = 0
        self.x2           = 100
        self.y2           = 100
        self.delay_ms     = 50      # pause BEFORE this action
        self.hold_ms      = 200     # duration of hold / swipe
        self.button       = "left"
        self.repeat       = 1
        self.enabled      = True

    def to_dict(self):
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d):
        a = cls()
        a.__dict__.update(d)
        return a

    def label(self, idx: int) -> str:
        icons = {
            "Клик": "🖱 ", "Двойной клик": "🖱🖱", "ПКМ": "🖱➡",
            "Удержание": "⏱ ", "Свайп": "↔ ",
        }
        ico = icons.get(self.action_type, "● ")
        en  = "✓" if self.enabled else "✗"
        if self.action_type == "Свайп":
            s = f"({self.x},{self.y}) → ({self.x2},{self.y2})  dur:{self.hold_ms}ms"
        elif self.action_type == "Удержание":
            s = f"({self.x},{self.y})  hold:{self.hold_ms}ms"
        else:
            s = f"({self.x},{self.y})  delay:{self.delay_ms}ms"
        rep = f"  ×{self.repeat}" if self.repeat > 1 else ""
        return f"  {en} {idx:2}. {ico} {self.action_type:<14}  {s}{rep}"


# ──────────────────────────────────────────────────────────────────────────────
# Action edit dialog
# ──────────────────────────────────────────────────────────────────────────────

class ActionDialog(ctk.CTkToplevel):
    def __init__(self, parent, action: Action = None):
        super().__init__(parent)
        self.title("✏  Настройка действия")
        self.geometry("510x530")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus()

        self.result: Action = None
        src = action or Action()

        # ── variables ──────────────────────────────────────────────────────────
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

    # ── layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Type + enabled
        s = self._section("Тип действия")
        row = ctk.CTkFrame(s, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkOptionMenu(row, values=Action.TYPES, variable=self.tv, width=210).pack(side="left")
        ctk.CTkCheckBox(row, text=" Включено", variable=self.ev).pack(side="left", padx=20)

        # Start coords
        s = self._section("Начальная точка  (X, Y)")
        self._coord_row(s, self.xv, self.yv, self._cap_start)

        # Swipe end coords
        s = self._section("Конечная точка  (X2, Y2)  ← только для Свайп")
        self._coord_row(s, self.x2v, self.y2v, self._cap_end)

        # Timing
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

        # Buttons
        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=(8, 14))
        ctk.CTkButton(
            bf, text="✓  Сохранить", width=145, height=38,
            fg_color="#2ecc71", hover_color="#27ae60", command=self._ok
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            bf, text="✗  Отмена", width=145, height=38,
            fg_color="#555", hover_color="#444", command=self.destroy
        ).pack(side="left", padx=8)

    def _section(self, title: str) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=8)
        f.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(
            f, text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FF6B9D"
        ).pack(anchor="w", padx=10, pady=(8, 3))
        return f

    def _coord_row(self, parent, xv, yv, cap_fn):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))
        for lbl, var in [("X:", xv), ("Y:", yv)]:
            ctk.CTkLabel(row, text=lbl, width=24).pack(side="left")
            ctk.CTkEntry(row, textvariable=var, width=82).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="📍 Захват", width=95, height=28,
            fg_color="#e94560", hover_color="#c0392b", command=cap_fn
        ).pack(side="left", padx=6)

    # ── capture ─────────────────────────────────────────────────────────────────

    def _capture(self, xv: tk.StringVar, yv: tk.StringVar):
        """Minimise, wait for a mouse click, fill coords, restore."""
        self.iconify()

        def _run():
            time.sleep(0.5)
            captured = []
            try:
                from pynput import mouse as pym

                def on_click(x, y, button, pressed):
                    if pressed:
                        captured.append((int(x), int(y)))
                        return False  # stop listener

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

    def _cap_start(self): self._capture(self.xv,  self.yv)
    def _cap_end(self):   self._capture(self.x2v, self.y2v)

    # ── save ────────────────────────────────────────────────────────────────────

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
        self.geometry("960x680")
        self.minsize(820, 580)

        self.actions: list[Action] = []
        self.running    = False
        self._thread    = None
        self._hotkey    = HOTKEY

        self._load_neko()
        self._build_ui()
        self._register_hotkey()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._tick()

    # ── assets ──────────────────────────────────────────────────────────────────

    def _load_neko(self):
        try:
            img = Image.open(os.path.join(ASSETS, "neko.png"))
            self._neko_sm = ctk.CTkImage(img.resize((90,  90),  Image.LANCZOS), size=(90,  90))
            self._neko_lg = ctk.CTkImage(img.resize((160, 160), Image.LANCZOS), size=(160, 160))
        except Exception:
            self._neko_sm = self._neko_lg = None

    # ── UI ───────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── sidebar ──────────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=188, corner_radius=0, fg_color="#14142b")
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(8, weight=1)

        if self._neko_sm:
            ctk.CTkLabel(sb, image=self._neko_sm, text="").grid(
                row=0, column=0, pady=(22, 4), padx=49)
        ctk.CTkLabel(
            sb, text=APP_NAME,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#FF6B9D"
        ).grid(row=1, column=0, pady=(0, 2))
        ctk.CTkLabel(
            sb, text=f"v{VERSION}",
            font=ctk.CTkFont(size=10), text_color="#555"
        ).grid(row=2, column=0, pady=(0, 18))

        def nav(row, text, cmd):
            b = ctk.CTkButton(
                sb, text=text, width=165, anchor="w",
                fg_color="transparent", hover_color="#2a2a4e",
                font=ctk.CTkFont(size=13), command=cmd)
            b.grid(row=row, column=0, padx=12, pady=3)
            return b

        nav(3, "⚡  Действия",   lambda: self._show("actions"))
        nav(4, "⚙  Настройки",  lambda: self._show("settings"))
        nav(5, "ℹ  О программе", lambda: self._show("about"))

        self._start_btn = ctk.CTkButton(
            sb, text=f"▶  Старт  [{HOTKEY.upper()}]",
            width=165, height=44,
            fg_color="#2ecc71", hover_color="#27ae60",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle
        )
        self._start_btn.grid(row=9, column=0, padx=12, pady=(0, 22))

        # ── main area ────────────────────────────────────────────────────────────
        self._main = ctk.CTkFrame(self, corner_radius=0, fg_color="#16213e")
        self._main.grid(row=0, column=1, sticky="nsew")
        self._main.grid_columnconfigure(0, weight=1)
        self._main.grid_rowconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkBaseClass] = {}
        self._build_actions_tab()
        self._build_settings_tab()
        self._build_about_tab()
        self._show("actions")

        # ── status bar ───────────────────────────────────────────────────────────
        self._status = ctk.CTkLabel(
            self, text="● Готов", anchor="w", padx=12, height=26,
            fg_color="#0b0b1a", text_color="#666",
            font=ctk.CTkFont(size=11))
        self._status.grid(row=1, column=0, columnspan=2, sticky="ew")

    # ── tabs ─────────────────────────────────────────────────────────────────────

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

        # toolbar
        tb = ctk.CTkFrame(f, fg_color="#1a1a2e", height=54)
        tb.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 5))
        tb.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            tb, text="⚡  Список действий",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FF6B9D"
        ).grid(row=0, column=0, padx=14, sticky="w")

        bf = ctk.CTkFrame(tb, fg_color="transparent")
        bf.grid(row=0, column=1, padx=8)
        for label, color, cmd in [
            ("+ Добавить",  "#e94560", self._add),
            ("✏ Изменить",  "#2980b9", self._edit),
            ("🗑 Удалить",   "#555",    self._delete),
        ]:
            ctk.CTkButton(
                bf, text=label, width=102, height=30,
                fg_color=color, command=cmd
            ).pack(side="left", padx=3, pady=12)

        # listbox
        lf = ctk.CTkFrame(f, fg_color="#111124")
        lf.grid(row=1, column=0, sticky="nsew", padx=14, pady=3)
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(0, weight=1)

        self._lb = tk.Listbox(
            lf, bg="#0d0d20", fg="#ddd",
            selectbackground="#e94560", selectforeground="#fff",
            borderwidth=0, highlightthickness=0,
            font=("Consolas", 11), activestyle="none"
        )
        self._lb.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        sb2 = ctk.CTkScrollbar(lf, command=self._lb.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self._lb.configure(yscrollcommand=sb2.set)
        self._lb.bind("<Double-Button-1>", lambda _: self._edit())

        # bottom bar
        bb = ctk.CTkFrame(f, fg_color="#1a1a2e", height=46)
        bb.grid(row=2, column=0, sticky="ew", padx=14, pady=(3, 12))
        for label, cmd in [("⬆ Вверх", self._up), ("⬇ Вниз", self._down)]:
            ctk.CTkButton(
                bb, text=label, width=90, height=30,
                fg_color="#2c3e50", command=cmd
            ).pack(side="left", padx=5, pady=8)
        ctk.CTkButton(
            bb, text="📂 Загрузить", width=115, height=30,
            fg_color="#2980b9", command=self._load
        ).pack(side="right", padx=5)
        ctk.CTkButton(
            bb, text="💾 Сохранить", width=115, height=30,
            fg_color="#8e44ad", command=self._save
        ).pack(side="right", padx=5)

    # ── settings tab ─────────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        f = ctk.CTkScrollableFrame(self._main, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self._tabs["settings"] = f

        ctk.CTkLabel(
            f, text="⚙  Настройки",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FF6B9D"
        ).grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        def card(row, title):
            c = ctk.CTkFrame(f, fg_color="#1a1a2e", corner_radius=8)
            c.grid(row=row, column=0, sticky="ew", padx=14, pady=5)
            c.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                c, text=title,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#aaa"
            ).grid(row=0, column=0, columnspan=3, padx=14, pady=(10, 4), sticky="w")
            return c

        def row(parent, r, label, var):
            ctk.CTkLabel(parent, text=label, anchor="w").grid(
                row=r, column=0, padx=14, pady=7, sticky="w")
            ctk.CTkEntry(parent, textvariable=var, width=110).grid(
                row=r, column=1, padx=14, pady=7, sticky="w")

        # ── Global ────────────────────────────────────────────────────────────────
        g = card(1, "Глобальные")
        self._sv_loops    = tk.StringVar(value="0")
        self._sv_gdelay   = tk.StringVar(value="0")
        self._sv_variance = tk.StringVar(value="0")
        row(g, 1, "Повторений цикла (0 = ∞):", self._sv_loops)
        row(g, 2, "Доп. задержка между действиями (мс):", self._sv_gdelay)
        row(g, 3, "Случайный разброс задержки (±мс):", self._sv_variance)
        self._sv_stop_err = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            g, text="Остановить при ошибке",
            variable=self._sv_stop_err
        ).grid(row=4, column=0, columnspan=2, padx=14, pady=(4, 12), sticky="w")

        # ── Mouse ─────────────────────────────────────────────────────────────────
        m = card(2, "Мышь")
        self._sv_move_dur = tk.StringVar(value="0")
        row(m, 1, "Длительность движения курсора (сек, 0 = мгновенно):", self._sv_move_dur)
        self._sv_smooth = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            m, text="Плавное перемещение курсора",
            variable=self._sv_smooth
        ).grid(row=2, column=0, columnspan=2, padx=14, pady=(4, 12), sticky="w")

        # ── Hotkey ────────────────────────────────────────────────────────────────
        h = card(3, "Горячая клавиша  Старт / Стоп")
        self._sv_hotkey = tk.StringVar(value=HOTKEY.upper())
        ctk.CTkLabel(h, text="Клавиша:").grid(row=1, column=0, padx=14, pady=7, sticky="w")
        ctk.CTkEntry(h, textvariable=self._sv_hotkey, width=110).grid(
            row=1, column=1, padx=14, sticky="w")
        ctk.CTkButton(
            h, text="Применить", width=100, height=28,
            fg_color="#8e44ad", command=self._apply_hotkey
        ).grid(row=1, column=2, padx=8, pady=(4, 12))

        ctk.CTkButton(
            f, text="💾  Применить настройки", width=210,
            fg_color="#8e44ad", hover_color="#7d3c98",
            command=lambda: self._status.configure(text="● Настройки применены")
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

        ctk.CTkLabel(
            c, text=APP_NAME,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color="#FF6B9D"
        ).pack()
        ctk.CTkLabel(
            c, text=f"Версия {VERSION}",
            font=ctk.CTkFont(size=12), text_color="#666"
        ).pack(pady=2)
        ctk.CTkLabel(
            c, text="Продвинутый автокликер для Windows 10",
            text_color="#999"
        ).pack(pady=4)

        info = ctk.CTkFrame(c, fg_color="#1a1a2e", corner_radius=8)
        info.pack(pady=10, padx=10, fill="x")
        ctk.CTkLabel(
            info, text="🎮  Горячие клавиши",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#FF6B9D"
        ).pack(pady=(10, 2))
        ctk.CTkLabel(
            info,
            text=f"[{HOTKEY.upper()}]  —  Старт / Стоп\n"
                 "[📍 Захват]  —  Кликните по экрану в диалоге\n"
                 "Угол (0, 0)  —  Аварийная остановка (FailSafe)",
            text_color="#ccc", justify="center"
        ).pack(pady=(0, 10))

        ctk.CTkLabel(
            c, text="github.com/xristos-dev/NyaClicker",
            text_color="#444", font=ctk.CTkFont(size=10)
        ).pack(pady=8)

    # ── list helpers ─────────────────────────────────────────────────────────────

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
            title="Сохранить список действий"
        )
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump([a.to_dict() for a in self.actions], fh,
                          ensure_ascii=False, indent=2)
            self._status.configure(text=f"● Сохранено: {os.path.basename(p)}")

    def _load(self):
        p = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            title="Загрузить список действий"
        )
        if p:
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.actions = [Action.from_dict(d) for d in data]
                self._refresh()
                self._status.configure(text=f"● Загружено: {os.path.basename(p)}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    # ── hotkey ───────────────────────────────────────────────────────────────────

    def _register_hotkey(self):
        try:
            keyboard.remove_hotkey(self._hotkey)
        except Exception:
            pass
        keyboard.add_hotkey(self._hotkey, self._toggle)

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
        self._status.configure(text=f"● Горячая клавиша изменена: {new.upper()}")

    # ── runner ───────────────────────────────────────────────────────────────────

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
            fg_color="#e74c3c", hover_color="#c0392b"
        )
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _stop(self):
        self.running = False
        self._start_btn.configure(
            text=f"▶  Старт  [{self._hotkey.upper()}]",
            fg_color="#2ecc71", hover_color="#27ae60"
        )

    def _run_loop(self):
        try:
            max_loops = int(self._sv_loops.get())
            g_delay   = int(self._sv_gdelay.get()) / 1000
            variance  = int(self._sv_variance.get()) / 1000
            move_dur  = float(self._sv_move_dur.get())
            stop_err  = self._sv_stop_err.get()
        except Exception:
            max_loops, g_delay, variance, move_dur, stop_err = 0, 0.0, 0.0, 0.0, True

        loop = 0
        while self.running:
            for action in self.actions:
                if not self.running:
                    break
                if not action.enabled:
                    continue
                self._execute(action, move_dur, stop_err)
                delay = g_delay + (random.uniform(-variance, variance) if variance > 0 else 0)
                if delay > 0:
                    time.sleep(max(0.0, delay))
            loop += 1
            if max_loops > 0 and loop >= max_loops:
                break

        self.after(0, self._stop)

    def _execute(self, a: Action, move_dur: float, stop_err: bool):
        try:
            if a.delay_ms > 0:
                time.sleep(a.delay_ms / 1000)

            for _ in range(a.repeat):
                if not self.running:
                    return

                if a.action_type == "Клик":
                    pyautogui.click(a.x, a.y, button=a.button, duration=move_dur)

                elif a.action_type == "Двойной клик":
                    pyautogui.doubleClick(a.x, a.y, duration=move_dur)

                elif a.action_type == "ПКМ":
                    pyautogui.rightClick(a.x, a.y, duration=move_dur)

                elif a.action_type == "Удержание":
                    pyautogui.moveTo(a.x, a.y, duration=move_dur)
                    pyautogui.mouseDown(button=a.button)
                    time.sleep(max(0.0, a.hold_ms / 1000))
                    pyautogui.mouseUp(button=a.button)

                elif a.action_type == "Свайп":
                    swipe_dur = max(0.05, a.hold_ms / 1000)
                    pyautogui.moveTo(a.x, a.y, duration=move_dur)
                    pyautogui.dragTo(a.x2, a.y2, duration=swipe_dur, button=a.button)

        except pyautogui.FailSafeException:
            self.running = False
        except Exception:
            if stop_err:
                self.running = False

    # ── status ticker ────────────────────────────────────────────────────────────

    def _tick(self):
        n = len(self.actions)
        if self.running:
            self._status.configure(
                text=f"🔴  РАБОТАЕТ  |  действий: {n}  |  [{self._hotkey.upper()}] — стоп",
                text_color="#e74c3c"
            )
        else:
            self._status.configure(
                text=f"⚫  Готов  |  действий: {n}  |  [{self._hotkey.upper()}] — старт",
                text_color="#666"
            )
        self.after(400, self._tick)

    def _close(self):
        self.running = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.destroy()


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = NyaClicker()
    app.mainloop()
