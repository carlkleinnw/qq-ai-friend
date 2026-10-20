"""Prepare a local AstrBot workspace; never overwrite user settings."""
from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "runtime" / "app"


def main() -> None:
    APP.mkdir(parents=True, exist_ok=True)
    (APP / ".astrbot").touch()
    for relative in ("data/config", "data/plugins", "data/temp", "logs"):
        (APP / relative).mkdir(parents=True, exist_ok=True)
    os.environ["ASTRBOT_ROOT"] = str(APP)
    os.environ["TEMP"] = str(APP / "data" / "temp")
    os.environ["TMP"] = str(APP / "data" / "temp")
    config_path = APP / "data" / "cmd_config.json"
    if not config_path.exists():
        password = secrets.token_urlsafe(18)
        os.environ["ASTRBOT_DASHBOARD_INITIAL_PASSWORD"] = password
        from astrbot.core.config.astrbot_config import AstrBotConfig

        config = AstrBotConfig(config_path=str(config_path))
        config["dashboard"]["host"] = "127.0.0.1"
        config["dashboard"]["port"] = 6185
        config["disable_metrics"] = True
        config["timezone"] = "Asia/Shanghai"
        config["log_file_enable"] = True
        config["provider_tts_settings"]["enable"] = False
        config["provider_tts_settings"]["provider_id"] = "edge_tts"
        config["provider_settings"]["show_tool_use_status"] = False
        config["provider_settings"]["show_tool_call_result"] = False
        config["platform_settings"]["enable_id_white_list"] = False
        config["platform_settings"]["reply_with_mention"] = False
        config["platform_settings"]["reply_with_quote"] = False
        # Credentials remain empty. The user enters them in the upstream WebUI.
        config["provider_sources"] = [{
            "id": "deepseek", "provider": "deepseek",
            "type": "openai_chat_completion", "provider_type": "chat_completion",
            "enable": True, "key": [], "api_base": "https://api.deepseek.com/v1",
            "timeout": 60, "proxy": "", "custom_headers": {},
        }]
        config["provider"] = [{
            "id": "deepseek/deepseek-flash", "provider_source_id": "deepseek",
            "model": "deepseek-flash", "enable": False,
        }]
        runner = config["agent_runner"]["config"]
        runner["model"]["provider_id"] = "deepseek/deepseek-flash"
        runner["model"]["request_max_retries"] = 2
        runner["persona"]["persona_id"] = "qq-friend"
        runner["compression"]["max_turns"] = 40
        runner["misc"]["max_steps"] = 8
        config.save_config()
        credentials = {"username": "astrbot", "initial_password": password}
        (ROOT / "runtime" / "dashboard-login.local.json").write_text(
            json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ROOT / "runtime" / "本机登录说明.txt").write_text(
            "面板：http://127.0.0.1:6185\n账号：astrbot\n初始密码："
            + password + "\n首次登录后请按面板提示设置自己的密码。\n"
            + "DeepSeek API Key 请在模型提供商设置中填写。\n",
            encoding="utf-8",
        )
        os.environ.pop("ASTRBOT_DASHBOARD_INITIAL_PASSWORD", None)
    plugins = APP / "data" / "plugins"
    for source, target in (
        ("private_companion", "astrbot_plugin_private_companion"),
        ("memory_companion", "astrbot_plugin_memory_companion"),
    ):
        destination = plugins / target
        if not destination.exists():
            shutil.copytree(
                ROOT / "runtime" / "vendor" / source, destination,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
            )
    print("Local workspace ready. User settings were preserved.")


if __name__ == "__main__":
    main()
