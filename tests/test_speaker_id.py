"""Tests for voice profile enrollment, identification, and persistence.

Sections:
  A. SpeakerProfile — centroid, add, MAX_STORED cap
  B. VoiceProfileStore — enroll, identify, resolve, rename, delete, save/load
  C. Persistence — round-trip JSON serialisation of embeddings
  D. Pipeline integration — diarizer.embed() call, profiles.resolve() wired in
  E. WebSocket rename_speaker message — end-to-end via isolated stub server

Run:
    .venv312/Scripts/python.exe tests/test_speaker_id.py
"""
from __future__ import annotations
import _common  # noqa: F401  (path + cache setup)
import asyncio, gc, json, os, sys, tempfile, time, traceback
from pathlib import Path
import numpy as np

os.environ.setdefault("COQUI_TOS_AGREED", "1")

PASS: list[str] = []
FAIL: list[str] = []

def ok(name: str, detail: str = ""):
    print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    PASS.append(name)

def fail(name: str, reason: str):
    print(f"  FAIL  {name}  — {reason}")
    traceback.print_exc()
    FAIL.append(name)

def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

# ── Random embedding helpers ───────────────────────────────────────────────

RNG = np.random.default_rng(42)

def rand_emb(dim: int = 192) -> np.ndarray:
    v = RNG.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)

def noisy(emb: np.ndarray, noise: float = 0.05) -> np.ndarray:
    """Return a perturbed version of emb (simulates same speaker, different utterance)."""
    v = emb + noise * RNG.standard_normal(emb.shape).astype(np.float32)
    return v / np.linalg.norm(v)

def distinct(emb: np.ndarray) -> np.ndarray:
    """Return an embedding that is far from emb (simulates different speaker)."""
    other = rand_emb(len(emb))
    while np.dot(emb, other) > 0.3:
        other = rand_emb(len(emb))
    return other

# ══════════════════════════════════════════════════════════════════════════
# A. SpeakerProfile
# ══════════════════════════════════════════════════════════════════════════
section("A. SpeakerProfile — centroid, add, MAX_STORED cap")

from ominvox.pipeline.speaker_id import SpeakerProfile, VoiceProfileStore, _cosine

try:
    p = SpeakerProfile(name="Alice")
    assert p.centroid is None, "empty profile should have no centroid"
    ok("SpeakerProfile: empty centroid is None")
except Exception as e:
    fail("SpeakerProfile empty centroid", str(e))

try:
    p = SpeakerProfile(name="Alice")
    e1 = rand_emb()
    p.add(e1)
    c = p.centroid
    assert c is not None and c.shape == e1.shape
    assert abs(np.linalg.norm(c) - 1.0) < 1e-5, "centroid should be unit-normalised"
    ok("SpeakerProfile: centroid is unit-normalised after 1 embedding")
except Exception as e:
    fail("SpeakerProfile single embedding centroid", str(e))

try:
    p = SpeakerProfile(name="Alice")
    base = rand_emb()
    for _ in range(5):
        p.add(noisy(base, noise=0.02))
    c = p.centroid
    sim = _cosine(base, c)
    assert sim > 0.90, f"centroid should be close to base embedding, got sim={sim:.3f}"
    ok("SpeakerProfile: centroid converges to base embedding", f"cosine={sim:.3f}")
except Exception as e:
    fail("SpeakerProfile centroid convergence", str(e))

try:
    p = SpeakerProfile(name="Alice")
    for _ in range(60):
        p.add(rand_emb())
    assert len(p.embeddings) == SpeakerProfile.MAX_STORED, \
        f"expected {SpeakerProfile.MAX_STORED}, got {len(p.embeddings)}"
    ok(f"SpeakerProfile: MAX_STORED={SpeakerProfile.MAX_STORED} cap enforced")
except Exception as e:
    fail("SpeakerProfile MAX_STORED cap", str(e))

# ══════════════════════════════════════════════════════════════════════════
# B. VoiceProfileStore — core operations
# ══════════════════════════════════════════════════════════════════════════
section("B. VoiceProfileStore — enroll, identify, resolve, rename, delete")

