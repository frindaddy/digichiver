"""PIO/DMA-backed MM54104 parallel-ROM emulator for the Digichiver board.

No Python executes after ROMEN asserts.  PIO1 turns each ROM request into an
absolute SRAM pointer, DMA fetches the byte, and PIO0 drives RDATA[0..7].
"""

from machine import Pin, mem32
import rp2
import uctypes

from rom_image import ROM_SIZE, load_ssr_pair


# RP2350 peripheral addresses and register layout.  The DMA channel aliases
# are deliberately used so one DMA channel can arm and trigger the other.
DMA_BASE = 0x50000000
DMA_CH_STRIDE = 0x40
DMA_READ_ADDR = 0x00
DMA_WRITE_ADDR = 0x04
DMA_TRANS_COUNT = 0x08
DMA_CTRL_TRIG = 0x0C
DMA_AL1_CTRL = 0x10
DMA_AL3_READ_ADDR_TRIG = 0x3C
DMA_CH_DBG_CTDREQ_BASE = 0x800
DMA_CH_DBG_TCR_BASE = 0x804
DMA_CHAN_ABORT = 0x464

DMA_CTRL_READ_ERROR = 1 << 30
DMA_CTRL_WRITE_ERROR = 1 << 29
DMA_CTRL_BUSY = 1 << 26
DMA_TRANS_COUNT_TRIGGER_SELF = 1 << 28

PIO0_BASE = 0x50200000
PIO1_BASE = 0x50300000
PIO_TXF0 = PIO0_BASE + 0x10
PIO_RXF0 = PIO1_BASE + 0x20
PIO_FDEBUG = 0x08
PIO_FLEVEL = 0x0C
PIO_FSTAT = 0x04
# RP2350 adds GPIOBASE after the PIO interrupt register block.  It is not
# adjacent to the FIFO registers as it is tempting to assume from RP2040.
PIO_GPIOBASE = 0x168

# DREQ values are shared by RP2040/RP2350: PIO0 TX0 is 0 and PIO1 RX0 is 12.
DREQ_PIO0_TX0 = 0
DREQ_PIO1_RX0 = 12

DMA_DATA_CHANNEL = 10
DMA_CONTROL_CHANNEL = 11

ROM_ALIGNMENT = ROM_SIZE
RDATA_BASE = 12
ROM_ADDR_BASE = 20
ROMEN_GPIO = 34


def _dma_channel_base(channel):
    return DMA_BASE + channel * DMA_CH_STRIDE


def _dma_ctrl(*, size, inc_read, inc_write, treq, chain_to, ring_size=0,
              ring_write=False, high_priority=True):
    """Build the RP2350 DMA CTRL_TRIG value needed by this emulator."""
    # RP2350 keeps DATA_SIZE and INCR_READ in their RP2040 positions, but
    # inserts INCR_READ_REV and INCR_WRITE_REV.  INCR_WRITE and every field
    # above it therefore move.  See RP2350 datasheet table 1151.
    value = 1  # EN
    value |= int(high_priority) << 1
    value |= size << 2
    value |= int(inc_read) << 4
    value |= int(inc_write) << 6
    value |= ring_size << 8
    value |= int(ring_write) << 12
    value |= chain_to << 13
    value |= treq << 17
    value |= 1 << 23  # IRQ_QUIET: this streaming path does not need IRQs.
    return value


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT)
def _capture_request():
    """Push an absolute SRAM address whenever the active ROM address changes."""
    pull(block)
    # OSR permanently holds the SRAM base address divided by 16 KiB.  X is
    # the last absolute address served and Y is the current address.
    wrap_target()
    label("idle")
    wait(0, gpio, 2)            # System GPIO34 with PIO GPIOBASE=16.
    mov(isr, osr)
    in_(pins, 14)               # GPIO20..33, relative to GPIO base 16.
    mov(x, isr)
    push(block)                 # Always serve the first address after ROMEN.

    label("active")
    jmp(pin, "idle")            # ROMEN high: wait for the next assertion.
    mov(isr, osr)
    in_(pins, 14)
    mov(y, isr)
    jmp(x_not_y, "changed")
    jmp("active")

    label("changed")
    mov(x, y)
    mov(isr, y)
    push(block)
    jmp("active")
    wrap()


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT)
def _trace_request():
    """Passively retain the first few distinct ROM addresses for bring-up."""
    wrap_target()
    label("trace_idle")
    wait(0, gpio, 2)            # System GPIO34 with PIO GPIOBASE=16.
    mov(isr, null)
    in_(pins, 14)
    mov(x, isr)
    push(noblock)

    label("trace_active")
    jmp(pin, "trace_idle")
    mov(isr, null)
    in_(pins, 14)
    mov(y, isr)
    jmp(x_not_y, "trace_changed")
    jmp("trace_active")

    label("trace_changed")
    mov(x, y)
    mov(isr, y)
    push(noblock)
    jmp("trace_active")
    wrap()


