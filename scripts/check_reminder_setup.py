"""Read-only audit of the existing reminder tools and bot configuration."""
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    credentials = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "bots": {}}
    with httpx.Client(base_url="http://127.0.0.1:6185", trust_env=False, timeout=20) as client:
        login = checked(client.post("/api/v1/auth/login", json={
            "username": credentials["username"], "password": credentials["initial_password"],
        }))
        client.headers["Authorization"] = "Bearer " + login["token"]
        base='/api/v1/plugins/extensions/astrbot_plugin_persona_studio/'
        response=client.get(base+'bot-identities');response.raise_for_status()
        identities=response.json()['bots']
        for bot in identities:
            response=client.get(base+'control-state',params={'bot_id':bot['bot_id']});response.raise_for_status()
            state=response.json()
            if state.get('status')=='error':raise RuntimeError('Cannot resolve bot configuration')
            persona_id,config_id=state['persona_id'],state['config_id']
            persona = checked(client.get("/api/v1/personas/by-id", params={"persona_id": persona_id}))
            config = checked(client.get("/api/v1/config-profiles/" + config_id))["config"]
            tools = persona.get("tools")
            all_tools = tools is None
            allowed = set(tools or [])
            report["bots"][bot['bot_id']] = {
                "name":bot['name'],"appid":bot['appid'],"persona_id":persona_id,"config_id":config_id,
                "local_runner":state['runner_type']=='local',
                "future_task_allowed": all_tools or "future_task" in allowed,
                "send_message_allowed": all_tools or "send_message_to_user" in allowed,
                "cron_tools_enabled": bool(config.get("provider_settings", {}).get("proactive_capability", {}).get("add_cron_tools", True)),
                "china_timezone": config.get("timezone") == "Asia/Shanghai",
            }
        jobs = checked(client.get("/api/v1/cron/jobs"))
        if isinstance(jobs,dict):jobs=jobs.get('jobs',[])
        report["task_counts"] = {
            "total": len(jobs),
            "enabled": sum(bool(job["enabled"]) for job in jobs),
            "one_time": sum(bool(job["run_once"]) for job in jobs),
        }
    flags=['local_runner','future_task_allowed','send_message_allowed','cron_tools_enabled','china_timezone']
    report["ready"] = bool(report['bots']) and all(all(row[k] for k in flags) for row in report["bots"].values())
    report['delivery_tested']=False
    (ROOT / "verification/reminder-readiness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    if not report["ready"]:
        raise SystemExit("Reminder setup needs attention; user settings were not changed.")


if __name__ == "__main__":
    main()
