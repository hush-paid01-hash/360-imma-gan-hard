"""
DualShock 2 Controller (PAD) — Input Handler
---------------------------------------------
The PS2 PAD communicates via SIO2 (serial I/O) on the IOP.
The controller state is a 32-bit bitmask:

  Byte 0 (buttons high):
    bit 7: SELECT    bit 6: L3      bit 5: R3    bit 4: START
    bit 3: UP        bit 2: RIGHT   bit 1: DOWN  bit 0: LEFT
  Byte 1 (buttons low):
    bit 7: L2        bit 6: R2      bit 5: L1    bit 4: R1
    bit 3: TRIANGLE  bit 2: CIRCLE  bit 1: CROSS bit 0: SQUARE
  Bytes 2–3: Right stick (X, Y)
  Bytes 4–5: Left stick (X, Y)

Bits are ACTIVE LOW (0 = pressed).
"""

from dataclasses import dataclass, field

# Button bit positions in the 16-bit button word (active low)
class Btn:
    SELECT   = 1 << 0
    L3       = 1 << 1
    R3       = 1 << 2
    START    = 1 << 3
    UP       = 1 << 4
    RIGHT    = 1 << 5
    DOWN     = 1 << 6
    LEFT     = 1 << 7
    L2       = 1 << 8
    R2       = 1 << 9
    L1       = 1 << 10
    R1       = 1 << 11
    TRIANGLE = 1 << 12
    CIRCLE   = 1 << 13
    CROSS    = 1 << 14
    SQUARE   = 1 << 15


@dataclass
class ControllerState:
    """State of one DualShock 2 controller."""
    buttons:   int = 0xFFFF   # all released (active low)
    lx: int = 0x80  # left  stick X (128=center)
    ly: int = 0x80  # left  stick Y
    rx: int = 0x80  # right stick X
    ry: int = 0x80  # right stick Y

    def press(self, btn: int) -> None:
        self.buttons &= ~btn

    def release(self, btn: int) -> None:
        self.buttons |= btn

    def to_bytes(self) -> bytes:
        """Serialize to 6-byte DualShock2 poll response (after header)."""
        return bytes([
            (self.buttons >> 0) & 0xFF,
            (self.buttons >> 8) & 0xFF,
            self.rx, self.ry,
            self.lx, self.ly,
        ])


class PAD:
    """
    Input manager for up to 2 controllers.
    Translates host keyboard/gamepad events into controller state.
    """

    def __init__(self):
        self.controllers = [ControllerState(), ControllerState()]

    def get_state(self, port: int = 0) -> ControllerState:
        return self.controllers[port % 2]

    def key_down(self, key: str, port: int = 0) -> None:
        btn = _KEY_MAP.get(key)
        if btn:
            self.controllers[port].press(btn)

    def key_up(self, key: str, port: int = 0) -> None:
        btn = _KEY_MAP.get(key)
        if btn:
            self.controllers[port].release(btn)


# Default keyboard mapping (pygame key names)
_KEY_MAP: dict[str, int] = {
    "return":    Btn.START,
    "rshift":    Btn.SELECT,
    "up":        Btn.UP,
    "down":      Btn.DOWN,
    "left":      Btn.LEFT,
    "right":     Btn.RIGHT,
    "z":         Btn.CROSS,
    "x":         Btn.CIRCLE,
    "a":         Btn.SQUARE,
    "s":         Btn.TRIANGLE,
    "q":         Btn.L1,
    "w":         Btn.L2,
    "e":         Btn.R1,
    "r":         Btn.R2,
}
