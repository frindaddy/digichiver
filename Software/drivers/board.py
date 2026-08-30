from machine import PWM, Pin

### Digitalker ###
DIGITALKER_CLK_4MHZ = PWM(Pin(0, Pin.OUT), freq=4_000_000)
DIGITALKER_CS_N = Pin(1, Pin.OUT, pull=Pin.PULL_UP)
DIGITALKER_WR_N = Pin(2, Pin.OUT, pull=Pin.PULL_UP)
DIGITALKER_CMS = Pin(3, Pin.OUT)
SW = [Pin(i, Pin.OUT) for i in range(4, 12)]
INTR = Pin(35, Pin.IN)

### ROM Emulator ###
ROM_ADDR_BASE_PIN_NUMBER = 20
ROMEN_N_GPIO_NUMBER = 43
RDATA_BASE_PIN_NUMBER = 11

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
LED_ORANGE = Pin(46, Pin.OUT)
LED_GREEN = Pin(47, Pin.OUT)
BUTTON = Pin(39, Pin.IN)