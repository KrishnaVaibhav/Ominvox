"""Translation. Backends (config mt.backend):
 - 'auto'   : Whisper's built-in translate when the target is English (fastest),
              NLLB-200 for every other target. NLLB loads on first use only.
 - 'whisper': always Whisper translate (STT task=translate) - English output only
 - 'nllb'   : always NLLB-200 (transcribe in the source language, then translate)"""
from __future__ import annotations
import sys
import threading

try:
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
except Exception:  # pragma: no cover
    AutoTokenizer = AutoModelForSeq2SeqLM = torch = None

# ISO-639-1 (Whisper's language codes) -> NLLB FLORES-200 codes
_NLLB = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "pl": "pol_Latn",
    "tr": "tur_Latn", "sv": "swe_Latn", "da": "dan_Latn", "no": "nob_Latn",
    "nn": "nno_Latn", "fi": "fin_Latn", "cs": "ces_Latn", "sk": "slk_Latn",
    "hu": "hun_Latn", "ro": "ron_Latn", "bg": "bul_Cyrl", "el": "ell_Grek",
    "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "sr": "srp_Cyrl", "hr": "hrv_Latn",
    "sl": "slv_Latn", "lt": "lit_Latn", "lv": "lvs_Latn", "et": "est_Latn",
    "ar": "arb_Arab", "he": "heb_Hebr", "fa": "pes_Arab", "ur": "urd_Arab",
    "hi": "hin_Deva", "bn": "ben_Beng", "ta": "tam_Taml", "te": "tel_Telu",
    "mr": "mar_Deva", "gu": "guj_Gujr", "kn": "kan_Knda", "ml": "mal_Mlym",
    "pa": "pan_Guru", "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans",
    "vi": "vie_Latn", "th": "tha_Thai", "id": "ind_Latn", "ms": "zsm_Latn",
    "tl": "tgl_Latn", "sw": "swh_Latn", "ca": "cat_Latn",
}


class Translator:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        self.backend = cfg["mt"].get("backend", "auto")
        self.tok = self.model = None
        self._load_lock = threading.Lock()
        self._load_failed = False
        if self.backend == "whisper" and self.target != "en":
            print(
                f"[mt] WARNING: backend='whisper' only translates to English, but "
                f"target_lang='{self.target}'. Output will be English. "
                f"Set mt.backend: auto in config.yaml for {self.target}.",
                file=sys.stderr,
            )
        if self.backend == "nllb":
            self._ensure_nllb()

    @property
    def target(self) -> str:
        # Read live so a target change in the UI applies without a restart.
        return self._cfg["translate"]["target_lang"]

    @target.setter
    def target(self, code: str):
        self._cfg["translate"]["target_lang"] = code

    def whisper_handles(self) -> bool:
        """True when STT should run Whisper's translate-to-English task."""
        if self.backend == "whisper":
            return True
        return self.backend == "auto" and self.target == "en"

    def _ensure_nllb(self) -> bool:
        if self.model is not None:
            return True
        if self._load_failed or AutoModelForSeq2SeqLM is None:
            return False
        with self._load_lock:
            if self.model is not None:
                return True
            name = self._cfg["mt"]["nllb_model"]
            print(f"[mt] loading {name} for '{self.target}' (first use only)...", flush=True)
            try:
                self.tok = AutoTokenizer.from_pretrained(name)
                model = AutoModelForSeq2SeqLM.from_pretrained(name)
                if torch.cuda.is_available():
                    model = model.half().to("cuda")   # fp16: ~1.2 GB VRAM instead of 2.4
                self.model = model.eval()
            except Exception as exc:
                self._load_failed = True
                print(f"[mt] could not load NLLB ({exc}); showing untranslated text.",
                      file=sys.stderr)
                return False
        return True

    def translate(self, text: str, src_lang: str) -> str:
        return self.translate_ex(text, src_lang)[0]

    def translate_ex(self, text: str, src_lang: str) -> tuple[str, str]:
        """Return (text, language_it_is_in). Falls back to the source text
        (and source language) when translation isn't possible."""
        if self.whisper_handles():
            return text, "en"          # Whisper already produced English
        if not text or src_lang == self.target:
            return text, src_lang
        tgt_code = _NLLB.get(self.target)
        if tgt_code is None or not self._ensure_nllb():
            return text, src_lang
        self.tok.src_lang = _NLLB.get(src_lang, "eng_Latn")
        enc = self.tok(text, return_tensors="pt")
        if torch.cuda.is_available():
            enc = {k: v.to("cuda") for k, v in enc.items()}
        tgt_id = self.tok.convert_tokens_to_ids(tgt_code)
        with torch.inference_mode():
            out = self.model.generate(**enc, forced_bos_token_id=tgt_id, max_new_tokens=256)
        return self.tok.batch_decode(out, skip_special_tokens=True)[0], self.target
