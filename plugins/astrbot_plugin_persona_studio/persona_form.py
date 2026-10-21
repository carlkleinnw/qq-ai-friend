"""Lossless form adapter for native plain-text system prompts; no chat engine."""
import hashlib
import json

HEADER = '<!-- ai-friend-persona:v1 -->\n## 个人简介\n'
SEPARATOR = '\n\n## 详细人设\n'


def unpack(prompt):
    if prompt.startswith(HEADER) and SEPARATOR in prompt[len(HEADER):]:
        return prompt[len(HEADER):].split(SEPARATOR, 1)
    return '', prompt


def pack(bio, prompt):
    if not isinstance(bio, str) or not isinstance(prompt, str):
        raise ValueError('简介和详细人设必须是文字。')
    if len(bio) > 1000 or len(prompt) > 20000:
        raise ValueError('简介最多 1000 字，详细人设最多 20000 字。')
    if not (bio.strip() or prompt.strip()):
        raise ValueError('请填写个人简介或详细人设。')
    if SEPARATOR in bio or HEADER in bio:
        raise ValueError('简介包含保留分隔格式，请改用普通文字。')
    return HEADER + bio + SEPARATOR + prompt if bio else prompt


def revision(persona):
    return hashlib.sha256(json.dumps(persona, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
