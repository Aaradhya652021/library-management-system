"""Serve the LMS with Waitress and expose it publicly through Cloudflare.

Usage:
    python scripts/run_public.py

This starts:
  1. a production Waitress server on PUBLIC_BIND:PUBLIC_PORT (default
     127.0.0.1:5000), and
  2. a Cloudflare "quick tunnel" that prints a temporary public
     https://<random>.trycloudflare.com URL.

The URL is also written to ``public_url.txt``.  Keep this window open; the URL
stops working when the process stops, and a new URL is generated next time.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Public mode enables Secure session cookies and HTTPS URL generation.
os.environ.setdefault("PUBLIC_MODE", "1")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from waitress import serve  # noqa: E402

from app import app  # noqa: E402

URL_FILE = ROOT / "public_url.txt"
DEFAULT_HOST = os.getenv("PUBLIC_BIND", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("PUBLIC_PORT", "5000"))
THREADS = int(os.getenv("PUBLIC_THREADS", "8"))


def find_cloudflared() -> str | None:
    override = os.getenv("CLOUDFLARED_PATH")
    if override and Path(override).is_file():
        return override
    local = ROOT / "tools" / "cloudflared.exe"
    if local.is_file():
        return str(local)
    return shutil.which("cloudflared")


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


def serve_app(host: str, port: int) -> None:
    try:
        serve(app, host=host, port=port, threads=THREADS, channel_timeout=120)
    except Exception as exc:  # pragma: no cover - only hit on startup failure
        print(f"Waitress failed: {exc}", flush=True)


def main() -> int:
    cloudflared = find_cloudflared()
    if not cloudflared:
        print("cloudflared was not found.")
        print("Download it to tools/cloudflared.exe or set CLOUDFLARED_PATH.")
        print("Windows download:")
        print("  https://github.com/cloudflare/cloudflared/releases/latest/"
              "download/cloudflared-windows-amd64.exe")
        return 1

    if not port_is_free(DEFAULT_HOST, DEFAULT_PORT):
        print(f"Port {DEFAULT_PORT} is already in use on {DEFAULT_HOST}.")
        print("Stop the other server or set PUBLIC_PORT to a free port.")
        return 1

    if os.getenv("SECRET_KEY", "dev-secret-change-me") == "dev-secret-change-me":
        print("Refusing to expose the site with the default SECRET_KEY.")
        print("Set a strong SECRET_KEY in .env first.")
        return 1

    URL_FILE.write_text("starting...\n", encoding="utf-8")
    threading.Thread(
        target=serve_app, args=(DEFAULT_HOST, DEFAULT_PORT), daemon=True
    ).start()
    print(f"Local server: http://{DEFAULT_HOST}:{DEFAULT_PORT}", flush=True)

    # Give Waitress a moment to bind before the tunnel starts retrying.
    time.sleep(1)

    command = [
        cloudflared,
        "tunnel",
        "--url",
        f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
        "--no-autoupdate",
    ]
    print("Starting Cloudflare quick tunnel ...", flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    public_url = None
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip()
            if line:
                print(line, flush=True)
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if match and public_url is None:
                public_url = match.group(0)
                URL_FILE.write_text(public_url + "\n", encoding="utf-8")
                print("\n" + "=" * 68, flush=True)
                print(f"PUBLIC URL: {public_url}", flush=True)
                print("=" * 68 + "\n", flush=True)
    except KeyboardInterrupt:
        print("\nStopping public tunnel ...", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
    return 0 if public_url else 1


if __name__ == "__main__":
    raise SystemExit(main())
