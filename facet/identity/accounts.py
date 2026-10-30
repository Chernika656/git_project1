"""Аккаунты, сессии и права доступа. Все решения о доступе принимает сервер."""
from contextlib import closing
import hashlib
import html
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from facet.projects.workspace import new_project, validate_project, now, Conflict

SPECIALTIES = {'leader', 'product', 'business', 'system', 'developer', 'qa', 'designer', 'manager'}
SENIORITIES = {'junior', 'middle', 'senior', 'lead', 'head'}
PROJECT_ROLES = {'viewer': 1, 'commenter': 2, 'editor': 3, 'manager': 4}
COLORS = {'purple', 'blue', 'peach', 'teal', 'rose'}
SESSION_AGE = 7 * 86400
FREE_MONTHLY_TOKENS = 1_000_000
PLAN_LIMITS = {'free': (20, FREE_MONTHLY_TOKENS), 'pro': (100, 5_000_000), 'team': (200, 20_000_000)}
HASH_SLOTS = threading.BoundedSemaphore(2)


class AccessError(Exception):
    def __init__(self, message='Недостаточно прав.', status=403, code='forbidden'):
        super().__init__(message)
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text(value, limit=200, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('Заполните обязательные поля и проверьте длину текста.')
    return value.strip()


def email_address(value):
    email = text(value, 254).lower()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email) or '\r' in email or '\n' in email:
        raise ValueError('Укажите корректную почту.')
    return email


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise ValueError('Пароль должен содержать от 15 до 128 символов.')
    salt = salt or secrets.token_hex(16)
    with HASH_SLOTS:
        result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=131072, r=8, p=1,
                                maxmem=256*1024*1024).hex()
    return 'scrypt$131072$8$1$' + salt + '$' + result


def password_matches(password, encoded):
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        return False
    try:
        salt = encoded.split('$')[4]
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except (ValueError, IndexError):
        return False


class Mailer:
    """SMTP через TLS или локальные .eml. Токены не возвращаются через API."""
    def __init__(self, directory, base_url):
        self.directory = Path(directory)
        self.base_url = base_url.rstrip('/')
        self.host = os.environ.get('WORKSPACE_SMTP_HOST', '')
        self.mode = 'smtp' if self.host else 'local'

    def send(self, email, subject, content, html_content=None):
        message = EmailMessage()
        message['Subject'], message['To'] = subject, email
        sender = os.environ.get('WORKSPACE_MAIL_FROM', 'workspace@localhost')
        message['From'] = formataddr(('Facet', sender))
        message['Reply-To'] = sender
        message['Date'] = formatdate(localtime=False)
        message['Message-ID'] = make_msgid(domain=sender.rpartition('@')[2] or None)
        message['X-Entity-Ref-ID'] = secrets.token_hex(12)
        message.set_content(content)
        if html_content:
            message.add_alternative(html_content, subtype='html')
        if not self.host:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.directory / (str(time.time_ns()) + '-' + secrets.token_hex(3) + '.eml')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(message.as_bytes())
            return
        port = int(os.environ.get('WORKSPACE_SMTP_PORT', '465'))
        context = ssl.create_default_context()
        if port == 465:
            client = smtplib.SMTP_SSL(self.host, port, context=context, timeout=15)
        else:
            client = smtplib.SMTP(self.host, port, timeout=15)
            client.starttls(context=context)
        with client:
            username = os.environ.get('WORKSPACE_SMTP_USER')
            if username:
                client.login(username, os.environ.get('WORKSPACE_SMTP_PASSWORD', ''))
            client.send_message(message)


