"""Languages a file can be translated into (the ones the voice model speaks)."""
from __future__ import annotations

# ISO-639-1 -> (English name, ISO-639-2 tag that video files use for tracks)
VOICE_LANGS: dict[str, tuple[str, str]] = {
    "en": ("English", "eng"), "es": ("Spanish", "spa"), "fr": ("French", "fra"),
    "de": ("German", "deu"), "it": ("Italian", "ita"), "pt": ("Portuguese", "por"),
    "pl": ("Polish", "pol"), "tr": ("Turkish", "tur"), "ru": ("Russian", "rus"),
    "nl": ("Dutch", "nld"), "cs": ("Czech", "ces"), "ar": ("Arabic", "ara"),
    "zh": ("Chinese", "zho"), "hu": ("Hungarian", "hun"), "ko": ("Korean", "kor"),
    "ja": ("Japanese", "jpn"), "hi": ("Hindi", "hin"),
}

# Names for languages Whisper may detect in a file (any of these can be the source).
OTHER_NAMES = {
    "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish", "el": "Greek",
    "uk": "Ukrainian", "ro": "Romanian", "bg": "Bulgarian", "hr": "Croatian", "sr": "Serbian",
    "sk": "Slovak", "sl": "Slovenian", "he": "Hebrew", "fa": "Persian", "ur": "Urdu",
    "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "gu": "Gujarati",
    "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "vi": "Vietnamese", "th": "Thai",
    "id": "Indonesian", "ms": "Malay", "tl": "Tagalog", "sw": "Swahili", "ca": "Catalan",
    "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian",
}

# ISO-639-2 tags seen in files -> ISO-639-1 (for preselecting a track's language)
_ISO2 = {v[1]: k for k, v in VOICE_LANGS.items()}
_ISO2.update({"fre": "fr", "ger": "de", "dut": "nl", "cze": "cs", "chi": "zh",
              "swe": "sv", "dan": "da", "nor": "no", "fin": "fi", "gre": "el", "ell": "el",
              "ukr": "uk", "rum": "ro", "ron": "ro", "heb": "he", "per": "fa", "fas": "fa",
              "vie": "vi", "tha": "th", "ind": "id"})


def name(code: str | None) -> str:
    if not code:
        return "Unknown"
    return VOICE_LANGS.get(code, (None,))[0] or OTHER_NAMES.get(code) or code


def iso2(code: str) -> str:
    return VOICE_LANGS.get(code, (None, "und"))[1]


def from_tag(tag: str | None) -> str | None:
    """A track's language tag ('eng', 'en', 'fre') -> ISO-639-1, or None."""
    if not tag:
        return None
    tag = tag.lower()
    if len(tag) == 2:
        return tag
    return _ISO2.get(tag)
