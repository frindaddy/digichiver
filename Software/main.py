import rp2
from machine import PWM, Pin

# add type hints for the rp2.PIO Instructions
try: 
    from typing_extensions import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False
if TYPE_CHECKING:
    from rp2.asm_pio import label, jmp, set, nop, wrap, wrap_target, pins, x, x_dec, y, y_dec

### PIN DEFINITIONS ###

# Digitalker
# Outputs
DIGITALKER_CLK_4MHZ = PWM(Pin(0, Pin.OUT), freq=4_000_000)
DIGITALKER_CS_N = Pin(1, Pin.OUT, pull=Pin.PULL_UP)
DIGITALKER_WR_N = Pin(2, Pin.OUT, pull=Pin.PULL_UP)
DIGITALKER_CMS = Pin(3, Pin.OUT)
SW = [Pin(i, Pin.OUT) for i in range(4, 12)]
# Inputs
RDATA = [Pin(i, Pin.OUT) for i in range(12, 20)]
ROM_ADDR = [Pin(i, Pin.IN) for i in range(20, 34)]
ROMEN_N = Pin(34, Pin.IN)
INTR = Pin(35, Pin.IN)

# I2S Bus
FSYNC = Pin(36, Pin.OUT)
BCLK = Pin(37, Pin.OUT)
SDATA = Pin(38, Pin.IN)

# microSD
SD_MISO = Pin(40, Pin.IN)
SD_CS_N = Pin(41, Pin.OUT)
SD_SCK = Pin(42, Pin.OUT)
SD_MOSI = Pin(43, Pin.OUT)
SD_DET = Pin(44, Pin.IN)

# GPIO
SPEAKER_DISABLE_N = Pin(45, Pin.OUT, pull=Pin.PULL_UP)
LED_RED = Pin(46, Pin.OUT)
LED_GR = Pin(47, Pin.OUT)
BUTTON = Pin(39, Pin.IN)
