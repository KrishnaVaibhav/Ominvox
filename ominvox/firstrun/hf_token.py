"""Hugging Face token: verify it (and access to the gated speaker models) and
store it in the project's .env file."""
from __future__ import annotations
import os
import re
from pathlib import Path

# Gated models the user must accept on huggingface.co (one click each).
GATED = ("pyannote/speaker-diarization-3.1", "pyannote/segmentation-3.0")
TOKEN_PAGE = "https://huggingface.co/settings/tokens"


def current_token() -> str | None:
    tok = os.environ.get("HF_TOKEN", "").strip()
    return tok if tok.startswith("hf_") and "paste_your_token" not in tok else None


def verify(token: str) -> dict:
    """{"valid", "user", "error", "models": [{"repo", "url", "ok"}]}"""
    from huggingface_hub import HfApi, auth_check
    out = {"valid": False, "user": None, "error": None,
           "models": [{"repo": r, "url": f"https://huggingface.co/{r}", "ok": False} for r in GATED]}
    token = (token or "").strip()
    if not token.startswith("hf_"):
        out["error"] = "That doesn't look like a token - it should start with hf_"
        return out
    try:
        out["user"] = HfApi().whoami(token=token).get("name")
        out["valid"] = True
    except Exception as exc:
        out["error"] = ("The token was rejected. Copy it again from huggingface.co/settings/tokens."
                        if "401" in str(exc) else f"Could not reach Hugging Face ({type(exc).__name__}).")
        return out
    for m in out["models"]:
        try:
            auth_check(m["repo"], token=token)
            m["ok"] = True
        except Exception:
            m["ok"] = False                     # terms not accepted yet
    return out


def save(root: Path, token: str) -> None:
    """Write HF_TOKEN into .env (keeping any other lines) and apply it now."""
    env = root / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [l for l in lines if not re.match(r"\s*HF_TOKEN\s*=", l)]
    lines.append(f"HF_TOKEN={token.strip()}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["HF_TOKEN"] = token.strip()
