"""SD-card WAV archiving for Digitalker ROM word dictionaries."""

import _thread
from array import array
import json
import os
import struct
import time
import uctypes

from machine import Pin, SPI, mem32
import rp2

from sdcard import SDCard

SAMPLE_RATE = 48_000
SAMPLE_BITS = 16
CHANNELS = 1
SD_MOUNT_POINT = "/sd"
I2S_CLOCK_SM = 8
I2S_CAPTURE_SM = 9
I2S_CLOCK_FREQ = 6_144_000
I2S_CAPTURE_FREQ = 24_576_000
PIO2_BASE = 0x50400000
PIO_FDEBUG = 0x08
PIO_FLEVEL = 0x0C
PIO_GPIOBASE = 0x168
PIO2_GPIOBASE = 16
PIO2_BCLK = 20
PIO2_FSYNC = 21
PIO2_SDATA = 22
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
I2S_DMA_WORDS = 4096
I2S_DMA_BYTES = I2S_DMA_WORDS * 4


def _dma_channel_base(channel: int) -> int:
    """Return the base address of an RP2350 DMA channel."""
    return DMA_BASE + channel * DMA_CH_STRIDE


def _dma_ctrl() -> int:
    """Build the paced, ring-buffer DMA control word for I2S RX."""
    value = 1  # EN
    value |= 1 << 1  # HIGH_PRIORITY
    value |= 2 << 2  # DATA_SIZE = 32-bit PIO FIFO words
    value |= 1 << 6  # INCR_WRITE
    value |= 14 << 8  # RING_SIZE = 16 KiB
    value |= 1 << 12  # RING_SEL = write address
    value |= I2S_DMA_CHANNEL << 13  # CHAIN_TO = self
    value |= I2S_DMA_DREQ << 17
    value |= 1 << 23  # IRQ_QUIET
    return value


@rp2.asm_pio(sideset_init=[rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW])
def _i2s_clock() -> None:
    """Generate a 3.072 MHz BCLK and a 48 kHz I2S FSYNC."""
    wrap_target()
    # Each FSYNC phase contains 32 BCLK cycles in exactly 64 PIO cycles.
    set(x, 30).side(2)
    nop().side(1)
    label("left")
    nop().side(0)
    jmp(x_dec, "left").side(1)
    set(x, 30).side(0)
    nop().side(3)
    label("right")
    nop().side(2)
    jmp(x_dec, "right").side(3)
    wrap()


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT, autopush=True, push_thresh=32)
def _i2s_capture() -> None:
    """Capture the 32-bit left I2S slot from SDATA."""
    wrap_target()
    wait(1, gpio, 21)
    wait(0, gpio, 21)
    wait(0, gpio, 20)
    wait(1, gpio, 20)
    wait(0, gpio, 20)
    set(x, 31)
    label("sample")
    wait(1, gpio, 4)
    in_(pins, 1)
    wait(0, gpio, 4)
    jmp(x_dec, "sample")
    wrap()


class ArchiveError(RuntimeError):
    """Raised when archive setup or recording cannot continue."""


