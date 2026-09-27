#!/usr/bin/env python3
"""Serve the model viewer and store human names for every animation clip.

This is `python -m http.server` from the repo root, so `/viewer/` and every GLB under
`/models/` keep working exactly as before, plus two endpoints the viewer's alias panel
talks to:

    GET  /api/aliases   -> models/current/animation_aliases.json (seeded if missing)
    POST /api/aliases   -> body is the whole document; validated, then written atomically

The document looks like this:

    {"version": 1,
     "models": {
       "jc_0831_Levant": {
         "jc0831_anim05_40f": {"name": "walk", "info": "slow, loops cleanly",
                               "all": false, "updated": "2026-09-20T12:00:00Z"}}}}

`name` is free text whose FIRST WORD is the role keyword (idle, walk, run, attack, hit,
die, victory, talk, sit, sleep, lie, special, other). `all` means the alias is meant for
the same clip slot on every model that has the same bone count. Entries with no name and
no info are dropped rather than stored.

Usage:
    python tools/anim_labeler.py --open
    python tools/anim_labeler.py --port 8791
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_PATH = ROOT / "models" / "current" / "animation_aliases.json"
SEED = {"version": 1, "models": {}}
MAX_BODY = 16 * 1024 * 1024

_write_lock = threading.Lock()


# ----------------------------------------------------------------------------- storage
def read_aliases() -> dict:
    """Return the alias document, creating the seed file the first time."""
    if not ALIAS_PATH.exists():
        ALIAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_aliases(SEED)
        return json.loads(json.dumps(SEED))
    with ALIAS_PATH.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError("animation_aliases.json is not a JSON object")
    doc.setdefault("version", 1)
    doc.setdefault("models", {})
    return doc


def write_aliases(doc: dict) -> None:
    """Write the document atomically: temp file in the same directory, then os.replace."""
    ALIAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(ALIAS_PATH.parent), prefix=".aliases-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ALIAS_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clean(doc: dict) -> tuple[dict, int, int]:
    """Validate and normalise a posted document. Returns (doc, model count, clip count)."""
    if not isinstance(doc, dict):
        raise ValueError("body must be a JSON object")
    if "version" not in doc or "models" not in doc:
        raise ValueError("body needs both a 'version' and a 'models' key")
    version = doc.get("version")
    if not isinstance(version, int):
        raise ValueError("'version' must be an integer")
    models = doc.get("models")
    if not isinstance(models, dict):
        raise ValueError("'models' must be an object keyed by model stem")

    out: dict[str, dict] = {}
    clips = 0
    for stem, entries in models.items():
        if not isinstance(entries, dict):
            raise ValueError(f"models[{stem!r}] must be an object keyed by clip name")
        keep: dict[str, dict] = {}
        for clip, entry in entries.items():
            if not isinstance(entry, dict):
                raise ValueError(f"models[{stem!r}][{clip!r}] must be an object")
            name = str(entry.get("name", "") or "").strip()
            info = str(entry.get("info", "") or "").strip()
            if not name and not info:
                continue  # empty on both sides means "no alias", so do not store it
            item = {"name": name, "info": info, "all": bool(entry.get("all", False))}
            updated = entry.get("updated")
            if isinstance(updated, str) and updated:
                item["updated"] = updated
            keep[clip] = item
            clips += 1
        if keep:
            out[stem] = keep
    return {"version": version, "models": out}, len(out), clips


# ------------------------------------------------------------------------------ server
class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files from the repo root, plus /api/aliases."""

    server_version = "JadeCocoonAnimLabeler/1.0"
    protocol_version = "HTTP/1.1"   # keep-alive: the viewer pulls a lot of GLBs

    def _no_store(self) -> bool:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        return path.startswith("/api/") or path.endswith("models.json")

    def end_headers(self) -> None:
        if self._no_store():
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- GET ------------------------------------------------------------------------
    def do_GET(self):  # noqa: N802  (stdlib naming)
        path = self.path.split("?", 1)[0]
        if path == "/api/aliases":
            try:
                doc = read_aliases()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self._send_json(doc)
            return
        if path.startswith("/api/"):
            self._send_json({"ok": False, "error": "no such endpoint"}, 404)
            return
        super().do_GET()

    # -- POST -----------------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/aliases":
            self._send_json({"ok": False, "error": "no such endpoint"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json({"ok": False, "error": "bad Content-Length"}, 400)
            return
        if length <= 0:
            self._send_json({"ok": False, "error": "empty body"}, 400)
            return
        if length > MAX_BODY:
            self._send_json({"ok": False, "error": "body too large"}, 413)
            return
        raw = self.rfile.read(length)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "error": f"bad JSON: {exc}"}, 400)
            return
        try:
            doc, n_models, n_clips = clean(doc)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        try:
            with _write_lock:
                write_aliases(doc)
        except OSError as exc:
            self._send_json({"ok": False, "error": f"could not write: {exc}"}, 500)
            return
        self._send_json({"ok": True, "models": n_models, "clips": n_clips})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Viewer + animation alias labeler server.")
    ap.add_argument("--port", type=int, default=8777, help="port to listen on (default 8777)")
    ap.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1)")
    ap.add_argument("--open", action="store_true", dest="open_browser",
                    help="open the viewer in a browser once the server is up")
    args = ap.parse_args(argv)

    try:
        doc = read_aliases()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"! {ALIAS_PATH} is unreadable: {exc}", file=sys.stderr)
        return 2
    clips = sum(len(v) for v in doc.get("models", {}).values())

    handler = functools.partial(Handler, directory=str(ROOT))
    try:
        httpd = Server((args.host, args.port), handler)
    except OSError as exc:
        print(f"! cannot bind {args.host}:{args.port} ({exc}). "
              f"Another server is probably already on that port; try --port 8778.",
              file=sys.stderr)
        return 2

    url = f"http://localhost:{args.port}/viewer/"
    print(f"Jade Cocoon animation labeler")
    print(f"  serving  {ROOT}")
    print(f"  viewer   {url}")
    print(f"  aliases  {ALIAS_PATH}  ({clips} clip{'' if clips == 1 else 's'} named)")
    print("  ctrl-c to stop")
    if args.open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, ConnectionResetError, socket.error):
        sys.exit(1)
