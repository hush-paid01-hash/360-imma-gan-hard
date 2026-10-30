"""
PS2EMU Interactive Debugger
-----------------------------
A GDB-style CLI debugger for the emulator.
Unique feature: step at EE instruction granularity, inspect
VU registers, disassemble GIF packets, dump VRAM regions.

Commands:
  r / run            — run until break
  s / step [N]       — step N instructions (default 1)
  c / continue       — continue until next breakpoint
  b / break ADDR     — set breakpoint at hex address
  d / delete ADDR    — remove breakpoint
  bl / blist         — list breakpoints
  p / print REG      — print register (e.g. "p v0", "p pc", "p cop0[12]")
  x / examine ADDR [COUNT] — examine memory (4 bytes per word)
  dis / disasm ADDR [N]    — disassemble N instructions at ADDR
  regs               — dump all EE registers
  info               — print system status
  q / quit           — exit debugger
"""

import shlex
import logging
from typing import Callable
from .system import PS2System
from .cpu.ee_isa import disassemble

log = logging.getLogger(__name__)

_GPR_ALIASES = {
    "zr":0, "at":1, "v0":2, "v1":3, "a0":4, "a1":5, "a2":6, "a3":7,
    "t0":8, "t1":9, "t2":10,"t3":11,"t4":12,"t5":13,"t6":14,"t7":15,
    "s0":16,"s1":17,"s2":18,"s3":19,"s4":20,"s5":21,"s6":22,"s7":23,
    "t8":24,"t9":25,"k0":26,"k1":27,"gp":28,"sp":29,"fp":30,"ra":31,
}


class Debugger:
    """Interactive debugger shell for PS2EMU."""

    def __init__(self, system: PS2System):
        self.sys        = system
        self._breaks    : set[int] = set()
        self._running   = False
        self._last_cmd  = ""

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def cmdloop(self) -> None:
        print("PS2EMU Debugger — type 'help' or '?' for commands")
        while True:
            try:
                raw = input("(ps2dbg) ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not raw:
                raw = self._last_cmd
            if not raw:
                continue
            self._last_cmd = raw
            try:
                if not self._dispatch(raw):
                    break
            except Exception as e:
                print(f"Error: {e}")

    def _dispatch(self, line: str) -> bool:
        parts = shlex.split(line)
        cmd   = parts[0].lower()
        args  = parts[1:]

        if cmd in ("q", "quit", "exit"):
            return False
        elif cmd in ("?", "help"):
            print(__doc__)
        elif cmd in ("r", "run"):
            self._cmd_run()
        elif cmd in ("s", "step"):
            n = int(args[0]) if args else 1
            self._cmd_step(n)
        elif cmd in ("c", "continue"):
            self._cmd_continue()
        elif cmd in ("b", "break"):
            if args:
                self._breaks.add(int(args[0], 16))
                print(f"Breakpoint set @ 0x{int(args[0],16):08X}")
        elif cmd in ("d", "delete"):
            if args:
                addr = int(args[0], 16)
                self._breaks.discard(addr)
                print(f"Breakpoint removed @ 0x{addr:08X}")
        elif cmd in ("bl", "blist"):
            for a in sorted(self._breaks):
                print(f"  0x{a:08X}")
        elif cmd in ("p", "print"):
            if args:
                self._cmd_print(args[0])
        elif cmd in ("x", "examine"):
            addr  = int(args[0], 16) if args else self.sys.ee.regs.pc
            count = int(args[1]) if len(args) > 1 else 4
            self._cmd_examine(addr, count)
        elif cmd in ("dis", "disasm"):
            addr  = int(args[0], 16) if args else self.sys.ee.regs.pc
            n     = int(args[1]) if len(args) > 1 else 10
            self._cmd_disasm(addr, n)
        elif cmd == "regs":
            print(self.sys.dump_regs())
        elif cmd == "info":
            self._cmd_info()
        elif cmd == "trace":
            on = (args[0].lower() in ("on", "1", "yes")) if args else True
            self.sys.enable_trace(on)
            print(f"Trace {'on' if on else 'off'}")
        else:
            print(f"Unknown command '{cmd}'. Type 'help'.")
        return True

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_step(self, n: int = 1) -> None:
        for _ in range(n):
            self.sys.ee.step()
        pc = self.sys.ee.regs.pc
        word = self.sys.bus.read32(pc)
        print(f"  PC=0x{pc:08X}  {disassemble(word, pc)}")

    def _cmd_continue(self) -> None:
        while True:
            self.sys.ee.step()
            if self.sys.ee.regs.pc in self._breaks:
                pc = self.sys.ee.regs.pc
                print(f"Breakpoint hit @ 0x{pc:08X}")
                word = self.sys.bus.read32(pc)
                print(f"  {disassemble(word, pc)}")
                break

    def _cmd_run(self) -> None:
        print("Running... (Ctrl+C to stop)")
        try:
            while True:
                self.sys.ee.step()
                if self.sys.ee.regs.pc in self._breaks:
                    pc = self.sys.ee.regs.pc
                    print(f"\nBreakpoint hit @ 0x{pc:08X}")
                    break
        except KeyboardInterrupt:
            print(f"\nStopped @ 0x{self.sys.ee.regs.pc:08X}")

    def _cmd_print(self, reg: str) -> None:
        r = self.sys.ee.regs
        reg = reg.lower()
        if reg == "pc":
            print(f"PC = 0x{r.pc:08X}")
        elif reg == "hi":
            print(f"HI = 0x{r.hi:016X}")
        elif reg == "lo":
            print(f"LO = 0x{r.lo:016X}")
        elif reg.startswith("cop0[") and reg.endswith("]"):
            idx = int(reg[5:-1])
            print(f"COP0[{idx}] = 0x{r.cop0[idx]:08X}")
        elif reg in _GPR_ALIASES:
            idx = _GPR_ALIASES[reg]
            print(f"${reg} = 0x{r.get_gpr64(idx):016X}")
        elif reg.startswith("$") and reg[1:] in _GPR_ALIASES:
            idx = _GPR_ALIASES[reg[1:]]
            print(f"${reg[1:]} = 0x{r.get_gpr64(idx):016X}")
        else:
            try:
                idx = int(reg.lstrip("r"))
                print(f"GPR[{idx}] = 0x{r.get_gpr64(idx):016X}")
            except ValueError:
                print(f"Unknown register '{reg}'")

    def _cmd_examine(self, addr: int, count: int) -> None:
        for i in range(count):
            a = addr + i * 4
            v = self.sys.bus.read32(a)
            print(f"  0x{a:08X}: 0x{v:08X}")

    def _cmd_disasm(self, addr: int, n: int) -> None:
        pc = self.sys.ee.regs.pc
        for i in range(n):
            a = addr + i * 4
            w = self.sys.bus.read32(a)
            marker = " <--" if a == pc else ""
            print(f"  0x{a:08X}: {disassemble(w, a)}{marker}")

    def _cmd_info(self) -> None:
        ee = self.sys.ee
        print(f"Frame:    {self.sys._frame}")
        print(f"Cycles:   {self.sys._cycles_run:,}")
        print(f"EE PC:    0x{ee.regs.pc:08X}")
        print(f"IOP halt: {self.sys.iop.is_halted()}")
        print(f"Disc:     {self.sys.cdvd._disc_type:#04x}")
        print(f"INTC:     stat=0x{self.sys.intc.stat:04X}  mask=0x{self.sys.intc.mask:04X}")
        print(f"SIF ctrl: 0x{self.sys.sif.ctrl:08X}")
