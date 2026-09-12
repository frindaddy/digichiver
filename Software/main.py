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
    digitalker.speak_word(0x00)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x01)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x02)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x03)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x04)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x05)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x06)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x07)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x08)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x09)
    digitalker.wait_for_interrupt()
    digitalker.speak_word(0x0A)
    digitalker.wait_for_interrupt()
finally:
    SPEAKER_DISABLE_N.value(0)
