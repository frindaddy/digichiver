"""Interactive Digitalker command entry point."""

from board import LED_GREEN, SPEAKER_DISABLE_N
from digitalker import Digitalker
from free_speak import SayError, free_speak, say_all
from rom_emulator import RomEmulator


def handle_command(command: str, rom: RomEmulator, digitalker: Digitalker, COMMANDS: list) -> bool:
    """Handle one command from the interactive command loop.
    Disables green LED during the command execution to indicate the system is busy.

    Args:
        command (str): A command such as ``/say hello`` or ``/say_all``.
        rom (RomEmulator): The ROM emulator used by the speech commands.
        digitalker (Digitalker): The Digitalker driver used by the speech commands.
        COMMANDS (list): A list of known commands for error reporting.

    Returns:
        bool: True when a known command was handled, otherwise False.

    Raises:
        SayError: If a speech command contains invalid or unknown words.
    """
    LED_GREEN.value(0)  # Turn off the green LED to indicate the system is busy
    
    command = command.strip()
    
    # Return False if command is not in command list
    if command not in COMMANDS and not any(command.startswith(cmd + " ") for cmd in COMMANDS):
        LED_GREEN.value(1)  # Turn on the green LED to indicate the system is ready
        return False        # Command was not handled
    
    if command == "/help":
        print("Available commands:")
        print("  /say <text>     - Speak the specified text using the Digitalker.")
        print("  /say_all        - Speak all words in the DVSS dictionary.")
        print("  /exit or /quit  - Exit the interactive command loop.")
    
    # Handle speech commands in a try-finally block to ensure the speaker is disabled 
    # and the LED is turned on if an error occurs
    try:
        SPEAKER_DISABLE_N.value(1)
        if command == "/say_all":
            say_all(rom, digitalker)
        if command == "/say" or command.startswith("/say "):
            free_speak(command[4:].strip(), rom, digitalker)
    finally:
        LED_GREEN.value(1)
        SPEAKER_DISABLE_N.value(0)
    
    SPEAKER_DISABLE_N.value(0)  # Disable the speaker after the command
    LED_GREEN.value(1)          # Turn on the green LED to indicate the system is ready
    return True                 # Command was handled

def print_banner():
    print("=====================================================")
    print(" DIGICHIVER - MM54104 Speech Processor & Archiver   ")
    print("=====================================================")

def main() -> None:
    """Run the interactive command loop."""
    print_banner()
    
    rom = RomEmulator()
    digitalker = Digitalker()
    COMMANDS = ["/help", "/say", "/say_all"]
    prompt = "digichiver> "

    # Turn on the green LED to indicate the system is ready
    LED_GREEN.value(1)

    # Run the REPL until /exit or /quit is entered
    while True:
        command = input(prompt)
        if command in ("/quit", "/exit"):
            LED_GREEN.value(0)
            return
        try:
            if not handle_command(command, rom, digitalker, COMMANDS):
                print(f"unknown command; available commands: {', '.join(COMMANDS)}")
        except SayError as error:
            print(error)
            SPEAKER_DISABLE_N.value(0)  # Disable speaker after an error
            LED_GREEN.value(1)          # Turn on the green LED to indicate the system is ready

if __name__ == "__main__":
    main()
