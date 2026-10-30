"""
PS2EMU - PlayStation 2 Emulator
================================
Architecture mirrors real PS2 hardware:
  - Emotion Engine (EE): MIPS R5900 64-bit CPU @ 294 MHz
  - Vector Processing Units: VU0 (COP2), VU1 (standalone)
  - Graphics Synthesizer (GS): rasterizer + VRAM
  - I/O Processor (IOP): MIPS R3000A @ 36.864 MHz
  - Sound Processing Unit (SPU2)
  - DMA Controller (DMAC)
  - Memory: 32MB EE RAM, 2MB IOP RAM, 4MB VRAM (GS local)
"""

__version__ = "0.1.0"
__author__ = "PS2EMU Project"
