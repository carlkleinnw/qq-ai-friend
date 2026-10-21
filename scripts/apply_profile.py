"""Apply first-run presets using upstream HTTP APIs, without API credentials."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from service import URL

ROOT = Path(__file__).resolve().parents[1]


def merge(target: dict, overrides: dict) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict):
            merge(target.setdefault(key, {}), value)
        else:
            target[key] = value


def checked(response: httpx.Response) -> dict | list:
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload.get("message", "Upstream request failed")))
    return payload.get("data")


def main() -> None:
    marker = ROOT / "runtime" / "profile-applied.local.json"
    if marker.exists():
        print("Profile already applied. User settings were preserved.")
        return
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    with httpx.Client(base_url=URL, trust_env=False, timeout=90) as client:
        login = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["token"]
        presets = json.loads((ROOT / "config/mvp-overrides.json").read_text(encoding="utf-8"))
        for plugin, overrides in presets.items():
            config = checked(client.get(f"/api/v1/plugins/{plugin}/config"))["config"]
            merge(config, overrides)
            checked(client.put(f"/api/v1/plugins/{plugin}/config", json={"config": config}))
        personas = checked(client.get("/api/v1/personas"))
        if not any(row.get("persona_id") == "qq-friend" for row in personas):
            checked(client.post("/api/v1/personas", json={
                "persona_id": "qq-friend",
                "system_prompt": (ROOT / "config/persona.md").read_text(encoding="utf-8"),
                "tools": ["memory_companion_recall", "memory_companion_query", "memory_companion_remember", "future_task", "send_message_to_user"],
                "skills": [],
            }))
        providers = checked(client.get("/api/v1/providers"))
        if isinstance(providers, dict):
            providers = providers.get("providers", [])
        if not any(row.get("id") == "edge_tts" for row in providers):
            checked(client.post("/api/v1/providers", json={
                "id": "edge_tts", "provider": "microsoft", "type": "edge_tts",
                "provider_type": "text_to_speech", "enable": True,
                "edge-tts-voice": "zh-CN-XiaoxiaoNeural", "timeout": 20,
            }))
        marker.write_text(json.dumps({"version": "0.1.0", "applied": True}), encoding="utf-8")
    print("MVP profile applied through the existing AstrBot settings API.")


if __name__ == "__main__":
    main()
