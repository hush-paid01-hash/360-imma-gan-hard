"""
I/O Processor (IOP) — MIPS R3000A @ 36.864 MHz
------------------------------------------------
The IOP is a secondary processor on the PS2 that handles:
  - CD/DVD drive interface (CDVD)
  - USB/FireWire host controller
  - Memory card access (SIO2)
  - Sound (via SPU2)
  - Game controllers (PAD)
  - SIF (Sub-bus Interface) DMA to/from EE

It runs its own OS (IOPBIOS, loaded from BIOS ROM) and
communicates with the EE via the SIF (Subsystem Interface).

This is a stub IOP — full IOP emulation requires implementing
all IOP modules and the SIF protocol.
"""

import logging
from ..memory.bus import MemoryBus

log = logging.getLogger(__name__)

IOP_RESET_VECTOR = 0xBFC00000


class IOP:
    """
    Minimal IOP stub.

    In a full emulator this would be a complete MIPS R3000A interpreter
    running IOPBIOS and IOP modules (cdvdman, sio2man, padman, etc.).
    The IOP shares physical RAM with the EE via the IOP RAM region.
    """

    def __init__(self, bus: MemoryBus):
        self.bus   = bus
        self.pc    = IOP_RESET_VECTOR
        self.gpr   = [0] * 32
        self.hi    = 0
        self.lo    = 0
        self.cycle = 0
        self._halted = True   # IOP starts halted; EE resets it via SIF

    def reset(self) -> None:
        self.pc = IOP_RESET_VECTOR
        self.gpr = [0] * 32
        self._halted = False
        log.info("IOP reset")

    def step(self) -> None:
        if self._halted:
            return
        # Placeholder: real IOP fetches and executes MIPS R3000A instructions
        # from its own address space (IOP RAM + IOP registers)
        self.cycle += 1

    def halt(self) -> None:
        self._halted = True
        log.info("IOP halted")

    def is_halted(self) -> bool:
        return self._halted
