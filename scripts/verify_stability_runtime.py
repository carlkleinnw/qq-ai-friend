"""Bounded, read-only observation of local dashboard and adapter processes."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time

import httpx
from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()
    if args.seconds < 1 or args.interval < 1:
        raise ValueError("Observation duration and interval must be positive")
    cr = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    state = json.loads((ROOT / "runtime/multibot.local.json").read_text())
    samples = []
    start = time.monotonic()
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=5) as client:
        client.headers["Authorization"] = "Bearer " + checked(client.post("/api/v1/auth/login", json={"username": cr["username"], "password": cr["initial_password"]}))["token"]
        while True:
            sample = {"elapsed_seconds": round(time.monotonic() - start, 1)}
            try:
                platforms = checked(client.get("/api/v1/bots/stats"))["platforms"]
                statuses = {item["id"]: item["status"] for item in platforms}
                sample.update(dashboard_available=True,
                              first_adapter_running=statuses.get(state["first_bot_id"]) == "running",
                              second_adapter_running=statuses.get(state["second_bot_id"]) == "running")
            except Exception as error:
                sample.update(dashboard_available=False, error_type=type(error).__name__)
            samples.append(sample)
            remaining = args.seconds - (time.monotonic() - start)
            if remaining <= 0:
                break
            time.sleep(min(args.interval, remaining))
    healthy = all(s.get("dashboard_available") and s.get("first_adapter_running") and s.get("second_adapter_running") for s in samples)
    report = {"checked_at": datetime.now().astimezone().isoformat(), "duration_seconds": round(time.monotonic() - start, 1),
              "all_samples_healthy": healthy, "samples": samples,
              "scope": "Local API and native adapter process state; not an end-to-end phone delivery or 24-hour uptime guarantee."}
    (ROOT / "verification/runtime-observation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Observation samples:", len(samples), "; all healthy:", healthy)
    if not healthy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
