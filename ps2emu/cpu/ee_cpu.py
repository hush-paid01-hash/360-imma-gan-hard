"""
Emotion Engine (EE) CPU Interpreter
-------------------------------------
Implements the MIPS R5900 ISA used by the PlayStation 2.

Execution model:
  - Fetch 32-bit instruction from PC
  - Decode via ee_isa.decode()
  - Dispatch to handler
  - Advance PC (handle branch delay slot)
  - Increment COP0 COUNT
  - Check for interrupts

Branch delay slot: MIPS always executes the instruction *after* a branch
before jumping. We handle this with a one-slot delay buffer.
"""

import logging
from . import ee_isa as isa
from .ee_regs import (
    EERegisters,
    COP0_STATUS, COP0_CAUSE, COP0_EPC, COP0_COUNT, COP0_COMPARE,
    SR_EXL, SR_ERL, SR_IE, SR_BEV,
    CAUSE_EXCCODE, EXCCODE_RI, EXCCODE_SYS,
)
from ..memory.bus import MemoryBus

log = logging.getLogger(__name__)

RESET_VECTOR     = 0xBFC00000  # KSEG1 mirror of BIOS start
EXCEPTION_VECTOR = 0x80000180  # General exception handler (normal)
EXCEPTION_VECTOR_BEV = 0xBFC00380  # General exception handler (boot)