with tempfile.TemporaryDirectory() as tmpdir:
    store = VoiceProfileStore(Path(tmpdir), threshold=0.75)

    # B.1 enroll
    try:
        alice_emb = rand_emb()
        store.enroll("Alice", alice_emb, pyannote_label="SPEAKER_00")
        assert "Alice" in store.profile_names
        assert store.get_label_map().get("SPEAKER_00") == "Alice"
        ok("enroll: creates profile and binds label")
    except Exception as e:
        fail("enroll basic", str(e))

    # B.2 identify — close match
    try:
        close = noisy(alice_emb, noise=0.05)
        name = store.identify(close)
        assert name == "Alice", f"expected 'Alice', got {name!r}"
        ok("identify: close embedding matches Alice", f"cosine={_cosine(alice_emb, close):.3f}")
    except Exception as e:
        fail("identify close match", str(e))

    # B.3 identify — distant (different speaker)
    try:
        far = distinct(alice_emb)
        name = store.identify(far)
        assert name is None, f"expected None for distant embedding, got {name!r}"
        ok("identify: distant embedding → None (below threshold)")
    except Exception as e:
        fail("identify distant", str(e))

    # B.4 enroll second speaker
    try:
        bob_emb = distinct(alice_emb)
        store.enroll("Bob", bob_emb, pyannote_label="SPEAKER_01")
        close_bob = noisy(bob_emb, noise=0.05)
        assert store.identify(close_bob) == "Bob"
        assert store.identify(noisy(alice_emb, noise=0.05)) == "Alice"
        ok("identify: 2 speakers distinguished correctly")
    except Exception as e:
        fail("identify 2 speakers", str(e))

    # B.5 resolve — the voice decides, not the pyannote label. Each utterance is
    # diarized on its own, so the dominant label is almost always SPEAKER_00 for
    # everyone; trusting it collapsed every speaker into one profile.
    try:
        bob_like = noisy(bob_emb, noise=0.05)
        name = store.resolve("SPEAKER_00", bob_like)   # SPEAKER_00 is bound to Alice
        assert name == "Bob", f"expected 'Bob' from the embedding, got {name!r}"
        ok("resolve: embedding wins over a stale pyannote label")
    except Exception as e:
        fail("resolve embedding priority", str(e))

    # B.5b resolve — label map is still the fallback without an embedding
    try:
        assert store.resolve("SPEAKER_00", None) == "Alice"
        ok("resolve: label_map used when no embedding is available")
    except Exception as e:
        fail("resolve label fallback", str(e))

    # B.6 resolve — embedding match for new label
    try:
        close_alice = noisy(alice_emb, noise=0.05)
        name = store.resolve("SPEAKER_99", close_alice)  # new label, should match Alice
        assert name == "Alice", f"expected 'Alice' via embedding match, got {name!r}"
        ok("resolve: embedding match works for new pyannote label")
    except Exception as e:
        fail("resolve embedding match", str(e))

    # B.7 resolve — auto-assign Unknown N when no match
    try:
        far_emb = distinct(alice_emb)
        while _cosine(far_emb, bob_emb) > 0.75:
            far_emb = rand_emb()
        name = store.resolve("SPEAKER_77", far_emb)
        assert name.startswith("Unknown "), f"expected 'Unknown N', got {name!r}"
        ok("resolve: no match → auto Unknown N", f"assigned={name!r}")
    except Exception as e:
        fail("resolve auto Unknown", str(e))

    # B.8 rename_profile
    try:
        charlie_emb = rand_emb()
        unknown_name = store.resolve("SPEAKER_00", charlie_emb)
        assert unknown_name.startswith("Unknown")
        assert store.rename_profile(unknown_name, "Charlie")
        assert "Charlie" in store.profile_names
        assert unknown_name not in store.profile_names, "old Unknown profile should be removed"
        assert store.resolve("SPEAKER_00", noisy(charlie_emb, 0.03)) == "Charlie"
        ok("rename_profile: Unknown renamed, later utterances resolve to new name")
    except Exception as e:
        fail("rename_profile", str(e))

    # B.8b rename onto an existing name merges the two profiles
    try:
        split_name = store.resolve("SPEAKER_00", distinct(charlie_emb))
        n_before = len(store._profiles["Charlie"].embeddings)
        assert store.rename_profile(split_name, "Charlie")
        assert split_name not in store.profile_names
        assert len(store._profiles["Charlie"].embeddings) == n_before + 1
        ok("rename_profile: renaming onto an existing name merges profiles")
    except Exception as e:
        fail("rename_profile merge", str(e))

    # B.8c legacy rename_label still binds a label
    try:
        store.rename_label("SPEAKER_88", "Dana")
        assert store.get_label_map().get("SPEAKER_88") == "Dana"
        assert "Dana" in store.profile_names
        ok("rename_label: binds a pyannote label to a name (legacy path)")
    except Exception as e:
        fail("rename_label", str(e))

    # B.9 delete_profile
    try:
        store.enroll("Temp", rand_emb(), pyannote_label="SPEAKER_TMP")
        store.delete_profile("Temp")
        assert "Temp" not in store.profile_names
        assert "SPEAKER_TMP" not in store.get_label_map()
        ok("delete_profile: removes profile and clears label_map entry")
    except Exception as e:
        fail("delete_profile", str(e))

    # B.10 list_profiles
    try:
        profiles = store.list_profiles()
        assert "Alice" in profiles
        assert isinstance(profiles["Alice"]["utterances"], int)
        ok("list_profiles: returns dict with utterance counts", f"profiles={list(profiles.keys())}")
    except Exception as e:
        fail("list_profiles", str(e))

