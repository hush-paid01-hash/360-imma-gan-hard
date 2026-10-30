"""
PS2 System — ties all components together
------------------------------------------
Wires up the EE CPU, IOP, GS, INTC, Timers, CDVD, and SIF
onto the memory bus, and provides the main emulation loop.
"""

import logging
import time
from .memory.bus import MemoryBus
from .memory.map import BIOS_BASE, BIOS_SIZE, HW_REGS_BASE
from .cpu.ee_cpu import EmotionEngine
from .iop.iop_cpu import IOP
from .iop.sif import SIF, SIF_REG_CTRL, SIF_REG_MSFLG, SIF_REG_SMFLG, SIF_REG_BD6
from .gs.gs import GS
from .hw.timers import EETimers, TIMER_BASE, TIMER_STEP, NUM_TIMERS
from .hw.intc import INTC, INTC_STAT, INTC_MASK, INT_TIM0, INT_VBLANK_S, INT_VBLANK_E
from .cdvd.cdvd import CDVD
from .loader.elf import load_elf

log = logging.getLogger(__name__)

# EE clock: 294.912 MHz  (≈ 294_912_000 Hz)
# We run at effective 1/8 speed for interpreter performance
EE_CLOCK_HZ   = 294_912_000
EE_CYCLES_PER_FRAME = EE_CLOCK_HZ // 60   # ~4.9M cycles/frame (NTSC 60Hz)

# INTC / timer register region
INTC_BASE = 0x1000F000
GS_PRIV_BASE = 0x12000000


class PS2System:
    """
    Top-level PS2 system.

    Usage:
        sys = PS2System()
        sys.load_bios("bios.bin")
        sys.load_disc("game.iso")
        sys.reset()
        sys.run_frame()   # call at 60 Hz
    """

    def __init__(self):
        self.bus    = MemoryBus()
        self.ee     = EmotionEngine(self.bus)
        self.iop    = IOP(self.bus)
        self.gs     = GS()
        self.intc   = INTC()
        self.timers = EETimers()
        self.sif    = SIF()
        self.cdvd   = CDVD()

        self._frame      = 0
        self._cycles_run = 0

        self._wire_bus()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_bios(self, path: str) -> None:
        self.bus.load_bios(path)

    def load_disc(self, path: str) -> None:
        self.cdvd.load_disc(path)

    def reset(self) -> None:
        self.ee.reset()
        self.iop.reset()
        self._frame = 0
        self._cycles_run = 0
        log.info("PS2 system reset — EE PC=0x%08X", self.ee.regs.pc)

    def run_frame(self) -> None:
        """
        Run one video frame worth of EE cycles (~4.9M at 294 MHz / 60 Hz).
        Raises VBlankEvent at end to allow host renderer to flip framebuffer.
        """
        target = EE_CYCLES_PER_FRAME
        ran = 0
        while ran < target:
            batch = min(64, target - ran)
            for _ in range(batch):
                self.ee.step()
            ran += batch
            # Tick timers every 64 EE cycles
            fired = self.timers.tick(batch)
            for ti in fired:
                self.intc.assert_irq(INT_TIM0 + ti)
            # Deliver interrupts to EE COP0 if pending
            self._check_interrupts()

        # VBlank
        self.intc.assert_irq(INT_VBLANK_S)
        self._check_interrupts()
        self.intc.clear_irq(INT_VBLANK_S)
        self.intc.assert_irq(INT_VBLANK_E)
        self._check_interrupts()
        self.intc.clear_irq(INT_VBLANK_E)

        self._frame += 1
        self._cycles_run += target

    def run(self, seconds: float = 1.0) -> None:
        """Run for `seconds` of emulated time (useful for BIOS boot testing)."""
        frames = int(seconds * 60)
        for _ in range(frames):
            self.run_frame()
        log.info("Ran %d frames (%.2f s emulated)", frames, frames / 60.0)

    def enable_trace(self, on: bool = True) -> None:
        self.ee.trace_enabled = on

    def dump_regs(self) -> str:
        return self.ee.regs.dump()

    # ------------------------------------------------------------------
    # Game ELF loading (bypass BIOS boot for testing)
    # ------------------------------------------------------------------

    def load_game_elf_direct(self, elf_data: bytes) -> None:
        """
        Load a game ELF directly into RAM and set EE PC to its entry point,
        bypassing the BIOS boot sequence. Useful for homebrew / testing.
        """
        entry = load_elf(elf_data, self.bus)
        self.ee.regs.pc = entry
        log.info("ELF loaded, PC → 0x%08X", entry)

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _wire_bus(self) -> None:
        """Register all hardware register read/write handlers on the bus."""

        # INTC
        self.bus.register_hw(INTC_STAT,
            lambda a: self.intc.read(a),
            lambda a, v: self.intc.write(a, v))
        self.bus.register_hw(INTC_MASK,
            lambda a: self.intc.read(a),
            lambda a, v: self.intc.write(a, v))

        # Timers T0–T3
        for i in range(NUM_TIMERS):
            base = TIMER_BASE + i * TIMER_STEP
            for off in (0x00, 0x10, 0x20, 0x30):
                addr = base + off
                self.bus.register_hw(addr,
                    lambda a: self.timers.read(a),
                    lambda a, v: self.timers.write(a, v))

        # SIF registers
        for addr in (SIF_REG_CTRL, SIF_REG_MSFLG, SIF_REG_SMFLG, SIF_REG_BD6):
            self.bus.register_hw(addr,
                lambda a: self.sif.ee_read(a),
                lambda a, v: self.sif.ee_write(a, v))

        # GS privileged registers — sit in a different region (0x12000000)
        # We don't use register_hw here (it only covers 0x1000xxxx).
        # Instead patch _read_bytes/_write_bytes directly via the bus GS path
        # (already handled in MemoryBus for GS_REGS_BASE region).

    def _check_interrupts(self) -> None:
        """Deliver INTC interrupt to EE if enabled."""
        from .cpu.ee_regs import COP0_STATUS, SR_IE, SR_EXL, SR_ERL, COP0_CAUSE
        status = self.ee.regs.cop0[COP0_STATUS]
        if (status & SR_IE) and not (status & (SR_EXL | SR_ERL)):
            if self.intc.pending():
                # Assert IP2 (INTC → EE COP0 INT2)
                self.ee.regs.cop0[COP0_CAUSE] |= (1 << 10)
                self.ee._exception(0, self.ee.regs.pc)
