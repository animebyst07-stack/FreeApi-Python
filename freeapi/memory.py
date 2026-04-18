import re
import logging
from freeapi.database import db, row, msk_now

logger = logging.getLogger('freeapi')

CONTEXT_WARN_KB = 165.0
CONTEXT_LIMIT_KB = 178.0

_TAG_WRITE_CTX_RE = re.compile(
    r'\u3010\u2295write:ctx\u2295\u3011([\s\S]*?)\u3010\u2295/write:ctx\u2295\u3011',
    re.DOTALL
)
_TAG_WRITE_FAV_RE = re.compile(
    r'\u3010\u2295write:fav\u2295\u3011([\s\S]*?)\u3010\u2295/write:fav\u2295\u3011',
    re.DOTALL
)
_TAG_LOAD_MEM_RE = re.compile(r'\u3010\u2295load:mem\u2295\u3011')

LIMIT_ERROR_KEYWORDS = [
    'запрос слишком большой',
    'сократите текст',
    'автоматический сброс истории',
    'измените лимит токенов',
]


def detect_limit_error(text):
    if not text:
        return False
    low = text.lower()
    return any(kw in low for kw in LIMIT_ERROR_KEYWORDS)


CYRILLIC_TOKEN_RATE = 3.3
LATIN_TOKEN_RATE = 1.3
_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)
_CYRILLIC_RE = re.compile(r'[\u0400-\u04ff]')


def estimate_tokens(text, images_count=0):
    src = text or ''
    words = src.split()
    word_tokens = 0.0
    for word in words:
        if _CYRILLIC_RE.search(word):
            word_tokens += CYRILLIC_TOKEN_RATE
        else:
            word_tokens += LATIN_TOKEN_RATE
    punct_tokens = len(_PUNCT_RE.findall(src)) * 0.3
    image_tokens = images_count * 2000
    return int(word_tokens + punct_tokens + image_tokens)


def tokens_to_kb(tokens):
    return round(tokens * 4 / 1024, 1)


def parse_tags(text):
    if not text:
        return text, []

    commands = []

    for match in _TAG_WRITE_CTX_RE.finditer(text):
        commands.append({'type': 'write_ctx', 'content': match.group(1).strip()})

    for match in _TAG_WRITE_FAV_RE.finditer(text):
        commands.append({'type': 'write_fav', 'content': match.group(1).strip()})

    if _TAG_LOAD_MEM_RE.search(text):
        commands.append({'type': 'load_mem', 'content': ''})

    clean = _TAG_WRITE_CTX_RE.sub('', text)
    clean = _TAG_WRITE_FAV_RE.sub('', clean)
    clean = _TAG_LOAD_MEM_RE.sub('', clean)
    clean = clean.strip()

    return clean, commands


def get_memory(key_id):
    with db() as conn:
        r = conn.execute(
            'SELECT context_md, favorite_md, lang_hint, context_updated_at, favorite_updated_at '
            'FROM agent_memory WHERE key_id = ?', (key_id,)
        ).fetchone()
    if not r:
        return {'context_md': '', 'favorite_md': '', 'lang_hint': 'ru',
                'context_updated_at': None, 'favorite_updated_at': None}
    return dict(r)


def save_context(key_id, content, lang_hint=None):
    now = msk_now()
    with db() as conn:
        existing = conn.execute('SELECT key_id, lang_hint FROM agent_memory WHERE key_id=?', (key_id,)).fetchone()
        if existing:
            hint = lang_hint or existing['lang_hint'] or 'ru'
            conn.execute(
                'UPDATE agent_memory SET context_md=?, lang_hint=?, context_updated_at=? WHERE key_id=?',
                (content, hint, now, key_id)
            )
        else:
            hint = lang_hint or 'ru'
            conn.execute(
                'INSERT INTO agent_memory(key_id, context_md, favorite_md, lang_hint, context_updated_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (key_id, content, '', hint, now)
            )
    logger.info('[MEMORY] context.md сохранён для ключа %s (%d символов)', key_id[:8], len(content))


def save_favorite(key_id, content):
    now = msk_now()
    with db() as conn:
        existing = conn.execute('SELECT key_id FROM agent_memory WHERE key_id=?', (key_id,)).fetchone()
        if existing:
            conn.execute(
                'UPDATE agent_memory SET favorite_md=?, favorite_updated_at=? WHERE key_id=?',
                (content, now, key_id)
            )
        else:
            conn.execute(
                'INSERT INTO agent_memory(key_id, context_md, favorite_md, lang_hint, favorite_updated_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (key_id, '', content, 'ru', now)
            )
    logger.info('[MEMORY] favorite.md сохранён для ключа %s (%d символов)', key_id[:8], len(content))


def clear_context(key_id):
    now = msk_now()
    with db() as conn:
        conn.execute(
            'UPDATE agent_memory SET context_md=\'\', context_updated_at=? WHERE key_id=?',
            (now, key_id)
        )
    logger.info('[MEMORY] context.md очищен для ключа %s', key_id[:8])


def clear_favorite(key_id):
    now = msk_now()
    with db() as conn:
        conn.execute(
            'UPDATE agent_memory SET favorite_md=\'\', favorite_updated_at=? WHERE key_id=?',
            (now, key_id)
        )
    logger.info('[MEMORY] favorite.md очищен для ключа %s', key_id[:8])


def clear_all(key_id):
    now = msk_now()
    with db() as conn:
        conn.execute(
            'UPDATE agent_memory SET context_md=\'\', favorite_md=\'\', '
            'context_updated_at=?, favorite_updated_at=? WHERE key_id=?',
            (now, now, key_id)
        )


def process_commands(key_id, commands, lang_hint=None):
    wrote_ctx = False
    wrote_fav = False
    for cmd in commands:
        t = cmd.get('type')
        content = cmd.get('content', '')
        if t == 'write_ctx' and content:
            save_context(key_id, content, lang_hint)
            wrote_ctx = True
        elif t == 'write_fav' and content:
            save_favorite(key_id, content)
            wrote_fav = True
    return wrote_ctx, wrote_fav


def format_memory_injection(memory):
    parts = []
    if memory.get('favorite_md'):
        parts.append(f"[MEMORY:favorite]\n{memory['favorite_md']}")
    if memory.get('context_md'):
        parts.append(f"[MEMORY:context]\n{memory['context_md']}")
    if not parts:
        return ''
    return '\n\n'.join(parts)


def build_context_warning():
    return (
        '\n\n[SYSTEM NOTICE — DO NOT SHOW TO USER]: '
        'Context is nearly full (~165KB/180KB limit). '
        'You MUST immediately write a compressed English summary of this conversation '
        'to context.md using the memory tag at the END of your response:\n'
        '\u3010\u2295write:ctx\u2295\u3011\nSummary here (English only)\n\u3010\u2295/write:ctx\u2295\u3011\n'
        'Also respond to the user as usual.'
    )


def contains_cyrillic(text):
    return bool(re.search(r'[\u0400-\u04ff]', text or ''))