class EmotionEngine:
    """
    MIPS R5900 interpreter.

    The interpreter runs one instruction per step(). A real emulator
    would implement a JIT recompiler for performance, but the interpreter
    is correct and useful for BIOS bring-up and debugging.
    """

    def __init__(self, bus: MemoryBus):
        self.bus   = bus
        self.regs  = EERegisters()
        self.cycle = 0

        # Branch delay slot state
        self._branch_target: int | None = None
        self._in_delay_slot  = False

        # Instruction trace (for debugging)
        self.trace_enabled = False

    def reset(self) -> None:
        self.regs = EERegisters()
        self.cycle = 0
        self._branch_target = None
        self._in_delay_slot  = False
        log.info("EE reset — PC=0x%08X", self.regs.pc)

    def step(self) -> None:
        """Execute one instruction."""
        pc = self.regs.pc

        # Fetch
        try:
            word = self.bus.read32(pc)
        except Exception as e:
            log.error("Instruction fetch fault @ 0x%08X: %s", pc, e)
            self._exception(4, pc)   # ADEL
            return

        ins = isa.decode(word)

        if self.trace_enabled:
            log.debug("[%08X] %s", pc, isa.disassemble(word, pc))

        # Advance PC before execution (branch may override next_pc)
        if self._in_delay_slot:
            next_pc = self._branch_target
            self._in_delay_slot = False
            self._branch_target = None
        else:
            next_pc = pc + 4

        self.regs.pc = next_pc

        # Execute
        try:
            self._execute(ins, pc)
        except _BranchTaken as b:
            self._branch_target = b.target
            self._in_delay_slot = True
            self.regs.pc = next_pc   # delay slot instruction is at next_pc
        except _JumpTaken as j:
            # JR/JALR: execute delay slot then jump
            self._branch_target = j.target
            self._in_delay_slot = True
            self.regs.pc = next_pc

        # Update cycle counter / COP0.COUNT
        self.cycle += 1
        self.regs.cop0[COP0_COUNT] = (self.regs.cop0[COP0_COUNT] + 1) & 0xFFFFFFFF

        # Timer interrupt: COUNT == COMPARE
        if self.regs.cop0[COP0_COUNT] == self.regs.cop0[COP0_COMPARE]:
            self.regs.cop0[COP0_CAUSE] |= (1 << 15)   # IP7 (timer)

    def run(self, n: int = 1000) -> None:
        """Run n instructions."""
        for _ in range(n):
            self.step()

    # ------------------------------------------------------------------
    # Instruction dispatch
    # ------------------------------------------------------------------

    def _execute(self, ins: isa.Instruction, pc: int) -> None:
        op = ins.op
        if   op == 0x00: self._special(ins, pc)
        elif op == 0x01: self._regimm(ins, pc)
        elif op == 0x02: self._J(ins, pc)
        elif op == 0x03: self._JAL(ins, pc)
        elif op == 0x04: self._BEQ(ins, pc)
        elif op == 0x05: self._BNE(ins, pc)
        elif op == 0x06: self._BLEZ(ins, pc)
        elif op == 0x07: self._BGTZ(ins, pc)
        elif op == 0x08: self._ADDI(ins)
        elif op == 0x09: self._ADDIU(ins)
        elif op == 0x0A: self._SLTI(ins)
        elif op == 0x0B: self._SLTIU(ins)
        elif op == 0x0C: self._ANDI(ins)
        elif op == 0x0D: self._ORI(ins)
        elif op == 0x0E: self._XORI(ins)
        elif op == 0x0F: self._LUI(ins)
        elif op == 0x10: self._COP0(ins, pc)
        elif op == 0x11: self._COP1(ins)
        elif op == 0x12: self._COP2(ins)
        elif op == 0x18: self._DADDI(ins)
        elif op == 0x19: self._DADDIU(ins)
        elif op == 0x1C: self._MMI(ins, pc)
        elif op == 0x1E: self._LQ(ins)
        elif op == 0x1F: self._SQ(ins)
        elif op == 0x20: self._LB(ins)
        elif op == 0x21: self._LH(ins)
        elif op == 0x23: self._LW(ins)
        elif op == 0x24: self._LBU(ins)
        elif op == 0x25: self._LHU(ins)
        elif op == 0x27: self._LWU(ins)
        elif op == 0x28: self._SB(ins)
        elif op == 0x29: self._SH(ins)
        elif op == 0x2B: self._SW(ins)
        elif op == 0x37: self._LD(ins)
        elif op == 0x3F: self._SD(ins)
        else:
            log.warning("[%08X] Unimplemented opcode 0x%02X", pc, op)
            self._exception(EXCCODE_RI, pc)

    # ------------------------------------------------------------------
    # SPECIAL (op=0x00) — R-type instructions
    # ------------------------------------------------------------------

    def _special(self, ins: isa.Instruction, pc: int) -> None:
        r = self.regs
        fn = ins.fn
        rd, rs, rt, sa = ins.rd, ins.rs, ins.rt, ins.sa

        if   fn == 0x00:  # SLL
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rt) & 0xFFFFFFFF) << sa))
        elif fn == 0x02:  # SRL
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rt) & 0xFFFFFFFF) >> sa))
        elif fn == 0x03:  # SRA
            v = r.get_gpr32(rt)
            if v < 0:
                r.set_gpr64(rd, self._sext32(-((-v) >> sa)))
            else:
                r.set_gpr64(rd, self._sext32(v >> sa))
        elif fn == 0x04:  # SLLV
            shamt = r.get_gpr32(rs) & 0x1F
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rt) & 0xFFFFFFFF) << shamt))
        elif fn == 0x06:  # SRLV
            shamt = r.get_gpr32(rs) & 0x1F
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rt) & 0xFFFFFFFF) >> shamt))
        elif fn == 0x07:  # SRAV
            shamt = r.get_gpr32(rs) & 0x1F
            v = r.get_gpr32(rt)
            r.set_gpr64(rd, self._sext32(v >> shamt))
        elif fn == 0x08:  # JR
            raise _JumpTaken(r.get_gpr64(rs))
        elif fn == 0x09:  # JALR
            r.set_gpr64(rd, pc + 8)
            raise _JumpTaken(r.get_gpr64(rs))
        elif fn == 0x0A:  # MOVZ
            if r.get_gpr64(rt) == 0:
                r.set_gpr64(rd, r.get_gpr64(rs))
        elif fn == 0x0B:  # MOVN
            if r.get_gpr64(rt) != 0:
                r.set_gpr64(rd, r.get_gpr64(rs))
        elif fn == 0x0C:  # SYSCALL
            self._exception(EXCCODE_SYS, pc)
        elif fn == 0x0F:  # SYNC
            pass  # memory barrier — nop for interpreter
        elif fn == 0x10:  # MFHI
            r.set_gpr64(rd, r.hi)
        elif fn == 0x11:  # MTHI
            r.hi = r.get_gpr64(rs)
        elif fn == 0x12:  # MFLO
            r.set_gpr64(rd, r.lo)
        elif fn == 0x13:  # MTLO
            r.lo = r.get_gpr64(rs)
        elif fn == 0x18:  # MULT
            a = self._s32(r.get_gpr32(rs))
            b = self._s32(r.get_gpr32(rt))
            result = a * b
            r.lo = self._sext32(result & 0xFFFFFFFF)
            r.hi = self._sext32((result >> 32) & 0xFFFFFFFF)
            r.set_gpr64(rd, r.lo)   # R5900: rd = LO
        elif fn == 0x19:  # MULTU
            a = r.get_gpr32(rs) & 0xFFFFFFFF
            b = r.get_gpr32(rt) & 0xFFFFFFFF
            result = a * b
            r.lo = self._sext32(result & 0xFFFFFFFF)
            r.hi = self._sext32((result >> 32) & 0xFFFFFFFF)
            r.set_gpr64(rd, r.lo)
        elif fn == 0x1A:  # DIV
            a = self._s32(r.get_gpr32(rs))
            b = self._s32(r.get_gpr32(rt))
            if b != 0:
                r.lo = self._sext32(int(a / b))
                r.hi = self._sext32(a % b)
        elif fn == 0x1B:  # DIVU
            a = r.get_gpr32(rs) & 0xFFFFFFFF
            b = r.get_gpr32(rt) & 0xFFFFFFFF
            if b != 0:
                r.lo = self._sext32(a // b)
                r.hi = self._sext32(a % b)
        elif fn == 0x20:  # ADD (with overflow trap — treated as ADDU on EE)
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rs) + r.get_gpr32(rt)) & 0xFFFFFFFF))
        elif fn == 0x21:  # ADDU
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rs) + r.get_gpr32(rt)) & 0xFFFFFFFF))
        elif fn == 0x22:  # SUB
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rs) - r.get_gpr32(rt)) & 0xFFFFFFFF))
        elif fn == 0x23:  # SUBU
            r.set_gpr64(rd, self._sext32((r.get_gpr32(rs) - r.get_gpr32(rt)) & 0xFFFFFFFF))
        elif fn == 0x24:  # AND
            r.set_gpr64(rd, r.get_gpr64(rs) & r.get_gpr64(rt))
        elif fn == 0x25:  # OR
            r.set_gpr64(rd, r.get_gpr64(rs) | r.get_gpr64(rt))
        elif fn == 0x26:  # XOR
            r.set_gpr64(rd, r.get_gpr64(rs) ^ r.get_gpr64(rt))
        elif fn == 0x27:  # NOR
            r.set_gpr64(rd, ~(r.get_gpr64(rs) | r.get_gpr64(rt)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x28:  # MFSA
            r.set_gpr64(rd, r.sa)
        elif fn == 0x29:  # MTSA
            r.sa = r.get_gpr64(rs) & 0x7F
        elif fn == 0x2A:  # SLT
            r.set_gpr64(rd, 1 if self._s64(r.get_gpr64(rs)) < self._s64(r.get_gpr64(rt)) else 0)
        elif fn == 0x2B:  # SLTU
            r.set_gpr64(rd, 1 if r.get_gpr64(rs) < r.get_gpr64(rt) else 0)
        elif fn == 0x2C:  # DADD
            r.set_gpr64(rd, (r.get_gpr64(rs) + r.get_gpr64(rt)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x2D:  # DADDU
            r.set_gpr64(rd, (r.get_gpr64(rs) + r.get_gpr64(rt)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x2E:  # DSUB
            r.set_gpr64(rd, (r.get_gpr64(rs) - r.get_gpr64(rt)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x2F:  # DSUBU
            r.set_gpr64(rd, (r.get_gpr64(rs) - r.get_gpr64(rt)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x38:  # DSLL
            r.set_gpr64(rd, (r.get_gpr64(rt) << sa) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x3A:  # DSRL
            r.set_gpr64(rd, r.get_gpr64(rt) >> sa)
        elif fn == 0x3B:  # DSRA
            r.set_gpr64(rd, self._s64(r.get_gpr64(rt)) >> sa)
        elif fn == 0x3C:  # DSLL32
            r.set_gpr64(rd, (r.get_gpr64(rt) << (sa + 32)) & 0xFFFFFFFFFFFFFFFF)
        elif fn == 0x3E:  # DSRL32
            r.set_gpr64(rd, r.get_gpr64(rt) >> (sa + 32))
        elif fn == 0x3F:  # DSRA32
            r.set_gpr64(rd, self._s64(r.get_gpr64(rt)) >> (sa + 32))
        else:
            log.warning("Unimplemented SPECIAL fn=0x%02X", fn)

    # ------------------------------------------------------------------
    # REGIMM (op=0x01)
    # ------------------------------------------------------------------

    def _regimm(self, ins: isa.Instruction, pc: int) -> None:
        r = self.regs
        target = pc + 4 + (ins.simm << 2)
        rt = ins.rt
        if rt == 0x00:   # BLTZ
            if self._s64(r.get_gpr64(ins.rs)) < 0:
                raise _BranchTaken(target)
        elif rt == 0x01:  # BGEZ
            if self._s64(r.get_gpr64(ins.rs)) >= 0:
                raise _BranchTaken(target)
        elif rt == 0x10:  # BLTZAL
            r.set_gpr64(31, pc + 8)
            if self._s64(r.get_gpr64(ins.rs)) < 0:
                raise _BranchTaken(target)
        elif rt == 0x11:  # BGEZAL
            r.set_gpr64(31, pc + 8)
            if self._s64(r.get_gpr64(ins.rs)) >= 0:
                raise _BranchTaken(target)

    # ------------------------------------------------------------------
    # Branches / Jumps
    # ------------------------------------------------------------------

    def _J(self, ins: isa.Instruction, pc: int) -> None:
        target = ((pc + 4) & 0xF0000000) | (ins.tgt << 2)
        raise _JumpTaken(target)

    def _JAL(self, ins: isa.Instruction, pc: int) -> None:
        self.regs.set_gpr64(31, pc + 8)
        target = ((pc + 4) & 0xF0000000) | (ins.tgt << 2)
        raise _JumpTaken(target)

    def _BEQ(self, ins: isa.Instruction, pc: int) -> None:
        if self.regs.get_gpr64(ins.rs) == self.regs.get_gpr64(ins.rt):
            raise _BranchTaken(pc + 4 + (ins.simm << 2))

    def _BNE(self, ins: isa.Instruction, pc: int) -> None:
        if self.regs.get_gpr64(ins.rs) != self.regs.get_gpr64(ins.rt):
            raise _BranchTaken(pc + 4 + (ins.simm << 2))

    def _BLEZ(self, ins: isa.Instruction, pc: int) -> None:
        if self._s64(self.regs.get_gpr64(ins.rs)) <= 0:
            raise _BranchTaken(pc + 4 + (ins.simm << 2))

    def _BGTZ(self, ins: isa.Instruction, pc: int) -> None:
        if self._s64(self.regs.get_gpr64(ins.rs)) > 0:
            raise _BranchTaken(pc + 4 + (ins.simm << 2))

    # ------------------------------------------------------------------
    # ALU immediate
    # ------------------------------------------------------------------

    def _ADDI(self, ins: isa.Instruction) -> None:
        v = self._sext32((self.regs.get_gpr32(ins.rs) + ins.simm) & 0xFFFFFFFF)
        self.regs.set_gpr64(ins.rt, v)

    def _ADDIU(self, ins: isa.Instruction) -> None:
        v = self._sext32((self.regs.get_gpr32(ins.rs) + ins.simm) & 0xFFFFFFFF)
        self.regs.set_gpr64(ins.rt, v)

    def _SLTI(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, 1 if self._s64(self.regs.get_gpr64(ins.rs)) < ins.simm else 0)

    def _SLTIU(self, ins: isa.Instruction) -> None:
        imm = ins.simm & 0xFFFFFFFFFFFFFFFF
        self.regs.set_gpr64(ins.rt, 1 if self.regs.get_gpr64(ins.rs) < imm else 0)

    def _ANDI(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.regs.get_gpr64(ins.rs) & ins.imm)

    def _ORI(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.regs.get_gpr64(ins.rs) | ins.imm)

    def _XORI(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.regs.get_gpr64(ins.rs) ^ ins.imm)

    def _LUI(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self._sext32(ins.imm << 16))

    def _DADDI(self, ins: isa.Instruction) -> None:
        v = (self.regs.get_gpr64(ins.rs) + ins.simm) & 0xFFFFFFFFFFFFFFFF
        self.regs.set_gpr64(ins.rt, v)

    def _DADDIU(self, ins: isa.Instruction) -> None:
        v = (self.regs.get_gpr64(ins.rs) + ins.simm) & 0xFFFFFFFFFFFFFFFF
        self.regs.set_gpr64(ins.rt, v)

    # ------------------------------------------------------------------
    # Memory load/store
    # ------------------------------------------------------------------

    def _addr(self, ins: isa.Instruction) -> int:
        return (self.regs.get_gpr64(ins.rs) + ins.simm) & 0xFFFFFFFFFFFFFFFF

    def _LB(self, ins: isa.Instruction) -> None:
        v = self.bus.read8(self._addr(ins))
        self.regs.set_gpr64(ins.rt, v if v < 0x80 else v - 0x100)

    def _LH(self, ins: isa.Instruction) -> None:
        v = self.bus.read16(self._addr(ins))
        self.regs.set_gpr64(ins.rt, v if v < 0x8000 else v - 0x10000)

    def _LW(self, ins: isa.Instruction) -> None:
        v = self.bus.read32(self._addr(ins))
        self.regs.set_gpr64(ins.rt, self._sext32(v))

    def _LBU(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.bus.read8(self._addr(ins)))

    def _LHU(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.bus.read16(self._addr(ins)))

    def _LWU(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.bus.read32(self._addr(ins)))

    def _LD(self, ins: isa.Instruction) -> None:
        self.regs.set_gpr64(ins.rt, self.bus.read64(self._addr(ins)))

    def _LQ(self, ins: isa.Instruction) -> None:
        addr = (self.regs.get_gpr64(ins.rs) + ins.simm) & ~0xF
        self.regs.set_gpr(ins.rt, self.bus.read128(addr))

    def _SB(self, ins: isa.Instruction) -> None:
        self.bus.write8(self._addr(ins), self.regs.get_gpr64(ins.rt) & 0xFF)

    def _SH(self, ins: isa.Instruction) -> None:
        self.bus.write16(self._addr(ins), self.regs.get_gpr64(ins.rt) & 0xFFFF)

    def _SW(self, ins: isa.Instruction) -> None:
        self.bus.write32(self._addr(ins), self.regs.get_gpr64(ins.rt) & 0xFFFFFFFF)

    def _SD(self, ins: isa.Instruction) -> None:
        self.bus.write64(self._addr(ins), self.regs.get_gpr64(ins.rt))

    def _SQ(self, ins: isa.Instruction) -> None:
        addr = (self.regs.get_gpr64(ins.rs) + ins.simm) & ~0xF
        self.bus.write128(addr, self.regs.get_gpr(ins.rt))

    # ------------------------------------------------------------------
    # COP0 (privileged / system control)
    # ------------------------------------------------------------------

    def _COP0(self, ins: isa.Instruction, pc: int) -> None:
        r = self.regs
        sub = ins.rs  # COP0 sub-opcode in [25:21]
        if sub == 0x00:   # MFC0: rt = COP0[rd]
            r.set_gpr64(ins.rt, self._sext32(r.cop0[ins.rd]))
        elif sub == 0x04:  # MTC0: COP0[rd] = rt
            r.cop0[ins.rd] = r.get_gpr32(ins.rt) & 0xFFFFFFFF
        elif sub == 0x10:  # CO — fn in [5:0]
            if ins.fn == 0x18:   # ERET
                if r.cop0[COP0_STATUS] & SR_ERL:
                    r.pc = r.cop0[30]           # ErrorEPC
                    r.cop0[COP0_STATUS] &= ~SR_ERL
                else:
                    r.pc = r.cop0[COP0_EPC]
                    r.cop0[COP0_STATUS] &= ~SR_EXL
            elif ins.fn == 0x08: # TLBP
                pass
            elif ins.fn == 0x01: # TLBR
                pass
            elif ins.fn == 0x02: # TLBWI
                pass
            elif ins.fn == 0x06: # TLBWR
                pass
        else:
            log.debug("Unimplemented COP0 sub=0x%02X fn=0x%02X", sub, ins.fn)

    def _COP1(self, ins: isa.Instruction) -> None:
        log.debug("COP1 (FPU) not fully implemented")

    def _COP2(self, ins: isa.Instruction) -> None:
        log.debug("COP2 (VU0 macro) not fully implemented")

    def _MMI(self, ins: isa.Instruction, pc: int) -> None:
        log.debug("MMI fn=0x%02X not implemented", ins.fn)

    # ------------------------------------------------------------------
    # Exception handling
    # ------------------------------------------------------------------

    def _exception(self, exccode: int, pc: int) -> None:
        r = self.regs
        status = r.cop0[COP0_STATUS]
        r.cop0[COP0_EPC] = pc
        r.cop0[COP0_CAUSE] = (r.cop0[COP0_CAUSE] & ~CAUSE_EXCCODE) | (exccode << 2)
        r.cop0[COP0_STATUS] = status | SR_EXL
        if status & SR_BEV:
            r.pc = EXCEPTION_VECTOR_BEV
        else:
            r.pc = EXCEPTION_VECTOR
        self._branch_target = None
        self._in_delay_slot  = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sext32(v: int) -> int:
        v &= 0xFFFFFFFF
        return v if v < 0x80000000 else v - 0x100000000

    @staticmethod
    def _s32(v: int) -> int:
        v &= 0xFFFFFFFF
        return v if v < 0x80000000 else v - 0x100000000

    @staticmethod
    def _s64(v: int) -> int:
        v &= 0xFFFFFFFFFFFFFFFF
        return v if v < 0x8000000000000000 else v - 0x10000000000000000


class _BranchTaken(Exception):
    __slots__ = ("target",)
    def __init__(self, target: int): self.target = target

class _JumpTaken(Exception):
    __slots__ = ("target",)
    def __init__(self, target: int): self.target = target
