"""Translation. Two backends:
 - 'whisper': handled upstream (STT task=translate, target must be English)
 - 'nllb'   : arbitrary target language via NLLB-200."""
from __future__ import annotations

try:
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
except Exception:  # pragma: no cover
    AutoTokenizer = AutoModelForSeq2SeqLM = torch = None

# minimal ISO-639-1 -> NLLB FLORES code map (extend as needed)
_NLLB = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "hi": "hin_Deva", "ja": "jpn_Jpan", "zh": "zho_Hans", "ar": "arb_Arab",
    "pt": "por_Latn", "ru": "rus_Cyrl", "it": "ita_Latn", "ko": "kor_Hang",
}


class Translator:
    def __init__(self, cfg: dict):
        self.backend = cfg["mt"]["backend"]
        self.target = cfg["translate"]["target_lang"]
        self.tok = self.model = None
        # The 'whisper' backend can only translate INTO English (Whisper's
        # task=translate is X->en only). Warn loudly instead of silently
        # emitting English when the user asked for another language.
        if self.backend == "whisper" and self.target != "en":
            import sys
            print(
                f"[mt] WARNING: backend='whisper' only translates to English, but "
                f"target_lang='{self.target}'. Output will be English. "
                f"Set mt.backend: nllb in config.yaml for {self.target}.",
                file=sys.stderr,
            )
        if self.backend == "nllb" and AutoModelForSeq2SeqLM is not None:
            name = cfg["mt"]["nllb_model"]
            self.tok = AutoTokenizer.from_pretrained(name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(name)
            if torch.cuda.is_available():
                self.model = self.model.to("cuda")

    def translate(self, text: str, src_lang: str) -> str:
        if not text:
            return text
        if self.backend != "nllb" or self.model is None:
            return text  # whisper path already produced target (English) text
        self.tok.src_lang = _NLLB.get(src_lang, "eng_Latn")
        enc = self.tok(text, return_tensors="pt")
        if torch.cuda.is_available():
            enc = {k: v.to("cuda") for k, v in enc.items()}
        tgt_id = self.tok.convert_tokens_to_ids(_NLLB.get(self.target, "eng_Latn"))
        out = self.model.generate(**enc, forced_bos_token_id=tgt_id, max_new_tokens=256)
        return self.tok.batch_decode(out, skip_special_tokens=True)[0]
