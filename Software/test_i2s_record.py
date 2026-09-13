"""Temporary one-word PCM1809 I2S-to-WAV hardware smoke test."""

import time

from archive import I2SRecorder, SDArchive, WavWriter
from board import LED_GREEN, SPEAKER_DISABLE_N
from digitalker import Digitalker
from rom_emulator import RomEmulator


ROM_SOURCES = ("SSR1.bin", "SSR2.bin")
OUTPUT_PATH = "/sd/i2s_test_sequence.wav"
TEST_SECONDS = 5


def main() -> None:
    """Record repeated SSR words to a WAV file for I2S diagnosis."""
    rom = RomEmulator()
    digitalker = Digitalker()
    card = None
    recorder = None
    writer = None
    completed = False

    LED_GREEN.value(0)
    try:
        card = SDArchive()
        writer = WavWriter(OUTPUT_PATH)
        rom.load(*ROM_SOURCES)
        recorder = I2SRecorder()
        SPEAKER_DISABLE_N.value(1)
        start_time = time.ticks_ms()

        sequence = {"word_index": 1}

        def start_sequence() -> None:
            """Start the first word of the nonblocking test sequence."""
            digitalker.start_word(sequence["word_index"])

        def sequence_finished() -> bool:
            """Start the next word until the test duration expires."""
            if not digitalker.speech_finished():
                return False
            if time.ticks_diff(time.ticks_ms(), start_time) >= TEST_SECONDS * 1000:
                digitalker.finish_speech()
                return True
            sequence["word_index"] = (
                sequence["word_index"] + 1 if sequence["word_index"] < 143 else 1
            )
            digitalker.start_word(sequence["word_index"])
            return False

        recorder.record_active_speech(start_sequence, sequence_finished, writer)
        print(
            "captured samples:", writer.sample_count,
            "nonzero bytes:", writer.nonzero_bytes,
            "I2S diagnostics:", recorder.last_capture_diagnostics,
        )
        writer.close()
        writer = None
        completed = True
        print("saved " + OUTPUT_PATH)
    finally:
        SPEAKER_DISABLE_N.value(0)
        LED_GREEN.value(1)
        if writer is not None:
            writer.discard()
        if recorder is not None:
            recorder.close()
        if card is not None:
            card.close()
        rom.stop()
        if not completed:
            print("I2S recording failed")


main()
