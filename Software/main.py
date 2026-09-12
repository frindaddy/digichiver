"""Minimal interactive bring-up entry point for the SSR Digitalker ROM."""

from board import LED_GREEN, SPEAKER_DISABLE_N
from digitalker import Digitalker
from rom_emulator import RomEmulator

rom = RomEmulator()
digitalker = Digitalker()
LED_GREEN.value(1)

SPEAKER_DISABLE_N.value(1)
try:
    rom.load("DVSSROM1.bin")
    for i in range(144):
        digitalker.speak_word(i)
    rom.load("DVSSROM2.bin")
    for i in range(133):
        digitalker.speak_word(i)
    rom.load("DVSSROM3.bin")
    for i in range(129):
        digitalker.speak_word(i)
    rom.load("DVSSROM4.bin")
    for i in range(140):
        digitalker.speak_word(i)
    rom.load("DVSSROM5.bin")
    for i in range(108):
        digitalker.speak_word(i)
finally:
    SPEAKER_DISABLE_N.value(0)
