"""
PS2 Physical Memory Map
-----------------------
Derived from official PS2 hardware documentation and reverse engineering.

EE Physical Address Space (512MB, 29-bit physical):
  0x00000000 - 0x01FFFFFF  EE RAM (32 MB)
  0x10000000 - 0x100FFFFF  EE Registers (hardware I/O)
  0x11000000 - 0x11003FFF  VU0 Code Memory (4 KB)
  0x11004000 - 0x11007FFF  VU0 Data Memory (4 KB)
  0x11008000 - 0x1100BFFF  VU1 Code Memory (16 KB)
  0x1100C000 - 0x1100FFFF  VU1 Data Memory (16 KB)
  0x12000000 - 0x12001FFF  GS Registers
  0x1C000000 - 0x1DFFFFFF  IOP RAM mirror
  0x1F000000 - 0x1F00FFFF  SSBUS (expansion)
  0x1F800000 - 0x1F8003FF  IOP scratchpad
  0x1FC00000 - 0x1FFFFFFF  BIOS ROM (4 MB)

KSEG0 (cached):   0x80000000 | phys
KSEG1 (uncached): 0xA0000000 | phys
KSEG2:            0xC0000000 (TLB mapped)
"""

EE_RAM_BASE        = 0x00000000
EE_RAM_SIZE        = 0x02000000   # 32 MB

SCRATCHPAD_BASE    = 0x70000000
SCRATCHPAD_SIZE    = 0x00004000   # 16 KB (EE scratchpad)

HW_REGS_BASE       = 0x10000000
HW_REGS_SIZE       = 0x00010000

VU0_CODE_BASE      = 0x11000000
VU0_CODE_SIZE      = 0x00001000   # 4 KB (1K instructions)
VU0_DATA_BASE      = 0x11004000
VU0_DATA_SIZE      = 0x00001000

VU1_CODE_BASE      = 0x11008000
VU1_CODE_SIZE      = 0x00004000   # 16 KB (4K instructions)
VU1_DATA_BASE      = 0x1100C000
VU1_DATA_SIZE      = 0x00004000

GS_REGS_BASE       = 0x12000000
GS_REGS_SIZE       = 0x00002000

IOP_RAM_BASE       = 0x1C000000
IOP_RAM_SIZE       = 0x00200000   # 2 MB

BIOS_BASE          = 0x1FC00000
BIOS_SIZE          = 0x00400000   # 4 MB

KSEG0_OFFSET       = 0x80000000
KSEG1_OFFSET       = 0xA0000000

def phys_addr(vaddr: int) -> int:
    """Translate virtual address to physical (handle KSEG0/KSEG1)."""
    if vaddr >= 0xC0000000:
        raise ValueError(f"TLB-mapped address 0x{vaddr:08X} not supported yet")
    if vaddr >= KSEG1_OFFSET:
        return vaddr - KSEG1_OFFSET
    if vaddr >= KSEG0_OFFSET:
        return vaddr - KSEG0_OFFSET
    return vaddr
