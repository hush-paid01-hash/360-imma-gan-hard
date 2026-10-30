"""
PS2 Memory Bus
--------------
Central interconnect between EE CPU, GS, IOP, and hardware registers.
Handles physical address routing to the correct memory region.
"""

import struct
import logging
from typing import Optional, Callable
from .map import (
    phys_addr,
    EE_RAM_BASE, EE_RAM_SIZE,
    SCRATCHPAD_BASE, SCRATCHPAD_SIZE,
    HW_REGS_BASE, HW_REGS_SIZE,
    VU0_CODE_BASE, VU0_CODE_SIZE,
    VU0_DATA_BASE, VU0_DATA_SIZE,
    VU1_CODE_BASE, VU1_CODE_SIZE,
    VU1_DATA_BASE, VU1_DATA_SIZE,
    GS_REGS_BASE, GS_REGS_SIZE,
    IOP_RAM_BASE, IOP_RAM_SIZE,
    BIOS_BASE, BIOS_SIZE,
)

log = logging.getLogger(__name__)


class MemoryBus:
    """
    Unified memory bus implementing the PS2 physical address space.

    Regions are backed by bytearrays (fast, mutable) except for BIOS
    which is loaded from file and treated as read-only after init.
    """

    def __init__(self):
        self.ee_ram      = bytearray(EE_RAM_SIZE)
        self.scratchpad  = bytearray(SCRATCHPAD_SIZE)
        self.iop_ram     = bytearray(IOP_RAM_SIZE)
        self.bios        = bytearray(BIOS_SIZE)
        self.vu0_code    = bytearray(VU0_CODE_SIZE)
        self.vu0_data    = bytearray(VU0_DATA_SIZE)
        self.vu1_code    = bytearray(VU1_CODE_SIZE)
        self.vu1_data    = bytearray(VU1_DATA_SIZE)

        # Hardware register handlers: addr -> (read_fn, write_fn)
        self._hw_handlers: dict[int, tuple[Optional[Callable], Optional[Callable]]] = {}

    def load_bios(self, path: str) -> None:
        """Load BIOS ROM image from file (must be exactly 4 MB)."""
        with open(path, "rb") as f:
            data = f.read()
        if len(data) != BIOS_SIZE:
            raise ValueError(
                f"BIOS must be {BIOS_SIZE:#x} bytes, got {len(data):#x}"
            )
        self.bios[:] = data
        log.info("BIOS loaded from %s (%d KB)", path, len(data) // 1024)

    def register_hw(self, addr: int,
                    read_fn: Optional[Callable] = None,
                    write_fn: Optional[Callable] = None) -> None:
        self._hw_handlers[addr] = (read_fn, write_fn)

    # ------------------------------------------------------------------
    # Core read/write — all accesses go through here
    # ------------------------------------------------------------------

    def read(self, vaddr: int, size: int) -> int:
        pa = phys_addr(vaddr)
        data = self._read_bytes(pa, size)
        fmts = {1: "<B", 2: "<H", 4: "<I", 8: "<Q", 16: "<QQ"}
        if size == 16:
            lo, hi = struct.unpack("<QQ", data)
            return (hi << 64) | lo
        return struct.unpack(fmts[size], data)[0]

    def write(self, vaddr: int, value: int, size: int) -> None:
        pa = phys_addr(vaddr)
        fmts = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}
        if size == 16:
            data = struct.pack("<QQ", value & 0xFFFFFFFFFFFFFFFF, value >> 64)
        else:
            data = struct.pack(fmts[size], value & ((1 << size * 8) - 1))
        self._write_bytes(pa, data)

    def read8(self, vaddr: int) -> int:  return self.read(vaddr, 1)
    def read16(self, vaddr: int) -> int: return self.read(vaddr, 2)
    def read32(self, vaddr: int) -> int: return self.read(vaddr, 4)
    def read64(self, vaddr: int) -> int: return self.read(vaddr, 8)
    def read128(self, vaddr: int) -> int: return self.read(vaddr, 16)

    def write8(self, vaddr: int, v: int) -> None:  self.write(vaddr, v, 1)
    def write16(self, vaddr: int, v: int) -> None: self.write(vaddr, v, 2)
    def write32(self, vaddr: int, v: int) -> None: self.write(vaddr, v, 4)
    def write64(self, vaddr: int, v: int) -> None: self.write(vaddr, v, 8)
    def write128(self, vaddr: int, v: int) -> None: self.write(vaddr, v, 16)

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    def _region_of(self, pa: int):
        if EE_RAM_BASE <= pa < EE_RAM_BASE + EE_RAM_SIZE:
            return self.ee_ram, pa - EE_RAM_BASE
        if SCRATCHPAD_BASE <= pa < SCRATCHPAD_BASE + SCRATCHPAD_SIZE:
            return self.scratchpad, pa - SCRATCHPAD_BASE
        if BIOS_BASE <= pa < BIOS_BASE + BIOS_SIZE:
            return self.bios, pa - BIOS_BASE
        if IOP_RAM_BASE <= pa < IOP_RAM_BASE + IOP_RAM_SIZE:
            return self.iop_ram, pa - IOP_RAM_BASE
        if VU0_CODE_BASE <= pa < VU0_CODE_BASE + VU0_CODE_SIZE:
            return self.vu0_code, pa - VU0_CODE_BASE
        if VU0_DATA_BASE <= pa < VU0_DATA_BASE + VU0_DATA_SIZE:
            return self.vu0_data, pa - VU0_DATA_BASE
        if VU1_CODE_BASE <= pa < VU1_CODE_BASE + VU1_CODE_SIZE:
            return self.vu1_code, pa - VU1_CODE_BASE
        if VU1_DATA_BASE <= pa < VU1_DATA_BASE + VU1_DATA_SIZE:
            return self.vu1_data, pa - VU1_DATA_BASE
        return None, 0

    def _read_bytes(self, pa: int, size: int) -> bytes:
        # Hardware registers — routed to registered handlers
        if HW_REGS_BASE <= pa < HW_REGS_BASE + HW_REGS_SIZE:
            aligned = pa & ~0x3
            read_fn, _ = self._hw_handlers.get(aligned, (None, None))
            if read_fn:
                return struct.pack("<I", read_fn(aligned) & 0xFFFFFFFF)
            log.debug("Unhandled HW read @ 0x%08X", pa)
            return b"\x00" * size
        if GS_REGS_BASE <= pa < GS_REGS_BASE + GS_REGS_SIZE:
            log.debug("GS reg read @ 0x%08X", pa)
            return b"\x00" * size

        region, offset = self._region_of(pa)
        if region is None:
            log.warning("Unmapped read @ 0x%08X", pa)
            return b"\x00" * size
        return bytes(region[offset:offset + size])

    def _write_bytes(self, pa: int, data: bytes) -> None:
        if HW_REGS_BASE <= pa < HW_REGS_BASE + HW_REGS_SIZE:
            aligned = pa & ~0x3
            _, write_fn = self._hw_handlers.get(aligned, (None, None))
            if write_fn:
                val = struct.unpack("<I", data[:4].ljust(4, b"\x00"))[0]
                write_fn(aligned, val)
            else:
                log.debug("Unhandled HW write @ 0x%08X = %s", pa, data.hex())
            return
        if GS_REGS_BASE <= pa < GS_REGS_BASE + GS_REGS_SIZE:
            log.debug("GS reg write @ 0x%08X = %s", pa, data.hex())
            return
        # BIOS is read-only
        if BIOS_BASE <= pa < BIOS_BASE + BIOS_SIZE:
            log.warning("Write to BIOS ROM @ 0x%08X (ignored)", pa)
            return

        region, offset = self._region_of(pa)
        if region is None:
            log.warning("Unmapped write @ 0x%08X", pa)
            return
        region[offset:offset + len(data)] = data
