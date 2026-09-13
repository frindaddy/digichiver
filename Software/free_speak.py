"""Resolve DVSS vocabulary text and speak it through the Digitalker."""

import json
import re

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

_SMALL_NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS_NUMBER_WORDS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)
_DIGIT_WORDS = _SMALL_NUMBER_WORDS[:10]
_NUMERIC_TOKEN = re.compile(r"^[+-]?[0-9][0-9,]*(?:\.[0-9]+)?$")
_COMMA_FORMAT = re.compile(r"^[0-9]{1,3}(?:,[0-9]{3})+$")

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

def _small_number_words(value: int) -> list:
    """Convert a number from 0 through 999 into vocabulary words.

    Args:
        value (int): The non-negative number to convert.

    Returns:
        list: Spoken number words without a conjunction such as ``and``.
    """
    if value < 20:
        return [_SMALL_NUMBER_WORDS[value]]
    if value < 100:
        words = [_TENS_NUMBER_WORDS[value // 10]]
        if value % 10:
            words.append(_SMALL_NUMBER_WORDS[value % 10])
        return words

    words = [_SMALL_NUMBER_WORDS[value // 100], "hundred"]
    remainder = value % 100
    if remainder:
        words.extend(_small_number_words(remainder))
    return words

def _integer_number_words(value: int) -> list:
    """Convert an integer through one billion into vocabulary words.

    Args:
        value (int): The non-negative integer to convert.

    Returns:
        list: Spoken number words, using ``thousand`` and ``million`` groups.
    """
    if value == 0:
        return ["zero"]
    if value > 1_000_000_000:
        return [_DIGIT_WORDS[int(digit)] for digit in str(value)]

    words = []
    millions, value = divmod(value, 1_000_000)
    thousands, remainder = divmod(value, 1_000)
    if millions:
        words.extend(_integer_number_words(millions))
        words.append("million")
    if thousands:
        words.extend(_small_number_words(thousands))
        words.append("thousand")
    if remainder:
        words.extend(_small_number_words(remainder))
    return words

def _numeric_words(token: str) -> list:
    """Convert a validated numeric token into vocabulary words.

    Args:
        token (str): A signed decimal token with optional commas.

    Returns:
        list: Spoken vocabulary words for the numeric token.

    Raises:
        SayError: If the token uses invalid comma placement or syntax.
    """
    numeric_match = _NUMERIC_TOKEN.match(token)
    if numeric_match is None or numeric_match.group(0) != token:
        raise SayError(f"invalid numeric token: {token}")

    sign = []
    if token[0] in "+-":
        sign = ["plus" if token[0] == "+" else "minus"]
        token = token[1:]

    integer_text, separator, fraction_text = token.partition(".")
    integer_digits = integer_text.replace(",", "")
    comma_match = _COMMA_FORMAT.match(integer_text)
    if "," in integer_text and (
        comma_match is None or comma_match.group(0) != integer_text
    ):
        raise SayError(f"invalid comma placement in numeric token: {token}")
    if len(integer_digits) > 1 and integer_digits.startswith("0"):
        words = [_DIGIT_WORDS[int(digit)] for digit in integer_digits]
    else:
        words = _integer_number_words(int(integer_digits))
    if separator:
        words.append("point")
        words.extend(_DIGIT_WORDS[int(digit)] for digit in fraction_text)
    return sign + words

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
        if _NUMERIC_TOKEN.match(word):
            words = _numeric_words(word)
            for numeric_word in words:
                entry = SAY_INDEX.get(numeric_word)
                if entry is None:
                    raise SayError(f"numeric word is not in DVSS vocabulary: {numeric_word}")
                resolved.append((entry[0], entry[1], numeric_word))
            continue
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

def free_speak(text: str, rom: "RomEmulator", digitalker: "Digitalker") -> None:
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
