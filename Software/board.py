from machine import PWM, Pin

### Digitalker ###
# Explicit output values are required here: a pull-up does not define the
# output latch while the pin is in output mode.  Keep the Digitalker deselected
# and its write strobe inactive before its clock is enabled.
DIGITALKER_CS_N = Pin(1, Pin.OUT, value=1)
DIGITALKER_WR_N = Pin(2, Pin.OUT, value=1)
DIGITALKER_CMS = Pin(3, Pin.OUT, value=1)
SW = [Pin(i, Pin.OUT, value=0) for i in range(4, 12)]
DIGITALKER_CLK_4MHZ = PWM(Pin(0, Pin.OUT), freq=4_000_000)
DIGITALKER_CLK_4MHZ.duty_u16(0)
INTR = Pin(35, Pin.IN)

### ROM Emulator ###
ROM_ADDR = [Pin(i, Pin.IN) for i in range(20, 34)]
ROMEN_N = Pin(34, Pin.IN)
RDATA = [Pin(i, Pin.OUT) for i in range(12, 20)]

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
SPEAKER_DISABLE_N = Pin(45, Pin.OUT, value=0)
LED_ORANGE = Pin(46, Pin.OUT)
LED_GREEN = Pin(47, Pin.OUT)
BUTTON = Pin(39, Pin.IN)
