"""Compose QQ's documented /v2/menu payload; no separate persona store."""
from copy import deepcopy


def persona_menu(presets):
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
            {'type': 'send_message', 'name': preset['name'],
             'send_message': '/人设 ' + (preset['id'] if preset.get('id', '').startswith('custom-') else str(index))}
            for index, preset in enumerate(presets[start:start + 5], start + 1)]})
    return menus


def merge_persona_menu(current, presets):
    if not presets:
        raise ValueError('请先配置人设预设。')
    owned = persona_menu(presets)
    for menu in owned:
        for item in menu['sub_menu_items']:
            if sum(2 if ord(char) > 127 else 1 for char in item['name']) > 14:
                raise ValueError('预设名称过长，QQ 子菜单最多支持七个中文字符。')
    existing = deepcopy((current or {}).get('items', []))
    commands = {'/人设', '/自定义人设', '/当前人设', '/确认人设', '/取消人设'}
    for item in owned:
        collision = next((m for m in existing if m.get('name') == item['name']), None)
        if collision is not None:
            children = collision.get('sub_menu_items', [])
            if (collision.get('type') != 'menu' or not children or
                any(c.get('type') != 'send_message' or c.get('send_message', '').strip().split(' ', 1)[0] not in commands
                    for c in children)):
                raise ValueError('QQ 已有同名菜单，请先保留原配置并调整名称：' + item['name'])
            # QQ adds metadata such as a default icon on readback. Keep it so
            # repeated synchronization does not needlessly publish a new version.
            existing[existing.index(collision)] = {**collision, **item}
        else:
            existing.append(item)
    if len(existing) > 10:
        raise ValueError('QQ 已有菜单较多，添加人设入口会超过十项；原菜单未修改。')
    return {'items': existing}
