"""Enable the existing TTS adapter for 大肥鱼; preserve other bots and user settings."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import httpx

from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]
STYLE_HEADER = "## 大肥鱼聊天与朗读风格"


def speaking_prompt(original: str, style: str) -> str:
    style = style.strip()
    if STYLE_HEADER in original:
        if original.rstrip().endswith(style):
            return original
        raise ValueError("Existing speaking style was edited; preserve it and edit through the persona page")
    return original.rstrip() + "\n\n" + style + "\n"


def voice_profile(original: dict, provider_id: str, *, enabled=True) -> dict:
    result = deepcopy(original)
    settings = result.setdefault("provider_tts_settings", {})
    settings["enable"] = enabled
    if enabled:
        settings.update(provider_id=provider_id, dual_output=True, trigger_probability=1.0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disable", action="store_true", help="Return 大肥鱼 to text replies")
    args = parser.parse_args()
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    profiles = json.loads((ROOT / "runtime/multibot.local.json").read_text())["profiles"]
    if profiles["qq-friend"] == profiles["gpt-lord"]:
        raise ValueError("Bots share a profile; independent configuration is required")
    preset = json.loads((ROOT / "config/dafeiyu-voice.json").read_text(encoding="utf-8"))
    style = (ROOT / "config/dafeiyu-speaking-style.md").read_text(encoding="utf-8")
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=60) as client:
        token = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))["token"]
        client.headers["Authorization"] = "Bearer " + token
        target_url = "/api/v1/config-profiles/" + profiles["qq-friend"]
        other_url = "/api/v1/config-profiles/" + profiles["gpt-lord"]
        target = checked(client.get(target_url))["config"]
        other = checked(client.get(other_url))["config"]
        persona_url = "/api/v1/personas/by-id"
        persona = checked(client.get(persona_url, params={"persona_id": "qq-friend"}))
        other_persona = checked(client.get(persona_url, params={"persona_id": "gpt-lord"}))
        prompt = speaking_prompt(persona["system_prompt"], style) if not args.disable else persona["system_prompt"]
        provider_rows = checked(client.get("/api/v1/providers"))
        if isinstance(provider_rows, dict):
            provider_rows = provider_rows.get("providers", [])
        existing = next((r for r in provider_rows if r.get("id") == preset["id"]), None)
        if existing is not None and not args.disable:
            full = checked(client.get("/api/v1/providers/by-id", params={"provider_id": preset["id"]}))
            installed = full.get("provider", full)
            if any(installed.get(k) != v for k, v in preset.items()):
                raise ValueError("Voice provider was edited; preserve it and edit through provider settings")
        backup = ROOT / "runtime/backups/before-dafeiyu-voice.json"
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(json.dumps({"target_profile": target, "persona": persona}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.disable and existing is None:
            checked(client.post("/api/v1/providers", json=preset))
        if prompt != persona["system_prompt"]:
            payload = {k: v for k, v in persona.items() if k not in {"created_at", "updated_at"}}
            payload["system_prompt"] = prompt
            checked(client.put(persona_url, params={"persona_id": "qq-friend"}, json=payload))
        updated = voice_profile(target, preset["id"], enabled=not args.disable)
        if updated != target:
            checked(client.put(target_url, json=updated))
        assert checked(client.get(target_url))["config"] == updated
        assert checked(client.get(other_url))["config"] == other, "Other bot profile changed"
        assert checked(client.get(persona_url, params={"persona_id": "gpt-lord"})) == other_persona, "Other bot persona changed"
    print(json.dumps({"dafeiyu_voice_enabled": not args.disable, "gpt_profile_unchanged": True,
                      "gpt_persona_unchanged": True, "voice_provider": preset["id"]}))


if __name__ == "__main__":
    main()
