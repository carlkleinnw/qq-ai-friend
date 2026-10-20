"""Start and stop the packaged AstrBot process in its Conda environment."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
APP = RUNTIME / "app"
PYTHON = RUNTIME / "conda" / "python.exe"
STATE = RUNTIME / "service.local.json"
URL = "http://127.0.0.1:6185"


def managed_process() -> psutil.Process | None:
    if not STATE.exists():
        return None
    record = json.loads(STATE.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created"]) > 0.01:
            raise RuntimeError("Process identity changed; no process was stopped.")
        if Path(process.exe()).resolve() != PYTHON.resolve():
            raise RuntimeError("Process executable differs; no process was stopped.")
        if "astrbot.cli" not in process.cmdline():
            raise RuntimeError("Process command differs; no process was stopped.")
        return process
    except psutil.NoSuchProcess:
        return None


def ready() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/v1/auth/setup-status", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def start(open_browser: bool = True) -> None:
    process = managed_process()
    if not process:
        if ready():
            raise RuntimeError("Port 6185 belongs to another instance. No process was stopped.")
        environment = os.environ.copy()
        environment.update({
            "ASTRBOT_ROOT": str(APP), "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8", "TEMP": str(APP / "data" / "temp"),
            "TMP": str(APP / "data" / "temp"),
            "UV_CACHE_DIR": "E:/DeveloperCache/uv",
            "PIP_CACHE_DIR": "E:/DeveloperCache/pip",
            "PATH": str(RUNTIME / "tools") + os.pathsep + str(PYTHON.parent)
            + os.pathsep + str(PYTHON.parent / "Library" / "bin")
            + os.pathsep + environment.get("PATH", ""),
        })
        with (RUNTIME / "server.stdout.log").open("ab") as stdout, (RUNTIME / "server.stderr.log").open("ab") as stderr:
            child = subprocess.Popen(
                [str(PYTHON), "-m", "astrbot.cli", "run"], cwd=APP, env=environment,
                stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        process = psutil.Process(child.pid)
        STATE.write_text(json.dumps({"pid": process.pid, "created": process.create_time()}), encoding="utf-8")
    for _ in range(90):
        if ready():
            print("AI friend is ready: " + URL)
            if open_browser:
                webbrowser.open(URL)
            return
        if not managed_process():
            raise RuntimeError("Application exited. See runtime/server.stderr.log.")
        time.sleep(0.5)
    raise RuntimeError("Startup timed out. See runtime/server.stderr.log.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"], nargs="?", default="start")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.action == "start":
        start(not args.no_browser)
    elif args.action == "stop":
        process = managed_process()
        if process:
            process.terminate()
            process.wait(timeout=15)
            STATE.unlink(missing_ok=True)
        print("AI friend stopped. Saved settings and data are preserved.")
    else:
        print("Running: " + URL if managed_process() and ready() else "Not running")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
