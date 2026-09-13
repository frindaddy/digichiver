"""Archive Digitalker ROM words as 48 kHz, 16-bit mono WAV files on SD.

PIO2 generates the I2S clocks and captures PCM1809 channel 1 while DMA moves
the samples into RAM.  Python only copies completed blocks to the SD card;
handling individual samples in Python cannot keep up with a 48 kHz stream.
"""

import json
import os
import struct
import time

import rp2
import uctypes
from machine import SPI, mem32

from sdcard import SDCard

# Add type hinting for rp2.pio functions if available, but don't require it for runtime.
try:
    import typing
    if typing.TYPE_CHECKING:
        from rp2 import (  # noqa: TC004
            gpio,
            in_,
            jmp,
            label,
            nop,
            pins,
            set,
            wait,
            wrap,
            wrap_target,
            x,
            x_dec,
        )
except ImportError:
    pass

SAMPLE_RATE = 48_000
SAMPLE_BITS = 16
CHANNELS = 1
SD_MOUNT_POINT = "/sd"
# The legacy SD driver defaults to 1.32 MHz after card initialization, which
# is too close to the 768 kbit/s raw PCM rate once filesystem overhead is
# included.  12 MHz leaves ample headroom on the board's short SPI traces.
SD_SPI_BAUDRATE = 12_000_000
I2S_CLOCK_SM = 8
I2S_CAPTURE_SM = 9
I2S_CLOCK_FREQ = 6_144_000      # 128 PIO cycles/frame -> 48 kHz FSYNC.
I2S_CAPTURE_FREQ = 24_576_000   # Enough cycles to service BCLK waits.
PIO2_BASE = 0x50400000
PIO_GPIOBASE = 0x168
PIO2_GPIOBASE = 16
PIO2_RXF1 = PIO2_BASE + 0x24

DMA_BASE = 0x50000000
DMA_CH_STRIDE = 0x40
DMA_READ_ADDR = 0x00
DMA_WRITE_ADDR = 0x04
DMA_TRANS_COUNT = 0x08
DMA_CTRL_TRIG = 0x0C
DMA_CHAN_ABORT = 0x464
DMA_CTRL_BUSY = 1 << 26
DMA_READ_ERROR = 1 << 30
DMA_WRITE_ERROR = 1 << 29
I2S_DMA_CHANNEL = 8
I2S_DMA_DREQ = 21  # DREQ_PIO2_RX1
I2S_DMA_SAMPLES = 16384         # 32 KiB, the largest RP2350 DMA ring.
I2S_DMA_BYTES = I2S_DMA_SAMPLES * 2
# Commit 4 KiB blocks during capture.  This reduces FAT/SD write overhead but
# leaves more than 250 ms of ring-buffer headroom for card busy periods.
I2S_WRITE_SAMPLES = 2048
# INTR reports the end of the digital speech stream.  Retain a short tail for
# the analog filter and ADC path so final consonants are not clipped.
POST_SPEECH_TAIL_MS = 50


def _dma_channel_base(channel: int) -> int:
    """Return the base address of an RP2350 DMA channel."""
    return DMA_BASE + channel * DMA_CH_STRIDE


def _ring_byte_offset(buffer_address: int) -> int:
    """Return the offset that aligns ``buffer_address`` to a DMA ring boundary.

    RP2350 DMA ring mode wraps an address's low bits; it does not wrap after a
    chosen byte count from the initial write address.  The backing allocation
    is therefore over-sized and this offset selects its aligned sub-window.
    """
    return (-buffer_address) & (I2S_DMA_BYTES - 1)


def _dma_ctrl() -> int:
    """Build the self-chained, PIO-paced 16-bit DMA control word."""
    value = 1  # EN
    value |= 1 << 1  # HIGH_PRIORITY
    value |= 1 << 2  # DATA_SIZE = 16-bit PCM samples
    value |= 1 << 6  # INCR_WRITE
    value |= 15 << 8  # RING_SIZE = 32 KiB (wrap low 15 address bits)
    value |= 1 << 12  # RING_SEL = write address
    value |= I2S_DMA_CHANNEL << 13  # CHAIN_TO = self
    value |= I2S_DMA_DREQ << 17
    value |= 1 << 23  # IRQ_QUIET
    return value


