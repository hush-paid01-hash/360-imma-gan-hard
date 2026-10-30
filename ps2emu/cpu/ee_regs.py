"""
Emotion Engine (EE) Register File
----------------------------------
MIPS R5900 has:
  - 32 x 128-bit general-purpose registers (GPR)  [hi 64 bits used by SIMD]
  - 32 x 32-bit floating-point registers (FPR)    [COP1]
  - HI, LO, HI1, LO1 (64-bit each, two sets for MULT pipeline)
  - SA (shift amount, for MFSA/MTSA)
  - PC (program counter)
  - COP0 registers (status, cause, EPC, etc.)

All GPRs are 128-bit on R5900 (vs 64-bit on standard MIPS64).
We store them as Python ints (arbitrary width) for correctness.
"""

import ctypes

# COP0 register indices (named per MIPS spec + R5900 additions)
COP0_INDEX     = 0
COP0_RANDOM    = 1
COP0_ENTRYLO0  = 2
COP0_ENTRYLO1  = 3
COP0_CONTEXT   = 4
COP0_PAGEMASK  = 5
COP0_WIRED     = 6
COP0_BADVADDR  = 8
COP0_COUNT     = 9
COP0_ENTRYHI   = 10
COP0_COMPARE   = 11
COP0_STATUS    = 12
COP0_CAUSE     = 13
COP0_EPC       = 14
COP0_PRID      = 15   # Processor revision ID
COP0_CONFIG    = 16
COP0_BADPADDR  = 23   # R5900 extension: bad physical address
COP0_DEBUG     = 24
COP0_PERF      = 25
COP0_TAGLO     = 28
COP0_TAGHI     = 29
COP0_ERROREPC  = 30

# Status register bits
SR_IE   = 1 << 0   # interrupt enable
SR_EXL  = 1 << 1   # exception level
SR_ERL  = 1 << 2   # error level
SR_KSU  = 3 << 3   # 00=kernel, 01=supervisor, 10=user
SR_IM   = 0xFF << 8  # interrupt mask
SR_BEV  = 1 << 22  # boot exception vectors
SR_CU0  = 1 << 28  # COP0 usable
SR_CU1  = 1 << 29  # COP1 (FPU) usable
SR_CU2  = 1 << 30  # COP2 (VU0) usable

# Cause register
CAUSE_EXCCODE = 0x1F << 2  # exception code field
CAUSE_IP      = 0xFF << 8  # interrupt pending

EXCCODE_INT   = 0
EXCCODE_ADEL  = 4   # address error (load)
EXCCODE_ADES  = 5   # address error (store)
EXCCODE_IBE   = 6   # instruction bus error
EXCCODE_DBE   = 7   # data bus error
EXCCODE_SYS   = 8   # syscall
EXCCODE_BP    = 9   # breakpoint
EXCCODE_RI    = 10  # reserved instruction
EXCCODE_CPU   = 11  # coprocessor unusable
EXCCODE_OVF   = 12  # arithmetic overflow


class EERegisters:
    """Full Emotion Engine register state."""

    __slots__ = (
        "gpr",        # list[int], 32 x 128-bit
        "fpr",        # list[float], 32 x 32-bit (COP1)
        "hi", "lo",   # 64-bit multiply result (set 0)
        "hi1", "lo1", # 64-bit multiply result (set 1)
        "sa",         # shift amount (7-bit)
        "pc",         # program counter
        "cop0",       # list[int], 32 x 32-bit COP0 registers
        "fcr",        # FPU control register (FCR31)
    )

    def __init__(self):
        self.gpr   = [0] * 32
        self.fpr   = [0.0] * 32
        self.hi    = 0
        self.lo    = 0
        self.hi1   = 0
        self.lo1   = 0
        self.sa    = 0
        self.pc    = 0xBFC00000  # BIOS reset vector (KSEG1 mirror of 0x1FC00000)
        self.cop0  = [0] * 32
        self.fcr   = 0

        # Initial COP0 state per R5900 spec
        self.cop0[COP0_STATUS] = SR_BEV | SR_ERL   # boot: unmapped, error level
        self.cop0[COP0_PRID]   = 0x00002E20         # R5900 processor ID
        self.cop0[COP0_CONFIG] = 0x00070460         # default config

    # ------------------------------------------------------------------
    # GPR helpers — R5900 GPR[0] is always zero (hardware wired)
    # ------------------------------------------------------------------

    def get_gpr(self, idx: int) -> int:
        if idx == 0:
            return 0
        return self.gpr[idx]

    def set_gpr(self, idx: int, value: int) -> None:
        if idx == 0:
            return
        # Clamp to 128-bit (sign-extend from 64-bit for standard ops)
        self.gpr[idx] = value & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF

    def get_gpr32(self, idx: int) -> int:
        """Lower 32 bits, sign-extended to 64 (standard MIPS behavior)."""
        v = self.get_gpr(idx) & 0xFFFFFFFF
        if v & 0x80000000:
            return v | 0xFFFFFFFF00000000
        return v

    def get_gpr64(self, idx: int) -> int:
        return self.get_gpr(idx) & 0xFFFFFFFFFFFFFFFF

    def set_gpr64(self, idx: int, value: int) -> None:
        # Sign-extend 64→128 per R5900 ABI
        v64 = value & 0xFFFFFFFFFFFFFFFF
        if v64 & (1 << 63):
            v128 = v64 | (0xFFFFFFFFFFFFFFFF << 64)
        else:
            v128 = v64
        self.set_gpr(idx, v128)

    def dump(self) -> str:
        lines = [f"PC=0x{self.pc:08X}  HI=0x{self.hi:016X}  LO=0x{self.lo:016X}"]
        names = [
            "zr", "at", "v0", "v1", "a0", "a1", "a2", "a3",
            "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
            "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
            "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra",
        ]
        for i in range(0, 32, 4):
            row = "  ".join(
                f"{names[i+j]:>2}=0x{self.get_gpr64(i+j):016X}"
                for j in range(4)
            )
            lines.append(row)
        return "\n".join(lines)