@rp2.asm_pio(
    out_shiftdir=rp2.PIO.SHIFT_RIGHT,
    out_init=(rp2.PIO.OUT_LOW,) * 8,
)
def _drive_data():
    """Consume one DMA word and present its low byte on RDATA[0..7]."""
    wrap_target()
    pull(block)
    out(pins, 8)
    wrap()


class RomEmulator:
    """Serve an SSR1/SSR2 image as the MM54104's 16 KiB parallel ROM."""

    def __init__(self, ssr1_path="SSR1.bin", ssr2_path="SSR2.bin"):
        self.ssr1_path = ssr1_path
        self.ssr2_path = ssr2_path
        self._allocation = None
        self._rom = None
        self._rom_address = None
        self._capture_sm = None
        self._output_sm = None
        self._trace_sm = None
        self.running = False

    def load(self):
        """Allocate an aligned SRAM image and load SSR1 followed by SSR2."""
        if self.running:
            raise RuntimeError("stop the ROM emulator before loading a new image")

        # PIO creates the DMA source address by replacing the low 14 bits, so
        # the backing image must begin on a 16 KiB boundary.
        allocation = bytearray(ROM_SIZE + ROM_ALIGNMENT - 1)
        allocation_address = uctypes.addressof(allocation)
        offset = (-allocation_address) & (ROM_ALIGNMENT - 1)
        rom = memoryview(allocation)[offset:offset + ROM_SIZE]
        load_ssr_pair(rom, self.ssr1_path, self.ssr2_path)

        self._allocation = allocation  # Keep the DMA buffer alive and fixed.
        self._rom = rom
        self._rom_address = uctypes.addressof(rom)
        if self._rom_address & (ROM_ALIGNMENT - 1):
            raise RuntimeError("unable to allocate a 16 KiB-aligned ROM image")

    def start(self):
        """Arm PIO and DMA.  Call load() successfully before start()."""
        if self.running:
            return
        if self._rom is None:
            raise RuntimeError("call load() before start()")

        # The bus is not tri-stated by the fitted always-enabled level shifter;
        # make its inactive value known until the first ROM transaction.
        for gpio in range(RDATA_BASE, RDATA_BASE + 8):
            Pin(gpio, Pin.OUT, value=0)
        for gpio in range(ROM_ADDR_BASE, ROMEN_GPIO + 1):
            Pin(gpio, Pin.IN)

        # PIO0 handles GPIO12..19 with base 0.  PIO1 handles GPIO20..34 with
        # base 16, allowing both the 14-bit address bus and ROMEN in one SM.
        mem32[PIO0_BASE + PIO_GPIOBASE] = 0
        mem32[PIO1_BASE + PIO_GPIOBASE] = 16
        self._output_sm = rp2.StateMachine(
            0, _drive_data, freq=150_000_000, out_base=Pin(RDATA_BASE)
        )
        self._capture_sm = rp2.StateMachine(
            4, _capture_request, freq=150_000_000,
            in_base=Pin(ROM_ADDR_BASE), jmp_pin=Pin(ROMEN_GPIO)
        )
        self._trace_sm = rp2.StateMachine(
            5, _trace_request, freq=150_000_000,
            in_base=Pin(ROM_ADDR_BASE), jmp_pin=Pin(ROMEN_GPIO)
        )

        self._configure_dma()
        self._output_sm.active(1)
        self._capture_sm.put(self._rom_address >> 14)
        self._trace_sm.active(1)
        self._capture_sm.active(1)
        self.running = True

    def stop(self):
        """Disable request generation before stopping the DMA pipeline."""
        if self._capture_sm is not None:
            self._capture_sm.active(0)
        if self._output_sm is not None:
            self._output_sm.active(0)
        if self._trace_sm is not None:
            self._trace_sm.active(0)
        self._abort_dma_channels()
        self.running = False

    def request_trace(self):
        """Drain and return captured ``(ROM offset, ROM byte)`` pairs.

        The passive trace state machine has a four-entry FIFO.  It records the
        first four requests since the previous call and drops later requests,
        so reading it immediately before a command starts a fresh trace.
        """
        if self._trace_sm is None:
            return []

        # Stop the producer while draining.  Otherwise Python can empty one
        # slot, the active SM can immediately refill it, and this loop can
        # grow the result list until the heap is exhausted.
        was_active = self._trace_sm.active()
        if was_active:
            self._trace_sm.active(0)

        result = []
        for _ in range(min(4, self._trace_sm.rx_fifo())):
            offset = self._trace_sm.get() & (ROM_SIZE - 1)
            result.append((offset, self._rom[offset]))

        # Discard anything beyond the documented four-entry trace.
        while self._trace_sm.rx_fifo():
            self._trace_sm.get()

        if was_active:
            self._trace_sm.active(1)
        return result

    def diagnostics(self):
        """Return raw hardware state useful when bringing up the ROM bus."""
        control = _dma_channel_base(DMA_CONTROL_CHANNEL)
        data = _dma_channel_base(DMA_DATA_CHANNEL)
        data_read_address = mem32[data + DMA_READ_ADDR] & 0xFFFFFFFF
        last_offset = data_read_address - self._rom_address
        if 0 <= last_offset < ROM_SIZE:
            last_byte = self._rom[last_offset]
        else:
            last_offset = None
            last_byte = None
        return {
            "implementation": "rp2350-dma-v6-romen-index",
            "running": self.running,
            "rom_address": self._rom_address,
            # The low 28 bits are the remaining transfers in the current
            # self-triggered one-address control block.
            "control_dma_count": mem32[control + DMA_TRANS_COUNT] & 0xFFFFFFFF,
            "control_dma_reload": mem32[
                DMA_BASE + DMA_CH_DBG_TCR_BASE + DMA_CONTROL_CHANNEL * DMA_CH_STRIDE
            ] & 0xFFFFFFFF,
            "control_dma_dreq_credits": mem32[
                DMA_BASE + DMA_CH_DBG_CTDREQ_BASE + DMA_CONTROL_CHANNEL * DMA_CH_STRIDE
            ] & 0x3F,
            "control_dma_ctrl": mem32[control + DMA_CTRL_TRIG] & 0xFFFFFFFF,
            "data_dma_read_address": data_read_address,
            "last_rom_offset": last_offset,
            "last_rom_byte": last_byte,
            "data_dma_count": mem32[data + DMA_TRANS_COUNT] & 0xFFFFFFFF,
            "data_dma_reload": mem32[
                DMA_BASE + DMA_CH_DBG_TCR_BASE + DMA_DATA_CHANNEL * DMA_CH_STRIDE
            ] & 0xFFFFFFFF,
            "data_dma_ctrl": mem32[data + DMA_CTRL_TRIG] & 0xFFFFFFFF,
            "pio0_flevel": mem32[PIO0_BASE + PIO_FLEVEL] & 0xFFFFFFFF,
            "pio0_fdebug": mem32[PIO0_BASE + PIO_FDEBUG] & 0xFFFFFFFF,
            "pio1_flevel": mem32[PIO1_BASE + PIO_FLEVEL] & 0xFFFFFFFF,
            "pio1_fstat": mem32[PIO1_BASE + PIO_FSTAT] & 0xFFFFFFFF,
            "pio1_fdebug": mem32[PIO1_BASE + PIO_FDEBUG] & 0xFFFFFFFF,
        }

    def _configure_dma(self):
        data = _dma_channel_base(DMA_DATA_CHANNEL)
        control = _dma_channel_base(DMA_CONTROL_CHANNEL)

        # A MicroPython soft reset does not necessarily reset the DMA block.
        # Clearing EN only pauses a BUSY channel, so an old endless transfer
        # would ignore all triggers below.  Abort both sides of the pipeline
        # together, as required by RP2350 datasheet section 12.6.8.3.
        self._abort_dma_channels()

        # Clear any stale FIFO error flags from an earlier bring-up attempt.
        mem32[PIO0_BASE + PIO_FDEBUG] = 0xFFFFFFFF
        mem32[PIO1_BASE + PIO_FDEBUG] = 0xFFFFFFFF

        # The data channel is dormant until control DMA writes READ_ADDR_TRIG.
        # Its reload count remains one, so every trigger fetches one byte.  A
        # byte-wide peripheral write replicates the byte in the PIO FIFO word;
        # _drive_data always shifts out its low eight bits.
        mem32[data + DMA_READ_ADDR] = self._rom_address
        mem32[data + DMA_WRITE_ADDR] = PIO_TXF0
        mem32[data + DMA_TRANS_COUNT] = 1
        # AL1_CTRL is a non-triggering alias, leaving this channel armed but
        # dormant until the first address arrives from the control channel.
        mem32[data + DMA_AL1_CTRL] = _dma_ctrl(
            size=0, inc_read=False, inc_write=False, treq=DREQ_PIO0_TX0,
            chain_to=DMA_DATA_CHANNEL,
        )

        # Each request is one absolute address.  Writing it directly to the
        # data channel's AL3_READ_ADDR_TRIG alias reloads COUNT=1 and starts
        # the byte fetch.
        mem32[control + DMA_READ_ADDR] = PIO_RXF0
        mem32[control + DMA_WRITE_ADDR] = data + DMA_AL3_READ_ADDR_TRIG
        mem32[control + DMA_TRANS_COUNT] = DMA_TRANS_COUNT_TRIGGER_SELF | 1
        mem32[control + DMA_CTRL_TRIG] = _dma_ctrl(
            size=2, inc_read=False, inc_write=False, treq=DREQ_PIO1_RX0,
            chain_to=DMA_CONTROL_CHANNEL,
        )

    def _abort_dma_channels(self):
        """Put both reserved DMA channels into a known idle state."""
        channels = (DMA_DATA_CHANNEL, DMA_CONTROL_CHANNEL)
        mask = (1 << DMA_DATA_CHANNEL) | (1 << DMA_CONTROL_CHANNEL)

        for channel in channels:
            # EN=0 pauses the channel; CHAIN_TO=self disables chaining.  The
            # two error bits are write-one-to-clear.
            mem32[_dma_channel_base(channel) + DMA_CTRL_TRIG] = (
                DMA_CTRL_READ_ERROR
                | DMA_CTRL_WRITE_ERROR
                | (channel << 13)
            )

        mem32[DMA_BASE + DMA_CHAN_ABORT] = mask
        for _ in range(100_000):
            if not (mem32[DMA_BASE + DMA_CHAN_ABORT] & mask):
                break
        else:
            raise RuntimeError("DMA channels 10/11 did not abort")

        # Reset accumulated DREQ credits and re-initiate each handshake.
        for channel in channels:
            mem32[
                DMA_BASE + DMA_CH_DBG_CTDREQ_BASE + channel * DMA_CH_STRIDE
            ] = 0
