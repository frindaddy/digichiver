# Digichiver Software

This folder houses the software used to run the Digichiver board.

## ROM Images

Create one emulator and pass one or two ROM file paths to `load()`:

```python
rom = RomEmulator()
rom.load("DT1052.bin")
rom.load("SSR1.bin", "SSR2.bin")
```

`load()` automatically starts the emulator. Call it again to replace the
currently loaded ROM; the new files are validated before the active image is
stopped. A failed reload leaves the previous image running. If restarting the
new image fails, the new image is retained and the emulator remains stopped.

A single file may contain 1 to 16 KiB. It is loaded from address `0x0000`,
and any remaining space through `0x3fff` is filled with zeroes. Two-file ROMs
must contain exactly 8 KiB in each file; the files are loaded consecutively.
ROM files larger than 16 KiB are rejected.

Paths are resolved from the MicroPython working directory. Copy the selected
ROM files to the Pico and pass their filenames to `load()`.

## Free Speak

The Digichiver software is capable of free speech using the `/say` REPL command.

`free_speak.py` exposes `free_speak()` and uses the PDF-derived table in
`dvss_dictionary.json` to resolve
DVSS vocabulary entries to a ROM filename and Digitalker word index:

```python
from digitalker import Digitalker
from free_speak import free_speak
from rom_emulator import RomEmulator

rom = RomEmulator()
digitalker = Digitalker()
free_speak("emergency enable", rom, digitalker)
```

Input is case-insensitive and whitespace is collapsed. The complete input is
resolved before any speech starts, and unknown entries raise an error with
their position. Explicit aliases include `thank you` and `wake up`; DVSS
pronunciation variants such as `the.r` remain separate entries.

The suffixes in canonical entries are archive/audio labels, not automatic
grammar rules. Ending fragments such as `-ing.fs1` and `-ing.ms3` are distinct
recorded components, while labels such as `.r`, `.s`, `.m`, and `.p` have no
fully documented expansion. Aliases therefore explicitly map friendly input
to canonical dictionary entries in the JSON file. The runtime never strips suffixes or
chooses between pronunciation variants automatically.

The five `DVSSROM*.bin` files must be in the same flat MicroPython directory
as `free_speak.py`, `rom_emulator.py`, and `dvss_dictionary.json`.

Numbers in `free_speak()` are expanded into available DVSS words. Integer values are
spoken structurally through exactly one billion, which is pronounced as
`one thousand million` because the vocabulary has no `billion` entry. Larger
values are spoken digit by digit. Commas are accepted as separators, leading
zeroes are preserved digit by digit, signs use `minus` or `plus`, and decimal
fractions use `point` followed by individual digits.

Unknown words are also checked for literal DVSS affix composition. The selected
prefix/suffix mappings and number-word tables live in the `composition` and
`numbers` sections of `dvss_dictionary.json`. For example,
`degrees` is spoken as `degree` plus `-s.ms1`, and `reenter` is spoken as
`re-.spl` plus `enter`. Composition uses one selected prefix, one exact root,
and one selected suffix at most. It does not apply spelling transformations;
the exact dictionary entry or alias is always preferred.

The dictionary was transcribed from `ROMs/DVSS/DVSS_ROMS_INDEX.pdf`.
The five ROM files and `dvss_dictionary.json` must be deployed together with `free_speak.py`.

### REPL commands

`main.py` starts the command loop after creating the emulator and Digitalker.
Enter commands such as:

```text
/say hello this is my speech
```

Use `/exit` or `/quit` to leave the helper loop and return to the normal code.

### ROM Image Sources

ROM images from the Digitalker Digital Voice Selection Software (DVSS) are provided as a courtesy by [@MarkD833](https://github.com/MarkD833) thanks to his invaluable work archiving the DVSS outputs [(link to DVSS repo)](https://github.com/MarkD833/Digitalker-Digital-Voice-Selection-Software). The DVSS images have been converted from Intel HEX to binary files for compatability with the Digichiver hardware.

All other ROM images are sourced from the [Internet Archive](https://archive.org/details/digitalker).