@rp2.asm_pio(sideset_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW])
def _i2s_clock() -> None:
    """Generate 3.072 MHz BCLK and 48 kHz I2S FSYNC on two side-set pins.

    FSYNC low denotes the left slot.  It changes only with a falling BCLK edge
    and remains stable for a full bit clock before the slot's MSB, as I2S
    requires.  Each left/right slot has 32 BCLK periods.
    """
    wrap_target()
    # Change FSYNC on BCLK's falling edge, one bit clock before each slot's
    # MSB.  Each FSYNC phase contains 32 BCLK cycles in 64 PIO cycles.
    set(x, 30).side(0)
    nop().side(1)
    label("left")
    nop().side(0)
    jmp(x_dec, "left").side(1)
    set(x, 30).side(2)
    nop().side(3)
    label("right")
    nop().side(2)
    jmp(x_dec, "right").side(3)
    wrap()


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT, autopush=True, push_thresh=16)
def _i2s_capture() -> None:
    """Push the upper 16 bits of every 32-bit left I2S slot to RX FIFO.

    The PCM1809 transmits MSB first.  SHIFT_LEFT places the first 16 received
    bits in the FIFO word's low half, allowing 16-bit DMA to write WAV-ready
    little-endian samples without Python-side bit shifting.  The remaining
    left-slot bits and all right-slot bits are skipped while waiting for the
    next FSYNC falling edge.
    """
    wrap_target()
    # asm_pio cannot resolve module globals inside a decorated program.  PIO2
    # GPIOBASE=16 maps operands 0..15 to physical GPIO32..47, so 5 is FSYNC
    # GPIO37 and 4 is BCLK GPIO36.
    wait(1, gpio, 5)
    wait(0, gpio, 5)
    wait(0, gpio, 4)
    wait(1, gpio, 4)
    wait(0, gpio, 4)
    # The first BCLK after FSYNC is the I2S one-bit delay.  Capture the next
    # 16 rising edges, which contain the high 16 bits of the left sample.
    set(x, 15)
    label("sample")
    wait(1, gpio, 4)
    in_(pins, 1)
    wait(0, gpio, 4)
    jmp(x_dec, "sample")
    wrap()


class ArchiveError(RuntimeError):
    """Raised when archive setup or recording cannot continue."""


def archive_group(group_id: str, rom, digitalker) -> None:
    """Archive every configured word in one ROM group.

    Each completed word is written as ``/sd/<output>/<index>_<word>.wav`` and
    announced on the REPL.  Existing files with the same names are replaced.

    Args:
        group_id (str): Metadata group identifier.
        rom: A RomEmulator instance.
        digitalker: A Digitalker instance.
    """
    groups = load_archive_groups()
    group = groups.get(group_id)
    if group is None:
        raise ArchiveError(f"unknown archive group: {group_id}")
    dictionary = load_word_dictionary(group["dictionary"])
    sources = group["sources"]
    if len(sources) not in (1, 2):
        raise ArchiveError("archive group requires a supported one- or two-file ROM")
    card = SDArchive()
    rom.load(*sources)
    recorder = I2SRecorder()
    output_dir = SD_MOUNT_POINT + "/" + group.get("output", group_id)
    try:
        os.mkdir(output_dir)
    except OSError:
        pass
    try:
        for index_text in sorted(dictionary, key=lambda value: int(value)):
            index = int(index_text)
            word = dictionary[index_text]
            path = output_dir + "/" + str(index) + "_" + sanitize_filename(word) + ".wav"
            writer = WavWriter(path)
            try:
                recorder.record_word(digitalker, index, writer)
                writer.close()
                print("saved " + word + " to " + path)
            except Exception:
                writer.discard()
                raise
    finally:
        recorder.close()
        card.close()


