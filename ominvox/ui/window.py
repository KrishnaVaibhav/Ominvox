"""Show the interface in its own native window (Edge WebView2 via pywebview).

The server runs in a background thread; closing the window quits the app.
Falls back to the browser if pywebview / WebView2 isn't available.
"""
from __future__ import annotations
import threading
import time
import webbrowser

import uvicorn

from .server import UIServer


def run_window(srv: UIServer, host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        import webview
    except Exception:
        print("pywebview not installed - opening in the browser instead.")
        return srv.serve(host, port, open_browser=True)

    url = srv.running_instance(host, port)        # never load the models twice
    server = None
    if url is None:
        port = srv._free_port(host, port)
        server = uvicorn.Server(uvicorn.Config(srv._build_app(), host=host, port=port,
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
        srv.shutdown()
        server.should_exit = True
