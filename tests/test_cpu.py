"""
Unit tests for EE CPU components.
Tests run without a BIOS — they feed raw instruction words directly.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ps2emu.memory.bus import MemoryBus
from ps2emu.cpu.ee_cpu import EmotionEngine
from ps2emu.cpu import ee_isa


def make_cpu():
    bus = MemoryBus()
    cpu = EmotionEngine(bus)
    cpu.regs.pc = 0x00000000   # put instructions at EE RAM start
    return cpu, bus


def write_instr(bus: MemoryBus, addr: int, *words: int) -> None:
    import struct
    for i, w in enumerate(words):
        bus.write32(addr + i * 4, w)


class TestDecoder:
    def test_addiu(self):
        ins = ee_isa.decode(0x24020001)   # ADDIU v0, zr, 1
        assert ins.op == 0x09
        assert ins.rt == 2
        assert ins.rs == 0
        assert ins.simm == 1

    def test_lui(self):
        ins = ee_isa.decode(0x3C010001)   # LUI at, 0x0001
        assert ins.op == 0x0F
        assert ins.rt == 1
        assert ins.imm == 1

    def test_ori(self):
        ins = ee_isa.decode(0x34420010)   # ORI v0, v0, 0x10
        assert ins.op == 0x0D
        assert ins.rt == 2
        assert ins.rs == 2
        assert ins.imm == 0x10

    def test_jr(self):
        ins = ee_isa.decode(0x03E00008)   # JR ra
        assert ins.op == 0x00
        assert ins.fn == 0x08
        assert ins.rs == 31

    def test_sw(self):
        ins = ee_isa.decode(0xAC430008)   # SW v1, 8(v0)
        assert ins.op == 0x2B
        assert ins.rs == 2
        assert ins.rt == 3
        assert ins.simm == 8


class TestALU:
    def test_addiu_basic(self):
        cpu, bus = make_cpu()
        # ADDIU v0, zr, 42
        write_instr(bus, 0, 0x24020000 | 42)
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 42

    def test_lui_ori(self):
        cpu, bus = make_cpu()
        # LUI v0, 0xDEAD  ;  ORI v0, v0, 0xBEEF
        write_instr(bus, 0,
            0x3C02DEAD,   # LUI v0, 0xDEAD
            0x3442BEEF,   # ORI v0, v0, 0xBEEF
        )
        cpu.step()
        cpu.step()
        # LUI sign-extends 32→64: 0xDEAD0000 → 0xFFFFFFFFDEAD0000 (bit31=1)
        # ORI preserves upper bits: 0xFFFFFFFFDEAD0000 | 0xBEEF = 0xFFFFFFFFDEADBEEF
        assert cpu.regs.get_gpr64(2) == 0xFFFFFFFFDEADBEEF

    def test_gpr0_always_zero(self):
        cpu, bus = make_cpu()
        write_instr(bus, 0, 0x24000099)   # ADDIU zr, zr, 0x99
        cpu.step()
        assert cpu.regs.get_gpr64(0) == 0

    def test_addu(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 10)
        cpu.regs.set_gpr64(5, 32)
        # ADDU v0, a0, a1  ->  $4 + $5 -> $2
        write_instr(bus, 0, 0x00851021)   # ADDU v0, a0, a1
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 42

    def test_slt(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 5)
        cpu.regs.set_gpr64(5, 10)
        write_instr(bus, 0, 0x0085102A)   # SLT v0, a0, a1  (5 < 10 → 1)
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 1

    def test_and_or_xor(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 0xFF00)
        cpu.regs.set_gpr64(5, 0x00FF)
        write_instr(bus, 0,
            0x00851024,   # AND v0, a0, a1  -> 0x0000
            0x00851025,   # OR  v0, a0, a1  -> 0xFFFF
            0x00851026,   # XOR v0, a0, a1  -> 0xFFFF
        )
        cpu.regs.pc = 0
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0x0000
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0xFFFF
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0xFFFF

    def test_mult(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 6)
        cpu.regs.set_gpr64(5, 7)
        write_instr(bus, 0, 0x00851018)   # MULT zr, a0, a1
        cpu.step()
        assert cpu.regs.lo == 42

    def test_div(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 100)
        cpu.regs.set_gpr64(5, 7)
        write_instr(bus, 0, 0x0085001A)   # DIV zr, a0, a1
        cpu.step()
        assert cpu.regs.lo == 14   # 100//7=14
        assert cpu.regs.hi == 2    # 100%7=2

    def test_shift_left(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 1)
        write_instr(bus, 0, 0x00041080)   # SLL v0, a0, 2
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 4

    def test_dsll32(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 1)
        # DSLL32 v0, a0, 0  -> shifts left by 32
        write_instr(bus, 0, 0x0004103C)
        cpu.step()
        assert cpu.regs.get_gpr64(2) == (1 << 32)


class TestMemory:
    def test_sw_lw(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 0x100)   # base addr
        cpu.regs.set_gpr64(5, 0xDEAD)  # value
        write_instr(bus, 0,
            0xAC850000,   # SW a1, 0(a0)
            0x8C820000,   # LW v0, 0(a0)
        )
        cpu.step()
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0xDEAD

    def test_sb_lb(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 0x200)
        cpu.regs.set_gpr64(5, 0x7F)
        write_instr(bus, 0,
            0xA0850000,   # SB a1, 0(a0)
            0x80820000,   # LB v0, 0(a0)
        )
        cpu.step()
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0x7F

    def test_sh_lh(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 0x300)
        cpu.regs.set_gpr64(5, 0x1234)
        write_instr(bus, 0,
            0xA4850000,   # SH a1, 0(a0)
            0x84820000,   # LH v0, 0(a0)
        )
        cpu.step()
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0x1234

    def test_lbu(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 0x400)
        cpu.regs.set_gpr64(5, 0xFF)
        write_instr(bus, 0,
            0xA0850000,   # SB a1, 0(a0)
            0x90820000,   # LBU v0, 0(a0)
        )
        cpu.step()
        cpu.step()
        assert cpu.regs.get_gpr64(2) == 0xFF   # unsigned — no sign extension


class TestBranch:
    def test_bne_taken(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 1)
        cpu.regs.set_gpr64(5, 2)
        # BNE a0, a1, +8  (branch to 0x0C)
        write_instr(bus, 0,
            0x14850001,   # BNE a0, a1, +1 (offset=1 → target = PC+4 + 4 = 8)
            0x00000000,   # NOP (delay slot)
            0x24020010,   # ADDIU v0, zr, 16  ← should be executed (target)
            0x24020099,   # ADDIU v0, zr, 153 ← should be skipped
        )
        cpu.step()   # BNE
        cpu.step()   # delay slot NOP
        cpu.step()   # should be at target: ADDIU v0,zr,16
        assert cpu.regs.get_gpr64(2) == 16

    def test_beq_not_taken(self):
        cpu, bus = make_cpu()
        cpu.regs.set_gpr64(4, 1)
        cpu.regs.set_gpr64(5, 2)
        # BEQ a0, a1 (1 != 2 — not taken)
        write_instr(bus, 0,
            0x10850005,   # BEQ a0, a1, +5 (not taken)
            0x00000000,   # NOP delay slot
            0x2402ABCD,   # ADDIU v0,zr,0xABCD  ← should execute
        )
        cpu.step(); cpu.step(); cpu.step()
        # 0xABCD has bit15=1 → simm = -21555 → sign-extended to 0xFFFFFFFFFFFFABCD
        assert cpu.regs.get_gpr64(2) == 0xFFFFFFFFFFFFABCD

    def test_j(self):
        cpu, bus = make_cpu()
        # J 0x00000010  (target word addr = 4 → byte = 0x10)
        write_instr(bus, 0,
            0x08000004,   # J 4   (target = 0x00000010)
            0x00000000,   # NOP delay slot
            0x24020001,   # ADDIU v0,zr,1  (should be skipped)
            0x00000000,   # padding
            0x24020002,   # ADDIU v0,zr,2  (at 0x10, should execute)
        )
        cpu.step()  # J
        cpu.step()  # delay slot
        cpu.step()  # at target
        assert cpu.regs.get_gpr64(2) == 2


class TestDisassembler:
    def test_addiu_disasm(self):
        s = ee_isa.disassemble(0x24020001, 0x100)
        assert "ADDIU" in s
        assert "v0" in s

    def test_sw_disasm(self):
        s = ee_isa.disassemble(0xAC430008, 0x100)
        assert "SW" in s
        assert "8" in s

    def test_bne_disasm(self):
        s = ee_isa.disassemble(0x14850001, 0x100)
        assert "BNE" in s
        assert "0x" in s   # target address shown


class TestMemoryMap:
    def test_bios_region(self):
        from ps2emu.memory.map import BIOS_BASE, phys_addr
        assert phys_addr(0xBFC00000) == BIOS_BASE

    def test_kseg0(self):
        from ps2emu.memory.map import phys_addr
        assert phys_addr(0x80001234) == 0x00001234

    def test_kseg1(self):
        from ps2emu.memory.map import phys_addr
        assert phys_addr(0xA0001234) == 0x00001234

    def test_ee_ram_rw(self):
        bus = MemoryBus()
        bus.write32(0x00001000, 0xDEADBEEF)
        assert bus.read32(0x00001000) == 0xDEADBEEF

    def test_scratchpad_rw(self):
        bus = MemoryBus()
        bus.write32(0x70000000, 0x12345678)
        assert bus.read32(0x70000000) == 0x12345678


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
