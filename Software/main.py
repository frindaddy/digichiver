"""Minimal interactive bring-up entry point for the SSR Digitalker ROM."""

from board import LED_GREEN, SPEAKER_DISABLE_N
from digitalker import Digitalker
from rom_emulator import RomEmulator

rom = RomEmulator()
digitalker = Digitalker()
LED_GREEN.value(1)

SPEAKER_DISABLE_N.value(1)
try:
    rom.load("DT1052.bin")
    for i in range(10):
        digitalker.speak_word(i)
    rom.load("SSR1.bin", "SSR2.bin")
    for i in range(144):
        digitalker.speak_word(i)
finally:
    SPEAKER_DISABLE_N.value(0)
