"""Bridge to the PCSX2 engine (GPLv3, installed separately by the user)."""
import os
import shutil
import subprocess
from pathlib import Path

GAME_EXTS = {".iso", ".bin", ".chd", ".cso", ".gz", ".elf", ".isz"}
ENGINE_NAMES = ("pcsx2-qt", "pcsx2", "PCSX2", "pcsx2-qt.AppImage")


def find_engine(explicit: str | None = None) -> str | None:
    """Locate the PCSX2 executable: explicit path, $PCSX2_PATH, then PATH."""
    for c in (explicit, os.environ.get("PCSX2_PATH")):
        if c and Path(c).is_file():
            return str(c)
    for name in ENGINE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def scan_games(folder: str) -> list[Path]:
    root = Path(folder).expanduser()
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in GAME_EXTS)


def build_command(engine: str, game: str, bios: str | None = None,
                  fullscreen: bool = True, fast_boot: bool = True) -> list[str]:
    cmd = [engine, "-batch"]
    if fullscreen:
        cmd.append("-fullscreen")
    cmd.append("-fastboot" if fast_boot else "-slowboot")
    # PCSX2's "-bios" boots the BIOS shell and ignores the disc, so the BIOS is
    # never passed here; it is taken from PCSX2's own BIOS folder setting.
    if Path(game).suffix.lower() == ".elf":
        cmd += ["-elf", game]
    else:
        cmd += ["--", game]
    return cmd


def launch(engine: str, game: str, wait: float = 3.0, **kw) -> subprocess.Popen:
    if not Path(game).is_file():
        raise FileNotFoundError(game)
    proc = subprocess.Popen(build_command(engine, game, **kw),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        return proc  # still running: started fine
    err = (proc.stderr.read() or b"").decode(errors="replace").strip()
    raise RuntimeError(f"Engine exited early (code {proc.returncode}). {err[-400:]}")