def load_archive_groups(config_path: str="archive_config.json") -> dict:
    """Load and validate archive group metadata.

    Args:
        config_path (str, optional): Archive configuration path. Defaults to
            ``archive_config.json``.

    Returns:
        dict: Archive group metadata keyed by group identifier.

    Raises:
        ArchiveError: If metadata is missing or malformed.
    """
    try:
        with open(config_path, "r") as dictionary_file:
            data = json.load(dictionary_file)
        groups = data["groups"]
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ArchiveError(f"cannot load archive metadata: {error}") from error
    if not isinstance(groups, dict):
        raise ArchiveError("groups must be a JSON object")
    return groups


def load_word_dictionary(path: str) -> dict:
    """Load an index-to-word archive dictionary.

    Args:
        path (str): JSON dictionary path.

    Returns:
        dict: Numeric string indexes mapped to word labels.

    Raises:
        ArchiveError: If the dictionary is missing or invalid.
    """
    try:
        with open(path, "r") as dictionary_file:
            words = json.load(dictionary_file)
    except (OSError, TypeError, ValueError) as error:
        raise ArchiveError(f"cannot load archive word dictionary: {error}") from error
    if not isinstance(words, dict):
        raise ArchiveError("archive word dictionary must be a JSON object")
    for index, word in words.items():
        if not index.isdigit() or not isinstance(word, str) or not word:
            raise ArchiveError(f"invalid archive dictionary entry: {index!r}")
    return words


def sanitize_filename(word: str) -> str:
    """Make a dictionary word safe for a flat SD-card filename.

    Args:
        word (str): The dictionary word label.

    Returns:
        str: A minimally sanitized filename component.
    """
    safe = word.replace("/", "_").replace("\\", "_").replace(":", "_")
    safe = safe.replace('"', "_").replace("*", "_").replace("?", "_")
    safe = safe.replace("<", "_").replace(">", "_").replace("|", "_")
    return safe.strip(" .") or "word"


def wav_header(sample_count: int) -> bytes:
    """Build a PCM RIFF/WAV header for the current sample count.

    Args:
        sample_count (int): Number of mono 16-bit samples.

    Returns:
        bytes: A 44-byte PCM WAV header.
    """
    data_size = sample_count * CHANNELS * (SAMPLE_BITS // 8)
    riff_size = 36 + data_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE", b"fmt ", 16, 1, CHANNELS,
        SAMPLE_RATE, SAMPLE_RATE * CHANNELS * SAMPLE_BITS // 8,
        CHANNELS * SAMPLE_BITS // 8, SAMPLE_BITS, b"data", data_size,
    )


