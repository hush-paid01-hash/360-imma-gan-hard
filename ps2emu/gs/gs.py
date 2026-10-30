"""
Graphics Synthesizer (GS)
--------------------------
The GS is a custom ASIC rasterizer on the PS2 with:
  - 4 MB embedded eDRAM (VRAM, 1024-bit wide bus)
  - Fixed-function rasterization pipeline
  - Up to 1024x1024 texture pages
  - Various primitive types: point, line, triangle, sprite
  - Alpha blending, z-test, texture mapping
  - Two drawing contexts (CTXT1 / CTXT2)

GS has two access modes:
  1. Privileged registers (0x12000000): accessed by EE kernel
  2. GIF (Graphics Interface) packets: DMA from EE, fed via GIF PATH3

GS registers (64-bit each, write-only most of them):
  PMODE    (0x00): output circuit control
  SMODE1   (0x04): video mode (NTSC/PAL etc.)
  SMODE2   (0x08): sync / interlace
  SRFSH    (0x0C): refresh enable
  SYNCH1   (0x10): H-sync timing
  SYNCH2   (0x14): H-sync timing
  SYNCV    (0x18): V-sync timing
  DISPFB1  (0x1C): display framebuffer 1
  DISPLAY1 (0x20): display 1 position/size
  DISPFB2  (0x24): display framebuffer 2
  DISPLAY2 (0x28): display 2 position/size
  EXTBUF   (0x2C): external input buffer
  EXTDATA  (0x30): external input data
  EXTWRITE (0x34): external write trigger
  BGCOLOR  (0x38): background color
  CSR      (0x1000): GS status/control (read/write)
  IMR      (0x1004): interrupt mask
  BUSDIR   (0x1040): VRAM bus direction (host→local / local→host)
  SIGLBLID (0x1080): signal/label ID

GIF PATH registers inside GS (context-dependent):
  FRAME, ZBUF, XYOFFSET, SCISSOR, ALPHA, DIMX,
  DTHE, COLCLAMP, TEST, PABE, FBA, TEXFLUSH, etc.
"""

import logging
import struct
from typing import Optional

log = logging.getLogger(__name__)

VRAM_SIZE = 4 * 1024 * 1024   # 4 MB


class GSContext:
    """Per-context drawing state (CTXT1 or CTXT2)."""
    __slots__ = (
        "frame_base", "frame_width", "frame_psm",
        "zbuf_base", "zbuf_psm", "zbuf_mask",
        "xyoffset_x", "xyoffset_y",
        "scissor_x0", "scissor_x1", "scissor_y0", "scissor_y1",
        "prmode",   # primitive attributes
        "tex0",     # texture setup register
        "alpha",    # alpha blending
        "test",     # pixel test (z-test, alpha-test, etc.)
    )
    def __init__(self):
        self.frame_base  = 0
        self.frame_width = 10   # 64-pixel units
        self.frame_psm   = 0    # pixel storage mode (0=PSMCT32)
        self.zbuf_base   = 0
        self.zbuf_psm    = 0
        self.zbuf_mask   = 0
        self.xyoffset_x  = 0
        self.xyoffset_y  = 0
        self.scissor_x0  = 0; self.scissor_x1 = 639
        self.scissor_y0  = 0; self.scissor_y1 = 447
        self.prmode      = 0
        self.tex0        = 0
        self.alpha       = 0
        self.test        = 0


