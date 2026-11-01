"""Custom 'Hush Emulator' frontend: dark carbon + neon-lime card list."""
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from launcher import engine

CFG = Path.home() / ".hush_emulator.json"
BG, CARD, ACCENT, FG, DIM = "#0b0d10", "#161a20", "#b6ff3c", "#e8ecf1", "#6b7480"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HUSH EMULATOR")
        self.geometry("820x560")
        self.configure(bg=BG)
        self.cfg = json.loads(CFG.read_text()) if CFG.exists() else {}
        self.games: list[Path] = []

        tk.Label(self, text="HUSH EMULATOR", bg=BG, fg=ACCENT,
                 font=("Courier", 26, "bold")).pack(anchor="w", padx=20, pady=(16, 0))
        self.status = tk.Label(self, bg=BG, fg=DIM, font=("Courier", 10))
        self.status.pack(anchor="w", padx=20)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=20, pady=10)
        for text, cmd in (("GAMES FOLDER", self.pick_folder), ("BIOS", self.pick_bios),
                          ("ENGINE", self.pick_engine)):
            self._btn(bar, text, cmd).pack(side="left", padx=(0, 8))

        opts = tk.Frame(self, bg=BG)
        opts.pack(fill="x", padx=20)
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        tk.Entry(opts, textvariable=self.search, bg=CARD, fg=FG, insertbackground=FG,
                 bd=0, font=("Courier", 11)).pack(side="left", fill="x", expand=True,
                                                  ipady=4, padx=(0, 8))
        self.view = tk.StringVar(value="all")
        for text, val in (("ALL", "all"), ("RECENT", "recent"), ("FAVORITES", "favorites")):
            tk.Radiobutton(opts, text=text, value=val, variable=self.view, command=self.refresh,
                           indicatoron=False, bg=CARD, fg=FG, selectcolor=ACCENT, bd=0,
                           font=("Courier", 9, "bold"), padx=8, pady=4).pack(side="left", padx=2)
        self.fullscreen = tk.BooleanVar(value=self.cfg.get("fullscreen", True))
        self.fastboot = tk.BooleanVar(value=self.cfg.get("fastboot", True))
        for text, var in (("FULLSCREEN", self.fullscreen), ("FAST BOOT", self.fastboot)):
            tk.Checkbutton(opts, text=text, variable=var, bg=BG, fg=FG, selectcolor=CARD,
                           activebackground=BG, activeforeground=ACCENT,
                           font=("Courier", 9, "bold")).pack(side="left", padx=4)

        self.listbox = tk.Listbox(self, bg=CARD, fg=FG, selectbackground=ACCENT,
                                  selectforeground=BG, bd=0, highlightthickness=0,
                                  font=("Courier", 12), activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=20)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.play())
        self.listbox.bind("<Return>", lambda _e: self.play())
        self.listbox.bind("f", lambda _e: self.toggle_fav())
        row = tk.Frame(self, bg=BG)
        row.pack(pady=14)
        self._btn(row, "▶  PLAY", self.play, big=True).pack(side="left", padx=6)
        self._btn(row, "★ FAVORITE", self.toggle_fav).pack(side="left", padx=6)
        self.refresh()

    def _btn(self, parent, text, cmd, big=False):
        return tk.Button(parent, text=text, command=cmd, bg=ACCENT if big else CARD,
                         fg=BG if big else FG, bd=0, relief="flat",
                         font=("Courier", 14 if big else 10, "bold"),
                         padx=18 if big else 10, pady=6, activebackground=FG)

    def _set(self, key, value):
        self.cfg[key] = value
        CFG.write_text(json.dumps(self.cfg))
        self.refresh()

    def refresh(self):
        allg = engine.scan_games(self.cfg.get("folder", ""))
        favs = self.cfg.get("favorites", [])
        self.games = engine.filter_games(allg, self.search.get(), favs,
                                         self.cfg.get("recent", []), self.view.get())
        self.listbox.delete(0, "end")
        for g in self.games:
            self.listbox.insert("end", f"{'★' if str(g) in favs else ' '} {g.stem}")
        eng = engine.find_engine(self.cfg.get("engine"))
        self.status.config(text=f"engine: {eng or 'NOT FOUND'}   "
                                f"bios: {'set' if self.cfg.get('bios') else 'default'}   "
                                f"games: {len(self.games)}/{len(allg)}")

    def pick_folder(self):
        d = filedialog.askdirectory()
        if d:
            self._set("folder", d)

    def pick_bios(self):
        f = filedialog.askopenfilename(title="PS2 BIOS (your own dump)")
        if f:
            self._set("bios", f)

    def pick_engine(self):
        f = filedialog.askopenfilename(title="PCSX2 executable")
        if f:
            self._set("engine", f)

    def toggle_fav(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = str(self.games[sel[0]])
        favs = [f for f in self.cfg.get("favorites", []) if f != key]
        if len(favs) == len(self.cfg.get("favorites", [])):
            favs.append(key)
        self._set("favorites", favs)
        self.listbox.selection_set(sel[0])

    def play(self):
        sel = self.listbox.curselection()
        eng = engine.find_engine(self.cfg.get("engine"))
        if not eng:
            return messagebox.showerror("Engine missing",
                                        "Install PCSX2 (pcsx2.net) and select it via ENGINE.")
        if not sel:
            return messagebox.showinfo("Pick a game", "Select a game first.")
        try:
            game = str(self.games[sel[0]])
            engine.launch(eng, game, fullscreen=self.fullscreen.get(),
                          fast_boot=self.fastboot.get())
            self.cfg.update(fullscreen=self.fullscreen.get(), fastboot=self.fastboot.get())
            self._set("recent", engine.push_recent(self.cfg.get("recent", []), game))
        except (OSError, RuntimeError) as e:
            messagebox.showerror("Launch failed", str(e))


if __name__ == "__main__":
    App().mainloop()
