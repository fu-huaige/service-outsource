"""Replay the three documented cases against an isolated real backend."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    backend, out = args.backend.resolve(), args.out.resolve()
    if not (backend / "scripts/serve_e2e.py").is_file():
        parser.error("backend must contain scripts/serve_e2e.py")
    if out.exists():
        parser.error("out must be a new directory")
    out.mkdir(parents=True)
    # Keep scratch state for investigation; never reset a user's existing directory.
    state = Path(tempfile.mkdtemp(prefix="indusopt-skill-verification-"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}/api/v1"
    env = os.environ.copy()
    env.update(INDUSOPT_LLM_PROVIDER="none", INDUSOPT_BACKGROUND_OPTIMIZATION="false",
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = (out / "backend.log").open("w", encoding="utf-8")
    server = None
    record = {"python": platform.python_version(), "platform": platform.platform(),
              "verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "backend_mode": "isolated SQLite, create_all; no migrations",
              "mock_backend": False, "cases": {}, "status": "failed"}
    script = ROOT / "indusopt-data-selection/scripts/indusopt_skill.py"
    record["skill_script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
    source_digest = hashlib.sha256()
    for folder in (backend / "app", backend / "algorithms"):
        for path in sorted(folder.rglob("*.py")):
            source_digest.update(path.relative_to(backend).as_posix().encode("utf-8"))
            source_digest.update(path.read_bytes())
    record["backend_app_algorithms_sha256"] = source_digest.hexdigest()
    record["dependencies"] = {name: importlib.metadata.version(name) for name in
                              ("numpy", "fastapi", "sqlalchemy", "optuna", "pydantic", "aiosqlite")}
    try:
        server = subprocess.Popen(
            [sys.executable, "-B", str(backend / "scripts/serve_e2e.py"),
             "--port", str(port), "--state-dir", str(state), "--keep"],
            cwd=state, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError("Backend exited; see backend.log")
            try:
                with urlopen(base + "/health/live", timeout=1) as response:
                    if json.load(response).get("success") is True:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Backend readiness timed out")
        for name, scenario, confirm in [("pending", "S2", False), ("s2", "S2", True), ("s6", "S6", True)]:
            command = [sys.executable, "-B", str(script), "--base-url", base, "analyze",
                       "--csv", str(ROOT / f"示例与实测/{scenario}输入/input.csv"),
                       "--time-column", "timestamp", "--inputs", "u1,u2,u3",
                       "--output-column", "y", "--delays", "1,1,1",
                       "--data-kind", "synthetic", "--artifact-root", str(state / "artifacts"),
                       "--out", str(out / name)]
            if confirm:
                command.append("--confirm-lags")
            result = subprocess.run(command, cwd=state, env=env, capture_output=True,
                                    encoding="utf-8", errors="replace", timeout=180, creationflags=flags, check=False)
            (out / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            case = out / name
            if name == "pending":
                assert result.returncode == 0
                assert load(case / "pending-confirmation.json")["status"] == "waiting_confirmation"
                requests = load(case / "requests.json")
                assert not any("/apply" in r["path"] or "/modeling/" in r["path"] for r in requests)
                assert not (case / "manifest.json").exists()
                record["cases"][name] = "waiting_confirmation; no apply or modeling request"
            elif name == "s2":
                assert result.returncode == 0, "S2 failed; see s2.log"
                assert load(case / "manifest.json")["status"] == "succeeded"
                assert (case / "report.md").is_file() and (case / "selected.csv").is_file()
                assert not (case / "failure.json").exists()
                record["cases"][name] = {"status": "succeeded", "comparison": load(case / "comparison.json")}
            else:
                assert result.returncode == 1, "S6 result differs from documented failure case"
                assert load(case / "07_selected_model.error.txt")["error"]["code"] == "DESIGN_MATRIX_RANK_DEFICIENT"
                assert not (case / "manifest.json").exists() and not (case / "selected.csv").exists()
                record["cases"][name] = "expected rank-deficient stop; no successful export"
            print(f"{name}: verified", flush=True)
        record["status"] = "passed"
    except (OSError, ValueError, KeyError, AssertionError, RuntimeError, subprocess.SubprocessError) as exc:
        record["error"] = str(exc)
        print(f"Verification failed: {exc}", file=sys.stderr)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        log.close()
        (out / "verification.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Scratch state retained at: {state}")
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
