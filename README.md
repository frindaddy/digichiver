# Digichiver

Digichiver is an open hardware and software platform for operating, emulating,
and archiving the audio output of the National Semiconductor MM54104 Mozer
Digitalker speech synthesis system. The board can drive a physical MM54104,
serve historical speech ROM images through an RP2354B-based ROM emulator, and
record the resulting audio to a microSD card. Archived audio outputs are
available in the [Digitalker audio archive repository](https://github.com/frindaddy/digitalker-audio-archive).

## Repository Layout

The repository is organized by the part of the project it describes:

- `Hardware/` contains the KiCad schematics, PCB layout, custom footprints,
	fabrication outputs, and hardware design notes. Start with
	[`Hardware/readme.md`](Hardware/readme.md) for the circuit description.
- `Software/` contains the MicroPython firmware modules, ROM images, speech
	dictionaries, and archive configuration. Start with
	[`Software/readme.md`](Software/readme.md) for deployment and operation.
- `Simulation/` contains LTspice simulations for the analog speech filter.
- `DesignDocs/` contains project requirements and system architecture notes.
- `Datasheets/` contains component and reference documentation used by the
	design.
- `LICENSE` contains the project license.

## Using Digichiver

Digichiver requires the assembled board, an MM54104 Digitalker chip, and the
required ROM files for the speech vocabulary being used. The board is powered
and programmed over USB-C. Install the supplied
`Software/digichiver_firmware.uf2` firmware using the RP2354B USB bootloader,
then copy the required Python modules, ROM images, and JSON dictionaries from
`Software/` to the board's MicroPython filesystem.

After reset, connect to the board's MicroPython REPL. The software starts an
interactive `digichiver>` command loop for loading ROMs, speaking words,
checking word indexes, and archiving ROM groups to an inserted microSD card.
The complete command reference and file-deployment requirements are documented
in [`Software/readme.md`](Software/readme.md).

The hardware design can be opened with KiCad. The firmware itself targets
MicroPython on the RP2354B and uses the board-specific `machine` and `rp2`
interfaces, so the runtime modules are not intended to be launched as ordinary
desktop Python applications.
