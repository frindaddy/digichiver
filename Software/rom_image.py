"""ROM-image loading helpers shared by the emulator and host tests."""

ROM_BANK_SIZE = 8 * 1024
ROM_SIZE = 2 * ROM_BANK_SIZE


def _read_exact(path, target):
    """Read one ROM bank into *target*, rejecting short and oversized files."""
    with open(path, "rb") as rom_file:
        bytes_read = rom_file.readinto(target)
        if bytes_read != ROM_BANK_SIZE:
            raise ValueError("%s must contain exactly %d bytes" % (path, ROM_BANK_SIZE))
        if rom_file.read(1):
            raise ValueError("%s must contain exactly %d bytes" % (path, ROM_BANK_SIZE))


def load_ssr_pair(target, ssr1_path, ssr2_path):
    """Load SSR1 then SSR2 into a writable 16 KiB buffer.

    The Digitalker presents ROM_ADDR13 as the 8 KiB-bank select: SSR1 occupies
    addresses 0x0000..0x1fff and SSR2 occupies 0x2000..0x3fff.
    """
    if len(target) != ROM_SIZE:
        raise ValueError("ROM target must be exactly %d bytes" % ROM_SIZE)

    # bytearray slices are copies on CPython and MicroPython; DMA needs the
    # original allocation, so always pass writable memoryviews to readinto().
    view = memoryview(target)
    _read_exact(ssr1_path, view[:ROM_BANK_SIZE])
    _read_exact(ssr2_path, view[ROM_BANK_SIZE:])