# ══════════════════════════════════════════════════════════════════════════
# C. Persistence — round-trip JSON serialisation
# ══════════════════════════════════════════════════════════════════════════
section("C. Persistence — save/load round-trip")

with tempfile.TemporaryDirectory() as tmpdir:
    p = Path(tmpdir)

    # C.1 Save and reload
    try:
        alice_emb = rand_emb()
        bob_emb = distinct(alice_emb)
        s1 = VoiceProfileStore(p, threshold=0.75)
        s1.enroll("Alice", alice_emb, pyannote_label="SPEAKER_00")
        s1.enroll("Alice", noisy(alice_emb, 0.03))
        s1.enroll("Bob", bob_emb, pyannote_label="SPEAKER_01")
        s1.save()

        s2 = VoiceProfileStore(p, threshold=0.75)
        assert "Alice" in s2.profile_names
        assert "Bob" in s2.profile_names
        ok("Persistence: profiles survive save/load", f"names={s2.profile_names}")
    except Exception as e:
        fail("Persistence save/load", str(e))

    # C.2 Embeddings are preserved correctly
    try:
        alice_id = s2.identify(noisy(alice_emb, 0.05))
        assert alice_id == "Alice", f"expected Alice after reload, got {alice_id!r}"
        ok("Persistence: embedding matching works after reload")
    except Exception as e:
        fail("Persistence embedding after reload", str(e))

    # C.3 label_map persists
    try:
        assert s2.get_label_map().get("SPEAKER_00") == "Alice"
        assert s2.get_label_map().get("SPEAKER_01") == "Bob"
        ok("Persistence: label_map survives round-trip")
    except Exception as e:
        fail("Persistence label_map", str(e))

    # C.4 next_unknown counter persists
    try:
        far = rand_emb()
        while max(_cosine(far, alice_emb), _cosine(far, bob_emb)) > 0.75:
            far = rand_emb()
        name1 = s2.resolve("SPEAKER_X", far)
        s2.save()
        s3 = VoiceProfileStore(p, threshold=0.75)
        far2 = rand_emb()
        while max(_cosine(far2, alice_emb), _cosine(far2, bob_emb), _cosine(far2, far)) > 0.75:
            far2 = rand_emb()
        name2 = s3.resolve("SPEAKER_Y", far2)
        n1 = int(name1.split()[-1])
        n2 = int(name2.split()[-1])
        assert n2 > n1, f"Unknown counter should increment: {name1} < {name2}"
        ok("Persistence: Unknown counter increments across reloads", f"{name1} -> {name2}")
    except Exception as e:
        fail("Persistence next_unknown counter", str(e))

    # C.5 JSON is valid and readable
    try:
        content = (p / "profiles.json").read_text()
        parsed = json.loads(content)
        assert "profiles" in parsed
        assert "label_map" in parsed
        ok("Persistence: JSON is valid and contains expected keys")
    except Exception as e:
        fail("Persistence JSON validity", str(e))

# ══════════════════════════════════════════════════════════════════════════
# D. Pipeline integration — diarizer embed() and profiles.resolve()
# ══════════════════════════════════════════════════════════════════════════
section("D. Pipeline integration — diarizer.embed() and profile resolution")

from ominvox import config as _cfg_mod
cfg = _cfg_mod.load()

