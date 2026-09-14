"""Resolve free-speak vocabulary and speak it through the Digitalker."""

import json
import re
import time

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from digitalker import Digitalker
    from rom_emulator import RomEmulator

with open("free_speak_dictionary.json", "r") as _dictionary_file:
    _dictionary_data = json.load(_dictionary_file)

class FreeSpeakError(ValueError):
    """Base exception for invalid free-speak input."""


class UnknownWordError(FreeSpeakError):
    """Raised when an input token is not in the free-speak vocabulary."""

    def __init__(self, word: str, position: int) -> None:
        """Initialize an error for an unknown input token.

        Args:
            word (str): The original unknown token.
            position (int): The zero-based token position.
        """
        self.word = word
        self.position = position
        super().__init__(f"unknown free-speak word {word!r} at position {position}")


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
                raise ValueError(f"duplicate free-speak vocabulary key: {word}")
            index[key] = (rom_name, address)
    for alias, canonical in _dictionary_data.get("aliases", {}).items():
        if not isinstance(canonical, str):
            raise TypeError(f"alias target must be a string: {alias}")
        target = index.get(canonical.lower())
        if target is None:
            raise ValueError(f"alias target is not in free-speak vocabulary: {canonical}")
        alias_key = alias.lower()
        if alias_key in index:
            raise ValueError(f"alias shadows canonical vocabulary: {alias}")
        index[alias_key] = target
    return index

FREE_SPEAK_INDEX = _build_index()

_COMPOSITION_DATA = _dictionary_data["composition"]
_PREFIX_FRAGMENTS = _COMPOSITION_DATA["prefixes"]
_SUFFIX_FRAGMENTS = _COMPOSITION_DATA["suffixes"]
_FRAGMENT_KEYS = set(_PREFIX_FRAGMENTS.values()) | set(_SUFFIX_FRAGMENTS.values())
for _fragment in _FRAGMENT_KEYS:
    if _fragment not in FREE_SPEAK_INDEX:
        raise ValueError(f"composition fragment is not in free-speak vocabulary: {_fragment}")

_NUMBER_DATA = _dictionary_data["numbers"]
_SMALL_NUMBER_WORDS = _NUMBER_DATA["small"]
_TENS_NUMBER_WORDS = _NUMBER_DATA["tens"]
_DIGIT_WORDS = _SMALL_NUMBER_WORDS[:10]
for _number_word in _SMALL_NUMBER_WORDS[0:20] + [word for word in _TENS_NUMBER_WORDS if word]:
    if _number_word not in FREE_SPEAK_INDEX:
        raise ValueError(f"number word is not in free-speak vocabulary: {_number_word}")
    
_NUMERIC_TOKEN = re.compile(r"^[+-]?[0-9][0-9,]*(?:\.[0-9]+)?$")


def _sleep_ms(milliseconds: int) -> None:
    """Sleep for milliseconds on MicroPython or CPython.

    Args:
        milliseconds (int): The duration to sleep.
    """
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(milliseconds)
    else:
        time.sleep(milliseconds / 1000)

def _composed_words(word: str) -> list:
    """Compose an unknown word from at most one prefix, root, and suffix.

    Prefixes and suffixes are matched literally; no spelling changes are
    applied. An exact dictionary entry is checked by the caller first.

    Args:
        word (str): The normalized unknown word.

    Returns:
        list: Canonical fragment/root words in speech order, or an empty list.
    """
    prefix_candidates = [("", "")]
    for spelling, fragment in _PREFIX_FRAGMENTS.items():
        if word.startswith(spelling) and len(word) > len(spelling):
            prefix_candidates.append((spelling, fragment))

    suffix_candidates = [("", "")]
    for spelling, fragment in _SUFFIX_FRAGMENTS.items():
        if word.endswith(spelling) and len(word) > len(spelling):
            suffix_candidates.append((spelling, fragment))

    for prefix_spelling, prefix_fragment in prefix_candidates:
        after_prefix = word[len(prefix_spelling):]
        for suffix_spelling, suffix_fragment in suffix_candidates:
            root_end = len(after_prefix) - len(suffix_spelling)
            root = after_prefix[:root_end]
            root_entry = FREE_SPEAK_INDEX.get(root)
            if root_entry is None or root in _FRAGMENT_KEYS:
                continue
            parts = []
            if prefix_fragment:
                parts.append(prefix_fragment)
            parts.append(root)
            if suffix_fragment:
                parts.append(suffix_fragment)
            return parts
    return []

