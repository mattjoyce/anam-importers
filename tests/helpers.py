"""Fixtures shared by the tests: a withings database, a real Anam daemon."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent


def withings_db(path: Path, groups: List[Dict[str, Any]]) -> Path:
    """A withings database shaped as the withings plugin 0.4.0 writes it."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE measurements (id INTEGER PRIMARY KEY AUTOINCREMENT, withings_id INTEGER, date TIMESTAMP,
            type INTEGER, value REAL, unit INTEGER, created_at TEXT, UNIQUE (withings_id, type));
        CREATE TABLE measure_groups (withings_id INTEGER PRIMARY KEY, attrib INTEGER, model TEXT,
            deviceid TEXT, timezone TEXT, created INTEGER, modified INTEGER);
    """)
    for g in groups:
        conn.execute("INSERT INTO measure_groups VALUES (?, ?, ?, ?, ?, 0, 0)",
                     (g["id"], g["attrib"], g.get("model"), g.get("deviceid"), g.get("timezone")))
        for typ, value in g["measures"]:
            conn.execute("INSERT INTO measurements (withings_id, date, type, value, unit, created_at) VALUES (?, ?, ?, ?, -3, 'x')",
                         (g["id"], g["date"], typ, value))
    conn.commit()
    conn.close()
    return path


def run_plugin(entry: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    """One ductile invocation: the request on stdin, the response from stdout."""
    out = subprocess.run([sys.executable, str(entry)], input=json.dumps(request), capture_output=True, text=True,
                         check=True, timeout=60)
    return json.loads(out.stdout)


class Daemon:
    """A real `anam daemon` on a new ledger under a temporary directory, with one
    importer. ANAM_BIN names the binary; tests that need it are skipped without it."""

    def __init__(self, source: str, types: List[str]):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.token = secrets.token_hex(32)
        operator = secrets.token_hex(24)
        (d / "token").write_text(operator)
        (d / "importers.yaml").write_text(
            "importers:\n  - source: %s\n    token_sha256: %s\n    types: [%s]\n"
            % (source, hashlib.sha256(self.token.encode()).hexdigest(), ", ".join(types)))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.env = {**{k: v for k, v in os.environ.items() if not k.startswith("ANAM_")},
                    "ANAM_PERSON_ID": "person-a", "ANAM_LEDGER_PATH": str(d / "ledger.db"),
                    "ANAM_DB_PATH": str(d / "tracking.db"), "ANAM_ARTIFACT_DIR": str(d / "artifacts"),
                    "ANAM_LISTEN": f"127.0.0.1:{port}", "ANAM_TOKEN_FILE": str(d / "token"),
                    "ANAM_IMPORTERS_FILE": str(d / "importers.yaml"), "ANAM_ZONE": "UTC"}
        binary = os.environ["ANAM_BIN"]
        subprocess.run([binary, "init"], env=self.env, check=True, capture_output=True, timeout=30)
        self.proc = subprocess.Popen([binary, "daemon"], env=self.env, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(self.url + "/healthz", timeout=1)  # noqa: S310
                return
            except OSError:
                time.sleep(0.1)
        self.close()
        raise RuntimeError("anam daemon did not become ready")

    def close(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=30)
        self.dir.cleanup()