class I2SRecorder:
    """Capture PCM1809 left-channel audio through PIO2 and DMA.

    The recorder owns PIO2 state machines 8 and 9 plus DMA channel 8.  It is
    not safe to use another feature on those hardware resources concurrently.
    """

    def __init__(self) -> None:
        """Configure the 48 kHz I2S clock source and 16-bit PCM DMA ring."""
        from board import BCLK, SDATA
        mem32[PIO2_BASE + PIO_GPIOBASE] = PIO2_GPIOBASE
        self.clock_sm = rp2.StateMachine(
            I2S_CLOCK_SM,
            _i2s_clock,
            freq=I2S_CLOCK_FREQ,
            sideset_base=BCLK,
        )
        self.capture_sm = rp2.StateMachine(
            I2S_CAPTURE_SM,
            _i2s_capture,
            freq=I2S_CAPTURE_FREQ,
            in_base=SDATA,
        )
        # DMA ring mode wraps the low 15 address bits at a natural 32 KiB
        # boundary, not relative to WRITE_ADDR.  An unaligned 32 KiB array
        # would eventually wrap into unrelated heap memory and corrupt it.
        self._raw_allocation = bytearray(I2S_DMA_BYTES * 2 - 1)
        raw_byte_offset = _ring_byte_offset(uctypes.addressof(self._raw_allocation))
        self.raw_buffer = memoryview(self._raw_allocation)[
            raw_byte_offset:raw_byte_offset + I2S_DMA_BYTES
        ]
        self.raw_buffer_address = uctypes.addressof(self.raw_buffer)
        if self.raw_buffer_address & (I2S_DMA_BYTES - 1):
            raise ArchiveError("unable to allocate an aligned I2S DMA ring")
        self.raw_read_index = 0
        self.clock_sm.active(1)
        # The PCM1809 leaves power-down once valid clocks are present.
        time.sleep_ms(10)

    def close(self) -> None:
        """Release the I2S peripheral."""
        self._stop_dma()
        self.capture_sm.active(0)
        self.clock_sm.active(0)

    def _stop_dma(self) -> None:
        """Abort and wait for the recorder's DMA channel only."""
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        mem32[dma + DMA_CTRL_TRIG] = (
            DMA_READ_ERROR | DMA_WRITE_ERROR | (I2S_DMA_CHANNEL << 13)
        )
        mem32[DMA_BASE + DMA_CHAN_ABORT] = 1 << I2S_DMA_CHANNEL
        for _ in range(100_000):
            if not (mem32[dma + DMA_CTRL_TRIG] & DMA_CTRL_BUSY):
                return
        raise ArchiveError("I2S DMA channel did not abort")

    def _start_dma(self) -> None:
        """Start endless, PIO-paced DMA from RX FIFO into the PCM ring."""
        self._stop_dma()
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        mem32[dma + DMA_READ_ADDR] = PIO2_RXF1
        mem32[dma + DMA_WRITE_ADDR] = self.raw_buffer_address
        # RP2350's all-ones count selects endless transfers; ring addressing
        # returns the write pointer to the aligned PCM window.
        mem32[dma + DMA_TRANS_COUNT] = 0xFFFFFFFF
        mem32[dma + DMA_CTRL_TRIG] = _dma_ctrl()
        self.raw_read_index = 0

    def _dma_write_index(self) -> int:
        """Return the sample slot DMA will write next in the PCM ring."""
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        offset = (mem32[dma + DMA_WRITE_ADDR] - self.raw_buffer_address)
        return (offset & (I2S_DMA_BYTES - 1)) >> 1

    def record_word(
        self,
        digitalker,
        index: int,
        writer: "WavWriter",
    ) -> None:
        """Capture one Digitalker word and its short analog output tail.

        Args:
            digitalker: A Digitalker object with nonblocking word controls.
            index (int): Digitalker word index.
            writer (WavWriter): Destination WAV writer.
        """
        try:
            self.record_active_speech(
                lambda: digitalker.start_word(index),
                digitalker.speech_finished,
                writer,
            )
        finally:
            digitalker.finish_speech()

    def record_active_speech(self, start_speech, speech_finished, writer: "WavWriter") -> None:
        """Capture a nonblocking speech sequence until it completes or times out.

        The caller must start speech without blocking and provide a completion
        predicate.  DMA runs continuously; this method periodically commits
        full PCM blocks and flushes the partial final block after capture stops.
        """
        error = None

        self.capture_sm.restart()
        self._start_dma()
        self.capture_sm.active(1)
        start_speech()
        deadline = time.ticks_add(time.ticks_ms(), 10_000)
        while not speech_finished():
            self._drain_capture(writer)
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                error = ArchiveError("I2S capture timed out")
                break
            time.sleep_ms(1)
        if error is None:
            # INTR marks digital speech completion, but the analog recording
            # path can still contain the final filtered syllable.
            tail_deadline = time.ticks_add(time.ticks_ms(), POST_SPEECH_TAIL_MS)
            while time.ticks_diff(tail_deadline, time.ticks_ms()) > 0:
                self._drain_capture(writer)
                time.sleep_ms(1)
        self.capture_sm.active(0)
        # Let the last FIFO word reach DMA, then freeze the write pointer before
        # copying the partial block.  Otherwise DMA could modify that block
        # while the SD driver is writing it.
        time.sleep_us(10)
        self._stop_dma()
        self._drain_capture(writer, flush=True)
        if error is not None:
            raise ArchiveError(f"I2S capture failed: {error}")

    def _drain_capture(self, writer: "WavWriter", flush: bool=False) -> None:
        """Copy completed DMA-ring samples to the WAV writer.

        Normal calls only write whole blocks to avoid slow small SD writes.
        ``flush=True`` is used after DMA stops to retain the final partial block.

        Args:
            writer (WavWriter): Destination WAV writer.

        """
        write_index = self._dma_write_index()
        available = (write_index - self.raw_read_index) & (I2S_DMA_SAMPLES - 1)
        if not flush:
            available -= available % I2S_WRITE_SAMPLES
        if not available:
            return

        first_count = min(available, I2S_DMA_SAMPLES - self.raw_read_index)
        self._write_capture_block(writer, self.raw_read_index, first_count)
        second_count = available - first_count
        if second_count:
            self._write_capture_block(writer, 0, second_count)
        self.raw_read_index = (self.raw_read_index + available) & (
            I2S_DMA_SAMPLES - 1
        )

    def _write_capture_block(
        self, writer: "WavWriter", start: int, sample_count: int
    ) -> None:
        """Copy and write a contiguous PCM ring region without conversion.

        The bytes copy is intentional: DMA continues filling the ring while an
        SD write is in progress, so passing a live memoryview could tear audio.
        """
        byte_start = start * 2
        block = bytes(
            self.raw_buffer[byte_start:byte_start + sample_count * 2]
        )
        writer.write(block)


