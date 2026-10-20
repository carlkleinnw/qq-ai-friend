"""Check real local APIs and browser settings without exposing credentials."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:6185"


def main():
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    checks = report["checks"]
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    with httpx.Client(base_url=URL, trust_env=False, timeout=20) as client:
        checks["unauthenticated_settings_denied"] = client.get("/api/v1/providers").status_code == 401
        response = client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        })
        response.raise_for_status()
        result = response.json()
        assert result.get("status") == "ok", "Login API failed"
        client.headers["Authorization"] = "Bearer " + result["data"]["token"]
        response = client.get("/api/v1/plugins")
        response.raise_for_status()
        plugins = response.json()["data"]
        checks["authenticated_settings_accessible"] = True
        for plugin in ("astrbot_plugin_private_companion", "astrbot_plugin_memory_companion"):
            checks[plugin + "_loaded"] = any(row["name"] == plugin and row["activated"] for row in plugins)
        personas = client.get("/api/v1/personas").json()["data"]
        checks["persona_retained"] = any(row["persona_id"] == "qq-friend" for row in personas)
        config = client.get("/api/v1/config-profiles/default").json()["data"]["config"]
        checks["loopback_only"] = config["dashboard"]["host"] == "127.0.0.1"
        report["external_setup"] = {
            "deepseek_key_present": any(
                key.strip() for source in config["provider_sources"] if source["id"] == "deepseek"
                for key in source.get("key", [])
            ),
            "deepseek_model_enabled": any(row.get("enable") for row in config["provider"] if row.get("provider_source_id") == "deepseek"),
            "qq_configured": any(row.get("type") == "qq_official" for row in config["platform"]),
        }
    private = ROOT / "verification/private"
    private.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(10000)
        page.goto(URL, wait_until="networkidle")
        page.locator("input[type=text]").fill(credentials["username"])
        page.locator("input[type=password]").fill(credentials["initial_password"])
        page.get_by_role("button", name="登录", exact=True).click()
        page.get_by_role("link", name="模型提供商", exact=True).wait_for()
        checks["browser_login"] = True
        page.get_by_role("link", name="模型提供商", exact=True).click()
        page.get_by_role("button").filter(has_text="deepseek").first.click()
        page.locator("input[type=password]").wait_for()
        checks["api_key_input_masked"] = True
        page.screenshot(path=str(private / "settings.png"), full_page=True)
        context.storage_state(path=str(ROOT / "runtime/ui-state.local.json"))
        browser.close()
    (ROOT / "verification/runtime-checks.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert all(checks.values()), "A local runtime check failed"


if __name__ == "__main__":
    main()
