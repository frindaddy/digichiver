# Digichiver Software

This folder houses the software used to run the Digichiver board.

## ROM images

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