class Accounts:
    def __init__(self, store, mailer):
        self.store, self.mailer = store, mailer
        self.claim_path = Path(store.path).parent / 'local-transfer.key'
        Path(store.path).chmod(0o600)
        with self.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                backup=Path(store.path).with_suffix('.pre-accounts.sqlite3')
                if not backup.exists():
                    with closing(sqlite3.connect(backup)) as destination:
                        db.backup(destination)
                    backup.chmod(0o600)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                    password TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
                    specialty TEXT NOT NULL, color TEXT NOT NULL DEFAULT 'purple');
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL,
                    expires REAL NOT NULL, seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS spaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, owner_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members (
                    space_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    seniority TEXT NOT NULL DEFAULT 'middle', department TEXT NOT NULL DEFAULT '',
                    manager_id TEXT, team_specialty TEXT,
                    PRIMARY KEY (space_id, user_id));
                CREATE TABLE IF NOT EXISTS project_spaces (
                    project_id TEXT PRIMARY KEY, space_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS grants (
                    project_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
                    PRIMARY KEY (project_id, user_id));
                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, space_id TEXT NOT NULL,
                    email TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL,
                    created_by TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS telegram_team_invites (
                    id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, space_id TEXT NOT NULL,
                    role TEXT NOT NULL, expires REAL NOT NULL, created_by TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', accepted_by TEXT, accepted REAL,
                    team_specialty TEXT, manager_id TEXT);
                CREATE INDEX IF NOT EXISTS telegram_team_invites_lookup
                    ON telegram_team_invites(space_id, state, expires);
                CREATE TABLE IF NOT EXISTS auth_limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_user_limits (
                    user_id TEXT PRIMARY KEY, daily_limit INTEGER NOT NULL,
                    updated REAL NOT NULL, updated_by TEXT NOT NULL,
                    monthly_limit INTEGER);
                CREATE TABLE IF NOT EXISTS user_plans (
                    user_id TEXT PRIMARY KEY, plan TEXT NOT NULL, expires REAL NOT NULL,
                    updated REAL NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plan_demo_claims (
                    user_id TEXT PRIMARY KEY, expires REAL NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS ai_usage (
                    day TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL, cost REAL NOT NULL, created REAL NOT NULL,
                    user_id TEXT);
                CREATE TABLE IF NOT EXISTS telegram_accounts (
                    telegram_id INTEGER PRIMARY KEY, user_id TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '', chat_id INTEGER NOT NULL,
                    notifications INTEGER NOT NULL DEFAULT 1, linked REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_links (
                    hash TEXT PRIMARY KEY, user_id TEXT, telegram_id INTEGER,
                    state TEXT NOT NULL DEFAULT 'pending', expires REAL NOT NULL,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS telegram_links_expiry ON telegram_links(expires);
                CREATE TABLE IF NOT EXISTS telegram_agent_context (
                    user_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_agent_actions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    block_id TEXT, title TEXT NOT NULL, description TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', expires REAL NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS telegram_agent_actions_expiry
                    ON telegram_agent_actions(user_id,state,expires);
                CREATE TABLE IF NOT EXISTS telegram_notification_outbox (
                    id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
                    content TEXT NOT NULL, button_text TEXT NOT NULL DEFAULT '',
                    callback_data TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS telegram_notification_pending
                    ON telegram_notification_outbox(state,created);
                CREATE TABLE IF NOT EXISTS telegram_team_context (
                    user_id TEXT PRIMARY KEY, space_id TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS team_events (
                    id TEXT PRIMARY KEY, space_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    target_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS team_events_space ON team_events(space_id,created DESC);
                CREATE TABLE IF NOT EXISTS email_links (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL,
                    password TEXT NOT NULL, expires REAL NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS email_links_user ON email_links(user_id, expires);
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY, project_id TEXT, block_id TEXT,
                    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    assignee_id TEXT NOT NULL, created_by TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'todo', due REAL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS work_items_assignee
                    ON work_items(assignee_id, status, updated DESC);
                CREATE INDEX IF NOT EXISTS work_items_project
                    ON work_items(project_id, updated DESC);
                CREATE TABLE IF NOT EXISTS account_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_user_state (
                    user_id TEXT PRIMARY KEY, blocked INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL, updated_by TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_audit (
                    id TEXT PRIMARY KEY, admin_id TEXT NOT NULL, action TEXT NOT NULL,
                    target_id TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS admin_audit_created ON admin_audit(created DESC);
                CREATE TABLE IF NOT EXISTS account_security_events (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS account_security_events_user
                    ON account_security_events(user_id,created DESC);
                CREATE TABLE IF NOT EXISTS notification_reads (
                    user_id TEXT NOT NULL, event_key TEXT NOT NULL, read REAL NOT NULL,
                    PRIMARY KEY (user_id,event_key));
                CREATE TABLE IF NOT EXISTS bpmn_versions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, block_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, xml TEXT NOT NULL, created REAL NOT NULL,
                    user_id TEXT NOT NULL,
                    UNIQUE(project_id, block_id, revision));
                CREATE INDEX IF NOT EXISTS bpmn_versions_lookup
                    ON bpmn_versions(project_id, block_id, created DESC);
            ''')
            member_columns = {row['name'] for row in db.execute('PRAGMA table_info(members)')}
            if 'seniority' not in member_columns:
                db.execute("ALTER TABLE members ADD COLUMN seniority TEXT NOT NULL DEFAULT 'middle'")
            if 'department' not in member_columns:
                db.execute("ALTER TABLE members ADD COLUMN department TEXT NOT NULL DEFAULT ''")
            if 'manager_id' not in member_columns:
                db.execute('ALTER TABLE members ADD COLUMN manager_id TEXT')
            if 'team_specialty' not in member_columns:
                db.execute('ALTER TABLE members ADD COLUMN team_specialty TEXT')
            invite_columns = {row['name'] for row in db.execute('PRAGMA table_info(telegram_team_invites)')}
            if 'team_specialty' not in invite_columns:
                db.execute('ALTER TABLE telegram_team_invites ADD COLUMN team_specialty TEXT')
            if 'manager_id' not in invite_columns:
                db.execute('ALTER TABLE telegram_team_invites ADD COLUMN manager_id TEXT')
            if 'user_id' not in {row['name'] for row in db.execute('PRAGMA table_info(ai_usage)')}:
                db.execute('ALTER TABLE ai_usage ADD COLUMN user_id TEXT')
            if 'monthly_limit' not in {row['name'] for row in db.execute('PRAGMA table_info(agent_user_limits)')}:
                db.execute('ALTER TABLE agent_user_limits ADD COLUMN monthly_limit INTEGER')
            db.execute('CREATE INDEX IF NOT EXISTS ai_usage_user_day ON ai_usage(user_id,day)')
            if not db.execute("SELECT 1 FROM account_meta WHERE key='migration_claimed'").fetchone():
                if not db.execute("SELECT 1 FROM account_meta WHERE key='migration_hash'").fetchone():
                    key = secrets.token_urlsafe(32)
                    fd = os.open(self.claim_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, 'w') as f:
                        f.write(key)
                    db.execute("INSERT INTO account_meta VALUES ('migration_hash',?)", (digest(key),))

    def db(self):
        db = self.store.connect()
        db.row_factory = sqlite3.Row
        return db

    def limit(self, category, identity, maximum=8, seconds=900, message='Слишком много попыток. Попробуйте позже.'):
        key = digest(category + ':' + identity)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_limits WHERE expires < ?', (time.time(),))
            row = db.execute('SELECT * FROM auth_limits WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= maximum:
                raise AccessError(message, 429, 'rate_limit')
            db.execute('INSERT INTO auth_limits VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                       (key, 1, time.time()+seconds))

    @staticmethod
    def _active_plan(db, user):
        row=db.execute('SELECT plan,expires FROM user_plans WHERE user_id=?',(user,)).fetchone()
        if row and row['plan'] in PLAN_LIMITS and row['expires']>time.time():
            return row['plan'],row['expires']
        return 'free',None

    def demo_purchase_plan(self, user, plan):
        if plan not in ('pro','team'):
            raise ValueError('Выберите тариф Pro или Team.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM users WHERE id=?',(user,)).fetchone():
                raise AccessError('Пользователь не найден.',404,'user_missing')
            existing=db.execute('SELECT plan,expires,updated_by FROM user_plans WHERE user_id=?',(user,)).fetchone()
            if existing and existing['expires']>time.time() and existing['updated_by']!='demo':
                raise AccessError('Тариф уже выдан администратором.',409,'plan_admin_grant')
            claim=db.execute('SELECT expires FROM plan_demo_claims WHERE user_id=?',(user,)).fetchone()
            stamp=time.time()
            expires=claim['expires'] if claim and claim['expires']>stamp else stamp+30*86400
            db.execute('''INSERT INTO plan_demo_claims (user_id,expires,created) VALUES (?,?,?)
                          ON CONFLICT(user_id) DO UPDATE SET expires=excluded.expires,created=excluded.created''',
                       (user,expires,stamp))
            db.execute('''INSERT INTO user_plans (user_id,plan,expires,updated,updated_by)
                          VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                          plan=excluded.plan,expires=excluded.expires,updated=excluded.updated,
                          updated_by=excluded.updated_by''',(user,plan,expires,stamp,'demo'))
        return {'plan':plan,'expires':expires,'demo':True}

    def agent_quota(self, user):
        today=datetime.now(timezone.utc).date().isoformat()
        with self.db() as db:
            custom=db.execute('SELECT daily_limit,monthly_limit FROM agent_user_limits WHERE user_id=?',(user,)).fetchone()
            plan,plan_expires=self._active_plan(db,user)
            demo=db.execute('SELECT expires FROM plan_demo_claims WHERE user_id=?',(user,)).fetchone()
            used=db.execute('SELECT count,expires FROM auth_limits WHERE key=? AND expires>?',
                            (digest('agent-day:'+user+':'+today),time.time())).fetchone()
            monthly=db.execute('SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) '
                               'FROM ai_usage WHERE user_id=? AND day>=? AND day<=?',
                               (user,today[:7]+'-01',today)).fetchone()
        month_limit=custom['monthly_limit'] if custom and custom['monthly_limit'] is not None else PLAN_LIMITS[plan][1]
        month_used=monthly[0]+monthly[1]
        return {'plan':plan,'plan_expires':plan_expires,
                'demo_expires':demo['expires'] if demo else None,
                'daily_limit':custom['daily_limit'] if custom else PLAN_LIMITS[plan][0],
                'used_today':used['count'] if used else 0,
                'resets_at':used['expires'] if used else None,
                'input_tokens_month':monthly[0], 'output_tokens_month':monthly[1],
                'monthly_token_limit':month_limit,'tokens_used_month':month_used,
                'token_percent_month':round(min(100,month_used/max(1,month_limit)*100),1)}

    def limit_agent(self, user):
        now_utc=datetime.now(timezone.utc)
        today=now_utc.date().isoformat()
        key=digest('agent-day:'+user+':'+today)
        expires=(datetime.combine(now_utc.date()+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)).timestamp()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            custom=db.execute('SELECT daily_limit,monthly_limit FROM agent_user_limits WHERE user_id=?',(user,)).fetchone()
            plan,_=self._active_plan(db,user)
            maximum=custom['daily_limit'] if custom else PLAN_LIMITS[plan][0]
            month_limit=custom['monthly_limit'] if custom and custom['monthly_limit'] is not None else PLAN_LIMITS[plan][1]
            if maximum == 0:
                raise AccessError('Агент для этого аккаунта отключён администратором.',403,'agent_disabled')
            month_start=today[:7]+'-01'
            month_used=db.execute('SELECT COALESCE(SUM(input_tokens+output_tokens),0) FROM ai_usage WHERE user_id=? AND day>=?',
                                  (user,month_start)).fetchone()[0]
            if month_used>=month_limit:
                raise AccessError(f'Месячный лимит агента — {month_limit:,} токенов. Он обновится первого числа по UTC.',429,'agent_monthly_limit')
            used=db.execute('SELECT count FROM auth_limits WHERE key=?',(key,)).fetchone()
            if used and used['count']>=maximum:
                raise AccessError(f'Дневной лимит агента — {maximum} запросов. Попробуйте снова после обновления лимита.',429,'rate_limit')
            db.execute('INSERT INTO auth_limits (key,count,expires) VALUES (?,?,?) '
                       'ON CONFLICT(key) DO UPDATE SET count=count+1,expires=excluded.expires',
                       (key,1,expires))

    def refund_agent(self, user):
        today=datetime.now(timezone.utc).date().isoformat()
        with self.db() as db:
            db.execute('UPDATE auth_limits SET count=count-1 WHERE key=? AND count>0',
                       (digest('agent-day:'+user+':'+today),))

    @staticmethod
    def public_user(row):
        result = {key: row[key] for key in ('id', 'email', 'name', 'specialty', 'color')}
        result['telegram_only'] = result['email'].endswith('@telegram.faccet.local')
        if result['telegram_only']:
            result['email'] = ''
        return result

    def register(self, data):
        email = email_address(data.get('email'))
        name = text(data.get('name'), 100)
        specialty = data.get('specialty', 'business')
        if specialty not in SPECIALTIES:
            raise ValueError('Неизвестная специализация.')
        encoded = password_hash(data.get('password'))
        with self.db() as db:
            if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                return
            identifier, space = secrets.token_hex(16), secrets.token_hex(16)
            db.execute('INSERT INTO users (id,email,name,password,specialty) VALUES (?,?,?,?,?)',
                       (identifier,email,name,encoded,specialty))
            db.execute('INSERT INTO spaces VALUES (?,?,?,?)', (space,'Личное','personal',identifier))
            db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)', (space,identifier,'owner'))
        self.issue_mail(email, 'verify')

    def issue_mail(self, email, kind):
        email = email_address(email)
        with self.db() as db:
            user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if not user or (kind == 'verify' and user['verified']) or (kind == 'reset' and not user['verified']):
                return
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO tokens VALUES (?,?,?,?)',
                       (digest(token), user['id'], kind, time.time() + (86400 if kind == 'verify' else 1800)))
        subject = 'Подтверждение почты' if kind == 'verify' else 'Восстановление пароля'
        action = 'Подтвердить почту' if kind == 'verify' else 'Восстановить пароль'
        lifetime = '24 часа' if kind == 'verify' else '30 минут'
        url = f'{self.mailer.base_url}/#{kind}={token}'
        plain = (f'Здравствуйте!\n\nВы запросили действие «{action}» в Facet.\n'
                 f'Откройте безопасную ссылку:\n{url}\n\n'
                 f'Ссылка действует {lifetime} и может быть использована один раз.\n'
                 'Если вы не запрашивали это действие, просто проигнорируйте письмо.\n\nКоманда Facet')
        safe_url = html.escape(url, quote=True)
        rich = f'''<!doctype html><html lang="ru"><body style="margin:0;background:#eef4ff;color:#172844;font:16px Arial,sans-serif">
<div style="max-width:560px;margin:32px auto;padding:32px;border:1px solid #cad8ee;border-radius:24px;background:#fff">
<p style="margin:0 0 12px;color:#5a6e8d;font-size:13px;letter-spacing:2px;text-transform:uppercase">Facet</p>
<h1 style="margin:0 0 18px;font-size:28px">{html.escape(subject)}</h1>
<p>Здравствуйте! Вы запросили действие в рабочем пространстве Facet.</p>
<p style="margin:28px 0"><a href="{safe_url}" style="display:inline-block;padding:14px 22px;border-radius:12px;background:#3979df;color:#fff;text-decoration:none;font-weight:bold">{html.escape(action)}</a></p>
<p style="color:#5a6e8d">Ссылка действует {lifetime} и может быть использована один раз.</p>
<p style="color:#5a6e8d">Если вы не запрашивали это действие, проигнорируйте письмо.</p>
</div></body></html>'''
        self.mailer.send(email, f'Facet — {subject.lower()}', plain, rich)

    def use_token(self, token, kind, password=None):
        token = text(token, 200)
        encoded = password_hash(password) if kind == 'reset' else None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tokens WHERE hash=? AND kind=? AND expires>?',
                             (digest(token), kind, time.time())).fetchone()
            if not row:
                raise ValueError('Ссылка истекла или уже использована. Запросите новую.')
            if kind == 'verify':
                db.execute('UPDATE users SET verified=1 WHERE id=?', (row['user_id'],))
            else:
                db.execute('UPDATE users SET password=? WHERE id=?', (encoded, row['user_id']))
                db.execute('DELETE FROM sessions WHERE user_id=?', (row['user_id'],))
            db.execute('DELETE FROM tokens WHERE user_id=? AND kind=?', (row['user_id'],kind))

    def login(self, email, password):
        email = email_address(email)
        with self.db() as db:
            user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        # Для неизвестного адреса также выполняем дорогое хеширование.
        if not user:
            password_matches(password, 'scrypt$131072$8$1$'+'00'*16+'$'+'00'*64)
            raise AccessError('Неверная почта или пароль.', 401, 'credentials')
        if not password_matches(password, user['password']):
            raise AccessError('Неверная почта или пароль.', 401, 'credentials')
        if not user['verified']:
            raise AccessError('Подтвердите почту по ссылке из письма.', 403, 'verify_email')
        return self.create_session(user['id'])

    def create_session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db() as db:
            user = db.execute('SELECT u.* FROM users u LEFT JOIN admin_user_state a ON a.user_id=u.id '
                              'WHERE u.id=? AND u.verified=1 AND COALESCE(a.blocked,0)=0', (user_id,)).fetchone()
            if not user:
                raise AccessError('Аккаунт недоступен.', 401, 'credentials')
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                       (digest(token),user['id'],csrf,time.time()+SESSION_AGE,time.time()))
        return token, self.public_user(user), csrf

    def telegram_start(self, user_id=None):
        raw = secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM telegram_links WHERE expires<?', (time.time(),))
            if user_id and not db.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
                raise AccessError('Аккаунт недоступен.', 401, 'credentials')
            db.execute('INSERT INTO telegram_links (hash,user_id,expires,created) VALUES (?,?,?,?)',
                       (digest(raw), user_id, time.time()+600, time.time()))
        return raw

    def telegram_confirm(self, raw, telegram):
        raw = text(raw, 100)
        telegram_id = int(telegram.get('id'))
        chat_id = int(telegram.get('chat_id', telegram_id))
        username = text(str(telegram.get('username') or ''), 64, False)
        first_name = text(str(telegram.get('first_name') or ''), 100, False)
        last_name = text(str(telegram.get('last_name') or ''), 100, False)
        if telegram_id <= 0 or chat_id <= 0:
            raise ValueError('Некорректный аккаунт Telegram.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            link = db.execute("SELECT * FROM telegram_links WHERE hash=? AND state='pending' AND expires>?",
                              (digest(raw), time.time())).fetchone()
            if not link:
                raise AccessError('Ссылка входа истекла. Запросите новую на сайте.', 400, 'telegram_link')
            bound = db.execute('SELECT user_id FROM telegram_accounts WHERE telegram_id=?',
                               (telegram_id,)).fetchone()
            user_id = link['user_id']
            created = False
            if user_id and bound and bound['user_id'] != user_id:
                raise AccessError('Этот Telegram уже привязан к другому аккаунту.', 409, 'telegram_bound')
            if not user_id and bound:
                user_id = bound['user_id']
            if not user_id:
                user_id, space = secrets.token_hex(16), secrets.token_hex(16)
                display_name = (first_name+' '+last_name).strip() or ('@'+username if username else 'Пользователь Telegram')
                internal_email = f'telegram-{telegram_id}@telegram.faccet.local'
                db.execute('INSERT INTO users (id,email,name,password,verified,specialty) VALUES (?,?,?,?,1,?)',
                           (user_id, internal_email, display_name, 'telegram-only', 'business'))
                db.execute('INSERT INTO spaces VALUES (?,?,?,?)', (space,'Личное','personal',user_id))
                db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)', (space,user_id,'owner'))
                created = True
            db.execute('''INSERT INTO telegram_accounts
                          (telegram_id,user_id,username,first_name,last_name,chat_id,linked)
                          VALUES (?,?,?,?,?,?,?)
                          ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,
                          first_name=excluded.first_name,last_name=excluded.last_name,
                          chat_id=excluded.chat_id,linked=excluded.linked''',
                       (telegram_id,user_id,username,first_name,last_name,chat_id,time.time()))
            db.execute("UPDATE telegram_links SET user_id=?,telegram_id=?,state='confirmed' WHERE hash=?",
                       (user_id,telegram_id,digest(raw)))
            if link['user_id']:
                self._security_event(db, user_id, 'telegram_linked', '@'+username if username else '')
        return {'user_id':user_id, 'created':created}

    def telegram_complete(self, raw):
        raw = text(raw, 100)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            link = db.execute('SELECT * FROM telegram_links WHERE hash=?', (digest(raw),)).fetchone()
            if not link or link['expires'] <= time.time():
                if link:
                    db.execute('DELETE FROM telegram_links WHERE hash=?', (digest(raw),))
                raise AccessError('Ссылка входа истекла. Начните заново.', 400, 'telegram_link')
            if link['state'] != 'confirmed' or not link['user_id']:
                return None
            user_id = link['user_id']
            db.execute('DELETE FROM telegram_links WHERE hash=?', (digest(raw),))
        return self.create_session(user_id)

    def telegram_account(self, user_id):
        with self.db() as db:
            row = db.execute('SELECT telegram_id,username,notifications,linked FROM telegram_accounts WHERE user_id=?',
                             (user_id,)).fetchone()
            return dict(row) if row else None

    def security_events(self, user_id, limit=8):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                'SELECT kind,details,created FROM account_security_events WHERE user_id=? '
                'ORDER BY created DESC LIMIT ?', (user_id, max(1, min(int(limit), 20))))]

    @staticmethod
    def _security_event(db, user_id, kind, details=''):
        db.execute('INSERT INTO account_security_events VALUES (?,?,?,?,?)',
                   (secrets.token_hex(16), user_id, kind, details, time.time()))

    def unlink_login_method(self, user_id, method, password, current_token=''):
        if method not in ('email', 'telegram'):
            raise ValueError('Неизвестный способ входа.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            telegram = db.execute('SELECT * FROM telegram_accounts WHERE user_id=?', (user_id,)).fetchone()
            if not user or not password_matches(password, user['password']):
                raise AccessError('Неверный текущий пароль.', 403, 'password')
            has_email = not user['email'].endswith('@telegram.faccet.local')
            if method == 'telegram':
                if not telegram:
                    raise AccessError('Telegram не подключён.', 409, 'telegram_missing')
                if not has_email:
                    raise AccessError('Сначала добавьте почту: нельзя отключить единственный способ входа.', 409, 'last_login_method')
                db.execute('DELETE FROM telegram_accounts WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM telegram_links WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM telegram_agent_context WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM telegram_team_context WHERE user_id=?', (user_id,))
                self._security_event(db, user_id, 'telegram_unlinked')
            else:
                if not has_email:
                    raise AccessError('Почта не подключена.', 409, 'email_missing')
                if not telegram:
                    raise AccessError('Сначала привяжите Telegram: нельзя отключить единственный способ входа.', 409, 'last_login_method')
                internal = f"telegram-{telegram['telegram_id']}@telegram.faccet.local"
                if db.execute('SELECT 1 FROM users WHERE email=? AND id<>?', (internal, user_id)).fetchone():
                    internal = f"telegram-{telegram['telegram_id']}-{secrets.token_hex(4)}@telegram.faccet.local"
                db.execute("UPDATE users SET email=?,password='telegram-only',verified=1 WHERE id=?", (internal, user_id))
                db.execute('DELETE FROM tokens WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM email_links WHERE user_id=?', (user_id,))
                if current_token:
                    db.execute('DELETE FROM sessions WHERE user_id=? AND token<>?', (user_id, digest(current_token)))
                else:
                    db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
                self._security_event(db, user_id, 'email_unlinked')
            updated = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        return self.public_user(updated)

    def web_notifications(self, user_id, limit=50):
        now_stamp = time.time()
        items = []
        with self.db() as db:
            tasks = db.execute('''SELECT w.id,w.title,w.due,w.created,w.updated,w.created_by,u.name creator
                FROM work_items w LEFT JOIN users u ON u.id=w.created_by
                WHERE w.assignee_id=? AND w.status<>'done' ORDER BY w.updated DESC LIMIT 60''',
                (user_id,)).fetchall()
            for row in tasks:
                if row['created_by'] != user_id:
                    items.append({'key':f'task:{row["id"]}:assigned','kind':'task','title':'Вам назначена задача',
                                  'body':row['title']+(f' · {row["creator"]}' if row['creator'] else ''),
                                  'created':row['created'],'target':'tasks'})
                if row['due'] and row['due'] <= now_stamp + 86400:
                    items.append({'key':f'task:{row["id"]}:due:{int(row["due"])}','kind':'deadline',
                                  'title':'Срок задачи '+('просрочен' if row['due'] < now_stamp else 'приближается'),
                                  'body':row['title'],'created':max(row['updated'], row['due']-86400),'target':'tasks'})
            for row in db.execute("SELECT id,title,created FROM telegram_agent_actions WHERE user_id=? AND state='pending' AND expires>? ORDER BY created DESC LIMIT 30", (user_id, now_stamp)):
                items.append({'key':f'approval:{row["id"]}','kind':'approval','title':'Агент ждёт подтверждения',
                              'body':row['title'],'created':row['created'],'target':'agent'})
            for row in db.execute('''SELECT e.id,e.kind,e.details,e.created,s.name space_name,a.name actor_name
                FROM team_events e JOIN members m ON m.space_id=e.space_id JOIN spaces s ON s.id=e.space_id
                LEFT JOIN users a ON a.id=e.actor_id WHERE m.user_id=? AND e.actor_id<>?
                ORDER BY e.created DESC LIMIT 40''', (user_id,user_id)):
                labels={'invite_created':'Новое приглашение в команде','member_joined':'Новый участник команды',
                        'member_removed':'Изменён состав команды','role_changed':'Изменена роль участника',
                        'profile_changed':'Обновлена структура команды','ownership_transferred':'Передано владение командой'}
                if row['kind'] not in labels:
                    continue
                items.append({'key':f'team:{row["id"]}','kind':'team','title':labels[row['kind']],
                              'body':f'{row["space_name"]} · {row["actor_name"] or "Участник"}',
                              'created':row['created'],'target':'team'})
            items.sort(key=lambda item:item['created'], reverse=True)
            items=items[:max(1,min(int(limit),100))]
            read={row['event_key'] for row in db.execute('SELECT event_key FROM notification_reads WHERE user_id=?',(user_id,))}
        for item in items:
            item['unread']=item['key'] not in read
        return {'items':items,'unread':sum(item['unread'] for item in items)}

    def mark_web_notifications(self, user_id, keys=None):
        available=self.web_notifications(user_id,100)['items']
        allowed={item['key'] for item in available}
        selected=allowed if not keys else {text(str(key),240) for key in keys if str(key) in allowed}
        with self.db() as db:
            db.executemany('INSERT OR REPLACE INTO notification_reads VALUES (?,?,?)',
                           ((user_id,key,time.time()) for key in selected))
        return self.web_notifications(user_id,100)['unread']

    def global_search(self, user_id, query, limit=40):
        query=text(query,100).casefold()
        if len(query)<2:
            return []
        results=[]
        def add(kind,title,subtitle='',**extra):
            haystack=(str(title)+' '+str(subtitle)).casefold()
            if query not in haystack:
                return
            results.append({'kind':kind,'title':str(title),'subtitle':str(subtitle),
                            'score':0 if str(title).casefold().startswith(query) else 1,**extra})
        with self.db() as db:
            project_rows=db.execute('''SELECT DISTINCT p.id,p.document,ps.space_id
                FROM projects p JOIN project_spaces ps ON ps.project_id=p.id
                JOIN members m ON m.space_id=ps.space_id AND m.user_id=?
                LEFT JOIN grants g ON g.project_id=p.id AND g.user_id=?
                WHERE m.role IN ('owner','admin') OR g.role IS NOT NULL''',(user_id,user_id)).fetchall()
            for row in project_rows:
                try: project=json.loads(row['document'])
                except (TypeError,json.JSONDecodeError): continue
                common={'project_id':row['id'],'space_id':row['space_id']}
                add('project',project.get('name','Проект'),project.get('goal',''),view='overview',**common)
                for block in project.get('blocks',[]):
                    block_id=block.get('id')
                    subtitle=project.get('name','Проект')+' · '+str(block.get('description',''))
                    add('block',block.get('name','Блок'),subtitle,block_id=block_id,view='overview',**common)
                    for view,key,label in [('requirements','requirements','Требования'),('technical','technical','API и данные')]:
                        content=block.get(key,'')
                        if content and query in str(content).casefold():
                            add(view,label+' · '+block.get('name','Блок'),str(content)[:180],block_id=block_id,view=view,**common)
                    xml=block.get('bpmn','')
                    if xml:
                        try:
                            root=ET.fromstring(xml)
                            for node in root.iter():
                                name=node.attrib.get('name','').strip()
                                if name and query in name.casefold():
                                    add('bpmn',name,project.get('name','Проект')+' · '+block.get('name','Блок'),
                                        block_id=block_id,element_id=node.attrib.get('id'),view='bpmn',**common)
                        except ET.ParseError: pass
                for term in project.get('glossary',[]):
                    if isinstance(term,dict):
                        add('glossary',term.get('term') or term.get('name') or 'Термин',term.get('definition',''),
                            term_id=term.get('id'),view='glossary',**common)
            task_rows=db.execute('''SELECT w.id,w.title,w.description,w.status,p.document
                FROM work_items w LEFT JOIN projects p ON p.id=w.project_id
                WHERE w.assignee_id=? OR w.created_by=? ORDER BY w.updated DESC LIMIT 200''',(user_id,user_id)).fetchall()
            for row in task_rows:
                project_name=''
                try: project_name=json.loads(row['document']).get('name','') if row['document'] else ''
                except (TypeError,json.JSONDecodeError): pass
                add('task',row['title'],project_name+' · '+row['description'],target_section='tasks')
            member_rows=db.execute('''SELECT DISTINCT u.id,u.name,u.email,u.specialty,s.name space_name
                FROM members mine JOIN members other ON other.space_id=mine.space_id
                JOIN users u ON u.id=other.user_id JOIN spaces s ON s.id=mine.space_id
                WHERE mine.user_id=? LIMIT 250''',(user_id,)).fetchall()
            for row in member_rows:
                email='' if row['email'].endswith('@telegram.faccet.local') else row['email']
                add('member',row['name'],row['space_name']+' · '+email,target_section='team')
        results.sort(key=lambda item:(item.pop('score'),item['kind'],item['title'].casefold()))
        return results[:max(1,min(int(limit),60))]

    def project_analytics(self, user_id, space, period=30):
        period=max(7,min(int(period),90))
        now_stamp=time.time();start_stamp=now_stamp-period*86400
        with self.db() as db:
            member=self.space_role(db,user_id,space)
            rows=db.execute('''SELECT p.id,p.document,g.role project_role FROM projects p
                JOIN project_spaces ps ON ps.project_id=p.id
                LEFT JOIN grants g ON g.project_id=p.id AND g.user_id=? WHERE ps.space_id=?''',(user_id,space)).fetchall()
            if member['role'] not in ('owner','admin'):
                rows=[row for row in rows if row['project_role']]
            projects=[];project_ids=[];total_blocks=total_bpmn=total_approved=total_complete=0
            total_statuses={'draft':0,'review':0,'approved':0}
            for row in rows:
                try: document=json.loads(row['document'])
                except (TypeError,json.JSONDecodeError): continue
                blocks=document.get('blocks',[]);project_ids.append(row['id'])
                statuses={key:sum(block.get('status','draft')==key for block in blocks) for key in ('draft','review','approved')}
                bpmn_count=0;warnings=0;elements=flows=0;complete=0
                for block in blocks:
                    xml=block.get('bpmn','')
                    checks=[block.get('description'),xml,block.get('requirements'),block.get('technical'),block.get('owner')]
                    uml=block.get('uml') or {};checks.append(bool(uml.get('participants') or uml.get('messages')) if isinstance(uml,dict) else bool(uml))
                    complete+=sum(bool(value) for value in checks)
                    if not xml: continue
                    bpmn_count+=1
                    try:
                        root=ET.fromstring(xml);tags=[node.tag.rsplit('}',1)[-1] for node in root.iter()]
                        flow_count=tags.count('sequenceFlow');node_count=sum(tag in {'task','userTask','serviceTask','manualTask','businessRuleTask','scriptTask','sendTask','receiveTask','startEvent','endEvent','intermediateCatchEvent','intermediateThrowEvent','exclusiveGateway','parallelGateway','inclusiveGateway','eventBasedGateway','subProcess'} for tag in tags)
                        elements+=node_count;flows+=flow_count
                        warnings+=int('startEvent' not in tags)+int('endEvent' not in tags)+int(node_count>1 and flow_count==0)
                    except ET.ParseError: warnings+=1
                block_count=len(blocks);readiness=round(statuses['approved']/max(1,block_count)*100)
                completeness=round(complete/max(1,block_count*6)*100)
                projects.append({'id':row['id'],'name':document.get('name','Без названия'),'blocks':block_count,
                    'bpmn':bpmn_count,'elements':elements,'flows':flows,'warnings':warnings,
                    'readiness':readiness,'completeness':completeness,'statuses':statuses,
                    'updated':document.get('updated','')})
                total_blocks+=block_count;total_bpmn+=bpmn_count;total_approved+=statuses['approved']
                total_complete+=complete
                for key in total_statuses:
                    total_statuses[key]+=statuses[key]
            tasks=[]
            if project_ids:
                marks=','.join('?' for _ in project_ids)
                tasks=[dict(row) for row in db.execute(f'''SELECT w.*,u.name assignee_name FROM work_items w
                    LEFT JOIN users u ON u.id=w.assignee_id WHERE w.project_id IN ({marks})''',project_ids)]
            task_statuses={key:sum(task['status']==key for task in tasks) for key in ('todo','in_progress','done')}
            active=[task for task in tasks if task['status']!='done'];overdue=sum(bool(task['due'] and task['due']<now_stamp) for task in active)
            due_soon=sum(bool(task['due'] and now_stamp<=task['due']<=now_stamp+7*86400) for task in active)
            workload={}
            for task in active:
                entry=workload.setdefault(task['assignee_id'],{'id':task['assignee_id'],'name':task['assignee_name'] or 'Участник','todo':0,'in_progress':0,'overdue':0})
                entry[task['status']]+=1;entry['overdue']+=int(bool(task['due'] and task['due']<now_stamp))
            day_start=datetime.fromtimestamp(start_stamp,timezone.utc).date()
            days=[(day_start+timedelta(days=index)).isoformat() for index in range(period+1)]
            task_created={};task_done={};versions={}
            if project_ids:
                marks=','.join('?' for _ in project_ids);params=[start_stamp,*project_ids]
                task_created={row['day']:row['count'] for row in db.execute(
                    f"SELECT date(created,'unixepoch') day,COUNT(*) count FROM work_items WHERE created>=? AND project_id IN ({marks}) GROUP BY day",params)}
                task_done={row['day']:row['count'] for row in db.execute(
                    f"SELECT date(updated,'unixepoch') day,COUNT(*) count FROM work_items WHERE status='done' AND updated>=? AND project_id IN ({marks}) GROUP BY day",params)}
                versions={row['day']:row['count'] for row in db.execute(
                    f"SELECT date(created,'unixepoch') day,COUNT(*) count FROM bpmn_versions WHERE created>=? AND project_id IN ({marks}) GROUP BY day",params)}
            timeline=[{'day':day,'created':task_created.get(day,0),'done':task_done.get(day,0),'bpmn':versions.get(day,0)} for day in days]
            limit_row=db.execute('SELECT count,expires FROM auth_limits WHERE key=? AND expires>?',
                                 (digest('agent-day:'+user_id),now_stamp)).fetchone()
            custom_limit=db.execute('SELECT daily_limit FROM agent_user_limits WHERE user_id=?',(user_id,)).fetchone()
        projects.sort(key=lambda item:(-item['warnings'],item['readiness'],item['name'].casefold()))
        return {'period':period,'summary':{'projects':len(projects),'blocks':total_blocks,'bpmn':total_bpmn,
            'readiness':round(total_approved/max(1,total_blocks)*100),
            'completeness':round(total_complete/max(1,total_blocks*6)*100),
            'block_statuses':total_statuses,'task_statuses':task_statuses,
            'active_tasks':len(active),'due_soon':due_soon,'overdue':overdue},
            'projects':projects,'workload':sorted(workload.values(),key=lambda item:-(item['todo']+item['in_progress'])),
            'timeline':timeline,'agent':{'used':limit_row['count'] if limit_row else 0,'limit':custom_limit['daily_limit'] if custom_limit else 20,
            'resets_at':limit_row['expires'] if limit_row else None}}

    def telegram_agent_project(self, user, project_id=None):
        with self.db() as db:
            if project_id:
                self.permission(db,user,project_id,'viewer')
                db.execute('''INSERT INTO telegram_agent_context VALUES (?,?,?)
                              ON CONFLICT(user_id) DO UPDATE SET project_id=excluded.project_id,updated=excluded.updated''',
                           (user,project_id,time.time()))
                return project_id
            row=db.execute('SELECT project_id FROM telegram_agent_context WHERE user_id=?',(user,)).fetchone()
            if not row:
                return None
            try: self.permission(db,user,row['project_id'],'viewer')
            except AccessError:
                db.execute('DELETE FROM telegram_agent_context WHERE user_id=?',(user,))
                return None
            return row['project_id']

    def create_telegram_agent_action(self,user,project_id,title,description='',block_id=None):
        title=text(title,240);description=text(description or '',4000,required=False)
        with self.db() as db:
            self.permission(db,user,project_id,'editor')
            db.execute('DELETE FROM telegram_agent_actions WHERE expires<?',(time.time(),))
            identifier=secrets.token_hex(6)
            db.execute('INSERT INTO telegram_agent_actions VALUES (?,?,?,?,?,?,?,?,?)',
                       (identifier,user,project_id,block_id,title,description,'pending',time.time()+1800,time.time()))
        return identifier

    def telegram_agent_action(self,user,identifier,consume=False):
        with self.db() as db:
            row=db.execute("SELECT * FROM telegram_agent_actions WHERE id=? AND user_id=? AND state='pending' AND expires>?",
                           (identifier,user,time.time())).fetchone()
            if not row: raise AccessError('Предложение истекло. Запустите анализ заново.',404,'agent_action')
            result=dict(row)
            if consume:
                db.execute("UPDATE telegram_agent_actions SET state='done' WHERE id=? AND state='pending'",(identifier,))
        if consume:
            try:
                result['task_id']=self.create_work_item(user,result['title'],result['project_id'],result['block_id'],user,result['description'])
            except Exception:
                with self.db() as db: db.execute("UPDATE telegram_agent_actions SET state='pending' WHERE id=?",(identifier,))
                raise
        return result

    def telegram_user(self, telegram_id):
        try:
            telegram_id = int(telegram_id)
        except (TypeError, ValueError):
            return None
        with self.db() as db:
            row = db.execute('SELECT u.* FROM telegram_accounts t JOIN users u ON u.id=t.user_id '
                             'LEFT JOIN admin_user_state a ON a.user_id=u.id '
                             'WHERE t.telegram_id=? AND u.verified=1 AND COALESCE(a.blocked,0)=0',
                             (telegram_id,)).fetchone()
            return self.public_user(row) if row else None

    def telegram_notifications(self, user, enabled=None):
        with self.db() as db:
            row = db.execute('SELECT notifications FROM telegram_accounts WHERE user_id=?', (user,)).fetchone()
            if not row:
                raise AccessError('Сначала привяжите Telegram к аккаунту.', 404, 'telegram_account')
            if enabled is not None:
                db.execute('UPDATE telegram_accounts SET notifications=? WHERE user_id=?',
                           (1 if enabled else 0, user))
                return bool(enabled)
            return bool(row['notifications'])

    @staticmethod
    def _queue_telegram(db,event_key,user,content,button_text='',callback_data=''):
        if not user:return
        db.execute('''INSERT OR IGNORE INTO telegram_notification_outbox
                      VALUES (?,?,?,?,?,?,'pending',0,?)''',
                   (secrets.token_hex(12),event_key,user,text(content,3500),
                    text(button_text or '',60,required=False),text(callback_data or '',64,required=False),time.time()))

    def pending_telegram_notifications(self,limit=20):
        with self.db() as db:
            return [dict(row) for row in db.execute('''SELECT o.*,t.chat_id FROM telegram_notification_outbox o
                JOIN telegram_accounts t ON t.user_id=o.user_id AND t.notifications=1
                LEFT JOIN admin_user_state a ON a.user_id=o.user_id
                WHERE o.state='pending' AND o.attempts<5 AND COALESCE(a.blocked,0)=0
                ORDER BY o.created LIMIT ?''',(max(1,min(int(limit),50)),)).fetchall()]

    def finish_telegram_notification(self,identifier,delivered):
        with self.db() as db:
            if delivered: db.execute("UPDATE telegram_notification_outbox SET state='sent' WHERE id=?",(identifier,))
            else: db.execute('UPDATE telegram_notification_outbox SET attempts=attempts+1 WHERE id=?',(identifier,))

    def start_email_link(self, user_id, email, password):
        """Prepare a verified email/password login for an account created through Telegram."""
        email = email_address(email)
        encoded = password_hash(password)
        raw = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not user or not user['email'].endswith('@telegram.faccet.local'):
                raise AccessError('Почта уже подключена к этому аккаунту.', 409, 'email_linked')
            if db.execute('SELECT 1 FROM users WHERE email=? AND id<>?', (email, user_id)).fetchone():
                raise AccessError('Эта почта уже используется другим аккаунтом.', 409, 'email_bound')
            db.execute('DELETE FROM email_links WHERE user_id=? OR expires<?', (user_id, time.time()))
            db.execute('INSERT INTO email_links VALUES (?,?,?,?,?,?)',
                       (digest(raw), user_id, email, encoded, time.time()+86400, time.time()))
        url = f'{self.mailer.base_url}/#email={raw}'
        safe_url = html.escape(url, quote=True)
        plain = (f'Здравствуйте!\n\nПодтвердите добавление адреса {email} к аккаунту Facet:\n{url}\n\n'
                 'Ссылка действует 24 часа и может быть использована один раз.\n'
                 'Если вы не запрашивали это действие, проигнорируйте письмо.\n\nКоманда Facet')
        rich = f'''<!doctype html><html lang="ru"><body style="margin:0;background:#eef4ff;color:#172844;font:16px Arial,sans-serif">
<div style="max-width:560px;margin:32px auto;padding:32px;border:1px solid #cad8ee;border-radius:24px;background:#fff">
<p style="margin:0 0 12px;color:#5a6e8d;font-size:13px;letter-spacing:2px;text-transform:uppercase">Facet</p>
<h1 style="margin:0 0 18px;font-size:28px">Добавление почты</h1>
<p>Подтвердите адрес <strong>{html.escape(email)}</strong> для входа в Facet.</p>
<p style="margin:28px 0"><a href="{safe_url}" style="display:inline-block;padding:14px 22px;border-radius:12px;background:#3979df;color:#fff;text-decoration:none;font-weight:bold">Подтвердить почту</a></p>
<p style="color:#5a6e8d">Ссылка действует 24 часа и может быть использована один раз.</p>
</div></body></html>'''
        self.mailer.send(email, 'Facet — добавление почты', plain, rich)

    def complete_email_link(self, raw):
        raw = text(raw, 200)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            link = db.execute('SELECT * FROM email_links WHERE hash=? AND expires>?',
                              (digest(raw), time.time())).fetchone()
            if not link:
                raise ValueError('Ссылка истекла или уже использована. Запросите новую в профиле.')
            user = db.execute('SELECT * FROM users WHERE id=?', (link['user_id'],)).fetchone()
            if not user or not user['email'].endswith('@telegram.faccet.local'):
                db.execute('DELETE FROM email_links WHERE user_id=?', (link['user_id'],))
                raise AccessError('Почта уже подключена к аккаунту.', 409, 'email_linked')
            if db.execute('SELECT 1 FROM users WHERE email=? AND id<>?', (link['email'], link['user_id'])).fetchone():
                raise AccessError('Эта почта уже используется другим аккаунтом.', 409, 'email_bound')
            db.execute('UPDATE users SET email=?,password=?,verified=1 WHERE id=?',
                       (link['email'], link['password'], link['user_id']))
            db.execute('DELETE FROM email_links WHERE user_id=?', (link['user_id'],))
            self._security_event(db, link['user_id'], 'email_linked', link['email'])
            updated = db.execute('SELECT * FROM users WHERE id=?', (link['user_id'],)).fetchone()
        return self.public_user(updated)

    def create_work_item(self, user, title, project_id=None, block_id=None, assignee_id=None, description='', due=None):
        title = text(title, 240)
        description = text(description or '', 4000, required=False)
        assignee_id = assignee_id or user
        due_stamp=None
        if due not in (None,''):
            try:
                if isinstance(due,(int,float)): due_stamp=float(due)
                else:
                    parsed=datetime.fromisoformat(str(due).replace('Z','+00:00'))
                    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
                    due_stamp=parsed.timestamp()
            except (ValueError,TypeError,OverflowError):
                raise ValueError('Укажите корректный срок задачи.') from None
            if due_stamp<=time.time(): raise ValueError('Срок задачи должен быть в будущем.')
        identifier = secrets.token_hex(12)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if project_id:
                _, space = self.permission(db, user, project_id, 'editor')
                self.space_role(db, assignee_id, space)
                self.permission(db, assignee_id, project_id, 'viewer')
                project = db.execute('SELECT document FROM projects WHERE id=?', (project_id,)).fetchone()
                if not project:
                    raise KeyError()
                if block_id and not any(item.get('id') == block_id for item in json.loads(project['document']).get('blocks', [])):
                    raise ValueError('Блок проекта не найден.')
            elif assignee_id != user:
                shared = db.execute(
                    "SELECT 1 FROM members actor JOIN spaces s ON s.id=actor.space_id AND s.kind='team' "
                    'JOIN members colleague ON colleague.space_id=s.id '
                    'WHERE actor.user_id=? AND colleague.user_id=? LIMIT 1', (user, assignee_id)).fetchone()
                if not shared:
                    raise AccessError('Задачу можно поручить только участнику вашей команды.')
            stamp = time.time()
            db.execute('INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (identifier, project_id, block_id, title, description, assignee_id, user,
                        'todo', due_stamp, stamp, stamp))
            if assignee_id != user:
                actor=db.execute('SELECT name FROM users WHERE id=?',(user,)).fetchone()
                project_name=''
                if project_id:
                    document=db.execute('SELECT document FROM projects WHERE id=?',(project_id,)).fetchone()
                    if document:
                        try: project_name=json.loads(document['document']).get('name','')
                        except (TypeError,json.JSONDecodeError): pass
                scope=f'\nПроект: {project_name}' if project_name else ''
                self._queue_telegram(db,f'task:{identifier}:assigned',assignee_id,
                    f'📋 Вам назначена задача\n\n{title}{scope}\nПоручил: {actor["name"] if actor else "Участник команды"}',
                    'Открыть задачи','m:t')
        return identifier

    def queue_due_task_reminders(self,horizon=86400):
        current=time.time()
        with self.db() as db:
            rows=db.execute("SELECT id,title,assignee_id,due FROM work_items WHERE status<>'done' AND due>? AND due<=?",
                            (current,current+max(300,min(int(horizon),604800)))).fetchall()
            for row in rows:
                deadline=datetime.fromtimestamp(row['due']).strftime('%d.%m в %H:%M')
                self._queue_telegram(db,f'deadline:{row["id"]}:{int(row["due"])}',row['assignee_id'],
                    f'⏰ Приближается срок задачи\n\n{row["title"]}\nСрок: {deadline}','Открыть задачи','m:t')
        return len(rows)

    def work_assignees(self, user):
        """Return the current user and verified colleagues from shared team spaces."""
        with self.db() as db:
            current = db.execute('SELECT id,name,specialty,color FROM users WHERE id=? AND verified=1', (user,)).fetchone()
            if not current:
                raise AccessError('Аккаунт недоступен.', 401, 'credentials')
            rows = db.execute(
                "SELECT u.id,u.name,u.specialty,u.color,s.name team_name FROM members actor "
                "JOIN spaces s ON s.id=actor.space_id AND s.kind='team' "
                'JOIN members colleague ON colleague.space_id=s.id '
                'JOIN users u ON u.id=colleague.user_id AND u.verified=1 '
                'WHERE actor.user_id=? ORDER BY u.name,s.name', (user,)).fetchall()
        people = {current['id']: {**dict(current), 'teams': [], 'self': True}}
        for row in rows:
            person = people.setdefault(row['id'], {key: row[key] for key in ('id','name','specialty','color')} | {'teams': [], 'self': row['id'] == user})
            if row['team_name'] not in person['teams']:
                person['teams'].append(row['team_name'])
        return sorted(people.values(), key=lambda item: (not item['self'], item['name'].casefold()))

    def work_items(self, user, limit=12, include_created=False):
        limit = max(1, min(int(limit), 30))
        with self.db() as db:
            condition = '(w.assignee_id=? OR w.created_by=?)' if include_created else 'w.assignee_id=?'
            params = (user, user, limit) if include_created else (user, limit)
            rows = db.execute('SELECT w.*,p.document,u.name assignee_name FROM work_items w '
                              'LEFT JOIN projects p ON p.id=w.project_id JOIN users u ON u.id=w.assignee_id '
                              f'WHERE {condition} ORDER BY CASE w.status WHEN "in_progress" THEN 0 '
                              'WHEN "todo" THEN 1 ELSE 2 END,w.updated DESC LIMIT ?', params).fetchall()
            result = []
            for row in rows:
                project_name = ''
                if row['project_id']:
                    try:
                        self.permission(db, user, row['project_id'])
                    except AccessError:
                        continue
                    project_name = json.loads(row['document'])['name'] if row['document'] else ''
                item = {key: row[key] for key in ('id', 'project_id', 'block_id', 'title', 'description',
                                                  'status', 'due', 'created', 'updated', 'assignee_id', 'created_by')}
                item['project_name'] = project_name
                item['assignee_name'] = row['assignee_name']
                item['can_update'] = row['assignee_id'] == user
                result.append(item)
            return result

    def work_items_page(self, user, filter_name='active', page=1, page_size=24):
        """Paginate every visible task, including completed ones, for the web board."""
        if filter_name not in ('active', 'mine', 'created', 'done', 'all'):
            raise ValueError('Неизвестный фильтр задач.')
        page = max(1, min(int(page), 100000))
        page_size = max(1, min(int(page_size), 50))
        with self.db() as db:
            rows = db.execute('SELECT w.*,p.document,u.name assignee_name FROM work_items w '
                              'LEFT JOIN projects p ON p.id=w.project_id JOIN users u ON u.id=w.assignee_id '
                              'WHERE w.assignee_id=? OR w.created_by=? '
                              'ORDER BY CASE w.status WHEN "in_progress" THEN 0 '
                              'WHEN "todo" THEN 1 ELSE 2 END,w.updated DESC', (user, user)).fetchall()
            items = []
            for row in rows:
                project_name = ''
                if row['project_id']:
                    try:
                        self.permission(db, user, row['project_id'])
                    except AccessError:
                        continue
                    project_name = json.loads(row['document'])['name'] if row['document'] else ''
                item = {key: row[key] for key in ('id', 'project_id', 'block_id', 'title', 'description',
                                                  'status', 'due', 'created', 'updated', 'assignee_id', 'created_by')}
                item.update(project_name=project_name, assignee_name=row['assignee_name'],
                            can_update=row['assignee_id'] == user)
                items.append(item)
        counts = {
            'active': sum(item['status'] != 'done' for item in items),
            'todo': sum(item['status'] == 'todo' for item in items),
            'in_progress': sum(item['status'] == 'in_progress' for item in items),
            'mine': sum(item['assignee_id'] == user and item['status'] != 'done' for item in items),
            'created': sum(item['created_by'] == user and item['assignee_id'] != user for item in items),
            'done': sum(item['status'] == 'done' for item in items),
            'all': len(items),
        }
        selected = [item for item in items if (
            filter_name == 'all' or
            filter_name == 'active' and item['status'] != 'done' or
            filter_name == 'mine' and item['assignee_id'] == user and item['status'] != 'done' or
            filter_name == 'created' and item['created_by'] == user and item['assignee_id'] != user or
            filter_name == 'done' and item['status'] == 'done')]
        start = (page - 1) * page_size
        return {'items': selected[start:start + page_size], 'counts': counts,
                'total': len(selected), 'page': page, 'has_more': start + page_size < len(selected)}

    def update_work_item(self, user, identifier, status):
        if status not in ('todo', 'in_progress', 'done'):
            raise ValueError('Неизвестный статус задачи.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            item = db.execute('SELECT * FROM work_items WHERE id=?', (identifier,)).fetchone()
            if not item or item['assignee_id'] != user:
                raise AccessError('Задача недоступна.', 404, 'work_item')
            if item['project_id']:
                self.permission(db, user, item['project_id'])
            db.execute('UPDATE work_items SET status=?,updated=? WHERE id=?',
                       (status, time.time(), identifier))
        return status

    def admin_dashboard(self):
        """Read-only operational overview. Authorization is enforced by the HTTP layer."""
        with self.db() as db:
            users = [dict(row) for row in db.execute('''
                SELECT u.id,u.email,u.name,u.verified,u.specialty,u.color,COALESCE(a.blocked,0) blocked,
                       t.username,t.telegram_id,t.linked,
                       (SELECT MAX(seen) FROM sessions se WHERE se.user_id=u.id) last_seen,
                       (SELECT COUNT(DISTINCT m.space_id) FROM members m JOIN spaces s ON s.id=m.space_id AND s.kind='team' WHERE m.user_id=u.id) teams,
                       (SELECT COUNT(*) FROM grants g WHERE g.user_id=u.id) project_grants,
                       (SELECT COUNT(*) FROM work_items w WHERE w.assignee_id=u.id AND w.status<>'done') active_tasks
                FROM users u LEFT JOIN telegram_accounts t ON t.user_id=u.id
                LEFT JOIN admin_user_state a ON a.user_id=u.id
                ORDER BY COALESCE(last_seen,t.linked,0) DESC,u.name
            ''').fetchall()]
            month=datetime.now(timezone.utc).date().isoformat()[:7]+'-01'
            monthly_usage={row['user_id']:dict(row) for row in db.execute(
                'SELECT user_id,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens '
                'FROM ai_usage WHERE user_id IS NOT NULL AND day>=? GROUP BY user_id',(month,))}
            for item in users:
                custom=db.execute('SELECT daily_limit,monthly_limit FROM agent_user_limits WHERE user_id=?',(item['id'],)).fetchone()
                plan,expires=self._active_plan(db,item['id'])
                item['plan']=plan
                item['plan_expires']=expires
                source=db.execute('SELECT updated_by FROM user_plans WHERE user_id=? AND expires>?',(item['id'],time.time())).fetchone() if expires else None
                item['plan_source']='demo' if source and source['updated_by']=='demo' else 'admin' if source else None
                used=db.execute('SELECT count FROM auth_limits WHERE key=? AND expires>?',
                                (digest('agent-day:'+item['id']+':'+datetime.now(timezone.utc).date().isoformat()),time.time())).fetchone()
                item['agent_limit']=custom['daily_limit'] if custom else PLAN_LIMITS[plan][0]
                item['agent_used']=used['count'] if used else 0
                item['agent_input_month']=monthly_usage.get(item['id'],{}).get('input_tokens',0)
                item['agent_output_month']=monthly_usage.get(item['id'],{}).get('output_tokens',0)
                item['agent_monthly_limit']=custom['monthly_limit'] if custom and custom['monthly_limit'] is not None else PLAN_LIMITS[plan][1]
            projects=[]
            for row in db.execute('SELECT p.id,p.document,s.name space_name FROM projects p LEFT JOIN project_spaces ps ON ps.project_id=p.id LEFT JOIN spaces s ON s.id=ps.space_id').fetchall():
                try: document=json.loads(row['document'])
                except (TypeError,json.JSONDecodeError): continue
                projects.append({'id':row['id'],'name':document.get('name','Без названия'),'space_name':row['space_name'] or '—',
                                 'blocks':len(document.get('blocks',[])),'updated':document.get('updated',''),
                                 'members':db.execute('SELECT COUNT(*) FROM grants WHERE project_id=?',(row['id'],)).fetchone()[0]})
            task_counts={row['status']:row['count'] for row in db.execute('SELECT status,COUNT(*) count FROM work_items GROUP BY status')}
            start=datetime.now(timezone.utc).date()-timedelta(days=13)
            days=[(start+timedelta(days=i)).isoformat() for i in range(14)]
            linked={datetime.fromtimestamp(row['linked'],timezone.utc).date().isoformat():row['count'] for row in db.execute('SELECT linked,COUNT(*) count FROM telegram_accounts GROUP BY date(linked,"unixepoch")')}
            task_days={row['day']:row['count'] for row in db.execute('SELECT date(created,"unixepoch") day,COUNT(*) count FROM work_items GROUP BY day')}
            ai={row['day']:dict(row) for row in db.execute('SELECT day,COUNT(*) calls,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,SUM(cost) cost FROM ai_usage GROUP BY day')}
            timeline=[{'day':day,'telegram':linked.get(day,0),'tasks':task_days.get(day,0),
                       'ai_calls':ai.get(day,{}).get('calls',0),'ai_cost':round(ai.get(day,{}).get('cost') or 0,6)} for day in days]
            ai_total=db.execute('SELECT COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(cost),0) FROM ai_usage').fetchone()
            operations={'active_sessions':db.execute('SELECT COUNT(*) FROM sessions WHERE expires>? AND seen>?',
                                                     (time.time(),time.time()-43200)).fetchone()[0],
                        'pending_invites':db.execute("SELECT COUNT(*) FROM invitations WHERE state='pending' AND expires>?",(time.time(),)).fetchone()[0]
                                           +db.execute("SELECT COUNT(*) FROM telegram_team_invites WHERE state='pending' AND expires>?",(time.time(),)).fetchone()[0],
                        'pending_email_links':db.execute('SELECT COUNT(*) FROM email_links WHERE expires>?',(time.time(),)).fetchone()[0],
                        'blocked_users':sum(bool(user['blocked']) for user in users)}
            notification_queue=db.execute('''SELECT
                SUM(CASE WHEN o.attempts<5 THEN 1 ELSE 0 END) pending,
                SUM(CASE WHEN o.attempts>=5 THEN 1 ELSE 0 END) failed,
                MIN(CASE WHEN o.attempts<5 THEN o.created END) oldest
                FROM telegram_notification_outbox o
                JOIN telegram_accounts t ON t.user_id=o.user_id AND t.notifications=1
                LEFT JOIN admin_user_state a ON a.user_id=o.user_id
                WHERE o.state='pending' AND COALESCE(a.blocked,0)=0''').fetchone()
            operations['telegram_pending']=notification_queue['pending'] or 0
            operations['telegram_failed']=notification_queue['failed'] or 0
            operations['telegram_oldest_pending_seconds']=max(0,int(time.time()-notification_queue['oldest'])) if notification_queue['oldest'] else 0
            audit=[dict(row) for row in db.execute('''SELECT a.action,a.target_id,a.details,a.created,
                       COALESCE(u.name,'Администратор') admin_name,COALESCE(t.name,'') target_name
                       FROM admin_audit a LEFT JOIN users u ON u.id=a.admin_id
                       LEFT JOIN users t ON t.id=a.target_id ORDER BY a.created DESC LIMIT 100''').fetchall()]
            totals={'users':len(users),'verified':sum(bool(user['verified']) for user in users),
                    'telegram':sum(user['telegram_id'] is not None for user in users),
                    'teams':db.execute("SELECT COUNT(*) FROM spaces WHERE kind='team'").fetchone()[0],
                    'projects':len(projects),'tasks':sum(task_counts.values()),
                    'active_tasks':task_counts.get('todo',0)+task_counts.get('in_progress',0),
                    'ai_calls':ai_total[0],'ai_input':ai_total[1],'ai_output':ai_total[2],'ai_cost':round(ai_total[3],6)}
            plan_counts={plan:sum(user['plan']==plan for user in users) for plan in PLAN_LIMITS}
            demo_active=db.execute('''SELECT COUNT(*) FROM user_plans p JOIN plan_demo_claims d ON d.user_id=p.user_id
                                      WHERE p.updated_by='demo' AND p.expires>?''',(time.time(),)).fetchone()[0]
        for user in users:
            if user['email'].endswith('@telegram.faccet.local'): user['email']=''
        return {'totals':totals,'task_statuses':{key:task_counts.get(key,0) for key in ('todo','in_progress','done')},
                'timeline':timeline,'users':users[:500],'projects':sorted(projects,key=lambda item:item['updated'],reverse=True)[:500],
                'operations':operations,'audit':audit,'plans':{'counts':plan_counts,'demo_active':demo_active}}

    def admin_user_action(self, admin, user_id, action, daily_limit=None, monthly_limit=None, plan=None, duration_days=None):
        if action not in ('block','unblock','terminate_sessions','set_agent_limit','set_agent_tokens','set_plan'):
            raise ValueError('Неизвестное действие администратора.')
        if action=='set_agent_limit' and (type(daily_limit) is not int or not 0 <= daily_limit <= 200):
            raise ValueError('Лимит агента должен быть от 0 до 200 запросов в сутки.')
        if action=='set_agent_tokens' and (type(monthly_limit) is not int or not 0 <= monthly_limit <= 100_000_000):
            raise ValueError('Месячный лимит должен быть от 0 до 100 миллионов токенов.')
        if action=='set_plan' and (plan not in PLAN_LIMITS or
                                  (plan!='free' and (type(duration_days) is not int or not 1<=duration_days<=365))):
            raise ValueError('Укажите тариф и срок от 1 до 365 дней.')
        if user_id == admin and action == 'block':
            raise AccessError('Нельзя заблокировать собственный аккаунт.',409,'admin_self_block')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            target=db.execute('SELECT id,name FROM users WHERE id=?',(user_id,)).fetchone()
            if not target:
                raise AccessError('Пользователь не найден.',404,'user_missing')
            if action in ('block','unblock'):
                blocked=1 if action=='block' else 0
                db.execute('''INSERT INTO admin_user_state VALUES (?,?,?,?)
                              ON CONFLICT(user_id) DO UPDATE SET blocked=excluded.blocked,
                              updated=excluded.updated,updated_by=excluded.updated_by''',
                           (user_id,blocked,time.time(),admin))
            if action in ('block','terminate_sessions'):
                db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            if action=='set_agent_limit':
                db.execute('''INSERT INTO agent_user_limits (user_id,daily_limit,updated,updated_by) VALUES (?,?,?,?)
                              ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit,
                              updated=excluded.updated,updated_by=excluded.updated_by''',
                           (user_id,daily_limit,time.time(),admin))
            if action=='set_agent_tokens':
                active_plan,_=self._active_plan(db,user_id)
                db.execute('''INSERT INTO agent_user_limits (user_id,daily_limit,monthly_limit,updated,updated_by)
                              VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                              monthly_limit=excluded.monthly_limit,updated=excluded.updated,updated_by=excluded.updated_by''',
                           (user_id,PLAN_LIMITS[active_plan][0],monthly_limit,time.time(),admin))
            if action=='set_plan':
                if plan=='free':
                    db.execute('DELETE FROM user_plans WHERE user_id=?',(user_id,))
                else:
                    stamp=time.time()
                    db.execute('''INSERT INTO user_plans (user_id,plan,expires,updated,updated_by)
                                  VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                                  plan=excluded.plan,expires=excluded.expires,updated=excluded.updated,
                                  updated_by=excluded.updated_by''',
                               (user_id,plan,stamp+duration_days*86400,stamp,admin))
            db.execute('INSERT INTO admin_audit VALUES (?,?,?,?,?,?)',
                       (secrets.token_hex(16),admin,action,user_id,
                        f'{plan} · {duration_days or 0} дн.' if action=='set_plan' else
                        str(daily_limit if action=='set_agent_limit' else monthly_limit) if action.startswith('set_agent_') else target['name'],time.time()))
        return {'ok':True,'blocked':action=='block','daily_limit':daily_limit if action=='set_agent_limit' else None,
                'monthly_limit':monthly_limit if action=='set_agent_tokens' else None}

    def admin_system_action(self, admin, action, details):
        with self.db() as db:
            db.execute('INSERT INTO admin_audit VALUES (?,?,?,?,?,?)',
                       (secrets.token_hex(16),admin,action,admin,str(details),time.time()))

    def telegram_projects(self, user, limit=10):
        with self.db() as db:
            rows = db.execute('SELECT p.id,p.document FROM projects p JOIN project_spaces ps ON ps.project_id=p.id '
                              'JOIN members m ON m.space_id=ps.space_id AND m.user_id=? '
                              'ORDER BY p.rowid DESC', (user,)).fetchall()
            result = []
            for row in rows:
                try:
                    role, _ = self.permission(db, user, row['id'])
                except AccessError:
                    continue
                project = json.loads(row['document'])
                result.append({'id': row['id'], 'name': project['name'], 'role': role,
                               'blocks': len(project.get('blocks', [])), 'updated': project.get('updated', '')})
                if len(result) >= max(1, min(int(limit), 20)):
                    break
            return result

    @staticmethod
    def _approval_ref(project_id, block_id, block):
        content = json.dumps(block, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return digest(project_id + ':' + block_id + ':' + content)[:12]

    def telegram_approvals(self, user, limit=10):
        result = []
        with self.db() as db:
            rows = db.execute('SELECT p.id,p.document FROM projects p JOIN project_spaces ps ON ps.project_id=p.id '
                              'JOIN members m ON m.space_id=ps.space_id AND m.user_id=?', (user,)).fetchall()
            for row in rows:
                try:
                    self.permission(db, user, row['id'], 'manager')
                except AccessError:
                    continue
                project = json.loads(row['document'])
                for block in project.get('blocks', []):
                    if block.get('status') == 'review':
                        result.append({'ref': self._approval_ref(row['id'], block['id'], block),
                                       'project_id': row['id'], 'project_name': project['name'],
                                       'block_id': block['id'], 'block_name': block['name']})
                        if len(result) >= max(1, min(int(limit), 20)):
                            return result
        return result

    def telegram_approval_detail(self, user, reference):
        if not re.fullmatch(r'[0-9a-f]{12}', str(reference or '')):
            raise ValueError('Некорректное согласование.')
        with self.db() as db:
            rows = db.execute('SELECT p.id,p.document FROM projects p JOIN project_spaces ps ON ps.project_id=p.id '
                              'JOIN members m ON m.space_id=ps.space_id AND m.user_id=?', (user,)).fetchall()
            for row in rows:
                try:
                    self.permission(db, user, row['id'], 'manager')
                except AccessError:
                    continue
                project = json.loads(row['document'])
                for block in project.get('blocks', []):
                    if block.get('status') == 'review' and self._approval_ref(row['id'], block['id'], block) == reference:
                        xml = block.get('bpmn') or ''
                        names = []
                        if xml:
                            try:
                                root = ET.fromstring(xml)
                                names = [node.get('name', '').strip() for node in root.iter()
                                         if node.tag.rsplit('}', 1)[-1] in ('task', 'userTask', 'serviceTask',
                                             'scriptTask', 'manualTask', 'businessRuleTask', 'sendTask',
                                             'receiveTask', 'subProcess', 'callActivity') and node.get('name')]
                            except ET.ParseError:
                                pass
                        uml = block.get('uml') or {}
                        return {'ref': reference, 'project_id': row['id'], 'block_id': block['id'],
                                'project_name': project['name'], 'block_name': block['name'],
                                'revision': project.get('revision'),
                                'description': block.get('description') or '',
                                'requirements': block.get('requirements') or '',
                                'bpmn_tasks': len(names), 'bpmn_examples': names[:6],
                                'has_bpmn': bool(xml), 'uml_messages': len(uml.get('messages', [])),
                                'has_technical': bool(block.get('technical'))}
        raise AccessError('Согласование уже обработано или недоступно.', 404, 'approval')

    def decide_telegram_approval(self, user, reference, decision):
        if decision not in ('approve', 'reject') or not re.fullmatch(r'[0-9a-f]{12}', str(reference or '')):
            raise ValueError('Некорректное решение.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT p.id,p.document FROM projects p JOIN project_spaces ps ON ps.project_id=p.id '
                              'JOIN members m ON m.space_id=ps.space_id AND m.user_id=?', (user,)).fetchall()
            matches = []
            for row in rows:
                try:
                    self.permission(db, user, row['id'], 'manager')
                except AccessError:
                    continue
                project = json.loads(row['document'])
                for block in project.get('blocks', []):
                    if block.get('status') == 'review' and self._approval_ref(row['id'], block['id'], block) == reference:
                        matches.append((row['id'], project, block))
            if len(matches) != 1:
                raise AccessError('Согласование уже обработано или недоступно.', 404, 'approval')
            project_id, project, block = matches[0]
            block['status'] = 'approved' if decision == 'approve' else 'draft'
            project['revision'] = int(project.get('revision', 0)) + 1
            project['updated'] = now()
            validate_project(project)
            db.execute('UPDATE projects SET document=? WHERE id=?',
                       (json.dumps(project, ensure_ascii=False), project_id))
            actor=db.execute('SELECT name FROM users WHERE id=?',(user,)).fetchone()
            recipients=db.execute('''SELECT DISTINCT m.user_id FROM project_spaces ps
                JOIN members m ON m.space_id=ps.space_id LEFT JOIN grants g ON g.project_id=ps.project_id AND g.user_id=m.user_id
                WHERE ps.project_id=? AND m.user_id<>? AND (m.role IN ('owner','admin') OR g.role IN ('editor','manager'))''',
                (project_id,user)).fetchall()
            decision_text='одобрен' if block['status']=='approved' else 'возвращён в черновик'
            for recipient in recipients:
                self._queue_telegram(db,f'approval:{project_id}:{block["id"]}:{project["revision"]}:{recipient["user_id"]}',recipient['user_id'],
                    f'✅ Решение по согласованию\n\nБлок «{block["name"]}» {decision_text}.\nПроект: {project["name"]}\nРешение: {actor["name"] if actor else "Руководитель"}',
                    'Открыть проект',f'p:{project_id}')
            return {'project_id':project_id,'project_name': project['name'], 'block_name': block['name'], 'status': block['status']}

    def session(self, token):
        if not token:
            return None
        with self.db() as db:
            row = db.execute('SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id '
                             'LEFT JOIN admin_user_state a ON a.user_id=u.id '
                             'WHERE s.token=? AND s.expires>? AND u.verified=1 AND COALESCE(a.blocked,0)=0',
                             (digest(token),time.time())).fetchone()
            if row:
                db.execute('UPDATE sessions SET seen=? WHERE token=?', (time.time(),digest(token)))
                return {**self.public_user(row), 'csrf':row['csrf']}
        return None

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def update_profile(self, user, data):
        name = text(data.get('name'),100)
        if data.get('specialty') not in SPECIALTIES or data.get('color') not in COLORS:
            raise ValueError('Некорректная специализация или цвет аватара.')
        with self.db() as db:
            db.execute('UPDATE users SET name=?,specialty=?,color=? WHERE id=?',
                       (name,data['specialty'],data['color'],user))

    def spaces(self, user):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT s.*,m.role,m.team_specialty FROM spaces s JOIN members m ON m.space_id=s.id '
                                               'WHERE m.user_id=? ORDER BY s.kind,s.name', (user,))]

    def space_role(self, db, user, space, minimum='member'):
        row = db.execute('SELECT m.role,s.kind,s.owner_id FROM members m JOIN spaces s ON s.id=m.space_id '
                         'WHERE m.user_id=? AND m.space_id=?', (user,space)).fetchone()
        levels = {'member':1,'admin':2,'owner':3}
        if not row or levels[row['role']] < levels[minimum]:
            raise AccessError()
        return row

    def create_space(self, user, name):
        name = text(name,100)
        identifier = secrets.token_hex(16)
        with self.db() as db:
            if self._active_plan(db,user)[0]!='team':
                raise AccessError('Создание команды доступно на тарифе Team. Откройте «Настройки → Тарифы».',403,'team_plan_required')
            db.execute('INSERT INTO spaces VALUES (?,?,?,?)', (identifier,name,'team',user))
            db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)', (identifier,user,'owner'))
            self._team_event(db,identifier,user,user,'team_created',name)
        return identifier

    @staticmethod
    def _team_event(db,space,actor,target,kind,details=''):
        db.execute('INSERT INTO team_events VALUES (?,?,?,?,?,?,?)',
                   (secrets.token_hex(12),space,actor,target or '',kind,text(details or '',500,required=False),time.time()))

    def telegram_team_context(self,user,space=None):
        with self.db() as db:
            if space:
                self.space_role(db,user,space)
                db.execute('''INSERT INTO telegram_team_context VALUES (?,?,?)
                              ON CONFLICT(user_id) DO UPDATE SET space_id=excluded.space_id,updated=excluded.updated''',
                           (user,space,time.time()))
                return space
            row=db.execute('SELECT space_id FROM telegram_team_context WHERE user_id=?',(user,)).fetchone()
            if not row:return None
            try:self.space_role(db,user,row['space_id'])
            except AccessError:return None
            return row['space_id']

    def team(self, user, space):
        with self.db() as db:
            role = self.space_role(db,user,space)
            info = dict(db.execute('SELECT * FROM spaces WHERE id=?',(space,)).fetchone())
            info['role'] = role['role']
            info['members'] = [dict(r) for r in db.execute('SELECT u.id,u.name,u.email,COALESCE(m.team_specialty,u.specialty) specialty,u.color,m.role,m.seniority,m.department,m.manager_id '
                                                         'FROM members m JOIN users u ON m.user_id=u.id WHERE m.space_id=?', (space,))]
            for member in info['members']:
                if member['email'].endswith('@telegram.faccet.local'):
                    member['email'] = ''
            info['invitations'] = []
            info['telegram_invitations'] = []
            if role['role'] in ('owner','admin'):
                info['invitations'] = [dict(r) for r in db.execute('SELECT id,email,role,expires,state FROM invitations '
                                                                 "WHERE space_id=? AND state='pending' AND expires>?",(space,time.time()))]
                info['telegram_invitations'] = [dict(r) for r in db.execute(
                    'SELECT id,role,team_specialty,manager_id,expires,state FROM telegram_team_invites '
                    "WHERE space_id=? AND state='pending' AND expires>? ORDER BY expires DESC", (space,time.time()))]
            info['history']=[dict(r) for r in db.execute('''SELECT e.kind,e.details,e.created,
                COALESCE(a.name,'Система') actor_name,COALESCE(t.name,'') target_name
                FROM team_events e LEFT JOIN users a ON a.id=e.actor_id LEFT JOIN users t ON t.id=e.target_id
                WHERE e.space_id=? ORDER BY e.created DESC LIMIT 50''',(space,)).fetchall()]
            return info

    def telegram_invite_spaces(self, user):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                "SELECT s.id,s.name,m.role FROM spaces s JOIN members m ON m.space_id=s.id "
                "WHERE m.user_id=? AND s.kind='team' AND m.role IN ('owner','admin') ORDER BY s.name", (user,))]

    def create_telegram_team_invite(self, user, space, role, specialty=None, manager_id=None):
        if role not in ('member', 'admin'):
            raise ValueError('Можно пригласить участника или администратора.')
        if specialty is not None and specialty not in SPECIALTIES:
            raise ValueError('Выберите специализацию участника.')
        if manager_id is not None and not isinstance(manager_id,str):
            raise ValueError('Выберите руководителя из команды.')
        manager_id=manager_id or None
        raw, identifier = secrets.token_urlsafe(24), secrets.token_hex(16)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = self.space_role(db, user, space, 'admin')
            if actor['kind'] != 'team' or (role == 'admin' and actor['role'] != 'owner'):
                raise AccessError('Только владелец может пригласить администратора.')
            if manager_id:
                self.space_role(db,manager_id,space)
            # Ограничиваем число забытых активных ссылок одной команды.
            active = db.execute("SELECT count(*) FROM telegram_team_invites WHERE space_id=? AND state='pending' AND expires>?",
                                (space, time.time())).fetchone()[0]
            if active >= 25:
                raise AccessError('Слишком много активных ссылок. Отзовите старые приглашения.', 409, 'invite_limit')
            db.execute('INSERT INTO telegram_team_invites (id,hash,space_id,role,team_specialty,manager_id,expires,created_by) '
                       'VALUES (?,?,?,?,?,?,?,?)',
                       (identifier, digest(raw), space, role, specialty, manager_id, time.time()+7*86400, user))
            self._team_event(db,space,user,'','invite_created',role)
            name = db.execute('SELECT name FROM spaces WHERE id=?', (space,)).fetchone()['name']
        return {'id': identifier, 'token': raw, 'space_id': space, 'space_name': name,
                'role': role, 'specialty': specialty, 'manager_id': manager_id,
                'expires': time.time()+7*86400}

    def accept_telegram_team_invite(self, raw, telegram):
        raw = text(raw, 100)
        try:
            telegram_id = int(telegram.get('id'))
            chat_id = int(telegram.get('chat_id', telegram_id))
        except (TypeError, ValueError):
            raise ValueError('Некорректный аккаунт Telegram.')
        username = text(str(telegram.get('username') or ''), 64, False)
        first_name = text(str(telegram.get('first_name') or ''), 100, False)
        last_name = text(str(telegram.get('last_name') or ''), 100, False)
        if telegram_id <= 0 or chat_id <= 0:
            raise ValueError('Некорректный аккаунт Telegram.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            invite = db.execute("SELECT i.*,s.name AS space_name FROM telegram_team_invites i "
                                "JOIN spaces s ON s.id=i.space_id WHERE i.hash=? AND i.state='pending' AND i.expires>?",
                                (digest(raw), time.time())).fetchone()
            if not invite:
                raise AccessError('Приглашение уже использовано, отозвано или истекло.', 404, 'team_invite')
            bound = db.execute('SELECT user_id FROM telegram_accounts WHERE telegram_id=?',
                               (telegram_id,)).fetchone()
            created = False
            if bound:
                user_id = bound['user_id']
            else:
                user_id, personal_space = secrets.token_hex(16), secrets.token_hex(16)
                display_name = (first_name+' '+last_name).strip() or ('@'+username if username else 'Пользователь Telegram')
                internal_email = f'telegram-{telegram_id}@telegram.faccet.local'
                db.execute('INSERT INTO users (id,email,name,password,verified,specialty) VALUES (?,?,?,?,1,?)',
                           (user_id, internal_email, display_name, 'telegram-only', invite['team_specialty'] or 'business'))
                db.execute('INSERT INTO spaces VALUES (?,?,?,?)', (personal_space, 'Личное', 'personal', user_id))
                db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)',
                           (personal_space, user_id, 'owner'))
                created = True
            db.execute('''INSERT INTO telegram_accounts
                          (telegram_id,user_id,username,first_name,last_name,chat_id,linked)
                          VALUES (?,?,?,?,?,?,?)
                          ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,
                          first_name=excluded.first_name,last_name=excluded.last_name,
                          chat_id=excluded.chat_id,linked=excluded.linked''',
                       (telegram_id,user_id,username,first_name,last_name,chat_id,time.time()))
            current = db.execute('SELECT role FROM members WHERE space_id=? AND user_id=?',
                                 (invite['space_id'], user_id)).fetchone()
            if not current:
                manager_id=invite['manager_id'] if invite['manager_id']!=user_id and db.execute(
                    'SELECT 1 FROM members WHERE space_id=? AND user_id=?',
                    (invite['space_id'],invite['manager_id'])).fetchone() else None
                db.execute('INSERT INTO members (space_id,user_id,role,team_specialty,manager_id) VALUES (?,?,?,?,?)',
                           (invite['space_id'], user_id, invite['role'], invite['team_specialty'],manager_id))
                effective_role = invite['role']
            else:
                # Приглашение не повышает и не понижает права существующего участника.
                effective_role = current['role']
            db.execute("UPDATE telegram_team_invites SET state='accepted',accepted_by=?,accepted=? WHERE id=?",
                       (user_id, time.time(), invite['id']))
            self._team_event(db,invite['space_id'],user_id,user_id,'member_joined',effective_role)
            if invite['created_by']!=user_id:
                self._queue_telegram(db,f'team-join:{invite["id"]}',invite['created_by'],
                    f'👥 Новый участник команды\n\n{display_name if not bound else (username or "Пользователь")} вступил в «{invite["space_name"]}».',
                    'Открыть команду','m:c')
        return {'user_id': user_id, 'created': created, 'space_id': invite['space_id'],
                'space_name': invite['space_name'], 'role': effective_role,
                'specialty': invite['team_specialty']}

    def invite(self, user, space, email, role):
        email = email_address(email)
        if role not in ('member','admin'):
            raise ValueError('Можно пригласить участника или администратора.')
        raw, identifier = secrets.token_urlsafe(32), secrets.token_hex(16)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = self.space_role(db,user,space,'admin')
            if actor['kind'] != 'team' or (role == 'admin' and actor['role'] != 'owner'):
                raise AccessError('Только владелец назначает администраторов.')
            if db.execute('SELECT 1 FROM members m JOIN users u ON u.id=m.user_id WHERE m.space_id=? AND u.email=?',(space,email)).fetchone():
                raise ValueError('Этот человек уже в команде.')
            db.execute("UPDATE invitations SET state='revoked' WHERE space_id=? AND email=? AND state='pending'",(space,email))
            db.execute('INSERT INTO invitations (id,hash,space_id,email,role,expires,created_by) VALUES (?,?,?,?,?,?,?)',
                       (identifier,digest(raw),space,email,role,time.time()+7*86400,user))
            self._team_event(db,space,user,'','invite_created',role)
            name = db.execute('SELECT name FROM spaces WHERE id=?',(space,)).fetchone()['name']
        self.mailer.send(email,'Приглашение в команду',f'Вас пригласили в команду «{name}».\n'
                         f'Войдите или зарегистрируйтесь с почтой {email}, затем откройте ссылку:\n\n'
                         f'{self.mailer.base_url}/#invite={raw}\n\nСсылка действует 7 дней.')

    def accept_invite(self, user, raw):
        raw = text(raw,200)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            invite = db.execute("SELECT * FROM invitations WHERE hash=? AND state='pending' AND expires>?",
                                (digest(raw),time.time())).fetchone()
            email = db.execute('SELECT email FROM users WHERE id=?',(user,)).fetchone()['email']
            if not invite or invite['email'] != email:
                raise AccessError('Приглашение недоступно: проверьте почту аккаунта и срок ссылки.')
            # Принятие старого приглашения не может повысить права существующего участника.
            db.execute('INSERT OR IGNORE INTO members (space_id,user_id,role) VALUES (?,?,?)',(invite['space_id'],user,invite['role']))
            db.execute("UPDATE invitations SET state='accepted' WHERE id=?",(invite['id'],))
            self._team_event(db,invite['space_id'],user,user,'member_joined',invite['role'])
            return invite['space_id']

    def revoke_invite(self, user, space, identifier):
        with self.db() as db:
            actor = self.space_role(db,user,space,'admin')
            invite = db.execute('SELECT * FROM invitations WHERE id=? AND space_id=?',(identifier,space)).fetchone()
            telegram_invite = db.execute('SELECT * FROM telegram_team_invites WHERE id=? AND space_id=?',
                                         (identifier,space)).fetchone()
            selected = invite or telegram_invite
            if not selected or (selected['role']=='admin' and actor['role']!='owner'):
                raise AccessError()
            table = 'invitations' if invite else 'telegram_team_invites'
            db.execute(f"UPDATE {table} SET state='revoked' WHERE id=?",(identifier,))
            self._team_event(db,space,user,'','invite_revoked',selected['role'])

    def change_member(self, user, space, target, role):
        if role not in ('admin','member','remove'):
            raise ValueError('Неизвестная роль.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = self.space_role(db,user,space,'admin')
            current = self.space_role(db,target,space)
            if actor['kind']!='team' or current['role']=='owner' or target==user:
                raise AccessError('Владельца и собственные права нельзя менять этим действием.')
            if actor['role']!='owner' and current['role']=='admin':
                raise AccessError('Только владелец управляет администраторами.')
            if role in ('admin','member'):
                if actor['role']!='owner': raise AccessError('Только владелец меняет роли участников.')
                db.execute('UPDATE members SET role=? WHERE space_id=? AND user_id=?',(role,space,target))
                self._team_event(db,space,user,target,'role_changed',role)
                team_name=db.execute('SELECT name FROM spaces WHERE id=?',(space,)).fetchone()['name']
                self._queue_telegram(db,f'team-role:{space}:{target}:{role}:{int(time.time())}',target,
                    f'👥 Ваша роль изменена\n\nКоманда: {team_name}\nНовая роль: {"Администратор" if role=="admin" else "Участник"}',
                    'Открыть команды','m:c')
                return
            manager_row=db.execute('SELECT manager_id FROM members WHERE space_id=? AND user_id=?',
                                   (space,target)).fetchone()
            parent=manager_row['manager_id'] if manager_row else None
            if parent and not db.execute('SELECT 1 FROM members WHERE space_id=? AND user_id=?',
                                         (space,parent)).fetchone():
                parent=None
            db.execute('UPDATE members SET manager_id=? WHERE space_id=? AND manager_id=?',
                       (parent,space,target))
            db.execute('DELETE FROM members WHERE space_id=? AND user_id=?',(space,target))
            db.execute('DELETE FROM grants WHERE user_id=? AND project_id IN '
                       '(SELECT project_id FROM project_spaces WHERE space_id=?)',(target,space))
            email = db.execute('SELECT email FROM users WHERE id=?',(target,)).fetchone()['email']
            db.execute("UPDATE invitations SET state='revoked' WHERE space_id=? AND email=?",(space,email))
            db.execute("UPDATE invitations SET state='revoked' WHERE space_id=? AND created_by=? AND state='pending'",(space,target))
            db.execute("UPDATE telegram_team_invites SET state='revoked' WHERE space_id=? AND created_by=? AND state='pending'",
                       (space,target))
            self._team_event(db,space,user,target,'member_removed',current['role'])
            team_name=db.execute('SELECT name FROM spaces WHERE id=?',(space,)).fetchone()['name']
            self._queue_telegram(db,f'team-remove:{space}:{target}:{int(time.time())}',target,
                f'👥 Доступ к команде закрыт\n\nВы удалены из команды «{team_name}».','Открыть команды','m:c')

    def update_member_org(self, user, space, target, data):
        seniority = data.get('seniority')
        if seniority not in SENIORITIES:
            raise ValueError('Неизвестный уровень сотрудника.')
        specialty = data.get('specialty')
        if specialty is not None and specialty not in SPECIALTIES:
            raise ValueError('Неизвестная специализация сотрудника.')
        department = text(data.get('department', ''), 100, required=False)
        manager = data.get('manager_id') or None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.space_role(db,user,space,'admin')
            self.space_role(db,target,space)
            if manager:
                self.space_role(db,manager,space)
                if manager == target:
                    raise ValueError('Сотрудник не может быть собственным руководителем.')
                current = manager
                while current:
                    if current == target:
                        raise ValueError('Такое назначение создаёт цикл в структуре команды.')
                    row = db.execute('SELECT manager_id FROM members WHERE space_id=? AND user_id=?',(space,current)).fetchone()
                    current = row['manager_id'] if row else None
            db.execute('UPDATE members SET seniority=?,department=?,manager_id=?,team_specialty=COALESCE(?,team_specialty) WHERE space_id=? AND user_id=?',
                       (seniority,department,manager,specialty,space,target))
            self._team_event(db,space,user,target,'profile_changed',(specialty or '')+' · '+seniority+((' · '+department) if department else ''))

    def transfer(self, user, space, target, password):
        with self.db() as db:
            account = db.execute('SELECT password FROM users WHERE id=?',(user,)).fetchone()
        if not password_matches(password,account['password']):
            raise AccessError('Неверный пароль.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = self.space_role(db,user,space,'owner')
            self.space_role(db,target,space)
            if actor['kind']!='team' or target==user:
                raise ValueError('Выберите другого участника команды.')
            db.execute('UPDATE spaces SET owner_id=? WHERE id=?',(target,space))
            db.execute("UPDATE members SET role='admin' WHERE space_id=? AND user_id=?",(space,user))
            db.execute("UPDATE members SET role='owner' WHERE space_id=? AND user_id=?",(space,target))
            self._team_event(db,space,user,target,'ownership_transferred','owner')

    def permission(self, db, user, project, minimum='viewer'):
        row = db.execute('SELECT ps.space_id,m.role AS team_role,g.role AS project_role '
                         'FROM project_spaces ps JOIN members m ON m.space_id=ps.space_id AND m.user_id=? '
                         'LEFT JOIN grants g ON g.project_id=ps.project_id AND g.user_id=m.user_id '
                         'WHERE ps.project_id=?',(user,project)).fetchone()
        role = 'manager' if row and row['team_role'] in ('owner','admin') else row['project_role'] if row else None
        if PROJECT_ROLES.get(role,0) < PROJECT_ROLES[minimum]:
            raise AccessError('Проект недоступен или у вас недостаточно прав.',404 if minimum=='viewer' else 403)
        return role, row['space_id']

    def projects(self, user, space):
        with self.db() as db:
            self.space_role(db,user,space)
            result=[]
            for row in db.execute('SELECT p.* FROM projects p JOIN project_spaces ps ON ps.project_id=p.id WHERE ps.space_id=?',(space,)).fetchall():
                try: role,_=self.permission(db,user,row['id'])
                except AccessError: continue
                p=json.loads(row['document'])
                blocks=p.get('blocks',[])
                result.append(dict(
                    id=p['id'], name=p['name'], goal=p.get('goal',''), updated=p['updated'],
                    blocks=len(blocks), bpmn=sum(bool(b.get('bpmn')) for b in blocks),
                    uml=sum(bool((b.get('uml') or {}).get('participants') or (b.get('uml') or {}).get('messages')) for b in blocks),
                    access=role))
            return sorted(result,key=lambda p:p['updated'],reverse=True)

    def project(self, user, identifier):
        with self.db() as db:
            role,space=self.permission(db,user,identifier)
            row=db.execute('SELECT document FROM projects WHERE id=?',(identifier,)).fetchone()
            if not row: raise KeyError()
            return {**json.loads(row['document']),'access':role,'space_id':space}

    def create_project(self, user, space, name, imported=None, demo=False):
        p=validate_project(imported) if imported is not None else new_project(name,demo=demo)
        p={k:v for k,v in p.items() if k not in ('access','space_id')}
        p.update(id=secrets.token_hex(16),revision=1,updated=now())
        validate_project(p)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.space_role(db,user,space)
            db.execute('INSERT INTO projects VALUES (?,?)',(p['id'],json.dumps(p,ensure_ascii=False)))
            db.execute('INSERT INTO project_spaces VALUES (?,?)',(p['id'],space))
            db.execute('INSERT INTO grants VALUES (?,?,?)',(p['id'],user,'manager'))
        return {**p,'access':'manager','space_id':space}

    def save_project(self, user, identifier, p, revision):
        validate_project(p)
        # Метаданные доступа из запроса никогда не сохраняются и не назначают права.
        p={k:v for k,v in p.items() if k not in ('access','space_id')}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            role,space=self.permission(db,user,identifier,'editor')
            row=db.execute('SELECT document FROM projects WHERE id=?',(identifier,)).fetchone()
            if not row: raise KeyError()
            old=json.loads(row['document'])
            if type(revision) is not int or old['revision']!=revision:
                raise Conflict('Проект изменён. Экспортируйте свои правки и обновите страницу.')
            old_blocks={block['id']:block for block in old.get('blocks',[])}
            review_blocks=[];bpmn_changed=[]
            for block in p.get('blocks',[]):
                previous=old_blocks.get(block['id']);old_xml=previous.get('bpmn','') if previous else ''
                if block.get('status')=='review' and (not previous or previous.get('status')!='review'):
                    review_blocks.append(block)
                if old_xml and old_xml!=block.get('bpmn',''):
                    bpmn_changed.append(block)
                    db.execute('INSERT OR IGNORE INTO bpmn_versions VALUES (?,?,?,?,?,?,?)',
                               (secrets.token_hex(16),identifier,block['id'],old['revision'],old_xml,time.time(),user))
                    db.execute('DELETE FROM bpmn_versions WHERE id IN ('
                               'SELECT id FROM bpmn_versions WHERE project_id=? AND block_id=? '
                               'ORDER BY created DESC LIMIT -1 OFFSET 30)',(identifier,block['id']))
            p.update(id=identifier,revision=revision+1,updated=now())
            db.execute('UPDATE projects SET document=? WHERE id=?',(json.dumps(p,ensure_ascii=False),identifier))
            actor=db.execute('SELECT name FROM users WHERE id=?',(user,)).fetchone()
            managers=db.execute('''SELECT DISTINCT m.user_id FROM project_spaces ps JOIN members m ON m.space_id=ps.space_id
                LEFT JOIN grants g ON g.project_id=ps.project_id AND g.user_id=m.user_id
                WHERE ps.project_id=? AND m.user_id<>? AND (m.role IN ('owner','admin') OR g.role='manager')''',(identifier,user)).fetchall()
            collaborators=db.execute('''SELECT DISTINCT m.user_id FROM project_spaces ps JOIN members m ON m.space_id=ps.space_id
                LEFT JOIN grants g ON g.project_id=ps.project_id AND g.user_id=m.user_id
                WHERE ps.project_id=? AND m.user_id<>? AND (m.role IN ('owner','admin') OR g.role IN ('editor','manager'))''',(identifier,user)).fetchall()
            for block in review_blocks:
                for recipient in managers:
                    self._queue_telegram(db,f'review:{identifier}:{block["id"]}:{p["revision"]}:{recipient["user_id"]}',recipient['user_id'],
                        f'✅ Новый запрос на согласование\n\nБлок: {block["name"]}\nПроект: {p["name"]}\nОтправил: {actor["name"] if actor else "Участник"}',
                        'Открыть согласования','m:a')
            for block in bpmn_changed:
                for recipient in collaborators:
                    self._queue_telegram(db,f'bpmn:{identifier}:{block["id"]}:{p["revision"]}:{recipient["user_id"]}',recipient['user_id'],
                        f'◇ BPMN обновлена\n\nСхема: {block["name"]}\nПроект: {p["name"]}\nИзменил: {actor["name"] if actor else "Участник"}',
                        'Открыть проект',f'p:{identifier}')
        return {**p,'access':role,'space_id':space}

    @staticmethod
    def _bpmn_summary(xml):
        from facet.bpmn.checker import NODES, kind
        try: root=ET.fromstring(xml)
        except (ET.ParseError,TypeError): return {'elements':0,'flows':0,'names':{},'flow_defs':{}}
        names={};flow_defs={}
        for element in root.iter():
            local=kind(element)
            identifier=element.get('id')
            if local=='sequenceFlow':
                condition=next((child.text or '' for child in element if kind(child)=='conditionExpression'),'')
                flow_defs[identifier or f'flow-{len(flow_defs)}']=(element.get('sourceRef',''),element.get('targetRef',''),element.get('name',''),condition)
            elif identifier and local in NODES:
                names[identifier]={'kind':local,'name':element.get('name','')}
        return {'elements':len(names),'flows':len(flow_defs),'names':names,'flow_defs':flow_defs}

    def bpmn_history(self,user,project_id,block_id):
        with self.db() as db:
            role,_=self.permission(db,user,project_id,'viewer')
            row=db.execute('SELECT document FROM projects WHERE id=?',(project_id,)).fetchone()
            if not row: raise KeyError()
            project=json.loads(row['document']);block=next((item for item in project['blocks'] if item['id']==block_id),None)
            if block is None: raise KeyError()
            versions=db.execute('SELECT v.id,v.revision,v.xml,v.created,u.name FROM bpmn_versions v '
                                'LEFT JOIN users u ON u.id=v.user_id WHERE v.project_id=? AND v.block_id=? '
                                'ORDER BY v.created DESC LIMIT 30',(project_id,block_id)).fetchall()
        current_summary=self._bpmn_summary(block.get('bpmn',''))
        return {'access':role,'current':{'id':'current','revision':project['revision'],'created':project['updated'],
                'author':'Текущая версия','elements':current_summary['elements'],'flows':current_summary['flows']},
                'versions':[{'id':row['id'],'revision':row['revision'],'created':row['created'],'author':row['name'] or 'Участник',
                             'elements':self._bpmn_summary(row['xml'])['elements'],'flows':self._bpmn_summary(row['xml'])['flows']} for row in versions]}

    def bpmn_version(self,user,project_id,block_id,version_id):
        with self.db() as db:
            self.permission(db,user,project_id,'viewer')
            project_row=db.execute('SELECT document FROM projects WHERE id=?',(project_id,)).fetchone()
            version=db.execute('SELECT revision,xml,created FROM bpmn_versions WHERE id=? AND project_id=? AND block_id=?',
                               (version_id,project_id,block_id)).fetchone()
            if not project_row or not version: raise KeyError()
        project=json.loads(project_row['document']);block=next((item for item in project['blocks'] if item['id']==block_id),None)
        if block is None: raise KeyError()
        current=self._bpmn_summary(block.get('bpmn',''));previous=self._bpmn_summary(version['xml'])
        current_names,previous_names=current['names'],previous['names']
        added=[current_names[key]['name'] or key for key in current_names.keys()-previous_names.keys()]
        removed=[previous_names[key]['name'] or key for key in previous_names.keys()-current_names.keys()]
        renamed=[{'from':previous_names[key]['name'] or key,'to':current_names[key]['name'] or key}
                 for key in current_names.keys()&previous_names.keys() if current_names[key]!=previous_names[key]]
        current_flows,previous_flows=current['flow_defs'],previous['flow_defs']
        flow_changes=len(current_flows.keys()^previous_flows.keys())+sum(current_flows[key]!=previous_flows[key] for key in current_flows.keys()&previous_flows.keys())
        return {'id':version_id,'revision':version['revision'],'created':version['created'],'xml':version['xml'],
                'diff':{'added':added[:20],'removed':removed[:20],'renamed':renamed[:20],
                        'elements_delta':current['elements']-previous['elements'],'flows_delta':current['flows']-previous['flows'],
                        'flow_changes':flow_changes,'layout_only':not added and not removed and not renamed and not flow_changes and block.get('bpmn','')!=version['xml']}}

    def restore_bpmn(self,user,project_id,block_id,version_id,revision):
        version=self.bpmn_version(user,project_id,block_id,version_id)
        project=self.project(user,project_id);block=next((item for item in project['blocks'] if item['id']==block_id),None)
        if block is None: raise KeyError()
        block['bpmn']=version['xml']
        return self.save_project(user,project_id,project,revision)

    def delete_project(self, user, identifier):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.permission(db,user,identifier,'manager')
            db.execute('DELETE FROM grants WHERE project_id=?',(identifier,))
            db.execute('DELETE FROM project_spaces WHERE project_id=?',(identifier,))
            db.execute('DELETE FROM work_items WHERE project_id=?',(identifier,))
            for table in ('ai_chat','ai_drafts','bpmn_versions'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    db.execute(f'DELETE FROM {table} WHERE project_id=?',(identifier,))
            if not db.execute('DELETE FROM projects WHERE id=?',(identifier,)).rowcount:
                raise KeyError()

    def access_list(self, user, project):
        with self.db() as db:
            _,space=self.permission(db,user,project,'manager')
            members=[dict(r) for r in db.execute('SELECT u.id,u.name,u.email,m.role AS team_role,g.role AS project_role '
                                                'FROM members m JOIN users u ON u.id=m.user_id '
                                                'LEFT JOIN grants g ON g.user_id=u.id AND g.project_id=? WHERE m.space_id=?',(project,space))]
            for member in members:
                if member['email'].endswith('@telegram.faccet.local'):
                    member['email'] = ''
            return members

    def grant(self, user, project, target, role):
        if role not in {*PROJECT_ROLES,'none'}:
            raise ValueError('Неизвестное право доступа.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            _,space=self.permission(db,user,project,'manager')
            target_role=self.space_role(db,target,space)
            if target_role['role'] in ('owner','admin'):
                raise AccessError('У владельца и администраторов полный доступ к проектам команды.')
            if role=='none':
                db.execute('DELETE FROM grants WHERE project_id=? AND user_id=?',(project,target))
            else:
                db.execute('INSERT INTO grants VALUES (?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role',
                           (project,target,role))

    def migration_available(self):
        with self.db() as db:
            return not bool(db.execute("SELECT 1 FROM account_meta WHERE key='migration_claimed'").fetchone()) and bool(
                db.execute('SELECT 1 FROM projects WHERE id NOT IN (SELECT project_id FROM project_spaces) LIMIT 1').fetchone())

    def claim_legacy(self, user, key):
        key=text(key,200)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            expected=db.execute("SELECT value FROM account_meta WHERE key='migration_hash'").fetchone()
            if not expected or not hmac.compare_digest(expected['value'],digest(key)) or db.execute("SELECT 1 FROM account_meta WHERE key='migration_claimed'").fetchone():
                raise AccessError('Неверный ключ переноса или проекты уже перенесены.')
            space=db.execute("SELECT id FROM spaces WHERE kind='personal' AND owner_id=?",(user,)).fetchone()['id']
            projects=db.execute('SELECT id FROM projects WHERE id NOT IN (SELECT project_id FROM project_spaces)').fetchall()
            for p in projects:
                db.execute('INSERT INTO project_spaces VALUES (?,?)',(p['id'],space))
            db.execute("INSERT INTO account_meta VALUES ('migration_claimed',?)",(user,))
            db.execute("DELETE FROM account_meta WHERE key='migration_hash'")
        return len(projects)
