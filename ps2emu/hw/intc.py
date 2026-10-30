"""
EE Interrupt Controller (INTC)
--------------------------------
The INTC routes hardware interrupts to the EE COP0.
It has two registers at 0x1000F000:

  INTC_STAT (0x1000F000): interrupt status (R/W — write 1 to clear)
  INTC_MASK (0x1000F010): interrupt enable mask (R/W — write 1 to toggle)

Interrupt bits (INTC_STAT):
  bit 0:  GS          — graphics synthesizer
  bit 1:  SBUS        — sub-bus (SIF)
  bit 2:  VBLANK_S    — VBlank start
  bit 3:  VBLANK_E    — VBlank end
  bit 4:  VIF0        — VIF0 interrupt
  bit 5:  VIF1        — VIF1 interrupt
  bit 6:  VU0         — VU0 end-of-micro
  bit 7:  VU1         — VU1 end-of-micro
  bit 8:  IPU         — image processing unit
  bit 9:  TIM0        — timer 0
  bit 10: TIM1        — timer 1
  bit 11: TIM2        — timer 2
  bit 12: TIM3        — timer 3
  bit 13: SFIFO       — scratch FIFO
  bit 14: VU0WD       — VU0 watchdog
"""

import logging

log = logging.getLogger(__name__)

INTC_STAT = 0x1000F000
INTC_MASK = 0x1000F010

INT_GS       = 0
INT_SBUS     = 1
INT_VBLANK_S = 2
INT_VBLANK_E = 3
INT_VIF0     = 4
INT_VIF1     = 5
INT_VU0      = 6
INT_VU1      = 7
INT_IPU      = 8
INT_TIM0     = 9
INT_TIM1     = 10
INT_TIM2     = 11
INT_TIM3     = 12


class INTC:
    """EE Interrupt Controller."""

    def __init__(self):
        self.stat = 0
        self.mask = 0

    def assert_irq(self, bit: int) -> None:
        self.stat |= (1 << bit)

    def clear_irq(self, bit: int) -> None:
        self.stat &= ~(1 << bit)

    def pending(self) -> bool:
        return bool(self.stat & self.mask)

    def read(self, addr: int) -> int:
        if addr == INTC_STAT: return self.stat
        if addr == INTC_MASK: return self.mask
        return 0

    def write(self, addr: int, val: int) -> None:
        if addr == INTC_STAT:
            self.stat &= ~val   # write 1 to clear
        elif addr == INTC_MASK:
            self.mask ^= val    # write 1 to toggle
        log.debug("INTC write 0x%08X = 0x%08X  stat=0x%04X mask=0x%04X",
                  addr, val, self.stat, self.mask)
