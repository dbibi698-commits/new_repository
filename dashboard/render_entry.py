"""dashboard/render_entry.py — Mark-LVII dashboard on Render.

Serves the SAME FastAPI app the desktop build serves locally
(`DashboardServer.app` from `dashboard/server.py`), on Render's public URL.

What this is NOT: the desktop HUD (PyQt window + Gemini Live voice session)
CANNOT run on Render — there is no screen, no microphone and no Qt there.
Only the dashboard / API is hosted here. The PC stays the brain; Render is
just a public front door to its dashboard.

Deliberately does NOT call `DashboardServer.serve()`: that does LAN-only
things — a firewall check, self-signed certificate generation and the
8000 -> 8001 HTTP redirector — which must never run on Render. Render
terminates TLS itself, so this serves plain HTTP on 0.0.0.0:$PORT.

`DashboardServer.__init__` is safe on a headless Linux box (checked):
`_local_ip()` is fully try/except-guarded and falls back to 127.0.0.1,
`_read()` only reads the bundled dashboard/static/*.html files, the uploads
folder falls back to `<repo>/uploads`, and the `asyncio.Queue`s need no
running loop at construction time.
"""

import os
import sys
from pathlib import Path

# Make the repo root importable no matter how this file is launched, so
# `from dashboard.server import ...` always resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.server import DashboardServer  # noqa: E402

server = DashboardServer()
app = server.app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    print(f"[Render] Mark-LVII dashboard on 0.0.0.0:{port} (plain HTTP, "
          "TLS is terminated by Render)")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