class GS:
    """
    Graphics Synthesizer.

    In a full emulator this drives a real renderer (OpenGL/Vulkan).
    Here we model the register state and VRAM correctly so the
    BIOS can initialize the GS without crashing.
    """

    def __init__(self):
        self.vram = bytearray(VRAM_SIZE)
        self.ctx  = [GSContext(), GSContext()]

        # Privileged registers
        self.pmode    = 0
        self.smode1   = 0
        self.smode2   = 0
        self.dispfb1  = 0
        self.display1 = 0
        self.dispfb2  = 0
        self.display2 = 0
        self.bgcolor  = 0
        self.csr      = 0x551B400F   # reset value from HW
        self.imr      = 0xFF00

        # GIF state
        self._gif_path3_active = False
        self._gif_tag   = 0
        self._gif_nloop = 0
        self._gif_regs  = 0

        # Current primitive vertex buffer
        self._vertices: list[tuple] = []
        self._prim = 0

    def priv_read(self, offset: int) -> int:
        """Read from privileged GS register space (0x12000000+offset)."""
        if offset == 0x1000: return self.csr
        if offset == 0x1004: return self.imr
        log.debug("GS priv read offset 0x%04X", offset)
        return 0

    def priv_write(self, offset: int, val: int) -> None:
        """Write to privileged GS register space."""
        if offset == 0x00:   self.pmode    = val
        elif offset == 0x04: self.smode1   = val
        elif offset == 0x08: self.smode2   = val
        elif offset == 0x1C: self.dispfb1  = val
        elif offset == 0x20: self.display1 = val
        elif offset == 0x24: self.dispfb2  = val
        elif offset == 0x28: self.display2 = val
        elif offset == 0x38: self.bgcolor  = val
        elif offset == 0x1000:
            # Writing to CSR: bit 9=RESET clears GS state
            if val & (1 << 9):
                log.info("GS reset via CSR")
                self.csr = 0x551B400F
            else:
                self.csr = val
        elif offset == 0x1004:
            self.imr = val
        else:
            log.debug("GS priv write offset 0x%04X = 0x%016X", offset, val)

    def gif_write(self, data: bytes) -> None:
        """
        Feed GIF packet data (from GIF DMA / PATH3).
        GIF transfers are in 128-bit (16-byte) quadwords.
        """
        assert len(data) % 16 == 0, "GIF data must be 16-byte aligned"
        pos = 0
        while pos < len(data):
            qword = data[pos:pos+16]
            pos += 16
            self._gif_qword(qword)

    def _gif_qword(self, qw: bytes) -> None:
        lo, hi = struct.unpack("<QQ", qw)
        if self._gif_nloop == 0:
            # This is a GIFtag
            self._gif_nloop = lo & 0x7FFF
            self._gif_eop   = (lo >> 15) & 1
            prim_en         = (lo >> 46) & 1
            self._gif_prim  = (lo >> 47) & 0x7FF
            self._gif_flg   = (lo >> 58) & 3   # 0=PACKED,1=REGLIST,2=IMAGE
            self._gif_nreg  = (lo >> 60) & 0xF
            if self._gif_nreg == 0: self._gif_nreg = 16
            self._gif_regs  = hi   # 4-bit register descriptors, 16 packed
            if prim_en:
                self._set_prim(self._gif_prim)
            return

        if self._gif_flg == 0:   # PACKED
            self._gif_packed(lo, hi)
        elif self._gif_flg == 1: # REGLIST
            self._gif_reglist(lo, hi)
        elif self._gif_flg == 2: # IMAGE
            self._gif_image(lo, hi)

        self._gif_nloop -= 1

    def _gif_packed(self, lo: int, hi: int) -> None:
        reg_idx = ((self._gif_nreg - (self._gif_nloop % self._gif_nreg)) - 1) % self._gif_nreg
        reg = (self._gif_regs >> (reg_idx * 4)) & 0xF
        self._gs_write_reg(reg, lo | (hi << 64))

    def _gif_reglist(self, lo: int, hi: int) -> None:
        self._gs_write_reg((self._gif_regs >> 0)  & 0xF, lo & 0xFFFFFFFF)
        self._gs_write_reg((self._gif_regs >> 4)  & 0xF, lo >> 32)
        self._gs_write_reg((self._gif_regs >> 8)  & 0xF, hi & 0xFFFFFFFF)
        self._gs_write_reg((self._gif_regs >> 12) & 0xF, hi >> 32)

    def _gif_image(self, lo: int, hi: int) -> None:
        pass   # VRAM upload — handled by TRXPOS/TRXREG/TRXDIR

    def _gs_write_reg(self, reg: int, val: int) -> None:
        """GS internal register write (via GIF PACKED/REGLIST)."""
        handlers = {
            0x00: self._reg_prim,
            0x01: self._reg_rgbaq,
            0x02: self._reg_st,
            0x03: self._reg_uv,
            0x04: self._reg_xyzf2,
            0x05: self._reg_xyz2,
            0x0E: self._reg_ad,    # A+D: general register write
            0x0F: lambda v: None,   # NOP
        }
        fn = handlers.get(reg)
        if fn:
            fn(val)
        else:
            log.debug("GS reg 0x%02X = 0x%016X", reg, val)

    def _reg_prim(self, val: int) -> None:
        self._set_prim(val & 0x7FF)

    def _set_prim(self, prim: int) -> None:
        self._prim = prim
        self._vertices = []

    def _reg_rgbaq(self, val: int) -> None:
        self._rgba = val & 0xFFFFFFFFFF

    def _reg_st(self, val: int) -> None:
        self._s = (val & 0xFFFFFFFF)
        self._t = (val >> 32) & 0xFFFFFFFF

    def _reg_uv(self, val: int) -> None:
        self._u = val & 0x3FFF
        self._v = (val >> 16) & 0x3FFF

    def _reg_xyzf2(self, val: int) -> None:
        x = val & 0xFFFF
        y = (val >> 16) & 0xFFFF
        z = (val >> 32) & 0xFFFFFF
        self._kick_vertex(x, y, z, fog=((val >> 56) & 0xFF), drawing_kick=True)

    def _reg_xyz2(self, val: int) -> None:
        x = val & 0xFFFF
        y = (val >> 16) & 0xFFFF
        z = (val >> 32) & 0xFFFFFFFF
        self._kick_vertex(x, y, z, fog=0, drawing_kick=True)

    def _reg_ad(self, val: int) -> None:
        """A+D — writes to any GS register by address in upper 8 bits."""
        reg = (val >> 56) & 0xFF
        data = val & 0x00FFFFFFFFFFFFFF
        log.debug("GS A+D reg 0x%02X = 0x%016X", reg, data)

    def _kick_vertex(self, x: int, y: int, z: int, fog: int, drawing_kick: bool) -> None:
        self._vertices.append((x, y, z, getattr(self, "_rgba", 0)))
        prim_type = self._prim & 7
        verts_needed = [1, 2, 3, 3, 4, 4, 2, 2][prim_type] if prim_type < 8 else 1
        if drawing_kick and len(self._vertices) >= verts_needed:
            self._rasterize(prim_type, self._vertices[-verts_needed:])
            if prim_type in (3, 4):   # strip: keep last N-1
                self._vertices = self._vertices[-(verts_needed-1):]

    def _rasterize(self, prim_type: int, verts: list) -> None:
        # In a full emulator: rasterize to VRAM using the GS pixel pipeline
        # (z-test, texture mapping, alpha blend, etc.)
        pass

    def get_framebuffer(self, ctx_idx: int = 0) -> tuple[int, int, int, int]:
        """Return (base_addr, width_pixels, height_pixels, psm) for display."""
        ctx = self.ctx[ctx_idx]
        return (ctx.frame_base * 64, ctx.frame_width * 64, 448, ctx.frame_psm)
