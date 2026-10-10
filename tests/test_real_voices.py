"""Real-speech integration test (GPU, ~2 min, needs all models cached).

Synthetic sine "speech" can't exercise speaker ID or STT, so this test makes REAL
speech with four different built-in XTTS voices, resamples it to 16 kHz, and pushes
each line through the actual pipeline stages (no audio devices needed):

  diarizer embed -> VoiceProfileStore.resolve -> Whisper STT -> NLLB -> XTTS -> wav

Checks:
  1. four voices (incl. two similar female voices) resolve to four speakers, and
     repeat lines to the same one; one-word lines don't create phantom speakers
  2. Whisper transcribes the English lines
  3. target 'es' produces Spanish text via NLLB, spoken by XTTS
  4. switching target to 'en' live (no rebuild) goes back to Whisper's path

Run:  .venv312\\Scripts\\python.exe test_real_voices.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
from _common import Results
import copy
import os
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault("COQUI_TOS_AGREED", "1")

from ominvox import config
from ominvox.pipeline.orchestrator import Pipeline

def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x), n, endpoint=False),
                     np.arange(len(x)), x).astype(np.float32)


VOICES = {   # two male + two similar female voices (the hardest pair: Ana/Claribel)
    "A": "Damien Black", "B": "Ana Florence", "C": "Andrew Chipper", "D": "Claribel Dervla",
}
LINES = {
    "A": ["Good morning, I think we should leave before the storm arrives.",
          "Please bring the map and the lantern from the kitchen.",
          "We can talk about it tomorrow when everyone is here."],
    "B": ["I am not going anywhere until I find my brother.",
          "The bridge was destroyed last night, so the road is closed.",
          "Tell the captain that the ship is ready to sail."],
    "C": ["Nobody told me the meeting had been moved to Friday afternoon.",
          "If we hurry, we can still catch the last train out of the city.",
          "I have been working on this engine for three days straight."],
    "D": ["Where were you last night? I waited for hours and you never called.",
          "The garden looks beautiful now that the roses are finally blooming.",
          "Could you read the letter again, slowly this time, please?"],
}
SHORT = "No."

cfg = copy.deepcopy(config.load())
cfg["_speaker_dir"] = Path(tempfile.mkdtemp())       # never touch real profiles
cfg["mt"]["backend"] = "auto"
cfg["translate"]["source_lang"] = "auto"
cfg["translate"]["target_lang"] = "es"
cfg["tts"]["voice_mode"] = "match"

print("Loading pipeline (all models)...")
pipe = Pipeline(cfg, log=lambda m: None)

events: list[dict] = []
pipe._notify = events.append
spoken: list[np.ndarray] = []
lines: list[dict] = []
def _fake_submit(wav, anchor=None, meta=None):      # capture instead of playing
    spoken.append(wav)
    pipe._on_play({**(meta or {}), "play_t": meta["ready_t"], "late_s": 0.0,
                   "out_s": len(wav) / 24000})
pipe.player.submit = _fake_submit

tts = pipe.synth.tts
sr = cfg["audio"]["sample_rate"]
import torch

R = Results()
ok, fail, check = R.ok, R.fail, R.check
torch.manual_seed(1234)            # XTTS samples randomly; keep the test speech reproducible


def say(text: str, voice: str) -> np.ndarray:
    wav = np.asarray(tts.tts(text=text, speaker=voice, language="en"), dtype=np.float32)
    return resample(wav, 24000, sr)


print("Synthesising test speech...")
clips = {who: [say(t, VOICES[who]) for t in lines] for who, lines in LINES.items()}
order = [(clips[who][i], who) for i in range(3) for who in "ABCD"]   # round-robin dialogue

print("\n=== 1-3. Full chain, target=es ===")
names: dict[str, set] = {who: set() for who in VOICES}
for audio, who in order:
    events.clear()
    n_spoken = len(spoken)
    pipe._process_utterance(audio)
    utt = next((e for e in events if e["type"] == "utterance"), None)
    if utt is None:
        fail(f"utterance from {who}", "no transcript produced")
        continue
    names[who].add(utt["speaker"])
    print(f"    {who} -> {utt['speaker']:<10} [{utt['src_lang']}] {utt['src_text']}")
    print(f"    {'':>14} [{utt['tgt_lang']}] {utt['translated']}")
    if len(spoken) == n_spoken:
        fail(f"TTS for {who}", "no audio produced")

lm = next((e for e in events if e["type"] == "line_metrics"), None)
if lm and lm["lag_s"] > 0 and all(k in lm["stages"] for k in ("diarize", "stt", "mt", "tts")):
    ok("line_metrics reports lag + per-stage timing",
       f"lag {lm['lag_s']}s, stt {lm['stages']['stt']}ms, tts {lm['stages']['tts']}ms, rtf {lm['rtf']}")
else:
    fail("line_metrics", str(lm))
st = pipe.stats()
if st["lines_total"] == len(order) and st["lag"]["p95"] and st["suggested_lag_ms"]:
    ok("stats(): rolling lag + suggestion", f"avg {st['lag']['avg']}s p95 {st['lag']['p95']}s "
       f"-> suggest {st['suggested_lag_ms']} ms, VRAM {st['system'].get('vram_used_gb')} GB")
else:
    fail("stats()", str({k: st.get(k) for k in ('lines_total', 'lag', 'suggested_lag_ms')}))

assigned = {who: next(iter(v)) for who, v in names.items() if len(v) == 1}
if len(assigned) == len(VOICES) and len(set(assigned.values())) == len(VOICES):
    ok("four real voices -> four consistent speakers", str(assigned))
else:
    fail("speaker separation", str(names))

if len(spoken) == len(order):
    ok("XTTS spoke every translated line", f"{len(spoken)} clips")
else:
    fail("XTTS output count", f"{len(spoken)}/{len(order)}")

n_profiles = len(pipe.profiles.profile_names)
for who in "ABCD":
    for _ in range(3):                  # XTTS output length varies run to run
        clip = say(SHORT, VOICES[who])
        pad = np.zeros(int(0.75 * sr), np.float32)   # live segments carry trailing silence
        pipe._process_utterance(np.concatenate([clip, pad]))
n_after = len(pipe.profiles.profile_names)
if n_after == n_profiles:
    ok("one-word lines don't create phantom speakers", f"{n_profiles} profiles")
else:
    fail("short lines", f"profiles {n_profiles} -> {n_after}")

events.clear()
pipe._process_utterance(clips["A"][0])
utt = next(e for e in events if e["type"] == "utterance")
if utt["tgt_lang"] == "es" and utt["translated"] != utt["src_text"]:
    ok("NLLB translated to Spanish", utt["translated"])
else:
    fail("NLLB Spanish", f"{utt}")
if "storm" in utt["src_text"].lower():
    ok("Whisper transcribed English speech", utt["src_text"])
else:
    fail("Whisper transcript", utt["src_text"])

print("\n=== 4. Live target switch es -> en (no rebuild) ===")
cfg["translate"]["target_lang"] = "en"
events.clear()
pipe._process_utterance(clips["B"][0])
utt = next((e for e in events if e["type"] == "utterance"), None)
if utt and utt["tgt_lang"] == "en" and pipe.mt.whisper_handles():
    ok("target switch to en applied live", utt["translated"])
else:
    fail("live target switch", f"{utt}")

R.finish()
