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

        self.listbox = tk.Listbox(self, bg=CARD, fg=FG, selectbackground=ACCENT,
                                  selectforeground=BG, bd=0, highlightthickness=0,
                                  font=("Courier", 12), activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=20)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.play())
        self._btn(self, "▶  PLAY", self.play, big=True).pack(pady=14)
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
        self.games = engine.scan_games(self.cfg.get("folder", ""))
        self.listbox.delete(0, "end")
        for g in self.games:
            self.listbox.insert("end", f"  {g.stem}")
        eng = engine.find_engine(self.cfg.get("engine"))
        self.status.config(text=f"engine: {eng or 'NOT FOUND'}   "
                                f"bios: {'set' if self.cfg.get('bios') else 'default'}   "
                                f"games: {len(self.games)}")

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

    def play(self):
        sel = self.listbox.curselection()
        eng = engine.find_engine(self.cfg.get("engine"))
        if not eng:
            return messagebox.showerror("Engine missing",
                                        "Install PCSX2 (pcsx2.net) and select it via ENGINE.")
        if not sel:
            return messagebox.showinfo("Pick a game", "Select a game first.")
        try:
            engine.launch(eng, str(self.games[sel[0]]), bios=self.cfg.get("bios"))
        except (OSError, RuntimeError) as e:
            messagebox.showerror("Launch failed", str(e))


if __name__ == "__main__":
    App().mainloop()
