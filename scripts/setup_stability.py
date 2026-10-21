"""Configure existing native retry/error settings and install the small message-ID guard."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import httpx
from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]
ERROR_MESSAGE = "这次没有收到有效回复，可能是连接或模型服务暂时不可用。请稍后重发；若持续失败，请在本机检查模型设置。"


def main():
    marker = ROOT / "runtime/stability-applied.local.json"
    if marker.exists():
        print("稳定性配置已应用；保留你后续编辑的模型、提示词和插件设置。")
        return
    state = json.loads((ROOT / "runtime/multibot.local.json").read_text())
    cr = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=60) as c:
        c.headers["Authorization"] = "Bearer " + checked(c.post("/api/v1/auth/login", json={"username": cr["username"], "password": cr["initial_password"]}))["token"]
        url = "/api/v1/config-profiles/" + state["profiles"]["qq-friend"]
        other_url = "/api/v1/config-profiles/" + state["profiles"]["gpt-lord"]
        cfg = checked(c.get(url))["config"]
        other = checked(c.get(other_url))["config"]
        persona = checked(c.get("/api/v1/personas/by-id", params={"persona_id": "qq-friend"}))
        backup = ROOT / "runtime/backups/before-stability.json"
        if not backup.exists():
            backup.write_text(json.dumps({"config": cfg, "persona": persona}, ensure_ascii=False, indent=2), encoding="utf-8")
        stable_id = "deepseek_dafeiyu_stable"
        source_id = cfg["agent_runner"]["config"]["model"]["provider_id"]
        provider = checked(c.get("/api/v1/providers/by-id", params={"provider_id": source_id}))["provider"]
        providers = checked(c.get("/api/v1/providers"))
        if isinstance(providers, dict):
            providers = providers.get("providers", [])
        if not any(p.get("id") == stable_id for p in providers):
            stable = {**provider, "id": stable_id, "timeout": 25}
            if "key" in stable:
                raise ValueError("Expected a shared provider-source reference, not a copy of API keys")
            checked(c.post("/api/v1/providers", json=stable))
        merged = checked(c.get("/api/v1/providers/by-id", params={"provider_id": stable_id, "merged": True}))["provider"]
        if merged.get("timeout") != 25:
            raise ValueError("Stable model was edited; preserve it and review settings")
        updated = deepcopy(cfg)
        updated["agent_runner"]["config"]["model"].update(provider_id=stable_id, request_max_retries=2)
        if updated != cfg:
            checked(c.put(url, json=updated))
        if not persona.get("custom_error_message"):
            payload = {k: v for k, v in persona.items() if k not in {"created_at", "updated_at"}}
            payload["custom_error_message"] = ERROR_MESSAGE
            checked(c.put("/api/v1/personas/by-id", params={"persona_id": "qq-friend"}, json=payload))
        assert checked(c.get(other_url))["config"] == other
    source = ROOT / "plugins/astrbot_plugin_reliability"
    target = ROOT / "runtime/app/data/plugins/astrbot_plugin_reliability"
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            dest = target / path.relative_to(source)
            if dest.exists() and dest.read_bytes() != path.read_bytes():
                raise ValueError("Installed guard has other changes; refusing to overwrite")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    config_path = ROOT / "runtime/app/data/config/astrbot_plugin_reliability_config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({"bot_ids": [state["first_bot_id"]]}, indent=2), encoding="utf-8")
    marker.write_text(json.dumps({"applied": True, "version": "0.1.1"}), encoding="utf-8")
    print("大肥鱼：原生模型重试最多2次，每次网络超时25秒，失败提示已设置；GPT配置保留。消息防重将在服务重启后启用。")


if __name__ == "__main__":
    main()
