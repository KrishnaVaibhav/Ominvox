"""Web UI for Ominvox.  Start with:  run.bat --ui   (or Ominvox.exe / --window)

Serves ominvox/web/index.html and drives the pipeline over a WebSocket, so the
transcript, translation, live latency and processing metrics stream to the page
as the movie plays.
"""
from __future__ import annotations
import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
except ImportError:
    FastAPI = WebSocket = WebSocketDisconnect = HTMLResponse = JSONResponse = uvicorn = None  # type: ignore

from . import config as config_mod
from .orchestrator import Pipeline
from .speaker_id import VoiceProfileStore
from .capture import LoopbackCapture, enumerate_devices
from .metrics import Metrics
from .player import Player

WEB_DIR = Path(__file__).resolve().parent / "web"
_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
APP_ID = "ominvox"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class UIServer:
    """Owns the FastAPI app, pipeline lifecycle, and WebSocket broadcast."""

    def __init__(self, cfg: dict, persist: bool = False):
        self.cfg = cfg
        self.persist = persist                 # save UI changes to user_settings.json
        self._pipeline: Pipeline | None = None
        self._start_lock = threading.Lock()    # serialize start/stop clicks
        self._level_thread: threading.Thread | None = None
        self._level_stop = threading.Event()
        self._stop_requested = False
        self._clients: list[WebSocket] = []
        self._state = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dev_cache: dict | None = None    # cached device list (TTL below)
        self._dev_cache_ts = 0.0
        self._probe: LoopbackCapture | None = None   # "Check input" before models load
        self._probe_until = 0.0
        self._idle_metrics = Metrics()         # system stats while no pipeline exists
        # Standalone profile store for rename operations when pipeline is not running
        self._profiles = VoiceProfileStore(
            speaker_dir=cfg["_speaker_dir"],
            threshold=float(cfg.get("speaker_id", {}).get(
                "threshold", VoiceProfileStore.DEFAULT_THRESHOLD)),
        )
        self._resolve_saved_devices()

    # ── broadcast ────────────────────────────────────────────

    async def _broadcast(self, msg: dict):
        data = json.dumps(msg)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass

    def _emit(self, msg: dict):
        """Thread-safe: schedule broadcast on the uvicorn event loop."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)

    def _log(self, msg: str):
        self._emit({"type": "log", "msg": msg})

    # ── pipeline lifecycle ────────────────────────────────────

    def _ensure_pipeline(self) -> Pipeline:
        """Build the pipeline (loads all models) once, then reuse it. Start/Stop
        only toggle listening, so models are NOT reloaded and VRAM isn't re-grabbed."""
        if self._pipeline is None:
            self._pipeline = Pipeline(self.cfg, log=self._log, notify=self._emit)
        return self._pipeline

    def _start_pipeline(self):
        if self._start_lock.locked():
            return
        with self._start_lock:
            self._stop_probe()
            self._state = "loading"
            self._emit({"type": "status", "state": "loading"})
            try:
                pipe = self._ensure_pipeline()        # first call loads models (slow)
            except Exception as exc:
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                self._log(f"Pipeline init failed: {exc}")
                return
            if self._stop_requested:                  # Stop clicked while loading
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                return
            try:
                pipe.start_listening()                # restart-safe
            except Exception as exc:
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                self._log(f"Start failed: {exc}")
                return
            self._state = "running"
            self._emit({"type": "status", "state": "running"})

    def _stop_pipeline(self):
        if self._start_lock.locked():
            self._stop_requested = True     # still loading: stop as soon as that finishes
        with self._start_lock:
            self._stop_requested = False
            if self._pipeline:
                try:
                    self._pipeline.stop_listening()
                except Exception as exc:
                    self._log(f"Stop error: {exc}")
            self._state = "stopped"
        self._emit({"type": "status", "state": "stopped"})
        self._emit({"type": "level", "rms": 0.0})

    def shutdown(self):
        self._level_stop.set()
        self._stop_probe()
        if self._pipeline:
            try:
                self._pipeline.stop_listening()
            except Exception:
                pass

    # ── periodic: level meter + stats ─────────────────────────

    def _start_level_meter(self):
        """One long-lived thread: input level 5x/s, performance stats 1x/s, and
        reports capture/playback failures that happen mid-session."""
        if self._level_thread and self._level_thread.is_alive():
            return

        def _loop():
            reported = None
            tick = 0
            while not self._level_stop.is_set():
                pipe = self._pipeline
                if pipe and pipe._listening:
                    self._emit({"type": "level", "rms": float(pipe.capture.level)})
                    err = pipe.capture.error or pipe.player.error
                    if err and err != reported:
                        reported = err
                        self._log(f"Audio device error: {err}")
                elif self._probe is not None:
                    self._emit({"type": "level", "rms": float(self._probe.level), "probe": True})
                    if time.monotonic() > self._probe_until or self._probe.error:
                        if self._probe.error:
                            self._log(f"Input check failed: {self._probe.error}")
                        self._stop_probe()
                if tick % 5 == 0 and self._clients:
                    try:
                        self._emit(self._stats())
                    except Exception:
                        pass
                tick += 1
                time.sleep(0.2)

        self._level_thread = threading.Thread(target=_loop, daemon=True, name="level-meter")
        self._level_thread.start()

    def _stats(self) -> dict:
        if self._pipeline:
            return self._pipeline.stats()
        return {"type": "stats", "listening": False,
                "system": self._idle_metrics.system(),
                "sync_mode": self.cfg["playback"].get("sync_mode", "asap"),
                "fixed_lag_ms": self.cfg["playback"].get("fixed_lag_ms", 4000)}

    # ── input check / output test (work before models are loaded) ──

    def _start_probe(self, seconds: float = 10.0):
        """Open the selected input for a few seconds just to show its level."""
        if self._pipeline and self._pipeline._listening:
            return                          # the live meter already shows it
        self._stop_probe()
        cap = LoopbackCapture.from_cfg(self.cfg)
        try:
            cap.start()
        except Exception as exc:
            self._log(f"Input check failed: {exc}")
            self._emit({"type": "probe", "active": False})
            return
        self._probe, self._probe_until = cap, time.monotonic() + seconds
        self._emit({"type": "probe", "active": True, "device": cap.device_name})
        self._log(f"Checking input: {cap.device_name} - play something now")

    def _stop_probe(self):
        cap, self._probe = self._probe, None
        if cap is not None:
            cap.stop()
            self._emit({"type": "probe", "active": False})
            self._emit({"type": "level", "rms": 0.0})

    def _test_output(self):
        try:
            if self._pipeline and self._pipeline._listening:
                self._pipeline.player.play_test_tone()
                name = self._pipeline.player.device_name
            else:
                p = Player(self.cfg)
                p.start()
                p.play_test_tone()
                name = p.device_name
                time.sleep(1.0)
                p.stop()
            self._log(f"Played a test tone on: {name}")
        except Exception as exc:
            self._log(f"Output test failed: {exc}")

    # ── speakers ──────────────────────────────────────────────

    def _store(self) -> VoiceProfileStore:
        return self._pipeline.profiles if self._pipeline else self._profiles

    def _rename_speaker(self, msg: dict):
        old = (msg.get("speaker_id") or "").strip()     # current display name
        new_name = (msg.get("name") or "").strip()[:60]
        if not old or not new_name:
            return
        store = self._store()
        if store.has_profile(old):
            if self._pipeline:
                self._pipeline.rename_speaker(old, new_name)
            else:
                store.rename_profile(old, new_name)
        else:
            store.rename_label(old, new_name)           # legacy: a pyannote label
        if self._pipeline:
            # keep the standalone store in sync with what is now on disk
            self._profiles = VoiceProfileStore(self._profiles.dir, self._profiles.threshold)
        self._emit({"type": "speakers", "speakers": store.list_profiles(),
                    "renamed": {"from": old, "to": new_name}})

    def _reset_speakers(self):
        if self._pipeline:
            self._pipeline.reset_speakers()
        self._profiles.clear()
        self._emit({"type": "speakers", "speakers": {}, "reset": True})
        self._log("All speakers forgotten.")

    # ── devices ───────────────────────────────────────────────

    def _device_list(self, fresh: bool = False) -> dict:
        # Cache briefly so rapid/overlapping WS connects don't re-enumerate PortAudio
        # on every connect (enumeration is serialized but still blocks the event loop).
        now = time.time()
        if not fresh and self._dev_cache is not None and (now - self._dev_cache_ts) < 5.0:
            return self._dev_cache
        try:
            self._dev_cache = enumerate_devices()
        except Exception:
            self._dev_cache = {"inputs": [], "outputs": [],
                               "default_input": None, "default_output": None}
        self._dev_cache_ts = now
        return self._dev_cache

    @staticmethod
    def _name_of(devs: list[dict], idx) -> str | None:
        return next((d["name"] for d in devs if d["index"] == idx), None)

    def _resolve_saved_devices(self):
        """Device numbers change when hardware is plugged in or out, so saved
        choices are re-matched by name."""
        a, p = self.cfg["audio"], self.cfg["playback"]
        if not (a.get("input_device_name") or p.get("output_device_name")):
            return
        devs = self._device_list(fresh=True)
        for sect, key, name_key, lst in ((a, "input_device_index", "input_device_name", devs["inputs"]),
                                         (p, "output_device_index", "output_device_name", devs["outputs"])):
            name = sect.get(name_key)
            if not name:
                continue
            if self._name_of(lst, sect.get(key)) == name:
                continue
            match = next((d["index"] for d in lst if d["name"] == name), None)
            sect[key] = match            # None -> fall back to the default device

    def _config_payload(self) -> dict:
        pb = self.cfg["playback"]
        return {
            "source_lang": self.cfg["translate"]["source_lang"],
            "target_lang": self.cfg["translate"]["target_lang"],
            "voice_mode":  self.cfg["tts"]["voice_mode"],
            "delay_ms":    pb.get("delay_ms", 0),
            "sync_mode":   pb.get("sync_mode", "asap"),
            "fixed_lag_ms": pb.get("fixed_lag_ms", 4000),
            "devices":     self._device_list(),
            "input_device_index":  self.cfg["audio"].get("input_device_index"),
            "output_device_index": pb.get("output_device_index"),
        }

    # ── settings update ───────────────────────────────────────

    def _apply_config(self, msg: dict):
        saved: dict = {}
        tr, tts, pb, au = (self.cfg["translate"], self.cfg["tts"],
                           self.cfg["playback"], self.cfg["audio"])
        for key, sect, group in (("target_lang", tr, "translate"), ("source_lang", tr, "translate"),
                                 ("voice_mode", tts, "tts")):
            if key in msg:
                sect[key] = msg[key]
                saved.setdefault(group, {})[key] = msg[key]
        if "target_lang" in msg and self._pipeline and not self._pipeline.mt.whisper_handles():
            # Load the translator now, not on the next line (it takes a few seconds).
            mt = self._pipeline.mt
            if mt.model is None:
                self._log("Loading the translator for " + msg["target_lang"] + "...")
                threading.Thread(target=lambda: (mt._ensure_nllb(), self._log("Translator ready.")),
                                 daemon=True).start()
        if "delay_ms" in msg:
            pb["delay_ms"] = max(0, min(10000, int(msg["delay_ms"])))
            saved.setdefault("playback", {})["delay_ms"] = pb["delay_ms"]
        if "sync_mode" in msg and msg["sync_mode"] in ("asap", "fixed"):
            pb["sync_mode"] = msg["sync_mode"]
            saved.setdefault("playback", {})["sync_mode"] = pb["sync_mode"]
        if "fixed_lag_ms" in msg:
            pb["fixed_lag_ms"] = max(500, min(30000, int(msg["fixed_lag_ms"])))
            saved.setdefault("playback", {})["fixed_lag_ms"] = pb["fixed_lag_ms"]

        # ── audio device selection ──────────────────────────────
        dev_changed = False
        devs = self._device_list()
        if "input_device_index" in msg:
            idx = msg["input_device_index"]
            idx = int(idx) if idx not in (None, "") else None
            au["input_device_index"] = idx
            au["input_device_name"] = self._name_of(devs["inputs"], idx)
            saved.setdefault("audio", {}).update(input_device_index=idx,
                                                 input_device_name=au["input_device_name"])
            if self._pipeline:
                dev_changed |= self._pipeline.capture.device_index != idx
                self._pipeline.capture.device_index = idx
            if self._probe is not None:
                threading.Thread(target=self._start_probe, daemon=True).start()
        if "output_device_index" in msg:
            idx = msg["output_device_index"]
            idx = int(idx) if idx not in (None, "") else None
            pb["output_device_index"] = idx
            pb["output_device_name"] = self._name_of(devs["outputs"], idx)
            saved.setdefault("playback", {}).update(output_device_index=idx,
                                                    output_device_name=pb["output_device_name"])
            if self._pipeline:
                dev_changed |= self._pipeline.player.out_index != idx
                self._pipeline.player.out_index = idx
        if self.persist and saved:
            try:
                config_mod.save_user_settings(saved)
            except Exception as exc:
                self._log(f"Could not save settings: {exc}")
        # Re-open capture/playback streams so a new device takes effect immediately.
        # Done off the event loop: closing/opening audio streams can take seconds.
        if dev_changed and self._pipeline and self._pipeline._listening:
            threading.Thread(target=self._restart_audio, daemon=True).start()

    def _restart_audio(self):
        with self._start_lock:
            pipe = self._pipeline
            if not (pipe and pipe._listening):
                return
            pipe.stop_listening()
            try:
                pipe.start_listening()
                self._log("Switched audio device.")
            except Exception as exc:
                self._state = "stopped"
                self._emit({"type": "status", "state": "stopped"})
                self._log(f"Could not switch device: {exc}")

    # ── FastAPI app ───────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(title="Ominvox")

        @app.on_event("startup")
        async def _capture_loop():
            self._loop = asyncio.get_running_loop()
            self._start_level_meter()

        @app.get("/", response_class=HTMLResponse)
        async def root():
            return HTMLResponse(_HTML)

        @app.get("/api/health")
        async def health():
            return JSONResponse({"app": APP_ID, "state": self._state})

        @app.websocket("/ws")
        async def ws_handler(websocket: WebSocket):
            await websocket.accept()
            self._clients.append(websocket)
            # Send initial state + config + known speakers on connect
            await websocket.send_text(json.dumps({
                "type": "status",
                "state": self._state,
                "config": self._config_payload(),
                "speakers": self._store().list_profiles(),
            }))
            spawn = lambda fn: threading.Thread(target=fn, daemon=True).start()  # noqa: E731
            try:
                while True:
                    msg = json.loads(await websocket.receive_text())
                    t = msg.get("type")
                    if t == "start":
                        spawn(self._start_pipeline)
                    elif t == "stop":
                        spawn(self._stop_pipeline)
                    elif t == "set_config":
                        self._apply_config(msg)
                    elif t == "rename_speaker":
                        self._rename_speaker(msg)
                    elif t == "reset_speakers":
                        self._reset_speakers()
                    elif t == "refresh_devices":
                        devs = await asyncio.to_thread(self._device_list, True)
                        await websocket.send_text(json.dumps({"type": "devices", "devices": devs}))
                    elif t == "test_output":
                        spawn(self._test_output)
                    elif t == "check_input":
                        spawn(self._start_probe)
                    elif t == "stop_check_input":
                        spawn(self._stop_probe)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                try:
                    self._clients.remove(websocket)
                except ValueError:
                    pass

        return app

    # ── entry points ──────────────────────────────────────────

    @staticmethod
    def _free_port(host: str, port: int, tries: int = 20) -> int:
        """Return the first bindable port at or after `port` (avoids the
        winerror 10048 crash when a previous server is still holding 8765)."""
        import socket
        for candidate in range(port, port + tries):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind((host, candidate))
                    return candidate
                except OSError:
                    continue
        raise RuntimeError(
            f"No free port in {port}-{port + tries - 1}. "
            f"Close the other Ominvox UI (or pass --port)."
        )

    @staticmethod
    def running_instance(host: str, port: int) -> str | None:
        """URL of an Ominvox already serving on host:port, if any."""
        import urllib.request
        url = f"http://{host}:{port}"
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as r:
                if json.loads(r.read()).get("app") == APP_ID:
                    return url
        except Exception:
            pass
        return None

    def _require_fastapi(self):
        if FastAPI is None:
            raise RuntimeError(
                "FastAPI + uvicorn are required for the UI.\n"
                "Install: pip install fastapi 'uvicorn[standard]'"
            )

    def serve(self, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
        self._require_fastapi()
        existing = self.running_instance(host, port)
        if existing:
            print(f"Ominvox is already running at {existing} - opening it.")
            if open_browser:
                webbrowser.open(existing)
            return
        port = self._free_port(host, port)
        app = self._build_app()
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
        print(f"Ominvox UI -> http://{host}:{port}  (Ctrl+C to stop)")
        uvicorn.run(app, host=host, port=port, log_level="warning")

    def serve_window(self, host: str = "127.0.0.1", port: int = 8765):
        """Run the server in the background and show the UI in a native window
        (Edge WebView2). Closing the window quits the app. Falls back to the
        browser if pywebview / WebView2 isn't available."""
        self._require_fastapi()
        try:
            import webview
        except Exception:
            print("pywebview not installed - opening in the browser instead.")
            return self.serve(host, port, open_browser=True)

        url = self.running_instance(host, port)
        server = None
        if url is None:
            port = self._free_port(host, port)
            server = uvicorn.Server(uvicorn.Config(self._build_app(), host=host, port=port,
                                                   log_level="warning"))
            threading.Thread(target=server.run, daemon=True, name="ui-server").start()
            deadline = time.time() + 30
            while not server.started and time.time() < deadline:
                time.sleep(0.05)
            url = f"http://{host}:{port}"
        print(f"Ominvox UI -> {url}")

        webview.create_window("Ominvox", url, width=1440, height=900, min_size=(960, 620),
                              background_color="#0d0f1a")
        try:
            webview.start()
        except Exception as exc:
            print(f"Native window failed ({exc}) - opening in the browser instead.")
            webbrowser.open(url)
            if server is not None:
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
        if server is not None:
            self.shutdown()
            server.should_exit = True
