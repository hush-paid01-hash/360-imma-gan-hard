"""
EE Hardware Timers (T0–T3)
---------------------------
The PS2 EE has 4 general-purpose timers each with:
  - COUNT register (16-bit, auto-wraps)
  - MODE register (controls clock source, gate, compare enable, etc.)
  - COMP register (compare value, generates interrupt when COUNT == COMP)
  - HOLD register (captures COUNT on gate event)

Timer register layout (per timer, base = 0x10000000 + n*0x800):
  offset 0x00: COUNT (R/W, 16-bit)
  offset 0x10: MODE  (R/W)
  offset 0x20: COMP  (R/W, 16-bit)
  offset 0x30: HOLD  (R/O, 16-bit)

MODE bits:
  [2:0]  CLKS  clock select (0=bus/2, 1=bus/16, 2=bus/256, 3=h-blank)
  [3]    GATE  gate enable
  [4]    GATS  gate signal select (0=h-blank, 1=v-blank)
  [5]    GATM  gate mode (0=reset on low, 1=reset on high, 2/3=gate)
  [6]    ZRET  zero return (1=reset COUNT when == COMP)
  [7]    CUE   count-up enable
  [8]    CMPE  compare interrupt enable
  [9]    OVFE  overflow interrupt enable
  [10]   EQUF  equal flag (1=COUNT matched COMP since last clear)
  [11]   OVFF  overflow flag (1=COUNT overflowed since last clear)
"""

import logging

log = logging.getLogger(__name__)

NUM_TIMERS = 4
TIMER_BASE = 0x10000000
TIMER_STEP = 0x800


class Timer:
    __slots__ = ("count", "mode", "comp", "hold", "_accum")

    def __init__(self):
        self.count  = 0
        self.mode   = 0
        self.comp   = 0
        self.hold   = 0
        self._accum = 0   # fractional cycle accumulator

    @property
    def enabled(self) -> bool:
        return bool(self.mode & (1 << 7))  # CUE

    @property
    def clk_div(self) -> int:
        clks = self.mode & 0x7
        return [2, 16, 256, 1][clks]   # 3=h-blank treated as /1 approx

    def tick(self, cycles: int) -> bool:
        """Advance timer by `cycles` EE bus cycles. Returns True if INT."""
        if not self.enabled:
            return False
        self._accum += cycles
        steps = self._accum // self.clk_div
        self._accum %= self.clk_div
        if steps == 0:
            return False

        fire_int = False
        for _ in range(steps):
            self.count = (self.count + 1) & 0xFFFF
            # Compare match
            if (self.mode & (1 << 8)) and self.count == self.comp:
                self.mode |= (1 << 10)   # EQUF
                fire_int = True
                if self.mode & (1 << 6):  # ZRET
                    self.count = 0
            # Overflow
            if self.count == 0:
                if self.mode & (1 << 9):  # OVFE
                    self.mode |= (1 << 11)  # OVFF
                    fire_int = True
        return fire_int


class EETimers:
    """Four EE hardware timers with memory-mapped register interface."""

    def __init__(self):
        self.timers = [Timer() for _ in range(NUM_TIMERS)]
        self._int_pending = [False] * NUM_TIMERS

    def tick(self, cycles: int) -> list[int]:
        """Advance all timers. Returns list of timer indices that fired INT."""
        fired = []
        for i, t in enumerate(self.timers):
            if t.tick(cycles):
                self._int_pending[i] = True
                fired.append(i)
        return fired

    def read(self, addr: int) -> int:
        idx = (addr - TIMER_BASE) // TIMER_STEP
        off = addr & 0xFF
        if idx < 0 or idx >= NUM_TIMERS:
            return 0
        t = self.timers[idx]
        if off == 0x00: return t.count
        if off == 0x10: return t.mode
        if off == 0x20: return t.comp
        if off == 0x30: return t.hold
        return 0

    def write(self, addr: int, val: int) -> None:
        idx = (addr - TIMER_BASE) // TIMER_STEP
        off = addr & 0xFF
        if idx < 0 or idx >= NUM_TIMERS:
            return
        t = self.timers[idx]
        if off == 0x00:
            t.count = val & 0xFFFF
        elif off == 0x10:
            # Writing to MODE clears EQUF/OVFF if writing 1 to them
            cleared = val & 0xC00
            t.mode = (val & ~0xC00) | (t.mode & 0xC00 & ~cleared)
        elif off == 0x20:
            t.comp = val & 0xFFFF
        log.debug("Timer%d write off=0x%02X val=0x%04X", idx, off, val)
