"""OneBot群消息筛选与道馆每日检查状态。此模块不操作QQ或游戏窗口。"""
import hashlib
import hmac
import html
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_DB = Path(__file__).resolve().parents[2] / 'config' / 'dokan_qq_messages.db'


def local_now():
    return datetime.now(CHINA_TZ)


def split_keywords(value):
    return [word.strip() for word in re.split(r'[\r\n|]+', value) if word.strip()]


def message_text(event):
    message = event.get('message')
    if isinstance(message, list):
        # 只读取正文text段，不把图片、转发或回复ID当作消息文字。
        return ''.join(str(segment.get('data', {}).get('text', ''))
                       for segment in message if isinstance(segment, dict)
                       and segment.get('type') == 'text'
                       and isinstance(segment.get('data'), dict))
    raw = message if isinstance(message, str) else event.get('raw_message', '')
    return html.unescape(re.sub(r'\[CQ:[^\]]*\]', '', raw)) if isinstance(raw, str) else ''


def verify_signature(body, signature, secret):
    expected = 'sha1=' + hmac.new(secret.encode('utf-8'), body, 'sha1').hexdigest()
    return hmac.compare_digest(expected, signature or '')


@dataclass(frozen=True)
class CheckResult:
    allowed: bool
    attempts: int
    # None 表示不指定时间，交回道馆原调度器计算。
    next_run: Optional[datetime]
    reason: str


