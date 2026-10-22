"""Compose QQ's documented /v2/menu payload; no separate persona store."""
from copy import deepcopy


def persona_menu(presets):
    used = set()

    def label(name):
        def shorten(text, budget):
            result = ''
            for char in text:
                size = 2 if ord(char) > 127 else 1
                if size > budget:
                    break
                result += char
                budget -= size
            return result
        name = ' '.join(name.split()) or '人设'
        candidate = shorten(name, 14)
        count = 1
        while candidate in used:
            count += 1
            suffix = str(count)
            candidate = shorten(name, 14 - len(suffix)) + suffix
        used.add(candidate)
        return candidate
    menus = [
        {'type': 'menu', 'name': '人设设置', 'sub_menu_items': [
            {'type': 'send_message', 'name': name, 'send_message': command}
            for name, command in [('预设列表', '/人设'), ('自定义人设', '/自定义人设 '),
                                  ('当前人设', '/当前人设'), ('确认保存', '/确认人设'),
                                  ('取消修改', '/取消人设')]]},
    ]
    for start in range(0, len(presets), 5):
        page = start // 5 + 1
        menus.append({'type': 'menu', 'name': '选择预设' if page == 1 else f'预设{page}', 'sub_menu_items': [
            {'type': 'send_message', 'name': label(preset['name']),
             'send_message': '/人设 ' + preset['id']}
            for index, preset in enumerate(presets[start:start + 5], start + 1)]})
    return menus


def merge_persona_menu(current, presets):
    owned = persona_menu(presets)
    for menu in owned:
        for item in menu['sub_menu_items']:
            if sum(2 if ord(char) > 127 else 1 for char in item['name']) > 14:
                raise ValueError('预设名称过长，QQ 子菜单最多支持七个中文字符。')
    existing = deepcopy((current or {}).get('items', []))
    commands = {'/人设', '/自定义人设', '/当前人设', '/确认人设', '/取消人设'}
    def ours(menu):
        children = menu.get('sub_menu_items', [])
        return (menu.get('type') == 'menu' and bool(children) and
                all(c.get('type') == 'send_message' and
                    c.get('send_message', '').strip().split(' ', 1)[0] in commands for c in children))
    names = {m['name'] for m in owned}
    existing = [m for m in existing if not (ours(m) and m.get('name') not in names and
                (m.get('name') in {'人设设置', '选择预设'} or
                 (m.get('name', '').startswith('预设') and m['name'][2:].isdigit())))]
    for item in owned:
        collision = next((m for m in existing if m.get('name') == item['name']), None)
        if collision is not None:
            children = collision.get('sub_menu_items', [])
            if not ours(collision):
                raise ValueError('QQ 已有同名菜单，请先保留原配置并调整名称：' + item['name'])
            # QQ adds metadata such as a default icon on readback. Keep it so
            # repeated synchronization does not needlessly publish a new version.
            existing[existing.index(collision)] = {**collision, **item}
        else:
            existing.append(item)
    if len(existing) > 10:
        raise ValueError('QQ 已有菜单较多，添加人设入口会超过十项；原菜单未修改。')
    return {**(current or {}), 'items': existing}
