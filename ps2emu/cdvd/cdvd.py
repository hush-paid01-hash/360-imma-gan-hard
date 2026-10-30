"""
CDVD Drive Controller
----------------------
The PS2 CDVD subsystem is controlled by IOP module cdvdman.
Games are distributed on DVD-ROM (or CD-ROM for PS1 compat).

CDVD registers (IOP address space, mapped via SIF to EE):
  0x1F402004  N_COMMAND  — drive command register
  0x1F402005  N_READY    — command ready status
  0x1F402006  N_DATA     — command data port
  0x1F402008  S_COMMAND  — sub-command register
  0x1F40200A  S_READY    — sub-command ready
  0x1F40200B  S_DATA     — sub-command data
  0x1F40200C  KEY_XXX    — CD key / mechacon registers
  0x1F402016  N_STATUS   — drive status

Commands include:
  0x00 = CDVDGetToc        (read table of contents)
  0x06 = CDVDSeekL         (seek to LBA)
  0x07 = CDVDStartStream   (start streaming read)
  0x08 = CDVDStop          (stop spindle)
  0x09 = CDVDPause         (pause)
  0x0A = CDVDBreak         (abort current command)
  0x0C = CDVDReadNVM       (read NVM/EEPROM)
  0x0F = CDVDGetPS2Disc    (disc type detection)

This module implements a disc image loader (ISO 9660 for DVD)
and routes CDVD commands to the image.
"""

import logging
import struct
import os

log = logging.getLogger(__name__)

SECTOR_SIZE    = 2048     # Mode 2 Form 1 user data per sector
RAW_SECTOR_SIZE= 2352     # Full raw sector size

DISC_NONE   = 0
DISC_PS2DVD = 0x14
DISC_PS2CD  = 0x12
DISC_PSCD   = 0x11


class ISOImage:
    """
    ISO 9660 / UDF disc image reader.
    Supports .iso files (2048-byte sectors).
    """

    def __init__(self, path: str):
        self._f    = open(path, "rb")
        self._size = os.path.getsize(path)
        self._detect_disc_type()

    def _detect_disc_type(self) -> None:
        # Read primary volume descriptor at sector 16
        try:
            data = self.read_sector(16)
            if data[1:6] == b"CD001":
                self.disc_type = DISC_PS2DVD
                self._volume_id = data[40:72].decode("ascii", errors="replace").strip()
                log.info("ISO: disc type DVD, volume='%s'", self._volume_id)
            else:
                self.disc_type = DISC_NONE
                self._volume_id = ""
                log.warning("ISO: unknown disc format at sector 16")
        except Exception as e:
            log.error("ISO: failed to read PVD: %s", e)
            self.disc_type = DISC_NONE

    def read_sector(self, lba: int) -> bytes:
        self._f.seek(lba * SECTOR_SIZE)
        data = self._f.read(SECTOR_SIZE)
        if len(data) < SECTOR_SIZE:
            data = data.ljust(SECTOR_SIZE, b"\x00")
        return data

    def read_sectors(self, lba: int, count: int) -> bytes:
        chunks = []
        for i in range(count):
            chunks.append(self.read_sector(lba + i))
        return b"".join(chunks)

    def find_file(self, path: str) -> tuple[int, int]:
        """
        Locate a file in ISO 9660 directory tree.
        Returns (start_lba, size_bytes) or raises FileNotFoundError.
        path should be like "/SYSTEM.CNF" or "/SLUS_201.23;1"
        """
        # Parse root directory
        pvd = self.read_sector(16)
        root_lba  = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        return self._find_in_dir(root_lba, root_size, path.lstrip("/").split("/"))

    def _find_in_dir(self, dir_lba: int, dir_size: int,
                     parts: list[str]) -> tuple[int, int]:
        data = self.read_sectors(dir_lba, (dir_size + SECTOR_SIZE - 1) // SECTOR_SIZE)
        offset = 0
        target = parts[0].upper()
        while offset < len(data):
            rec_len = data[offset]
            if rec_len == 0:
                offset = (offset | (SECTOR_SIZE - 1)) + 1
                continue
            flags   = data[offset + 25]
            lba     = struct.unpack_from("<I", data, offset + 2)[0]
            size    = struct.unpack_from("<I", data, offset + 10)[0]
            name_len= data[offset + 32]
            name    = data[offset+33:offset+33+name_len].decode("ascii", errors="replace").upper()
            # Strip version suffix ";1"
            name = name.split(";")[0]
            if name == target:
                if len(parts) == 1:
                    return (lba, size)
                elif flags & 2:   # directory
                    return self._find_in_dir(lba, size, parts[1:])
            offset += rec_len
        raise FileNotFoundError(f"'{parts[0]}' not found in ISO")

    def close(self) -> None:
        self._f.close()


class CDVD:
    """CDVD controller with ISO image backend."""

    def __init__(self):
        self._image: ISOImage | None = None
        self._status    = 0x00   # idle
        self._disc_type = DISC_NONE
        self._lba       = 0
        self._sector_buf: bytes = b""
        self._sector_pos = 0

    def load_disc(self, path: str) -> None:
        if self._image:
            self._image.close()
        self._image = ISOImage(path)
        self._disc_type = self._image.disc_type
        log.info("CDVD: disc loaded '%s' (type=0x%02X)", path, self._disc_type)

    def eject(self) -> None:
        if self._image:
            self._image.close()
            self._image = None
        self._disc_type = DISC_NONE
        log.info("CDVD: disc ejected")

    def read_sectors(self, lba: int, count: int) -> bytes:
        if not self._image:
            raise IOError("No disc inserted")
        return self._image.read_sectors(lba, count)

    def get_disc_type(self) -> int:
        return self._disc_type

    def find_boot_elf(self) -> tuple[int, int]:
        """
        Find boot ELF by reading SYSTEM.CNF and parsing BOOT2= line.
        Returns (lba, size).
        """
        if not self._image:
            raise IOError("No disc inserted")
        # Read SYSTEM.CNF
        lba, size = self._image.find_file("SYSTEM.CNF")
        data = self._image.read_sectors(lba, (size + SECTOR_SIZE - 1) // SECTOR_SIZE)
        conf = data[:size].decode("latin-1", errors="replace")
        for line in conf.splitlines():
            if line.strip().startswith("BOOT2"):
                _, _, val = line.partition("=")
                boot_path = val.strip()
                # Format: cdrom0:\SLUS_201.23;1  — strip prefix
                boot_path = boot_path.split("\\", 1)[-1].split("/", 1)[-1]
                log.info("CDVD: BOOT2 = %s", boot_path)
                return self._image.find_file(boot_path)
        raise ValueError("BOOT2 entry not found in SYSTEM.CNF")
