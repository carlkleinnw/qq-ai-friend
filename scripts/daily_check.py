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
        with httpx.Client(base_url=service.URL, trust_env=False, timeout=10) as client:
            client.headers["Authorization"] = "Bearer " + checked(client.post("/api/v1/auth/login", json={"username": cr["username"], "password": cr["initial_password"]}))["token"]
            stats = checked(client.get("/api/v1/bots/stats"))["platforms"]
            cfg = checked(client.get('/api/v1/config-profiles/default'))['config']
            identity_response=client.get('/api/v1/plugins/extensions/astrbot_plugin_persona_studio/bot-identities')
            identity_response.raise_for_status()
            identities=identity_response.json()['bots']
            identity_map={bot['bot_id']:bot for bot in identities}
            bots = [bot for bot in cfg.get('platform', []) if bot.get('enable', True) and bot.get('type') in {'qq_official', 'qq_official_webhook'}]
            result['bots'] = [{'bot_id':bot['id'],'appid':str(bot.get('appid','')),
                               'name': identity_map.get(bot['id'],{}).get('name',bot['id']),
                               'connection_status':identity_map.get(bot['id'],{}).get('connection_status','unknown'),
                               'adapter_status': next((p['status'] for p in stats if p['id'] == bot['id']), 'missing')}
                              for index, bot in enumerate(bots)]
            routes = checked(client.get('/api/v1/config-routes'))['routing']
            model_keys=[]
            for bot in result['bots']:
                config_id=routes.get(bot['bot_id']+'::','default')
                cfg=checked(client.get('/api/v1/config-profiles/'+config_id))['config']
                runner=cfg.get('agent_runner',{})
                bot['runner_type']=runner.get('runner_type','local')
                bot['voice_enabled']=cfg.get('provider_tts_settings',{}).get('enable',False)
                if bot['runner_type']!='local':continue
                model=runner.get('config',{}).get('model',{})
                bot['retry_attempts']=model.get('request_max_retries')
                provider_id=model.get('provider_id')
                if provider_id:
                    provider=checked(client.get('/api/v1/providers/by-id',params={'provider_id':provider_id,'merged':True}))['provider']
                    bot['model_key_present']=any(str(key).strip() for key in provider.get('key',[]))
                    bot['model_timeout_seconds']=provider.get('timeout')
                else:bot['model_key_present']=False
                model_keys.append(bot['model_key_present'])
            result['model_key_present']=all(model_keys) if model_keys else None
            jobs = checked(client.get("/api/v1/cron/jobs"))
            if isinstance(jobs, dict):
                jobs = jobs.get("jobs", [])
            result["failed_reminders"] = sum(job.get("status") == "failed" for job in jobs)
    report = ROOT / "verification/daily-status.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("本地面板：" + ("可访问" if result["dashboard_ready"] else "未运行，请先双击启动AI好友"))
    for bot in result.get("bots", []):
        print(bot["name"] + " QQ连接：" + str(bot['connection_status']) + "；接入进程：" + str(bot["adapter_status"]))
    print("安装盘剩余空间：" + str(result["disk_free_gib"]) + " GB")
    if not result.get('bots') and result['dashboard_ready']:
        print('尚未接入 QQ：请在面板扫码保存，再从维护窗口同步。')
    if result.get('model_key_present') is False:
        print('尚未填写模型密钥：请在模型提供商设置中填写并保存。')
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