class SDArchive:
    """Mount an inserted SD card on SPI1 for archive output."""

    def __init__(self) -> None:
        """Check card detect, initialize the card, and mount it at ``/sd``."""
        from board import SD_CS_N, SD_DET, SD_MISO, SD_MOSI, SD_SCK
        if not SD_DET.value():
            raise ArchiveError("an SD card must be inserted for archive mode")
        self.spi = SPI(
            1, baudrate=1_000_000,
            sck=SD_SCK, mosi=SD_MOSI, miso=SD_MISO,
        )
        # SDCard uses 100 kHz for initialization, then applies this rate.  Do
        # not omit ``baudrate`` here: its legacy default cannot sustain WAV I/O.
        self.card = SDCard(self.spi, SD_CS_N, baudrate=SD_SPI_BAUDRATE)
        os.mount(self.card, SD_MOUNT_POINT)
        self.mounted = True

    def close(self) -> None:
        """Unmount the SD card."""
        if getattr(self, "mounted", False):
            os.umount(SD_MOUNT_POINT)
            self.mounted = False


class WavWriter:
    """Stream little-endian signed 16-bit mono PCM into a RIFF/WAV file."""

    def __init__(self, path: str) -> None:
        """Create a WAV with a placeholder header that is fixed on close.

        Args:
            path (str): Output WAV path.
        """
        self.path = path
        self.sample_count = 0
        self.file = open(path, "wb+")  # noqa: SIM115
        self.file.write(wav_header(0))

    def close(self) -> None:
        """Rewrite the RIFF and data sizes, then close a completed WAV."""
        self.file.seek(0)
        self.file.write(wav_header(self.sample_count))
        self.file.close()

    def discard(self) -> None:
        """Close and remove a WAV whose capture failed before completion."""
        self.file.close()
        try:
            os.remove(self.path)
        except OSError:
            pass
        
    def write(self, samples: bytes) -> None:
        """Append packed signed 16-bit mono samples.

        Args:
            samples (bytes): Little-endian signed 16-bit PCM bytes.
        """
        if len(samples) % 2:
            raise ArchiveError("PCM sample data must contain whole 16-bit samples")
        self.file.write(samples)
        self.sample_count += len(samples) // 2