def _integer_number_words(value: int) -> list:
    """Convert a non-negative integer into structural vocabulary words.

    Values through one billion use ``thousand`` and ``million`` groups.
    Because the vocabulary has no ``billion`` entry, exactly one billion is
    pronounced ``one thousand million``; larger values are spoken digit by
    digit.

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

def _normalize_text(text: str) -> str:
    """Lowercase text and collapse whitespace without changing punctuation.

    Args:
        text (str): The input text.

    Returns:
        str: Lowercase text with runs of whitespace collapsed.

    Raises:
        FreeSpeakError: If the input is empty or contains only whitespace.
    """
    normalized = " ".join(text.lower().split())
    if not normalized:
        raise FreeSpeakError("speech text must contain at least one word")
    return normalized

def _numeric_words(token: str) -> list:
    """Convert an integer or decimal token into vocabulary words.

    Accepted tokens may have an optional sign, comma-separated thousands
    groups, and a decimal fraction. Leading-zero integers and fraction digits
    are spoken one digit at a time.

    Args:
        token (str): A signed decimal token with optional commas.

    Returns:
        list: Spoken vocabulary words for the numeric token.

    Raises:
        FreeSpeakError: If the token uses invalid comma placement or syntax.
    """
    if _NUMERIC_TOKEN.match(token) is None:
        raise FreeSpeakError(f"invalid numeric token: {token}")

    sign = []
    if token[0] in "+-":
        sign = ["plus" if token[0] == "+" else "minus"]
        token = token[1:]

    integer_text, separator, fraction_text = token.partition(".")
    integer_digits = integer_text.replace(",", "")
    if "," in integer_text:
        comma_groups = integer_text.split(",")
        if (
            len(comma_groups[0]) < 1
            or len(comma_groups[0]) > 3
            or not comma_groups[0].isdigit()
            or any(
                len(group) != 3 or not group.isdigit()
                for group in comma_groups[1:]
            )
        ):
            raise FreeSpeakError(f"invalid comma placement in numeric token: {token}")
    if len(integer_digits) > 1 and integer_digits.startswith("0"):
        words = [_DIGIT_WORDS[int(digit)] for digit in integer_digits]
    else:
        words = _integer_number_words(int(integer_digits))
    if separator:
        words.append("point")
        words.extend(_DIGIT_WORDS[int(digit)] for digit in fraction_text)
    return sign + words

def _resolve(text: str) -> list:
    """Resolve all input words before making any hardware calls.

    Whole-input dictionary entries, including multi-word aliases, take
    precedence over token-by-token resolution. Individual tokens may be
    canonical entries, aliases, numbers, or literal affix compositions.

    Args:
        text (str): The normalized input text.

    Returns:
        list: Tuples containing the ROM filename, address, and original word.

    Raises:
        UnknownWordError: If a word is absent from the free-speak dictionary.
        FreeSpeakError: If numeric or generated composition vocabulary is
            invalid or incomplete.
    """
    whole_entry = FREE_SPEAK_INDEX.get(text)
    if whole_entry is not None:
        return [(whole_entry[0], whole_entry[1], text)]

    resolved = []
    for position, word in enumerate(text.split(" ")):
        if _NUMERIC_TOKEN.match(word):
            words = _numeric_words(word)
            for numeric_word in words:
                entry = FREE_SPEAK_INDEX.get(numeric_word)
                if entry is None:
                    raise FreeSpeakError(f"numeric word is not in free-speak vocabulary: {numeric_word}")
                resolved.append((entry[0], entry[1], numeric_word))
            continue
        entry = FREE_SPEAK_INDEX.get(word)
        if entry is None:
            composed = _composed_words(word)
            if not composed:
                raise UnknownWordError(word, position)
            for composed_word in composed:
                composed_entry = FREE_SPEAK_INDEX.get(composed_word)
                if composed_entry is None:
                    raise FreeSpeakError(
                        f"composed word is not in free-speak vocabulary: {composed_word}"
                    )
                resolved.append(
                    (composed_entry[0], composed_entry[1], composed_word)
                )
            continue
        resolved.append((entry[0], entry[1], word))
    return resolved

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

def _speak_resolved(resolved: list, rom: "RomEmulator", digitalker: "Digitalker", speech_pause_ms: int=0) -> None:
    """Speak resolved entries, loading a ROM only when it changes.

    Resolution must happen before this function is called so a failed lookup
    cannot occur after speech has started.

    Args:
        resolved (list): ROM, address, and word tuples in speech order.
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.
        speech_pause_ms (int): Optional pause in milliseconds between words.
    """
    active_rom = None

    for rom_name, address, _word in resolved:
        if rom_name != active_rom:
            rom.load(rom_name)
            active_rom = rom_name
        digitalker.speak_word(address)
        if speech_pause_ms:
            _sleep_ms(speech_pause_ms)

def free_speak(text: str, rom: "RomEmulator", digitalker: "Digitalker") -> None:
    """Resolve and speak DVSS text, switching ROMs as required.

    Input can contain canonical entries, aliases, numbers, and words made
    from the configured literal affixes. The complete input is resolved
    before the first ROM load or spoken word.

    Args:
        text (str): Case-insensitive, whitespace-separated DVSS words.
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.

    Raises:
        FreeSpeakError: If the text is empty.
        UnknownWordError: If any word is not in the free-speak dictionary.
    """
    normalized = _normalize_text(text)
    resolved = _resolve(normalized)
    _speak_resolved(resolved, rom, digitalker)

def say_all(rom: "RomEmulator", digitalker: "Digitalker", speech_pause_ms: int=50) -> None:
    """Speak every canonical dictionary entry in numeric ROM order.

    Aliases and composed forms are not included. The ROM filenames must use
    the ``DVSSROM<number>.bin`` naming convention used by the dictionary.

    Args:
        rom (RomEmulator): The ROM emulator used to select vocabulary images.
        digitalker (Digitalker): The Digitalker driver used to speak addresses.
        speech_pause_ms (int): Optional pause in milliseconds between words.
    """
    resolved = []
    rom_names = sorted(
        _dictionary_data["roms"],
        key=lambda name: int(name.replace("DVSSROM", "").replace(".bin", "")),
    )
    for rom_name in rom_names:
        for address, word in enumerate(_dictionary_data["roms"][rom_name], 1):
            resolved.append((rom_name, address, word))
    _speak_resolved(resolved, rom, digitalker, speech_pause_ms)
