import time

from board import (
    DIGITALKER_CLK_4MHZ,
    DIGITALKER_CMS,
    DIGITALKER_CS_N,
    DIGITALKER_WR_N,
    INTR,
    LED_ORANGE,
    SW,
)


class Digitalker:
    """Driver for the MM54104 Digitalker IC"""

    def __init__(self) -> None:
        """Initialization"""
        
        self.CMS = DIGITALKER_CMS
        self.CLK = DIGITALKER_CLK_4MHZ
        self.CS_N = DIGITALKER_CS_N
        self.INTR = INTR
        self.LED_ORANGE = LED_ORANGE
        self.SW = SW
        self.WR_N = DIGITALKER_WR_N

        # Establish inactive control levels before applying the clock.  This
        # also protects against stale GPIO output latches after a soft reset.
        self.CS_N.value(1)
        self.WR_N.value(1)
        self.CMS.value(1)

        # Start the Digitalker clock at 4 MHz with a 50% duty cycle
        self.CLK.duty_u16(32768)

    def _write_sw_bus(self, data: int) -> None:
        """Write to the SW bus (SW0-SW7)

        Args:
            data (int): The 8-bit value to write to the SW bus.

        Raises:
            ValueError: If the data is not an 8-bit value (0-255).
        """
        if not (0 <= data <= 0xFF):
            raise ValueError("Data must be an 8-bit value (0-255).")

        for i in range(8):
            self.SW[i].value((data >> i) & 1)
    
    def _wait_for_interrupt(self, timeout_ms: int = 10000) -> bool:
        """Wait for the Digitalker chip to signal it is done speaking.

        INTR is reset low by a valid command and rises at the completion of
        the speech sequence (DT1050 datasheet, Functional Description).

        Args:
            timeout_ms (int, optional): The maximum time to wait for the interrupt in milliseconds. Defaults to 10000.

        Returns:
            bool: True if the interrupt was received before the timeout, False otherwise.
        """
        start_time = time.ticks_ms()
        while self.INTR.value() == 0:  # Wait for INTR to go high
            if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                return False  # Timeout occurred
        return True  # INTR went high, speech finished
    
    def speak_word(self, address: int) -> None:
        """Send a word address to the Digitalker to speak.

        Args:
            address (int): The 8-bit address of the word to be spoken (0-255).

        Raises:
            ValueError: If the address is not an 8-bit value (0-255).
        """
        if not (0 <= address <= 0xFF):
            raise ValueError("Address must be a 8-bit value (0-255).")

        # Set word address on the SW bus
        self._write_sw_bus(address)

        self.CMS.value(0)           # Set CMS pin low to reset interrupt and start speech sequence
        self.LED_ORANGE.value(1)    # Turn on the orange LED to indicate speech is in progress
        self.CS_N.value(0)          # Set CS_N low to select the Digitalker
        time.sleep_us(5)            # Short delay to ensure CMS is registered (min 350ns)

        # Assert write strobe to latch the address
        self.WR_N.value(0)          # Set WR_N low
        time.sleep_us(5)            # Short delay to ensure WR_N is registered (min 430ns)
        self.WR_N.value(1)          # Set WR_N high to latch the address
        
        # Release CS_N after the write operation
        time.sleep_us(5)            # Short delay to ensure WR_N is registered (min 430ns)
        self.CS_N.value(1)          # Set CS_N high to deselect the Digitalker
        self._wait_for_interrupt()  # Wait for the Digitalker to signal completion
        self.LED_ORANGE.value(0)    # Turn off the orange LED to indicate speech is complete