def archive_group(group_id: str, rom, digitalker) -> None:
    """Archive every indexed word in a configured ROM group.

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
                recorder.speak_to_file(digitalker, index, writer)
                writer.close()
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
    """Capture PCM1809 audio with PIO2 and write the left channel as mono."""

    def __init__(self) -> None:
        """Configure the 48 kHz, 32-bit PCM1809 receiver."""
        from board import BCLK, FSYNC, SDATA
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
        self.pcm_buffer = bytearray(2048)
        self.pcm_count = 0
        self.raw_buffer = array("I", [0] * I2S_DMA_WORDS)
        self.raw_buffer_address = uctypes.addressof(self.raw_buffer)
        self.raw_read_index = 0
        self.clock_sm.active(1)
        # The PCM1809 automatically wakes after audio clocks are present.
        time.sleep_ms(10)

    def close(self) -> None:
        """Release the I2S peripheral."""
        self._stop_dma()
        self.capture_sm.active(0)
        self.clock_sm.active(0)

    def _stop_dma(self) -> None:
        """Abort the recorder DMA channel, leaving other channels untouched."""
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
        """Start DMA from PIO2 RX1 into the raw circular sample buffer."""
        self._stop_dma()
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        mem32[dma + DMA_READ_ADDR] = PIO2_RXF1
        mem32[dma + DMA_WRITE_ADDR] = self.raw_buffer_address
        mem32[dma + DMA_TRANS_COUNT] = 0xFFFFFFFF
        mem32[dma + DMA_CTRL_TRIG] = _dma_ctrl()
        self.raw_read_index = 0

    def _dma_write_index(self) -> int:
        """Return the next circular-buffer slot DMA will write."""
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        offset = (mem32[dma + DMA_WRITE_ADDR] - self.raw_buffer_address)
        return (offset & (I2S_DMA_BYTES - 1)) >> 2

    def _dma_diagnostics(self) -> dict:
        """Return DMA and PIO state needed to diagnose capture throughput."""
        dma = _dma_channel_base(I2S_DMA_CHANNEL)
        return {
            "ctrl": mem32[dma + DMA_CTRL_TRIG] & 0xFFFFFFFF,
            "transfer_count": mem32[dma + DMA_TRANS_COUNT] & 0xFFFFFFFF,
            "write_index": self._dma_write_index(),
            "pio_flevel": mem32[PIO2_BASE + PIO_FLEVEL] & 0xFFFFFFFF,
            "pio_fdebug": mem32[PIO2_BASE + PIO_FDEBUG] & 0xFFFFFFFF,
        }

    def record_word(
        self,
        digitalker,
        index: int,
        writer: "WavWriter",
    ) -> None:
        """Capture samples while one Digitalker word is spoken.

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

    def record_speech(self, speech_action, writer: "WavWriter") -> None:
        """Capture audio while a speech action runs.

        Args:
            speech_action (callable): A blocking speech action.
            writer (WavWriter): Destination WAV writer.
        """
        speech_state = {"done": False, "error": None}

        def speak() -> None:
            """Speak the word while the main thread services I2S callbacks."""
            try:
                speech_action()
            except Exception as error:  # noqa: BLE001
                speech_state["error"] = error
            finally:
                speech_state["done"] = True

        self.record_active_speech(
            lambda: _thread.start_new_thread(speak, ()),
            lambda: speech_state["done"],
            writer,
        )
        if speech_state["error"] is not None:
            raise ArchiveError(f"I2S capture failed: {speech_state['error']}")

    def record_active_speech(self, start_speech, speech_finished, writer: "WavWriter") -> None:
        """Capture PCM while a nonblocking speech sequence remains active."""
        state = {
            "done": False,
            "error": None,
            "samples": 0,
            "nonzero_samples": 0,
            "peak": 0,
            "raw_or": 0,
            "raw_examples": [],
        }
        self._capture_state = state

        self.capture_sm.restart()
        self._start_dma()
        self.capture_sm.active(1)
        start_speech()
        deadline = time.ticks_add(time.ticks_ms(), 10_000)
        while not speech_finished():
            state["samples"] += self._drain_capture(writer)
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                state["error"] = ArchiveError("I2S capture timed out")
                break
            time.sleep_ms(1)
        state["samples"] += self._drain_capture(writer)
        self.capture_sm.active(0)
        state["dma"] = self._dma_diagnostics()
        self._stop_dma()
        self._flush_capture(writer)
        state["done"] = state["error"] is None
        self.last_capture_diagnostics = state
        if state["error"] is not None:
            raise ArchiveError(f"I2S capture failed: {state['error']}")

    def _drain_capture(self, writer: "WavWriter") -> int:
        """Drain captured left-channel words into the WAV writer.

        Args:
            writer (WavWriter): Destination WAV writer.

        Returns:
            int: Number of PCM samples drained.
        """
        write_index = self._dma_write_index()
        available = (write_index - self.raw_read_index) & (I2S_DMA_WORDS - 1)
        sample_count = 0
        for _ in range(available):
            raw = self.raw_buffer[self.raw_read_index]
            self.raw_read_index = (self.raw_read_index + 1) & (I2S_DMA_WORDS - 1)
            self._capture_state["raw_or"] |= raw
            if len(self._capture_state["raw_examples"]) < 8:
                self._capture_state["raw_examples"].append(raw)
            sample = (raw >> 16) & 0xFFFF
            signed_sample = sample if sample < 0x8000 else sample - 0x10000
            if signed_sample:
                self._capture_state["nonzero_samples"] += 1
            self._capture_state["peak"] = max(
                self._capture_state["peak"], abs(signed_sample)
            )
            self.pcm_buffer[self.pcm_count] = sample & 0xFF
            self.pcm_buffer[self.pcm_count + 1] = sample >> 8
            self.pcm_count += 2
            sample_count += 1
            if self.pcm_count == len(self.pcm_buffer):
                writer.write(bytes(self.pcm_buffer))
                self.pcm_count = 0
        return sample_count

    def _flush_capture(self, writer: "WavWriter") -> None:
        """Write a final partial PCM block after a recording ends."""
        if self.pcm_count:
            writer.write(bytes(self.pcm_buffer[:self.pcm_count]))
            self.pcm_count = 0

    def speak_to_file(self, digitalker, index: int, writer: "WavWriter") -> None:
        """Capture one indexed word into a WAV writer.

        Args:
            digitalker: A Digitalker object with ``speak_word`` available.
            index (int): Digitalker word index.
            writer (WavWriter): Destination WAV writer.
        """
        self.record_word(digitalker, index, writer)


class SDArchive:
    """Mount an inserted SPI1 SD card for archive output."""

    def __init__(self) -> None:
        """Check card detect, initialize SPI1, and mount the card."""
        from board import SD_CS_N, SD_DET, SD_MISO, SD_MOSI, SD_SCK
        if not SD_DET.value():
            raise ArchiveError("an SD card must be inserted for archive mode")
        self.spi = SPI(1, baudrate=1_000_000, sck=SD_SCK, mosi=SD_MOSI, miso=SD_MISO)
        self.card = SDCard(self.spi, SD_CS_N)
        os.mount(self.card, SD_MOUNT_POINT)
        self.mounted = True

    def close(self) -> None:
        """Unmount the SD card."""
        if getattr(self, "mounted", False):
            os.umount(SD_MOUNT_POINT)
            self.mounted = False


class WavWriter:
    """Stream signed 16-bit mono samples to a WAV file."""

    def __init__(self, path: str) -> None:
        """Create a WAV file with a placeholder header.

        Args:
            path (str): Output WAV path.
        """
        self.path = path
        self.sample_count = 0
        self.nonzero_bytes = 0
        self.file = open(path, "wb+")  # noqa: SIM115
        self.file.write(wav_header(0))

    def close(self) -> None:
        """Finalize the WAV sizes and close the file."""
        self.file.seek(0)
        self.file.write(wav_header(self.sample_count))
        self.file.close()

    def discard(self) -> None:
        """Close and remove an incomplete WAV file."""
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
        self.nonzero_bytes += sum(1 for value in samples if value)
