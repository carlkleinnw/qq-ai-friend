"""Validate locally entered login details without putting passwords in process arguments."""
import json
from pathlib import Path
import sys
import httpx
from apply_profile import checked
from service import URL

ROOT = Path(__file__).resolve().parents[1]


def main():
    values = json.load(sys.stdin)
    username, password = values.get('username'), values.get('password')
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise ValueError('请填写当前面板的账号和密码。')
    with httpx.Client(base_url=URL, trust_env=False, timeout=30) as client:
        checked(client.post('/api/v1/auth/login', json={'username': username, 'password': password}))
    path = ROOT / 'runtime/dashboard-login.local.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'username': username, 'initial_password': password}), encoding='utf-8')
    temporary.replace(path)
    (ROOT / 'runtime/本机登录说明.txt').write_text('面板：' + URL + '\n账号：' + username + '\n密码：' + password + '\n请勿公开分享。\n', encoding='utf-8')
    print('登录验证成功，本机维护记录已更新。')


if __name__ == '__main__':
    main()
