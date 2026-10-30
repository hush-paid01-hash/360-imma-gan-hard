"""
SIF — Subsystem Interface
--------------------------
The SIF is the DMA channel between the EE and IOP.
It provides two unidirectional DMA channels:
  SIF0: IOP → EE  (used for IOP responses, pad/mc data)
  SIF1: EE  → IOP (used for EE commands to IOP modules)

The EE can send RPC (Remote Procedure Call) packets to IOP
modules over SIF1. IOP replies over SIF0.

SIF registers (EE side, 0x1000F200–0x1000F260):
  MSFLG  (0x1000F220): main → sub flags
  SMFLG  (0x1000F230): sub  → main flags
  CTRL   (0x1000F200): control (bit 0 = SIF reset)
  BD6    (0x1000F260): unknown bootstrap

This module tracks SIF state and routes RPC calls to
registered IOP module handlers.
"""

import logging
import struct
from typing import Callable

log = logging.getLogger(__name__)

SIF_REG_CTRL  = 0x1000F200
SIF_REG_MSFLG = 0x1000F220
SIF_REG_SMFLG = 0x1000F230
SIF_REG_BD6   = 0x1000F260


class SIF:
    """SIF DMA bridge between EE and IOP."""

    def __init__(self):
        self.msflg = 0   # main → sub flags
        self.smflg = 0   # sub  → main flags
        self.ctrl  = 0
        self._rpc_handlers: dict[int, Callable] = {}

    def register_rpc(self, module_id: int, handler: Callable) -> None:
        """Register an IOP RPC module handler."""
        self._rpc_handlers[module_id] = handler

    def ee_read(self, addr: int) -> int:
        if addr == SIF_REG_CTRL:  return self.ctrl
        if addr == SIF_REG_MSFLG: return self.msflg
        if addr == SIF_REG_SMFLG: return self.smflg
        if addr == SIF_REG_BD6:   return 0
        log.debug("SIF unknown read @ 0x%08X", addr)
        return 0

    def ee_write(self, addr: int, val: int) -> None:
        if addr == SIF_REG_CTRL:
            self.ctrl = val
            if val & 0x100:   # EE requesting IOP reset
                log.info("SIF: EE requested IOP reset")
            return
        if addr == SIF_REG_MSFLG:
            self.msflg |= val
            return
        if addr == SIF_REG_SMFLG:
            self.smflg &= ~val   # writing 1 clears bits
            return
        log.debug("SIF unknown write @ 0x%08X = 0x%08X", addr, val)
