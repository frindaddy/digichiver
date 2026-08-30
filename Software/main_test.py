from machine import Pin, PWM
from rom_emulator import ROMEmulator

# 1. Initialize Peripheral Clocks
DIGITALKER_CLK_4MHZ = PWM(Pin(0, Pin.OUT), freq=4_000_000)
DIGITALKER_CS_N     = Pin(1, Pin.OUT, value=1)
DIGITALKER_WR_N     = Pin(2, Pin.OUT, value=1)

# 2. Instantiate and Start PIO Hardware Emulator
emulator = ROMEmulator()

if emulator.load_rom("SSR1.bin"):
    emulator.setup_dma(dma_chan=0)
    emulator.start()