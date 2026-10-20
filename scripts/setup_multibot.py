"""Configure multiple bot personas using AstrBot's existing profile/router APIs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import httpx

from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "runtime/multibot.local.json"
PLUGIN = "/api/v1/plugins/astrbot_plugin_private_companion/config"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-bot", help="Original AstrBot bot ID when several connections exist")
    parser.add_argument("--bind-second", help="Existing AstrBot bot ID to bind to GPT大人")
    args = parser.parse_args()
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"profiles": {}}
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=90) as client:
        login = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["token"]
        default = checked(client.get("/api/v1/config-profiles/default"))["config"]
        original = checked(client.get("/api/v1/personas/by-id", params={"persona_id": "qq-friend"}))
        plugin = checked(client.get(PLUGIN))["config"]
        routes = checked(client.get("/api/v1/config-routes"))["routing"]
        backup = ROOT / "runtime/backups/before-multibot-api.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_text(json.dumps({"plugin": plugin, "routes": routes}, ensure_ascii=False, indent=2), encoding="utf-8")
        personas = checked(client.get("/api/v1/personas"))
        if not any(p["persona_id"] == "gpt-lord" for p in personas):
            checked(client.post("/api/v1/personas", json={
                "persona_id": "gpt-lord",
                "system_prompt": "你在 QQ 中的名字是“GPT大人”。这是用户可编辑的独立人格；性格、语言风格和角色背景由用户设计。未设置时不编造背景或共同经历。名字不代表实际模型供应商；询问身份时如实说明是 AI。只有工具确认成功后，才确认记忆已保存、提醒已建立或消息已投递。",
                "tools": original.get("tools", []), "skills": original.get("skills", []),
            }))
        first = state.get("first_bot_id") or args.first_bot
        existing = [p["id"] for p in default["platform"] if p.get("type") == "qq_official"]
        if not first:
            if len(existing) != 1:
                raise RuntimeError("Expected exactly one original QQ bot; inspect before binding.")
            first = existing[0]
            state["first_bot_id"] = first
        if first not in existing:
            raise RuntimeError("Original bot does not exist; no binding applied.")
        state["first_bot_id"] = first
        if args.bind_second and (args.bind_second == first or args.bind_second not in existing):
            raise RuntimeError("Second bot must exist and differ from the original bot.")
        if args.bind_second:
            bots = {p["id"]: p for p in default["platform"]}
            if bots[first].get("appid") == bots[args.bind_second].get("appid"):
                raise RuntimeError("These connections use the same QQ AppID; they are not separate bots.")
        for persona, name in (("qq-friend", "大肥鱼独立配置"), ("gpt-lord", "GPT大人独立配置")):
            if persona not in state["profiles"]:
                config = copy.deepcopy(default)
                # Upstream excludes global connection settings from secondary profiles.
                for key in ("platform", "provider", "provider_sources", "dashboard"):
                    config.pop(key, None)
                config["agent_runner"]["config"]["persona"]["persona_id"] = persona
                created = checked(client.post("/api/v1/config-profiles", json={"name": name, "config": config}))
                state["profiles"][persona] = created["conf_id"]
                STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        for bot, persona in ((first, "qq-friend"), (args.bind_second, "gpt-lord")):
            if not bot:
                continue
            pattern = bot + "::"
            desired = state["profiles"][persona]
            if routes.get(pattern) not in (None, desired):
                raise RuntimeError("A bot already has a different profile route; user configuration preserved.")
            # Put specific bot routes first: upstream routing uses first-match order.
            routes = {pattern: desired, **{k: v for k, v in routes.items() if k != pattern}}
        checked(client.put("/api/v1/config-routes", json={"routing": routes}))
        plugin["basic_config"].update({
            "plugin_specific_persona_id": "qq-friend",
            "enable_multi_persona_mode": True,
            "multi_persona_ids": list(dict.fromkeys([*plugin["basic_config"].get("multi_persona_ids", []), "qq-friend", "gpt-lord"])),
        })
        checked(client.put(PLUGIN, json={"config": plugin}))
        extension = "/api/plug/astrbot_plugin_private_companion/page/persona"
        config_state = client.get(extension + "/config-state", params={"persona_id": "gpt-lord"})
        if not config_state.json().get("success"):
            created = client.post(extension + "/config/create", json={
                "persona_id": "gpt-lord", "bot_name": "GPT大人", "mode": "copy", "source_persona_id": "qq-friend",
            })
            created.raise_for_status()
            if not created.json().get("success"):
                raise RuntimeError("Upstream companion persona configuration was not created.")
        if args.bind_second:
            state["second_bot_id"] = args.bind_second
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        assert checked(client.get("/api/v1/personas/by-id", params={"persona_id": "qq-friend"})) == original, "Original persona changed unexpectedly"
    print("Independent profiles and upstream multi-persona mode configured. Original persona preserved.")
    print("Second QQ bot bound:" + str(bool(state.get("second_bot_id"))))


if __name__ == "__main__":
    main()
