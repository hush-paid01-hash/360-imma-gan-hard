"""
MIPS R5900 (EE) Instruction Set Decoder
----------------------------------------
R5900 extends MIPS III/IV with:
  - 128-bit multimedia instructions (MMI)
  - PMFHI/PMFLO/PMTHI/PMTLO operating on 128-bit GPRs
  - Extended MUL/DIV pipeline (HI1/LO1)
  - COP2 = VU0 macro instructions

Instruction format (32-bit fixed):
  [31:26] opcode (6 bits)
  [25:21] rs     (5 bits)
  [20:16] rt     (5 bits)
  [15:11] rd     (5 bits)
  [10:6]  shamt  (5 bits)
  [5:0]   funct  (6 bits)   -- R-type
  [15:0]  imm    (16 bits)  -- I-type
  [25:0]  target (26 bits)  -- J-type

Primary opcodes (bits 31:26):
  0x00 = SPECIAL   (R-type via funct)
  0x01 = REGIMM    (rt selects condition branch)
  0x02 = J
  0x03 = JAL
  0x04 = BEQ
  0x05 = BNE
  0x06 = BLEZ
  0x07 = BGTZ
  0x08 = ADDI
  0x09 = ADDIU
  0x0A = SLTI
  0x0B = SLTIU
  0x0C = ANDI
  0x0D = ORI
  0x0E = XORI
  0x0F = LUI
  0x10 = COP0
  0x11 = COP1 (FPU)
  0x12 = COP2 (VU0 macro)
  0x18 = DADDI
  0x19 = DADDIU
  0x1A = LDL
  0x1B = LDR
  0x1C = MMI      (multimedia — R5900 extension)
  0x1E = LQ       (load quad, 128-bit — R5900)
  0x1F = SQ       (store quad, 128-bit — R5900)
  0x20 = LB
  0x21 = LH
  0x22 = LWL
  0x23 = LW
  0x24 = LBU
  0x25 = LHU
  0x26 = LWR
  0x27 = LWU
  0x28 = SB
  0x29 = SH
  0x2A = SWL
  0x2B = SW
  0x2C = SDL
  0x2D = SDR
  0x2E = SWR
  0x2F = CACHE
  0x31 = LWC1
  0x36 = LQC2    (load 128-bit to VU0 register)
  0x37 = LD
  0x39 = SWC1
  0x3E = SQC2    (store 128-bit from VU0 register)
  0x3F = SD
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Instruction:
    raw: int       # 32-bit word
    op:  int       # bits [31:26]
    rs:  int       # bits [25:21]
    rt:  int       # bits [20:16]
    rd:  int       # bits [15:11]
    sa:  int       # bits [10:6]  (shift amount)
    fn:  int       # bits [5:0]   (SPECIAL/MMI funct)
    imm: int       # bits [15:0]  (zero-extended)
    simm: int      # bits [15:0]  (sign-extended)
    tgt: int       # bits [25:0]  (jump target)


def decode(word: int) -> Instruction:
    op    = (word >> 26) & 0x3F
    rs    = (word >> 21) & 0x1F
    rt    = (word >> 16) & 0x1F
    rd    = (word >> 11) & 0x1F
    sa    = (word >>  6) & 0x1F
    fn    =  word        & 0x3F
    imm   =  word        & 0xFFFF
    simm  = imm if imm < 0x8000 else imm - 0x10000
    tgt   =  word        & 0x03FFFFFF
    return Instruction(raw=word, op=op, rs=rs, rt=rt, rd=rd,
                       sa=sa, fn=fn, imm=imm, simm=simm, tgt=tgt)


# Opcode mnemonics for disassembly
_OP_NAMES = {
    0x02: "J",     0x03: "JAL",
    0x04: "BEQ",   0x05: "BNE",
    0x06: "BLEZ",  0x07: "BGTZ",
    0x08: "ADDI",  0x09: "ADDIU",
    0x0A: "SLTI",  0x0B: "SLTIU",
    0x0C: "ANDI",  0x0D: "ORI",   0x0E: "XORI",
    0x0F: "LUI",
    0x10: "COP0",  0x11: "COP1",  0x12: "COP2",
    0x18: "DADDI", 0x19: "DADDIU",
    0x1C: "MMI",
    0x1E: "LQ",    0x1F: "SQ",
    0x20: "LB",    0x21: "LH",    0x22: "LWL",   0x23: "LW",
    0x24: "LBU",   0x25: "LHU",   0x26: "LWR",   0x27: "LWU",
    0x28: "SB",    0x29: "SH",    0x2B: "SW",    0x2F: "CACHE",
    0x31: "LWC1",  0x36: "LQC2",  0x37: "LD",
    0x39: "SWC1",  0x3E: "SQC2",  0x3F: "SD",
}

_SPECIAL_NAMES = {
    0x00: "SLL",   0x02: "SRL",   0x03: "SRA",
    0x04: "SLLV",  0x06: "SRLV",  0x07: "SRAV",
    0x08: "JR",    0x09: "JALR",
    0x0A: "MOVZ",  0x0B: "MOVN",
    0x0C: "SYSCALL", 0x0D: "BREAK", 0x0F: "SYNC",
    0x10: "MFHI",  0x11: "MTHI",
    0x12: "MFLO",  0x13: "MTLO",
    0x14: "DSLLV", 0x16: "DSRLV", 0x17: "DSRAV",
    0x18: "MULT",  0x19: "MULTU",
    0x1A: "DIV",   0x1B: "DIVU",
    0x20: "ADD",   0x21: "ADDU",  0x22: "SUB",   0x23: "SUBU",
    0x24: "AND",   0x25: "OR",    0x26: "XOR",   0x27: "NOR",
    0x28: "MFSA",  0x29: "MTSA",
    0x2A: "SLT",   0x2B: "SLTU",
    0x2C: "DADD",  0x2D: "DADDU", 0x2E: "DSUB",  0x2F: "DSUBU",
    0x30: "TGE",   0x31: "TGEU",  0x32: "TLT",   0x33: "TLTU",
    0x34: "TEQ",   0x36: "TNE",
    0x38: "DSLL",  0x3A: "DSRL",  0x3B: "DSRA",
    0x3C: "DSLL32",0x3E: "DSRL32",0x3F: "DSRA32",
}

_GPR_NAMES = [
    "zr", "at", "v0", "v1", "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
    "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
    "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra",
]


def disassemble(word: int, pc: int) -> str:
    """Return a human-readable disassembly string for one instruction."""
    ins = decode(word)
    r = _GPR_NAMES

    if ins.op == 0x00:  # SPECIAL
        name = _SPECIAL_NAMES.get(ins.fn, f"SPECIAL.{ins.fn:02X}")
        if ins.fn in (0x00, 0x02, 0x03, 0x38, 0x3A, 0x3B, 0x3C, 0x3E, 0x3F):
            return f"{name} {r[ins.rd]}, {r[ins.rt]}, {ins.sa}"
        if ins.fn in (0x08,):  # JR
            return f"{name} {r[ins.rs]}"
        if ins.fn in (0x09,):  # JALR
            return f"{name} {r[ins.rd]}, {r[ins.rs]}"
        if ins.fn in (0x10, 0x12):  # MFHI/MFLO
            return f"{name} {r[ins.rd]}"
        if ins.fn in (0x11, 0x13):  # MTHI/MTLO
            return f"{name} {r[ins.rs]}"
        if ins.fn in (0x18, 0x19, 0x1A, 0x1B):  # MUL/DIV
            return f"{name} {r[ins.rs]}, {r[ins.rt]}"
        return f"{name} {r[ins.rd]}, {r[ins.rs]}, {r[ins.rt]}"

    if ins.op in (0x02, 0x03):  # J / JAL
        target = ((pc + 4) & 0xF0000000) | (ins.tgt << 2)
        return f"{_OP_NAMES[ins.op]} 0x{target:08X}"

    if ins.op in (0x04, 0x05):  # BEQ/BNE
        target = pc + 4 + (ins.simm << 2)
        name = _OP_NAMES[ins.op]
        return f"{name} {r[ins.rs]}, {r[ins.rt]}, 0x{target:08X}"

    if ins.op in (0x06, 0x07):  # BLEZ/BGTZ
        target = pc + 4 + (ins.simm << 2)
        return f"{_OP_NAMES[ins.op]} {r[ins.rs]}, 0x{target:08X}"

    if ins.op == 0x0F:  # LUI
        return f"LUI {r[ins.rt]}, 0x{ins.imm:04X}"

    if ins.op in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E,
                  0x18, 0x19):
        name = _OP_NAMES.get(ins.op, f"OP.{ins.op:02X}")
        return f"{name} {r[ins.rt]}, {r[ins.rs]}, {ins.simm}"

    if ins.op in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                  0x28, 0x29, 0x2B, 0x2C, 0x2D, 0x2E,
                  0x31, 0x36, 0x37, 0x39, 0x3E, 0x3F,
                  0x1E, 0x1F):
        name = _OP_NAMES.get(ins.op, f"OP.{ins.op:02X}")
        return f"{name} {r[ins.rt]}, {ins.simm}({r[ins.rs]})"

    name = _OP_NAMES.get(ins.op, f"OP.{ins.op:02X}")
    return f"{name} [{word:08X}]"
