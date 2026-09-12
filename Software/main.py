"""Minimal interactive bring-up entry point for the SSR Digitalker ROM."""

from board import LED_GREEN, SPEAKER_DISABLE_N
from digitalker import Digitalker
from rom_emulator import RomEmulator

rom = RomEmulator()
rom.load()
rom.start()
digitalker = Digitalker()
LED_GREEN.value(1)

SPEAKER_DISABLE_N.value(1)
try:
    for i in range(144):
        digitalker.speak_word(i)
finally:
    SPEAKER_DISABLE_N.value(0)
