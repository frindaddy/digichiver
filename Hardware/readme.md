# Circuit Description

The doc describes the digichicver circuit schematic (and PCB layout, when needed).

## Block Diagram

This sheet show the block diagram for the Digichiver board. The sheet is broken into 4 sections, the USB-C power/data connector, the Control block, the Digitalker block, the Audio block, and the Power block.

The USB-C connector is setup for a USB 2.0 full-speed connection, as that is the max capability of the RP2354B. Two $5.1k\Omega$ resistors tie `CC1` and `CC2` to ground to specify that this board is a power sink, per the USB specification. This advertises that this board can consume a maximum of 2.5W (5V@500mA).

## Control

This sheet shows the RP2354B and microSD card, as well as their supporting circuitry and pinouts.

### RP2354B

The RP2354B is the MCU on the Digichiver board and is used to control the MM54104 Digitalker chip, emulate Digitalker ROM modules, and record the Digitalker output audio to the microSD card (plus other basic GPIO functions). It interfaces with the MM54104 Digitalker chip, microSD card, and the PCM1809 audio recorder. The RP2354B has 16MiB of internal flash in chip, so an external flash module is not required for operation.

#### RP2354B Power and Decoupling

The RP2354B nominally runs off a +3V3 supply, but requires a +1V1 rail for internal functions. Unlike its predecessor (the RP2340), the RP2354B ships with a built in switching regulator to generate this +1V1 rail in package, with the help of some supporting components. The design and layout of this power supply is strictly defined in [Hardware Design with the RP2350](https://pip-assets.raspberrypi.com/categories/1214-rp2350/documents/RP-008280-DS-1-hardware-design-with-rp2350.pdf), and the design recommendations were replicated here (part selection, connections, and layout).

Decoupling capacitors were placed based on the recommendations of [Hardware Design with the RP2350](https://pip-assets.raspberrypi.com/categories/1214-rp2350/documents/RP-008280-DS-1-hardware-design-with-rp2350.pdf); one for each power pin, and a special 4.7uF bulk cap for the +1V1 rail.

#### RP2354B USB Connection

The RP2354B is only capable of USB full speed (USB 2.0, 12Mbps, 48MHz clock). Though this is pretty slow speed, an attempt was made to keep the characteristic impedance of the USB traces close to the USB specification of $90\Omega$, differential. This board isn't being built with controlled impedances, so *rough* numbers are used for the calculation. To find the required trace width for a $90\Omega$ differential impedance, $Z_d$, we use the edge-coupled microstrip impedance equation.

$$Z_d \approx \frac{174}{\sqrt{\epsilon_r + 1.41}} \times \ln(\frac{5.98h}{0.8w + t}) \times [1-0.48^{-0.96\frac{s}{h}}]$$

where $Z_d$ is the differential impedance, $t$ is the trace thickness, $h$ is the height of the dielectric between the microstrip and ground plane, $s$ is the trace spacing, $\epsilon_r$ is the dielectric constant of the material, and $w$ is the trace width. The rough numbers are derived from the general JLCPCB 4 layer TG135 stackup and their manufacturing capabilities: $Z_d = 90\Omega$, $t = 1oz/ft^2$, $h = 8.283mil$, $s = 10mil$, and $\epsilon_r = 4.5$. Using these numbers, we calulate that the ideal trace width to achieve a $90\Omega$ differential impedance is `12.3645mil`.

$27\Omega$ series termination resistors are placed on the USB lines close to the RP2354B to meet the USB impedance specification.

#### RP2354B Clock

The RP2354B does not need an external clock to function (it ships with an internal oscillator), but a stable external frequency source greatly improves peripheral reliability and performance. As such, an external 12MHz crystal oscillator is used to clock the RP2354B. Part selection and circuit design are from the recommendations in [Hardware Design with the RP2350](https://pip-assets.raspberrypi.com/categories/1214-rp2350/documents/RP-008280-DS-1-hardware-design-with-rp2350.pdf).

#### Programming and Reset

Two pushbuttons, `SW1` and `SW2` are used to program and reset the RP2354B, respectively. When `SW1` is pressed on power up, the `QSPI_SS` line to the RP2354B is driven low, placing the device into programming mode. It will show up as a USB storage device, and a bootloader can be loaded into internal memory.

During operation, `SW2` can be pressed to reset the RP2354B by driving the `RUN` pin low.

#### Interfaces and GPIO

The MM54104 Digitalker control and ROM emulation busses take up most of the GPIO pins on the RP2354B. These signals are broken out as follows:

MM54104 Control Signals

| Signal | I/O | Pin Count |
| ------ | --- | --------- |
| SPC Word Selection Bus | O | 8 |
| SPC Chip Select | O | 1 |
| SPC Command Select | O | 1 |
| SPC Write Strobe | O | 1 |
| SPC Interrupt | I | 1 |

MM54104 ROM Emulation

| Signal | I/O | Pin Count |
| ------ | --- | --------- |
| ROM Address Bus | I | 14 |
| ROM Data Bus | O | 8 |
| ROMEN | I | 1 |

Because the MM54104 operates on +5V logic levels, these signals require level shifting. The level shifters are found on the Digitalker sheet.

An I2S interface connects the PCM1809 audio ADC to the RP2354B.

An SPI interface connects the RP2354B to the microSD card port.

One pushbutton, one green "Ready" LED, and one orange "Activity" LED are connected to the RP2354B as GPIO.

### microSD Card

The RP2354B has an SPI connection to the microSD card header. An SPI connection was selected over the typical SDIO connection for a few reasons: all microSD cards support SPI communication, the higher speeds of the SDIO interface are not required for this application, and the SPI interface requries 4 pins instead of 6. The SPI bus connects to the SPI1 peripheral on the RP2354B, per the [RP2354B datasheet](https://pip-assets.raspberrypi.com/categories/1214-rp2350/documents/RP-008373-DS-2-rp2350-datasheet.pdf). 10k pullup resistors are added on each SPI line to keep the bus in a known state on bootup.

The card detect line `SD_DET` is routed as a GPIO input to the RP2354B to check if a microSD card is actually inserted before writing to it. The physical mechanism in the microSD card slot is a mechanical switch that connects pin `9` to pin `10` when a card is inserted into the slot ([per DM3AT-SF-PEJM5 datasheet](https://www.hirose.com/product/document?clcode=CL0609-0033-6-00&productname=DM3AT-SF-https://www.hirose.com/product/document?clcode=CL0609-0033-6-00&productname=DM3AT-SF-PEJ2M5&series=DM3&documenttype=Catalog&lang=en&documentid=D49662_en)). When a card is not installed, the `SD_DET` line is pulled low by `R32`. When a microSD card is inserted into the slot, the `SD_DET` line is driven high to +3V3.

## Digitalker

This sheet shows the MM54104 Digitalker Speech Processing Chip IC socket (`XC1`), required level shifting, and speech output filtering.

### MM54104

The MM54104 is designed to be socketed on the board, rather than soldered directly. This helps protect the rare MM54104 from any soldering induced temperature stress, and keeps it easily replaceable in the case of failure due to age.

The MM54104 is powered by +9V, with a 100nF decoupling capacitor placed close to the power input pin.

The MM54104 requires an external 4MHz clock for operation. Rather than add additonal components to the BOM, the `OSC_IN` pin is connected to one of the RP2354B PWM output ports through a level shifter. The 4MHz clock is generated by the RP2354B PWM controller.

### Level Shifting

The MM54104 runs on a +7-11V power input, although uses +5V compatable TTL logic for its I/O connections. As such, level shifting is required between the +3V3 CMOS I/O from the RP2354B and the +5V TTL logic from the MM54104. This level shifting is accomplished using two different part numbers.

For the MM54104 → RP2354B connections, the SN74LVC245A is used. This level shifter operates on a single +3V3 rail, but has +5V tolerant inputs. This single supply architecture not only simplifies the power plane routing on the board, but also reduces the total input capacitance on the +5V rail[^1]. A total of two are required to shift the `ROM_ADDR[0..13]`, `ROMEN`, and `INTR` lines. The SN74LVC245As are configured as always enabled, A → B mode.

[^1]: The reduction of input capacitance is beneficial as the USB specification states that power sinking devices should have no more than 10uF of input capacitance on the +5V power rail to limit inrush current and prevent damaging the power sourcing device. With some quick napkin math, one can determine that this board nominally has 11.3uF of input capacitance on the +5V rail, plus whatever parasitic capacitance is added from the traces in the layout. Looking at the decoupling and bulk capacitors used on the +5V rail, the 10uF cap (`C31`) is $\pm$20%, and the 1uF cap (`C33`) and 100nF caps (`C5`, `C6`, `C7`) are $\pm$10%, therefore worst case input capacitance is `13.43uF`, plus whatever parasitic capacitance exists. For now, we pretend this is not a problem and will update after testing the board.  

For the RP2354B → MM54104 connections, the SN74LVCBT245 is used. This level shifter operates on split +3V3 and +5V rails. A total of three are required to shift the `DIGITALKER_CLK_4MHZ`, `DIGITALKER_CS`, `DIGITALKER_WR`, `DIGITALKER_CMS`, `SW[1..8]`, and `RDATA[0..7]` lines. The SN74LVCBT245s are configured as always enabled, A → B mode.

### Speech Output Filter

The speech output filter is designed to produce the maximum frequency response for the MM54104 speech output. It features a voltage rebiasing network to shift the output down to +3V3 tolerant levels, and a dual-stage Sallen-Key filter to match the filtering recommendations in the DT1050 datasheet.

First, a 1uF input capacitor is used to decouple the audio stream from the ~+4VDC "silence voltage" output by the MM54104. The audio stream is then rebiased to a +1V65 DC voltage offset through a pullup resistor (`R23`) to `V_BIAS`, which is generated with a 2:1 voltage divider. A 100nF decoupling capactior (`C42`) is used to keep `V_BIAS` clean from any switching noise that may exist on the +3V3 rail. The rebiased audio output then goes through the first Sallen-Key filter, which is a 7,234Hz low pass filter. The output of the low-pass filter goes into the next Sallen-Key filter, a 194Hz high-pass filter. Combined, the rebiasing and filtering produce the a similar frequency response to that recommended by the D1050 datasheet.

LTSpice simulations for this filtering circuit can be found in `Digichiver/Simulation`.

## Audio

This sheet contains the three audio output sources (audio ADC, 3.5mm jack, and onboard speaker) and their associated circuitry. All outputs are AC coupled to the filtered speech line through 1uF capacitors.

### Audio ADC

To record the audio stream to the microSD card, the RP2354B requires an external audio ADC connected via an I2S bus. The PCM1809 is used for this.

The PCM1809 has two stereo inputs, but the MM54104 produces only a single mono output. As such, only the positive input on channel 1 of the PCM1809 is connected, with the channel 1 negative input and both channel 2 inputs capacitively coupled to ground, per [the PCM1809 datasheet](https://www.ti.com/lit/ds/symlink/pcm1809.pdf?ts=1723810813788).

The PCM1809 is configured in I2S target mode, therefore the RP2354B controls the bus/chip. The RP2354B generates the `BCLK` and `FSYNC` signals, and the PCM1809 dynamically adjusts its sampling rate based on the `BCLK` to `FSYNC` ratio. The output data is sent on the `SDATA` line.

Decoupling capacitors are selected based on the typical application in [the PCM1809 datasheet](https://www.ti.com/lit/ds/symlink/pcm1809.pdf?ts=1723810813788).

### 3.5mm Jack

The 3.5mm jack provides an output source to external speaker amplifiers, if desired. To make the mono audio signal compatable with a stereo TRS jack, the audio is split to the tip (`T`) and ring (`R`) pins of the jack through $100\Omega$ resistors. The resistors prevent dead shorts between the T and R pins if a non TRS cable is inserted into the jack. A $100k\Omega$ resistor weakly pulls the line to ground to help prevent popping on cable connection/disconnection.

### Onboard Speaker

The onboard speaker `LS1` is driven using a stereo class-D amplifier IC, the PAM8302A. This amplifier is capable of driving an $8\Omega$ speaker at just under 800mW when powered by a +3V3 rail. As such, the $8\Omega$ 780mW CMS-2821-078T onboard speaker is a solid choice due to its matching specifications and reasonbly even frequency response.

Because the PAM8302A expects a stereo input, the mono MM54014 output is fed into the positive input channel and the negative input channel is capacitively coupled to ground.

`RV1` is a $10k\Omega$ logarithmic potentiometer used to control the ultimate volume of the onboard speaker.

A GPIO line `SPEAKER_MUTE` is routed to the RP2354B so the speaker can be disabled by software, when required.

## Power

This sheet shows the two switching power supplies responsible for deriving the +3V3 and +9V power rails from the +5V input rail. Both designs are based on a combination of the typical application diagrams in their respective datasheets and designs generated using the Texas Instruments [WEBENCH® Power Designer](https://webench.ti.com/power-designer/) tool.
