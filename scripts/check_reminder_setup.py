"""Read-only audit of the existing reminder tools and bot configuration."""
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    state = json.loads((ROOT / "runtime/multibot.local.json").read_text(encoding="utf-8"))
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "personas": {}}
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=20) as client:
        login = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["token"]
        for persona_id, config_id in state["profiles"].items():
            persona = checked(client.get("/api/v1/personas/by-id", params={"persona_id": persona_id}))
            config = checked(client.get("/api/v1/config-profiles/" + config_id))["config"]
            tools = persona.get("tools")
            all_tools = tools is None
            allowed = set(tools or [])
            report["personas"][persona_id] = {
                "future_task_allowed": all_tools or "future_task" in allowed,
                "send_message_allowed": all_tools or "send_message_to_user" in allowed,
                "cron_tools_enabled": bool(config.get("provider_settings", {}).get("proactive_capability", {}).get("add_cron_tools", True)),
                "china_timezone": config.get("timezone") == "Asia/Shanghai",
            }
        jobs = checked(client.get("/api/v1/cron/jobs"))
        report["task_counts"] = {
            "total": len(jobs),
            "enabled": sum(bool(job["enabled"]) for job in jobs),
            "one_time": sum(bool(job["run_once"]) for job in jobs),
        }
    report["ready"] = all(all(row.values()) for row in report["personas"].values())
    (ROOT / "verification/reminder-readiness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    if not report["ready"]:
        raise SystemExit("Reminder setup needs attention; user settings were not changed.")


if __name__ == "__main__":
    main()