class QQListener:
    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS qq_messages (
                profile TEXT NOT NULL, event_key TEXT NOT NULL,
                group_id TEXT NOT NULL, member_id TEXT NOT NULL,
                sent_at REAL NOT NULL, text TEXT NOT NULL,
                PRIMARY KEY (profile, event_key)
            );
            CREATE INDEX IF NOT EXISTS qq_messages_lookup
                ON qq_messages(profile, group_id, member_id, sent_at);
            CREATE TABLE IF NOT EXISTS qq_daily_checks (
                profile TEXT PRIMARY KEY, day TEXT NOT NULL,
                attempts INTEGER NOT NULL, phase TEXT NOT NULL,
                next_check REAL NOT NULL, reason TEXT NOT NULL
            );
        ''')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, profile, config, event, now=None):
        now = now or local_now()
        if not isinstance(event, dict) or event.get('post_type') != 'message' \
                or event.get('message_type') != 'group' or event.get('anonymous'):
            return False
        sender = event.get('sender') or {}
        member = event.get('user_id', sender.get('user_id') if isinstance(sender, dict) else None)
        if not config.group_id.strip().isdigit() or not config.member_id.strip().isdigit():
            return False
        if str(event.get('group_id')) != config.group_id.strip() or str(member) != config.member_id.strip():
            return False
        try:
            timestamp = float(event['time'])
            if not math.isfinite(timestamp):
                return False
            sent_at = datetime.fromtimestamp(timestamp, CHINA_TZ)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return False
        # 昨天的消息、毫秒时间戳和未来消息均不能放行。
        if sent_at.date() != now.date() or sent_at > now:
            return False
        text = message_text(event)
        if not text or len(text) > 65536:
            return False
        identity = [event.get('self_id'), event.get('message_id'), timestamp,
                    str(event.get('group_id')), str(member), text]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()
        with self._connect() as connection:
            connection.execute('DELETE FROM qq_messages WHERE sent_at < ?',
                               ((now - timedelta(days=2)).timestamp(),))
            cursor = connection.execute('INSERT OR IGNORE INTO qq_messages VALUES (?, ?, ?, ?, ?, ?)',
                                        (profile, key, config.group_id.strip(), config.member_id.strip(), timestamp, text))
            return cursor.rowcount > 0

    def _matches(self, connection, profile, config, now):
        required = split_keywords(config.keywords)
        excluded = split_keywords(config.excluded_keywords)
        if not required:
            return False
        start = datetime.combine(now.date(), time(), CHINA_TZ).timestamp()
        rows = connection.execute('''SELECT text FROM qq_messages
            WHERE profile=? AND group_id=? AND member_id=? AND sent_at>=? AND sent_at<=?
            ORDER BY sent_at DESC''',
            (profile, config.group_id.strip(), config.member_id.strip(), start, now.timestamp()))
        return any(any(word in row['text'] for word in required)
                   and not any(word in row['text'] for word in excluded) for row in rows)

    def has_match(self, profile, config, now=None):
        with self._connect() as connection:
            return self._matches(connection, profile, config, now or local_now())

    def reset_today(self, profile, now=None):
        """只重置当前配置的当日检查状态，保留消息缓存和任务调度。"""
        now = now or local_now()
        with self._connect() as connection:
            connection.execute('INSERT OR REPLACE INTO qq_daily_checks VALUES (?, ?, 0, ?, 0, ?)',
                               (profile, now.date().isoformat(), 'waiting', '手动重置当天检查次数'))

    def _state(self, connection, profile, now):
        state = connection.execute('SELECT * FROM qq_daily_checks WHERE profile=?', (profile,)).fetchone()
        if state is None or state['day'] != now.date().isoformat():
            connection.execute('INSERT OR REPLACE INTO qq_daily_checks VALUES (?, ?, 0, ?, 0, ?)',
                               (profile, now.date().isoformat(), 'waiting', ''))
            state = connection.execute('SELECT * FROM qq_daily_checks WHERE profile=?', (profile,)).fetchone()
        elif state['phase'] == 'finished':
            # 旧版本曾把游戏异常也记成当天结束；新版本只管理消息检查。
            connection.execute('UPDATE qq_daily_checks SET phase=?, next_check=0, reason=? WHERE profile=?',
                               ('waiting', '已恢复旧版提前结束的消息检查', profile))
            state = connection.execute('SELECT * FROM qq_daily_checks WHERE profile=?', (profile,)).fetchone()
        return state

    def _pending_result(self, state, config, now, scheduled_at=None):
        if state['attempts'] >= config.max_checks:
            return CheckResult(False, state['attempts'], None, '当天检查次数已达上限，按道馆原调度逻辑安排下次运行')
        if scheduled_at is not None:
            # OAS已按此时间启动任务；立即执行/手动改时间不能被旧next_check拦截。
            if now < scheduled_at:
                return CheckResult(False, state['attempts'], scheduled_at, '尚未到任务执行时间')
            return None
        if state['phase'] == 'ready':
            return None
        if state['next_check'] > now.timestamp():
            retry = datetime.fromtimestamp(state['next_check'], CHINA_TZ)
            return CheckResult(False, state['attempts'], retry, '尚未到重试时间')
        return None

    def check(self, profile, config, now=None, history_fetcher=None, scheduled_at=None):
        """未匹配才计次数；到上限交回原调度，未到上限仅按重试间隔推迟。"""
        now = now or local_now()
        if scheduled_at is not None:
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=CHINA_TZ)
            scheduled_at = scheduled_at.astimezone(CHINA_TZ)
        with self._connect() as connection:
            pending = self._pending_result(self._state(connection, profile, now), config, now, scheduled_at)
            if pending:
                return pending

        valid_config = (config.group_id.strip().isdigit() and int(config.group_id.strip()) > 0
                        and config.member_id.strip().isdigit() and int(config.member_id.strip()) > 0
                        and bool(split_keywords(config.keywords)))
        history_error = '' if valid_config else '请填写有效群号、成员QQ号和放行关键词'
        if valid_config and config.history_api_url.strip() and not self.has_match(profile, config, now):
            try:
                (history_fetcher or fetch_history)(self, profile, config, now)
            except Exception as error:
                # 不输出URL、访问令牌或QQ正文；接口错误也消耗一次检查预算。
                history_error = f'历史接口读取失败（{type(error).__name__}）'

        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            state = self._state(connection, profile, now)
            pending = self._pending_result(state, config, now, scheduled_at)
            if pending:
                return pending
            attempts = state['attempts']
            if self._matches(connection, profile, config, now):
                allowed, phase, target = True, 'ready', None
                reason = '当天指定成员消息包含放行关键词'
            else:
                attempts += 1
                allowed, phase = False, 'waiting'
                target = now + timedelta(minutes=config.retry_minutes)
                if attempts >= config.max_checks:
                    phase, target = 'exhausted', None
                    reason = (history_error + '；' if history_error else '') + '检查次数已达上限，按道馆原调度逻辑安排下次运行'
                else:
                    reason = history_error or '未收到当天指定成员的匹配消息'
            connection.execute('UPDATE qq_daily_checks SET attempts=?, phase=?, next_check=?, reason=? WHERE profile=?',
                               (attempts, phase, target.timestamp() if target is not None else 0, reason, profile))
            return CheckResult(allowed, attempts, target, reason)

def fetch_history(listener, profile, config, now):
    """按NapCat get_group_msg_history扩展接口补读有上限的群历史记录。"""
    import requests

    base = config.history_api_url.strip().rstrip('/')
    if urlparse(base).scheme not in ('http', 'https') or not urlparse(base).hostname:
        raise ValueError('历史消息API地址无效')
    url = base if base.endswith('/get_group_msg_history') else base + '/get_group_msg_history'
    headers = {'Authorization': 'Bearer ' + config.history_api_token} if config.history_api_token else {}
    cursor, previous = None, set()
    for _ in range(config.history_max_pages):
        payload = {'group_id': config.group_id.strip(), 'count': config.history_page_size,
                   'reverse_order': False, 'disable_get_url': True, 'parse_mult_msg': False}
        if cursor is not None:
            payload['message_seq'] = str(cursor)
        response = requests.post(url, json=payload, headers=headers, timeout=(3, 8))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get('status') != 'ok' or body.get('retcode') != 0:
            raise ValueError('OneBot历史接口未成功')
        messages = body.get('data', {}).get('messages')
        if not isinstance(messages, list):
            raise ValueError('历史接口未返回消息列表')
        if not messages:
            return
        dated = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            event = dict(message)
            event.update(post_type='message', message_type='group')
            event.setdefault('group_id', config.group_id.strip())
            listener.record(profile, config, event, now)
            try:
                timestamp = float(message['time'])
                if math.isfinite(timestamp):
                    dated.append((timestamp, message.get('message_id')))
            except (KeyError, TypeError, ValueError):
                continue
        if listener.has_match(profile, config, now):
            return
        if not dated:
            raise ValueError('历史消息缺少时间戳')
        oldest_time, next_cursor = min(dated, key=lambda item: item[0])
        if datetime.fromtimestamp(oldest_time, CHINA_TZ).date() < now.date():
            return
        if next_cursor is None or str(next_cursor) in previous:
            return
        previous.add(str(next_cursor))
        cursor = next_cursor


def fetch_builtin_history(listener, profile, config, now):
    """道馆运行在子进程，通过OAS自身的本机API读取进程内QQ连接。"""
    import requests
    import yaml
    from urllib.parse import quote

    deploy_path = Path(__file__).resolve().parents[2] / 'config' / 'deploy.yaml'
    deploy = yaml.safe_load(deploy_path.read_text(encoding='utf-8')) or {}
    port = int(deploy.get('Deploy', {}).get('Webui', {}).get('WebuiPort', 22288))
    if not 1 <= port <= 65535:
        raise ValueError('OAS后台端口无效')
    url = f'http://127.0.0.1:{port}/dokan/qq/history/{quote(profile, safe="")}'
    cursor, seen = -1, set()
    # Avoid proxying login/session or local message requests outside this computer.
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(config.history_max_pages):
            response = session.post(url, json={'cursor': cursor, 'count': config.history_page_size},
                                    headers={'X-OAS-QQ': '1'}, timeout=(3, 12))
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get('messages'), list):
                raise ValueError('内置QQ历史响应无效')
            dated = []
            for event in body['messages']:
                if not isinstance(event, dict):
                    continue
                listener.record(profile, config, event, now)
                try:
                    stamp = float(event['time'])
                    if math.isfinite(stamp):
                        dated.append(stamp)
                except (KeyError, TypeError, ValueError):
                    continue
            if listener.has_match(profile, config, now):
                return
            if dated and datetime.fromtimestamp(min(dated), CHINA_TZ).date() < now.date():
                return
            following = body.get('next_cursor')
            if following is None or type(following) is not int or following < 0:
                return
            if following in seen or (cursor >= 0 and following >= cursor):
                return
            seen.add(following)
            cursor = following
