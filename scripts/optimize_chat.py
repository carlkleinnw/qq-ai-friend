"""Tune existing AstrBot settings without replacing user personas or credentials."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def persona_digest(personas: list) -> str:
    return hashlib.sha256(json.dumps(personas, sort_keys=True).encode()).hexdigest()


def main() -> None:
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    private = ROOT / "verification/private"
    private.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=90) as client:
        login = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["token"]
        personas_before = checked(client.get("/api/v1/personas"))
        endpoint = "/api/v1/plugins/astrbot_plugin_private_companion/config"
        plugin = checked(client.get(endpoint))["config"]
        backup = private / "before-chat-optimization.json"
        if not backup.exists():
            backup.write_text(json.dumps(plugin, ensure_ascii=False, indent=2), encoding="utf-8")
        changes = {
            "basic_config": {} if plugin["basic_config"].get("enable_multi_persona_mode") else {"plugin_specific_persona_id": ""},
            "humanized_state_config": {
                "inject_passive_states": False,
                "enable_rest_reply_simulation": False,
                "enable_busy_reply_gate": False,
            },
        }
        changed = any(plugin[group].get(key) != value for group, values in changes.items() for key, value in values.items())
        for group, values in changes.items():
            plugin[group].update(values)
        if changed:
            checked(client.put(endpoint, json={"config": plugin}))
        saved = checked(client.get(endpoint))["config"]
        assert all(saved[group][key] == value for group, values in changes.items() for key, value in values.items())
        assert persona_digest(personas_before) == persona_digest(checked(client.get("/api/v1/personas"))), "Persona changed unexpectedly"
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "settings_saved": True,
        "user_personas_unchanged": True,
        "plugin_follows_astrbot_persona": True,
        "simulated_state_injection_disabled": True,
        "rest_and_busy_reply_gates_disabled": True,
    }
    (ROOT / "verification/chat-optimization.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