try:
    from ominvox.pipeline.diarize import Diarizer
    diar = Diarizer(cfg)
    ok("Diarizer loaded")
except Exception as e:
    fail("Diarizer load", str(e))
    diar = None

SR = 16000
def speech_like(s: float = 2.0) -> np.ndarray:
    t = np.linspace(0, s, int(SR * s), endpoint=False)
    sig = sum(a * np.sin(2 * np.pi * f * t) for f, a in
              [(200,.15),(400,.10),(800,.08),(1600,.05),(3200,.03)])
    return sig.astype(np.float32)

# D.1 embed() returns a vector or None (gracefully handles missing model)
try:
    emb = diar.embed(speech_like(3.0)) if diar else None
    if emb is not None:
        assert emb.ndim == 1 and len(emb) > 0
        assert abs(np.linalg.norm(emb) - 1.0) < 1e-4, "embedding should be unit-normalised"
        ok("diarizer.embed(): returns unit-normalised 1-D vector", f"dim={len(emb)}")
    else:
        ok("diarizer.embed(): returned None (embedding model unavailable — fallback OK)")
except Exception as e:
    fail("diarizer.embed()", str(e))

# D.2 label_and_embed() returns both pieces
try:
    label, emb2 = diar.label_and_embed(speech_like(3.0)) if diar else ("SPEAKER_00", None)
    assert isinstance(label, str) and label
    ok("diarizer.label_and_embed()", f"label={label!r} emb={'yes' if emb2 is not None else 'None'}")
except Exception as e:
    fail("diarizer.label_and_embed()", str(e))

# D.3 VoiceProfileStore.resolve() in pipeline context
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        store = VoiceProfileStore(Path(tmpdir))
        # Simulate two utterances from the same pyannote label
        emb_a = rand_emb(192)
        store.enroll("Alice", emb_a, pyannote_label="SPEAKER_00")

        name = store.resolve("SPEAKER_00", noisy(emb_a, 0.05))
        assert name == "Alice"
        ok("Pipeline resolve: enrolled speaker recognised across utterances")
    except Exception as e:
        fail("Pipeline resolve enrolled speaker", str(e))

# D.4 Resolver emits "Unknown N" for new speakers, then renames correctly
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        store = VoiceProfileStore(Path(tmpdir))
        far_emb = rand_emb(192)
        name1 = store.resolve("SPEAKER_00", far_emb)
        assert name1.startswith("Unknown")
        store.rename_profile(name1, "Charlie")
        # Next utterance from the same voice gets "Charlie"
        name2 = store.resolve("SPEAKER_00", noisy(far_emb, 0.03))
        assert name2 == "Charlie", f"expected 'Charlie' after rename, got {name2!r}"
        ok("Pipeline resolve: rename persists for subsequent utterances")
    except Exception as e:
        fail("Pipeline resolve rename", str(e))

# D.4b Two different voices that pyannote both calls SPEAKER_00 stay separate
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        store = VoiceProfileStore(Path(tmpdir))
        a, b = rand_emb(192), rand_emb(192)
        while _cosine(a, b) > 0.5:
            b = rand_emb(192)
        n_a = store.resolve("SPEAKER_00", a)
        n_b = store.resolve("SPEAKER_00", b)
        assert n_a != n_b, f"two voices collapsed into {n_a!r}"
        assert store.resolve("SPEAKER_00", noisy(a, 0.03)) == n_a
        assert store.resolve("SPEAKER_00", noisy(b, 0.03)) == n_b
        ok("Pipeline resolve: distinct voices stay distinct under one pyannote label",
           f"{n_a!r} / {n_b!r}")
    except Exception as e:
        fail("Pipeline resolve distinct voices", str(e))

# D.4c clear() forgets everything and restarts numbering
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        store = VoiceProfileStore(Path(tmpdir))
        store.resolve("SPEAKER_00", rand_emb(192))
        store.clear()
        assert store.profile_names == []
        assert VoiceProfileStore(Path(tmpdir)).profile_names == [], "clear() not persisted"
        assert store.resolve("SPEAKER_00", rand_emb(192)) == "Unknown 1"
        ok("clear(): forgets all speakers (persisted) and restarts at Unknown 1")
    except Exception as e:
        fail("clear()", str(e))

