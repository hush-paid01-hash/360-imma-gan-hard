"""
ELF Loader for PS2
-------------------
Parses and loads ELF32 executables (MIPS little-endian) into EE RAM.
The PS2 game boot flow:
  1. BIOS reads SYSTEM.CNF from disc
  2. BIOS loads the BOOT2 ELF into RAM
  3. BIOS jumps to ELF entry point

PS2 ELF characteristics:
  - MIPS little-endian (e_machine = 0x0008 EM_MIPS)
  - Multiple PT_LOAD segments
  - Entry point typically 0x00100000 (EE user space)
  - Sometimes compressed (not handled here)
"""

import struct
import logging
from ..memory.bus import MemoryBus

log = logging.getLogger(__name__)

ELF_MAGIC = b"\x7fELF"

# ELF32 header layout
ELF_HDR_FMT = "<4sBBBBxxxxxxxx HHIIIIIHHHHHH"
# Phdr layout
ELF_PHDR_FMT = "<IIIIIIII"

ET_EXEC = 2
EM_MIPS = 8
PT_LOAD = 1


class ELFLoadError(Exception):
    pass


def load_elf(data: bytes, bus: MemoryBus) -> int:
    """
    Parse ELF `data` and load PT_LOAD segments into `bus`.
    Returns the entry point address.
    """
    if data[:4] != ELF_MAGIC:
        raise ELFLoadError("Not an ELF file")

    ei_class = data[4]
    if ei_class != 1:
        raise ELFLoadError(f"Expected ELF32 (class 1), got {ei_class}")
    ei_data = data[5]
    if ei_data != 1:
        raise ELFLoadError(f"Expected little-endian (data 1), got {ei_data}")

    (magic, ei_cl, ei_dt, ei_ver, ei_os, e_type, e_machine, e_version,
     e_entry, e_phoff, e_shoff, e_flags, e_ehsize,
     e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx
    ) = struct.unpack_from("<4sBBBBxxxxxxxx HHIIIIIHHHHHH", data, 0)

    if e_type != ET_EXEC:
        raise ELFLoadError(f"Not an executable ELF (e_type={e_type})")
    if e_machine != EM_MIPS:
        raise ELFLoadError(f"Not a MIPS ELF (e_machine={e_machine})")

    log.info("ELF: entry=0x%08X  %d segments", e_entry, e_phnum)

    for i in range(e_phnum):
        phdr_off = e_phoff + i * e_phentsize
        (p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz,
         p_flags, p_align
        ) = struct.unpack_from(ELF_PHDR_FMT, data, phdr_off)

        if p_type != PT_LOAD:
            continue
        if p_filesz == 0 and p_memsz == 0:
            continue

        log.info("  LOAD vaddr=0x%08X  filesz=0x%X  memsz=0x%X  flags=0x%X",
                 p_vaddr, p_filesz, p_memsz, p_flags)

        # Zero BSS region first
        if p_memsz > p_filesz:
            for off in range(0, p_memsz - p_filesz, 4096):
                chunk = min(4096, p_memsz - p_filesz - off)
                bus._write_bytes(p_vaddr + p_filesz + off & 0x1FFFFFFF,
                                 b"\x00" * chunk)

        # Copy segment data
        seg = data[p_offset:p_offset + p_filesz]
        phys = p_vaddr & 0x1FFFFFFF   # strip KSEG bits
        bus._write_bytes(phys, seg)

    return e_entry
