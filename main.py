#!/usr/bin/env python3
"""
PS2EMU — Command-line entry point
==================================

Usage:
  python main.py --bios bios.bin --disc game.iso [options]
  python main.py --bios bios.bin --elf homebrew.elf
  python main.py --bios bios.bin --disc game.iso --debug

Options:
  --bios PATH      Path to PS2 BIOS ROM (4 MB, required)
  --disc PATH      Path to PS2 game ISO image
  --elf PATH       Load ELF directly (bypasses BIOS boot)
  --debug          Start in interactive debugger
  --trace          Enable instruction trace (verbose)
  --frames N       Run N frames then exit (default: run forever)
  --headless       No display window (useful for CI / testing)
  --scale N        Window scale factor (default: 2)

Notes:
  - You must supply your own legally-obtained PS2 BIOS dump.
  - Game ISO files must be your own legal backups.
  - DualShock2 keyboard mapping (port 1):
      Arrow keys = D-pad    Z/X/A/S = Cross/Circle/Square/Triangle
      Q/W = L1/L2           E/R = R1/R2
      Enter = Start         RShift = Select
"""

import sys
import os
import argparse
import logging
import time

from ps2emu.system import PS2System
from ps2emu.debugger import Debugger
from ps2emu.display.sdl_display import SDLDisplay
from ps2emu.input.pad import PAD

try:
    import pygame
    _PYGAME = True
except ImportError:
    _PYGAME = False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ps2emu",
        description="PS2EMU — PlayStation 2 Emulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--bios",     required=True, metavar="PATH", help="BIOS ROM file (4 MB)")
    p.add_argument("--disc",     metavar="PATH", help="Game ISO image")
    p.add_argument("--elf",      metavar="PATH", help="ELF executable (direct boot)")
    p.add_argument("--debug",    action="store_true", help="Start interactive debugger")
    p.add_argument("--trace",    action="store_true", help="Enable EE instruction trace")
    p.add_argument("--frames",   type=int, default=0, metavar="N",
                   help="Run N frames then exit (0 = run forever)")
    p.add_argument("--headless", action="store_true", help="Disable display window")
    p.add_argument("--scale",    type=int, default=2, metavar="N", help="Window scale (default 2)")
    p.add_argument("--log",      default="INFO",
                   choices=["DEBUG","INFO","WARNING","ERROR"],
                   help="Log level (default: INFO)")
    return p


def main() -> int:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("ps2emu.main")

    # ------------------------------------------------------------------ #
    # Validate BIOS
    # ------------------------------------------------------------------ #
    if not os.path.isfile(args.bios):
        print(f"Error: BIOS file '{args.bios}' not found.", file=sys.stderr)
        print("You must provide a legally-obtained PS2 BIOS dump (4 MB).", file=sys.stderr)
        return 1

    bios_size = os.path.getsize(args.bios)
    if bios_size != 0x400000:
        print(f"Error: BIOS must be 4,194,304 bytes, got {bios_size}.", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------ #
    # Build system
    # ------------------------------------------------------------------ #
    sys_ps2 = PS2System()

    log.info("Loading BIOS from '%s'", args.bios)
    sys_ps2.load_bios(args.bios)

    if args.disc:
        if not os.path.isfile(args.disc):
            print(f"Error: disc image '{args.disc}' not found.", file=sys.stderr)
            return 1
        log.info("Loading disc '%s'", args.disc)
        sys_ps2.load_disc(args.disc)

    if args.elf:
        if not os.path.isfile(args.elf):
            print(f"Error: ELF file '{args.elf}' not found.", file=sys.stderr)
            return 1
        log.info("Direct-loading ELF '%s'", args.elf)
        with open(args.elf, "rb") as f:
            elf_data = f.read()
        sys_ps2.load_game_elf_direct(elf_data)

    if args.trace:
        sys_ps2.enable_trace(True)

    sys_ps2.reset()

    # ------------------------------------------------------------------ #
    # Debug mode
    # ------------------------------------------------------------------ #
    if args.debug:
        dbg = Debugger(sys_ps2)
        dbg.cmdloop()
        return 0

    # ------------------------------------------------------------------ #
    # Run loop with display
    # ------------------------------------------------------------------ #
    pad = PAD()
    display: SDLDisplay | None = None

    if not args.headless and _PYGAME:
        display = SDLDisplay(
            width=640, height=448,
            title="PS2EMU",
            scale=args.scale,
        )
    else:
        log.info("Running headless (no display)")

    frame_target = 1.0 / 60.0
    frame_num    = 0
    fps_timer    = time.monotonic()
    fps_frames   = 0

    try:
        while True:
            t0 = time.monotonic()

            # --- Input ---
            if display:
                if not display.poll_events():
                    log.info("Window closed — exiting")
                    break
                if _PYGAME:
                    keys = pygame.key.get_pressed()
                    for name, btn in {
                        "up":Btn.UP,"down":Btn.DOWN,"left":Btn.LEFT,"right":Btn.RIGHT,
                    }.items() if False else []:   # placeholder — see pad.py
                        pass

            # --- Emulate one frame ---
            sys_ps2.run_frame()
            frame_num += 1
            fps_frames += 1

            # --- Display ---
            if display:
                gs   = sys_ps2.gs
                fb_base, fb_w, fb_h, psm = gs.get_framebuffer(0)
                display.blit_framebuffer(
                    bytes(gs.vram), fb_base, fb_w, fb_h, psm
                )
                # FPS counter
                now = time.monotonic()
                if now - fps_timer >= 1.0:
                    fps = fps_frames / (now - fps_timer)
                    display.set_title(f"PS2EMU  —  {fps:.1f} fps  (frame {frame_num})")
                    fps_timer  = now
                    fps_frames = 0
                display.flip()

            # --- Frame limit (don't burn CPU in headless mode) ---
            elapsed = time.monotonic() - t0
            if elapsed < frame_target:
                time.sleep(frame_target - elapsed)

            # --- Exit after N frames ---
            if args.frames and frame_num >= args.frames:
                log.info("Ran %d frames — done", frame_num)
                break

    except KeyboardInterrupt:
        log.info("Interrupted after %d frames", frame_num)
    finally:
        if display:
            display.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
