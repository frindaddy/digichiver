# Digichiver Software

The software in this directory runs the Digichiver board on MicroPython for
the RP2354B. It drives the MM54104 control bus, emulates its parallel ROM
interface, provides dictionary-based speech, and records speech through the
PCM1809 audio ADC to a microSD card.

## Software Layout

- `main.py` starts the interactive `digichiver>` command loop.
- `board.py` assigns the RP2354B GPIO, PWM, SPI, and I2S interfaces used by the
  board.
- `digitalker.py` drives the MM54104 word-selection bus and control signals.
- `rom_emulator.py` serves a selected ROM image using PIO and DMA without
  requiring Python to handle each ROM access.
- `free_speak.py` resolves text, aliases, numbers, and literal vocabulary
  fragments into Digitalker words.
- `archive.py` captures 48 kHz, 16-bit, mono PCM and writes WAV files to `/sd`.
- `sdcard.py` provides the SPI microSD-card driver.
- `Dictionaries/` contains the free-speak vocabulary, archive metadata, and
  index-to-word dictionaries.
- `ROMs/` contains the supplied ROM image collections and source indexes.
- `digichiver_firmware.uf2` is the firmware image for the RP2354B.

## Deployment

Install `digichiver_firmware.uf2` with the RP2354B USB bootloader. After the
board resets, copy the runtime files to the MicroPython filesystem. The
working directory matters because the software opens ROMs and JSON files by
filename, so the following files must be in one flat directory on the board:

```text
archive.py
archive_config.json
board.py
digitalker.py
free_speak.py
free_speak_dictionary.json
main.py
rom_emulator.py
sdcard.py
```

Copy the ROM files required by the selected operation into that same
directory. For `/say` and `/say_all`, also copy `DVSSROM1.bin` through
`DVSSROM5.bin`. For `/archive`, copy the source ROMs and dictionary files
named by `Dictionaries/archive_config.json`. Reset the board and connect to its
MicroPython REPL; `main.py` starts the command loop.

## ROM Emulator

`RomEmulator` presents a selected binary image as the MM54104's 16 KiB
parallel ROM. A single image may contain from 1 to 16 KiB. It is loaded at
address `0x0000` and zero-filled through `0x3fff`. Two-file images must contain
exactly 8 KiB per file and are concatenated in argument order.

```python
from rom_emulator import RomEmulator

rom = RomEmulator()
rom.load("DT1052.bin")
rom.load("SSR1.bin", "SSR2.bin")
```

`load()` validates the new files before stopping a currently running image.
An invalid reload leaves the previous image running. If the new image cannot
start, it remains selected but stopped. File paths are resolved from the
MicroPython working directory.

## Free Speak

`free_speak.py` maps text to the five DVSS ROMs and their word indexes. Input
is case-insensitive and runs of whitespace are collapsed. The complete input
is resolved before any ROM is loaded or word is spoken, so an unknown word
does not produce partial speech.

```python
from digitalker import Digitalker
from free_speak import free_speak
from rom_emulator import RomEmulator

rom = RomEmulator()
digitalker = Digitalker()
free_speak("emergency enable", rom, digitalker)
```

The dictionary supports canonical entries and explicit aliases such as
`thank you` and `wake up`. Numeric input accepts signs, comma-separated
integers, leading zeroes, and decimal fractions. Values are converted to
available vocabulary words; values above one billion are spoken digit by
digit. Unknown words may also resolve through one literal prefix, exact root,
and suffix composition. The `composition` and `numbers` sections of
`Dictionaries/free_speak_dictionary.json` define these mappings.

The dictionary was generated from `ROMs/DVSS/DVSS_ROMS_INDEX.pdf`. Its
pronunciation suffixes are recorded vocabulary labels, not automatic grammar
rules: the runtime does not strip suffixes or select variants by itself.

## REPL Commands

`main.py` creates the ROM emulator and Digitalker driver, then accepts commands
at the `digichiver>` prompt:

```text
/load_rom SSR1.bin SSR2.bin
/say hello this is my speech
/say_index 42
/say_index 0 50
/say_all
/archive ssr1/ssr2
```

- `/load_rom <file1> [file2]` loads one ROM image or two 8 KiB banks.
- `/say <text>` speaks text through the DVSS free-speak dictionary.
- `/say_index <start> [end]` speaks one index or an inclusive range from 0
  through 255. Decimal and `0x` hexadecimal indexes are accepted.
- `/say_all` speaks every word in the free-speak vocabulary.
- `/archive <group>` records a configured ROM group to the microSD card.
- `/help` prints the command list.
- `/exit` and `/quit` leave the command loop.

## ROM Archiving

Archiving requires an inserted microSD card. The archive groups and their ROM
sources are defined in `Dictionaries/archive_config.json`:

```text
/archive ssr1/ssr2
```

Groups with an index-to-word dictionary produce `/sd/<group>/<index>_<word>.wav`.
DVSS groups set `include_index` to false and write word-named files. Groups
without a known dictionary use `/sd/<group>/<index>.wav`. Files are 48 kHz,
16-bit, mono PCM recorded from the PCM1809 I2S input around each Digitalker
word. Genesis and Jameco JE-520 images are represented as separate bank
passes, such as `genesis-1`, `genesis-2`, `je520-1`, and `je520-2`.

## ROM Image Sources

The DVSS ROM images were converted from Intel HEX files and are provided as a
contribution from [@MarkD833](https://github.com/MarkD833), whose source
archive is the [Digitalker Digital Voice Selection Software repository](https://github.com/MarkD833/Digitalker-Digital-Voice-Selection-Software).
Other ROM images are sourced from the [Internet Archive](https://archive.org/details/digitalker).
