"""
SDL2 Display Backend
---------------------
Renders the GS framebuffer to a window using pygame (SDL2).
Falls back gracefully if pygame is not installed.

Usage:
    display = SDLDisplay(640, 448, title="PS2EMU")
    display.blit_framebuffer(vram_bytes, fb_base, fb_width, psm=0)
    display.flip()
    alive = display.poll_events()

PSM (Pixel Storage Mode) values supported for display:
  0 = PSMCT32  (RGBA8888 — 4 bytes/px)
  1 = PSMCT24  (RGB888 packed — 3 bytes/px, ignore alpha byte)
  2 = PSMCT16  (RGBA5551 — 2 bytes/px)
  10= PSMCT16S (RGB565  — 2 bytes/px)
"""

import logging
import struct

log = logging.getLogger(__name__)

try:
    import pygame
    _PYGAME_OK = True
except ImportError:
    _PYGAME_OK = False
    log.info("pygame not available — display disabled (headless mode)")


class SDLDisplay:
    """Window display backed by pygame/SDL2."""

    def __init__(self, width: int = 640, height: int = 448,
                 title: str = "PS2EMU", scale: int = 1):
        self.width  = width
        self.height = height
        self.scale  = scale
        self._alive = True
        self._screen = None

        if not _PYGAME_OK:
            log.warning("Display: headless (pygame missing)")
            return

        pygame.init()
        pygame.display.set_caption(title)
        self._screen = pygame.display.set_mode(
            (width * scale, height * scale),
            pygame.RESIZABLE
        )
        self._surface = pygame.Surface((width, height))
        log.info("Display: SDL2 window %dx%d (scale×%d)", width, height, scale)

    def blit_framebuffer(self, vram: bytes, fb_base: int,
                         fb_width: int, fb_height: int, psm: int = 0) -> None:
        """Copy framebuffer from VRAM bytes to the display surface."""
        if not _PYGAME_OK or self._screen is None:
            return

        stride = fb_width
        pixels = bytearray(self.width * self.height * 4)

        for y in range(min(fb_height, self.height)):
            for x in range(min(fb_width, self.width)):
                src = fb_base + (y * stride + x)
                if psm == 0:   # PSMCT32
                    src *= 4
                    if src + 4 > len(vram):
                        continue
                    r, g, b, a = vram[src], vram[src+1], vram[src+2], vram[src+3]
                elif psm in (2, 10):  # 16-bit
                    src *= 2
                    if src + 2 > len(vram):
                        continue
                    raw = struct.unpack_from("<H", vram, src)[0]
                    if psm == 2:   # PSMCT16 ABGR5551
                        r = (raw & 0x1F) << 3
                        g = ((raw >> 5) & 0x1F) << 3
                        b = ((raw >> 10) & 0x1F) << 3
                        a = 255 if (raw >> 15) else 0
                    else:          # PSMCT16S BGR565
                        r = (raw & 0x1F) << 3
                        g = ((raw >> 5) & 0x3F) << 2
                        b = ((raw >> 11) & 0x1F) << 3
                        a = 255
                else:
                    continue

                dst = (y * self.width + x) * 4
                pixels[dst]   = r
                pixels[dst+1] = g
                pixels[dst+2] = b
                pixels[dst+3] = a

        surf = pygame.image.frombuffer(bytes(pixels), (self.width, self.height), "RGBA")
        if self.scale == 1:
            self._screen.blit(surf, (0, 0))
        else:
            scaled = pygame.transform.scale(surf, (self.width * self.scale,
                                                    self.height * self.scale))
            self._screen.blit(scaled, (0, 0))

    def flip(self) -> None:
        if _PYGAME_OK and self._screen:
            pygame.display.flip()

    def poll_events(self) -> bool:
        """Process SDL events. Returns False if window was closed."""
        if not _PYGAME_OK:
            return True
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._alive = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._alive = False
        return self._alive

    def set_title(self, title: str) -> None:
        if _PYGAME_OK:
            pygame.display.set_caption(title)

    def close(self) -> None:
        if _PYGAME_OK:
            pygame.quit()
