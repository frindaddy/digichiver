"""Control the MM54104 Digitalker speech processor.

``start_word()`` starts a word without blocking so the archive recorder can
capture audio concurrently.  ``speak_word()`` is the blocking convenience
wrapper used by free-speech mode.
"""

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

CONTROL_SETTLE_US = 5
SPEECH_TIMEOUT_MS = 10_000


class Digitalker:
    """Drive the MM54104 control bus and monitor its active-low interrupt.

    A word command sets the eight-bit ``SW`` bus then pulses ``WR_N`` while
    the chip is selected.  The MM54104 holds ``INTR`` low during speech and
    releases it high when the current sequence completes.
    """

    def __init__(self) -> None:
        """Set safe inactive bus levels and start the required 4 MHz clock."""
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

        # The board configures the PWM frequency; 32768 is a 50% duty cycle.
        self.CLK.duty_u16(32768)

    def _write_sw_bus(self, data: int) -> None:
        """Present an unsigned 8-bit word address on the SW0-SW7 bus.

        Args:
            data (int): Word address, from 0 through 255.

        Raises:
            ValueError: If ``data`` is outside the 8-bit address range.
        """
        if not (0 <= data <= 0xFF):
            raise ValueError("data must be an 8-bit value (0-255)")

        for i in range(8):
            self.SW[i].value((data >> i) & 1)
    
    def _wait_for_interrupt(self, timeout_ms: int = SPEECH_TIMEOUT_MS) -> bool:
        """Wait for ``INTR`` to rise, returning ``False`` on timeout.

        This is intentionally a polling loop: callers that need to do work
        while speech runs use ``speech_finished()`` instead.  The blocking
        ``speak_word()`` wrapper returns after the timeout even if the chip
        did not complete, preserving the historical free-speech behavior.

        Args:
            timeout_ms (int, optional): Maximum wait time in milliseconds.

        Returns:
            bool: ``True`` when speech completes; ``False`` after timeout.
        """
        start_time = time.ticks_ms()
        while not self.speech_finished():
            if time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                return False
        return True

    def start_word(self, address: int) -> None:
        """Start a word without waiting for the completion interrupt.

        Callers must wait for ``speech_finished()`` before starting another
        word.  This method turns on the activity LED; call ``finish_speech()``
        after completion to turn it off.

        Args:
            address (int): Word address, from 0 through 255.

        Raises:
            ValueError: If ``address`` is outside the 8-bit address range.
        """
        if not (0 <= address <= 0xFF):
            raise ValueError("address must be an 8-bit value (0-255)")

        # Present the requested speech-ROM word address before strobing it.
        self._write_sw_bus(address)

        # CMS low clears INTR for a new sequence.  The 5 us delays exceed the
        # 350 ns CMS and 430 ns write-strobe timing requirements by margin.
        self.CMS.value(0)        # Select command mode and reset INTR.
        self.LED_ORANGE.value(1) # Indicate that speech is in progress.
        self.CS_N.value(0)       # Select the Digitalker for the write.
        time.sleep_us(CONTROL_SETTLE_US)

        # Pulse WR_N low-to-high to latch the SW bus word address.
        self.WR_N.value(0)       # Assert the active-low write strobe.
        time.sleep_us(CONTROL_SETTLE_US)
        self.WR_N.value(1)       # Latch the word and start speech.
        time.sleep_us(CONTROL_SETTLE_US)
        self.CS_N.value(1)       # Deselect; speech continues autonomously.

    def speech_finished(self) -> bool:
        """Return whether the active speech sequence has released ``INTR``."""
        return self.INTR.value() != 0

    def finish_speech(self) -> None:
        """Clear the activity indicator after completion or an aborted capture.

        This is board UI cleanup only; it does not send a command to the
        Digitalker or stop an active sequence.
        """
        self.LED_ORANGE.value(0)

    def speak_word(self, address: int) -> None:
        """Start one word and wait up to ten seconds for it to complete.

        This is the blocking API for interactive speech.  It always restores
        the activity LED, including if the completion interrupt times out.

        Args:
            address (int): Word address, from 0 through 255.
        """
        self.start_word(address)
        try:
            self._wait_for_interrupt()
        finally:
            self.finish_speech()