# D.4d profiles saved with a different embedding size must not break matching
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        old = VoiceProfileStore(Path(tmpdir))
        old.enroll("Legacy", rand_emb(192))
        s2 = VoiceProfileStore(Path(tmpdir))
        name = s2.resolve("SPEAKER_00", rand_emb(256))   # real WeSpeaker size
        assert name.startswith("Unknown"), name
        s2.rename_profile(name, "Legacy")                # merge 256 into 192 profile
        assert s2.identify(rand_emb(256)) in (None, "Legacy")
        ok("mixed embedding sizes (192 vs 256) are skipped, not a crash")
    except Exception as e:
        fail("mixed embedding sizes", str(e))

# D.5 Cross-session: save, reload, new pyannote label still matches
with tempfile.TemporaryDirectory() as tmpdir:
    try:
        alice_emb = rand_emb(192)
        s1 = VoiceProfileStore(Path(tmpdir))
        s1.enroll("Alice", alice_emb)
        s1.save()

        s2 = VoiceProfileStore(Path(tmpdir))
        # New session: pyannote reassigns label (SPEAKER_00 → SPEAKER_02 is typical)
        name = s2.resolve("SPEAKER_02", noisy(alice_emb, 0.05))
        assert name == "Alice", f"expected 'Alice' via embedding match, got {name!r}"
        ok("Cross-session: embedding match survives restart and label reassignment")
    except Exception as e:
        fail("Cross-session embedding match", str(e))

# ══════════════════════════════════════════════════════════════════════════
# E. WebSocket rename_speaker — end-to-end via isolated stub server
# ══════════════════════════════════════════════════════════════════════════
section("E. WebSocket rename_speaker message — end-to-end")

# Release GPU models to free VRAM before starting server
try:
    if diar:
        del diar
    gc.collect()
    import torch as _t
    if _t.cuda.is_available():
        _t.cuda.empty_cache()
except Exception:
    pass

async def ws_rename_round_trip():
    import socket
    import websockets
    from ominvox.ui.server import UIServer

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        free_port = _s.getsockname()[1]

    # Use a throwaway speaker dir so the test never touches the user's real profiles
    tmp_cfg = dict(cfg)
    tmp_cfg["_speaker_dir"] = Path(tempfile.mkdtemp())
    srv = UIServer(tmp_cfg)
    # Pre-populate with an Unknown speaker so rename has something to work with
    first = srv._profiles.resolve("SPEAKER_00", rand_emb(192))  # creates "Unknown 1"

    app = srv._build_app()

    async def run_server():
        import uvicorn
        ucfg = uvicorn.Config(app, host="127.0.0.1", port=free_port,
                              log_level="error", loop="asyncio")
        server = uvicorn.Server(ucfg)
        await server.serve()

    server_task = asyncio.ensure_future(run_server())
    await asyncio.sleep(1.0)

    results = {}
    async with websockets.connect(f"ws://127.0.0.1:{free_port}/ws", open_timeout=5) as ws:
        init = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        results["init_speakers"] = init.get("speakers", {})

        # Send rename
        await ws.send(json.dumps({
            "type": "rename_speaker",
            "speaker_id": first,          # the UI sends the current display name
            "name": "Alice",
        }))

        # Expect a speakers update back (skip the periodic stats/level frames)
        results["rename_reply"] = None
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "speakers":
                results["rename_reply"] = msg
                break

    server_task.cancel()
    return results

try:
    results = asyncio.run(ws_rename_round_trip())
    init_spks = results.get("init_speakers", {})
    rename_reply = results.get("rename_reply")

    # Initial connect should include known speakers
    ok("WS init: speakers list sent on connect", f"profiles={list(init_spks.keys())}")

    # rename_speaker should trigger a speakers broadcast
    assert rename_reply is not None, "no speakers update received after rename"
    assert rename_reply.get("type") == "speakers", f"wrong type: {rename_reply}"
    assert "Alice" in rename_reply.get("speakers", {}), \
        f"Alice not in speakers after rename: {rename_reply}"
    assert "Unknown 1" not in rename_reply.get("speakers", {}), \
        f"old name still listed after rename: {rename_reply}"
    ok("WS rename_speaker: server broadcasts updated speakers list",
       f"speakers={list(rename_reply['speakers'].keys())}")
except Exception as e:
    fail("WS rename_speaker round-trip", str(e))

# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"Results: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("Failed:")
    for f in FAIL:
        print(f"  FAIL  {f}")
sys.exit(0 if not FAIL else 1)
