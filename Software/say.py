"""Resolve DVSS vocabulary text and speak it through the Digitalker."""

import json

try:
    import typing
    if typing.TYPE_CHECKING:
        from digitalker import Digitalker
        from rom_emulator import RomEmulator
except ImportError:
    pass

with open("dvss_dictionary.json", "r") as _dictionary_file:
    _dictionary_data = json.load(_dictionary_file)

class SayError(ValueError):
    """Base exception for invalid speech input."""


class UnknownWordError(SayError):
    """Raised when an input token is not in the DVSS vocabulary."""

    def __init__(self, word: str, position: int) -> None:
        """Initialize an error for an unknown input token.

        Args:
            word (str): The original unknown token.
            position (int): The zero-based token position.
        """
        self.word = word
        self.position = position
        super().__init__(f"unknown DVSS word {word!r} at position {position}")


def _build_index() -> dict:
    """Build the lookup index from the human-readable JSON dictionary.

    Returns:
        dict: A lowercase word-to-ROM-and-address mapping.
    """
    index = {}
    for rom_name, words in _dictionary_data["roms"].items():
        for address, word in enumerate(words, 1):
            key = word.lower()
            if key in index:
                raise ValueError(f"duplicate DVSS vocabulary key: {word}")
            index[key] = (rom_name, address)
    for alias, canonical in _dictionary_data.get("aliases", {}).items():
        if not isinstance(canonical, str):
            raise TypeError(f"alias target must be a string: {alias}")
        target = index.get(canonical.lower())
        if target is None:
            raise ValueError(f"alias target is not in DVSS vocabulary: {canonical}")
        alias_key = alias.lower()
        if alias_key in index:
            raise ValueError(f"alias shadows canonical vocabulary: {alias}")
        index[alias_key] = target
    return index

SAY_INDEX = _build_index()

def _normalize_text(text: str) -> str:
    """Normalize case and whitespace without changing DVSS punctuation.

    Args:
        text (str): The input text.

    Returns:
        str: Lowercase text with runs of whitespace collapsed.

    Raises:
        SayError: If the input is empty or contains no words.
    """
    normalized = " ".join(text.lower().split())
    if not normalized:
        raise SayError("speech text must contain at least one word")
    return normalized

def _resolve(text: str) -> list:
    """Resolve all input words before any speech begins.

    Args:
        text (str): The normalized input text.

    Returns:
        list: Tuples containing the ROM filename, address, and original word.

    Raises:
        UnknownWordError: If a word is absent from the DVSS dictionary.
    """
    whole_entry = SAY_INDEX.get(text)
    if whole_entry is not None:
        return [(whole_entry[0], whole_entry[1], text)]

    resolved = []
    for position, word in enumerate(text.split(" ")):
        entry = SAY_INDEX.get(word)
        if entry is None:
            raise UnknownWordError(word, position)
        resolved.append((entry[0], entry[1], word))
    return resolved

def _speak_resolved(resolved: list, rom: "RomEmulator", digitalker: "Digitalker") -> None:
    """Speak resolved entries while loading each ROM only when it changes.

    Args:
        resolved (list): ROM, address, and word tuples in speech order.
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.
    """
    active_rom = None

    for rom_name, address, _word in resolved:
        if rom_name != active_rom:
            rom.load(rom_name)
            active_rom = rom_name
        digitalker.speak_word(address)

def say(text: str, rom: "RomEmulator", digitalker: "Digitalker") -> None:
    """Speak DVSS words from a string, switching ROMs as required.

    Args:
        text (str): Case-insensitive, whitespace-separated DVSS words.
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.

    Raises:
        SayError: If the text is empty.
        UnknownWordError: If any word is not in the DVSS dictionary.
    """
    normalized = _normalize_text(text)
    resolved = _resolve(normalized)
    _speak_resolved(resolved, rom, digitalker)

def say_all(rom: "RomEmulator", digitalker: "Digitalker") -> None:
    """Speak every canonical DVSS dictionary entry in ROM order.

    Args:
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.
    """
    resolved = [
        (rom_name, address, word)
        for rom_name, words in _dictionary_data["roms"].items()
        for address, word in enumerate(words, 1)
    ]
    _speak_resolved(resolved, rom, digitalker)
