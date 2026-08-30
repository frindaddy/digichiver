import rp2
from board import RDATA_BASE_PIN_NUMBER, ROM_ADDR_BASE_PIN_NUMBER
from machine import Pin, mem32

import linting

if linting.TYPE_CHECKING:
    from rp2.asm_pio import (  # noqa: TC004
        gpio,
        in_,
        out,
        pindirs,
        pins,
        set,
        wait,
        wrap,
        wrap_target,
    )


@rp2.asm_pio(
    in_shiftdir=rp2.PIO.SHIFT_RIGHT,
    autopush=True,
    push_thresh=14
)
def pio_address_sampler():
    wrap_target()
    wait(0, gpio, 34)   # Wait for active-LOW ROMEN_N (GPIO 34)
    in_(pins, 14)       # Sample 14 address bits starting at GPIO 20
    wait(1, gpio, 34)   # Hold until bus cycle completes
    wrap()


@rp2.asm_pio(
    out_shiftdir=rp2.PIO.SHIFT_RIGHT,
    autopull=True,
    pull_thresh=8,
    out_init=[rp2.PIO.OUT_LOW,] * 8,
    set_init=[rp2.PIO.OUT_LOW,] * 8
)
def pio_data_driver():
    wrap_target()
    out(pins, 8)        # Write 8-bit byte to RDATA pins (GPIO 12..19)
    set(pindirs, 31)    # Set pins to OUTPUT mode
    wait(1, gpio, 34)   # Maintain drive until ROMEN_N goes HIGH
    set(pindirs, 0)     # Release bus to High-Z (INPUT mode)
    wrap()


class ROMEmulator:
    """Emulates a Digitalker ROM using the RP2350's PIO and DMA capabilities."""
    
    def __init__(self) -> None:
        """Initialization of ROMEmulator class."""
        self.rom_buffer = None
        
        # Base addresses for RP2350 Registers
        PIO0_BASE = 0x40028000
        PIO1_BASE = 0x40030000
        self.DMA_BASE = 0x40000000

        # Set PIO0 gpio_base to 16 -> Covers GPIO 16 to 47 (ROM_ADDR & ROMEN_N)
        mem32[PIO0_BASE + 0x00] = (mem32[PIO0_BASE + 0x00] & ~(0x1F << 16)) | (16 << 16)
        
        # Set PIO1 gpio_base to 0 -> Covers GPIO 0 to 31 (RDATA)
        mem32[PIO1_BASE + 0x00] = (mem32[PIO1_BASE + 0x00] & ~(0x1F << 16)) | (0 << 16)

        # State Machine 0 on PIO 0 (Window 16..47)
        self.sm_addr = rp2.StateMachine(
            0,                     # State Machine 0 on PIO 0
            pio_address_sampler,
            freq=150_000_000,
            in_base=Pin(ROM_ADDR_BASE_PIN_NUMBER),
        )
        
        # State Machine 4 on PIO 1 (Window 0..31)
        # Note: SM ID 4 refers to State Machine 0 on PIO1
        self.sm_data = rp2.StateMachine(
            4,                     # State Machine 0 on PIO 1
            pio_data_driver,
            freq=150_000_000,
            out_base=Pin(RDATA_BASE_PIN_NUMBER),
            set_base=Pin(RDATA_BASE_PIN_NUMBER)
        )

        # Hardware FIFO addresses
        self.SM_ADDR_RXFIFO = PIO0_BASE + 0x20  # PIO0 SM0 RX FIFO
        self.SM_DATA_TXFIFO = PIO1_BASE + 0x10  # PIO1 SM0 TX FIFO
        
        # Start PIO state machines
        self._start()

    def _setup_dma(self, dma_chan: int = 0) -> None:
            """Registers the DMA channel to transfer data from the ROM buffer to the PIO1 TX FIFO.
    
            Args:
                dma_chan (int, optional): The DMA channel to use. Defaults to 0.
    
            Raises:
                RuntimeError: If the ROM buffer is not loaded before setting up DMA.
            """
            if not self.rom_buffer:
                raise RuntimeError("Load ROM into RAM before configuring DMA.")
    
            chan_base = self.DMA_BASE + (dma_chan * 0x40)
    
            # DREQ Signal for PIO0 RX FIFO 0 is 4
            DREQ_PIO0_RX0 = 4
    
            # Calculate bitmask for 8-bit transfer triggered by PIO0 RX
            ctrl_val = (
                (1 << 0)  |             # ENABLE
                (0 << 2)  |             # SIZE = 8-bit
                (1 << 4)  |             # INCR_READ = Yes
                (0 << 5)  |             # INCR_WRITE = No
                (DREQ_PIO0_RX0 << 15) | # TREQ_SEL = PIO0 RX0
                (dma_chan << 11)        # CHAIN_TO = Self
            )
    
            # Write DMA Hardware Control Registers
            mem32[chan_base + 0x00] = self.SM_ADDR_RXFIFO  # READ_ADDR
            mem32[chan_base + 0x04] = self.SM_DATA_TXFIFO  # WRITE_ADDR
            mem32[chan_base + 0x08] = 1                    # TRANS_COUNT (1 byte)
            mem32[chan_base + 0x0C] = ctrl_val             # CTRL_TRIG
    
            print(f"DMA Channel {dma_chan} hardware pipeline established.")

    def _start(self) -> None:
        """Enable PIO state machines and start the ROM emulator."""
        self.sm_data.active(1)
        self.sm_addr.active(1)
        print("Hardware PIO0 + PIO1 Active.")
    
    def _stop(self) -> None:
        """Disable PIO state machines and stop the ROM emulator."""
        self.sm_addr.active(0)
        self.sm_data.active(0)
        print("Hardware PIO0 + PIO1 state machines stopped.")

    def load_rom(self, rom_path: str, dma_chan: int = 0) -> bool:
        """Loads binary speech ROM into RAM buffer.

        Args:
            rom_path (str): Path to the ROM file.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with open(rom_path, "rb") as f:
                self.rom_buffer = bytearray(f.read())
            print(f"Loaded {len(self.rom_buffer)} bytes into RAM buffer.")
            
            # setup DMA channel after loading ROM
            self._setup_dma(dma_chan)
            return True
        except OSError:
            print(f"Error: ROM file '{rom_path}' not found.")
            return False