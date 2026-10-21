"""Read-only local checks: never call a paid model or expose credentials/error payloads."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

import httpx
import service
from apply_profile import checked

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = {"checked_at": datetime.now().isoformat(), "dashboard_ready": service.ready(),
              "disk_free_gib": round(shutil.disk_usage(ROOT).free / 1024 ** 3, 1)}
    try:
        result["managed_process_running"] = service.managed_process() is not None
    except RuntimeError:
        result["managed_process_running"] = False
    latest = ROOT / "runtime/backups/latest-native.local.json"
    result["latest_backup_at"] = json.loads(latest.read_text()).get("created_at") if latest.exists() else None
    if result["dashboard_ready"]:
        cr = json.loads((ROOT / "runtime/dashboard-login.local.json").read_text())
        state = json.loads((ROOT / "runtime/multibot.local.json").read_text())
        with httpx.Client(base_url=service.URL, trust_env=False, timeout=10) as client:
            client.headers["Authorization"] = "Bearer " + checked(client.post("/api/v1/auth/login", json={"username": cr["username"], "password": cr["initial_password"]}))["token"]
            stats = checked(client.get("/api/v1/bots/stats"))["platforms"]
            result["bots"] = [{"name": name, "adapter_status": next((p["status"] for p in stats if p["id"] == bot), "missing")}
                              for name, bot in [("大肥鱼", state["first_bot_id"]), ("GPT大人", state["second_bot_id"])]]
            cfg = checked(client.get("/api/v1/config-profiles/" + state["profiles"]["qq-friend"]))["config"]
            result["dafeiyu_voice_enabled"] = cfg["provider_tts_settings"]["enable"]
            result["dafeiyu_retry_attempts"] = cfg["agent_runner"]["config"]["model"]["request_max_retries"]
            provider_id = cfg["agent_runner"]["config"]["model"]["provider_id"]
            provider = checked(client.get("/api/v1/providers/by-id", params={"provider_id": provider_id, "merged": True}))["provider"]
            result["model_key_present"] = bool(provider.get("key"))
            result["model_network_timeout_seconds"] = provider.get("timeout")
            jobs = checked(client.get("/api/v1/cron/jobs"))
            if isinstance(jobs, dict):
                jobs = jobs.get("jobs", [])
            result["failed_reminders"] = sum(job.get("status") == "failed" for job in jobs)
    report = ROOT / "verification/daily-status.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("本地面板：" + ("可访问" if result["dashboard_ready"] else "未运行，请先双击启动AI好友"))
    for bot in result.get("bots", []):
        print(bot["name"] + "连接进程状态：" + str(bot["adapter_status"]))
    print("E盘剩余空间：" + str(result["disk_free_gib"]) + " GB")
    print("最近备份：" + str(result["latest_backup_at"] or "尚未创建"))
    if result.get("failed_reminders"):
        print("有失败提醒，请到面板的未来任务查看；核对是否已投递后再手动运行或调整时间。")
    print("此检查不调用模型，也不代表手机已实际收到新消息。结果见 verification/daily-status.json。")
    if not result["dashboard_ready"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("检查未完成，请确认服务已启动、本机登录信息仍有效。错误类型：" + type(error).__name__)
        sys.exit(1)
