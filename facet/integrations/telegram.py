"""Telegram transport: authentication and compact project assistant with inline actions."""
import hmac
import hashlib
import json
import os
import re
import time
from urllib.parse import quote, parse_qsl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from facet.identity.accounts import AccessError
from facet.ai.agent import AgentError


class TelegramBot:
    def __init__(self, accounts, agent=None):
        self.accounts = accounts
        self.agent = agent
        self.token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        self.username = os.environ.get('TELEGRAM_BOT_USERNAME', '').strip().lstrip('@')
        self.secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '').strip()
        self.site = os.environ.get('WORKSPACE_PUBLIC_URL', 'https://faccet.ru').rstrip('/')

    @property
    def enabled(self):
        return bool(self.token and self.username and self.secret)

    @property
    def admin_usernames(self):
        raw = os.environ.get('FACET_ADMIN_TELEGRAM_USERNAMES', 'fb_656')
        return {item.strip().lstrip('@').casefold() for item in raw.split(',') if item.strip()}

    def public_status(self, user_id=None):
        linked = self.accounts.telegram_account(user_id) if user_id else None
        return {'enabled': self.enabled, 'username': self.username if self.enabled else '', 'linked': linked}

    def start(self, user_id=None):
        if not self.enabled:
            raise AccessError('Telegram-бот ещё не подключён.', 503, 'telegram_disabled')
        token = self.accounts.telegram_start(user_id)
        return {'token': token,
                'url': f'https://t.me/{quote(self.username)}?start={quote(token)}',
                'expires_in': 600}

    def create_team_invite(self, user_id, space_id, role, specialty=None, manager_id=None):
        if not self.enabled:
            raise AccessError('Telegram-бот ещё не подключён.', 503, 'telegram_disabled')
        result = self.accounts.create_telegram_team_invite(user_id, space_id, role, specialty, manager_id)
        result['url'] = f'https://t.me/{quote(self.username)}?start=team_{quote(result.pop("token"))}'
        return result

    def check_secret(self, supplied):
        return bool(self.enabled and supplied and hmac.compare_digest(self.secret, supplied))

    def webapp_identity(self, init_data):
        if not self.enabled or not isinstance(init_data, str) or not init_data or len(init_data) > 12000:
            raise AccessError('Откройте приложение из Telegram-бота.', 401, 'telegram_webapp')
        try:
            params = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
            supplied_hash = params.pop('hash')
            auth_date = int(params.get('auth_date', '0'))
            user_data = json.loads(params.get('user', '{}'))
            telegram_id = int(user_data.get('id'))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise AccessError('Telegram не передал данные входа.', 401, 'telegram_webapp')
        if abs(time.time()-auth_date) > 600:
            raise AccessError('Данные входа Telegram устарели. Откройте Mini App заново.', 401, 'telegram_webapp')
        check_string = '\n'.join(f'{key}={params[key]}' for key in sorted(params))
        secret_key = hmac.new(b'WebAppData', self.token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied_hash):
            raise AccessError('Подпись Telegram недействительна.', 401, 'telegram_webapp')
        user = self.accounts.telegram_user(telegram_id)
        if not user:
            raise AccessError('Сначала зарегистрируйтесь через кнопку Start в боте.', 401, 'telegram_unlinked')
        return user_data, user

    def webapp_login(self, init_data):
        _, user = self.webapp_identity(init_data)
        return self.accounts.create_session(user['id'])

    def admin_webapp_login(self, init_data):
        telegram_user, user = self.webapp_identity(init_data)
        username = str(telegram_user.get('username') or '').lstrip('@').casefold()
        if username not in self.admin_usernames:
            raise AccessError('У этого Telegram-аккаунта нет доступа к администрированию.', 403, 'admin_required')
        return self.accounts.create_session(user['id'])

    def is_admin_user(self, user_id):
        account = self.accounts.telegram_account(user_id)
        return bool(account and str(account.get('username') or '').lstrip('@').casefold() in self.admin_usernames)

    def require_admin(self, user_id):
        if not self.is_admin_user(user_id):
            raise AccessError('Доступно только администратору Facet.', 403, 'admin_required')

    @staticmethod
    def button(label, data=None, url=None):
        result = {'text': label[:64]}
        if data is not None:
            result['callback_data'] = data
        if url is not None:
            result['url'] = url
        return result

    def main_keyboard(self, user):
        enabled = self.accounts.telegram_notifications(user['id'])
        rows = [
            [self.button('📋 Мои задачи', 'm:t'), self.button('✅ Согласования', 'm:a')],
            [self.button('🗂 Проекты', 'm:p'), self.button('🔔 Уведомления' if enabled else '🔕 Уведомления', 'm:n')],
            [self.button('👥 Команда','m:c'),self.button('🤖 Агент', 'm:g')],
        ]
        if self.accounts.telegram_invite_spaces(user['id']):
            rows.append([self.button('➕ Пригласить в команду', 'm:i')])
        if self.is_admin_user(user['id']):
            rows.append([{'text': '⚙ Администрирование Facet', 'web_app': {'url': self.site+'/admin-app?v=20260921-2'}}])
        rows.append([{'text': 'Открыть Facet', 'web_app': {'url': self.site+'/telegram-app?v=20260921-3'}}])
        return {'inline_keyboard': rows}

    def main_view(self, user):
        return (f'Facet · {user["name"]}\n\n'
                'Здесь можно вести личные задачи, просматривать проекты и согласовывать блоки, '
                'которые отправлены на проверку.\n\n'
                'Быстрая задача: /new Подготовить описание процесса', self.main_keyboard(user))

    def tasks_view(self, user):
        items = self.accounts.work_items(user['id'], 10)
        labels = {'todo': '○', 'in_progress': '◐', 'done': '●'}
        lines = ['📋 Мои задачи']
        keyboard = []
        if not items:
            lines += ['', 'Задач пока нет.', 'Создайте первую: /new Текст задачи']
        for index, item in enumerate(items, 1):
            scope = f' · {item["project_name"]}' if item['project_name'] else ''
            lines.append(f'\n{index}. {labels[item["status"]]} {item["title"]}{scope}')
            if item['status'] == 'todo':
                keyboard.append([self.button(f'▶ {index}. В работу', f't:{item["id"]}:p')])
            elif item['status'] == 'in_progress':
                keyboard.append([self.button(f'✓ {index}. Готово', f't:{item["id"]}:d')])
            else:
                keyboard.append([self.button(f'↩ {index}. Вернуть', f't:{item["id"]}:n')])
        keyboard.append([self.button('↻ Обновить', 'm:t'), self.button('‹ Меню', 'm:m')])
        return ''.join(lines), {'inline_keyboard': keyboard}

    def projects_view(self, user):
        projects = self.accounts.telegram_projects(user['id'], 10)
        roles = {'viewer': 'просмотр', 'commenter': 'комментарии', 'editor': 'редактор', 'manager': 'управление'}
        lines = ['🗂 Доступные проекты']
        keyboard = []
        if not projects:
            lines += ['', 'Нет доступных проектов.']
        for index, project in enumerate(projects, 1):
            lines.append(f'\n{index}. {project["name"]} · {project["blocks"]} блоков · {roles[project["role"]]}')
            keyboard.append([self.button(f'{index}. {project["name"]}'[:48], f'p:{project["id"]}')])
        keyboard.append([self.button('↻ Обновить', 'm:p'), self.button('‹ Меню', 'm:m')])
        return ''.join(lines), {'inline_keyboard': keyboard}

    def project_view(self, user, project_id):
        project = self.accounts.project(user['id'], project_id)
        statuses = {'draft': 0, 'review': 0, 'approved': 0}
        for block in project.get('blocks', []):
            if block.get('status') in statuses:
                statuses[block['status']] += 1
        goal = str(project.get('goal') or '').strip()
        content = (f'🗂 {project["name"]}\n\n{goal[:500] or "Цель проекта пока не заполнена."}\n\n'
                   f'Блоков: {len(project.get("blocks", []))}\n'
                   f'Черновики: {statuses["draft"]} · На проверке: {statuses["review"]} · Одобрено: {statuses["approved"]}')
        return content, {'inline_keyboard': [[self.button('🤖 Открыть агента', f'g:p:{project_id}')],
                                             [{'text': 'Открыть Facet', 'web_app': {'url': self.site+'/telegram-app'}}],
                                             [self.button('‹ Проекты', 'm:p'), self.button('‹ Меню', 'm:m')]]}

    def agent_projects_view(self, user):
        projects=self.accounts.telegram_projects(user['id'],10)
        lines=['🤖 Агент Facet','','Выберите проект для анализа. После выбора можно задавать вопросы командой:','/agent Что мешает завершению процесса?']
        keyboard=[]
        for index,project in enumerate(projects,1):
            keyboard.append([self.button(f'{index}. {project["name"]}'[:52],f'g:p:{project["id"]}')])
        if not projects: lines+=['','Доступных проектов пока нет.']
        keyboard.append([self.button('‹ Меню','m:m')])
        return '\n'.join(lines),{'inline_keyboard':keyboard}

    def agent_project_view(self,user,project_id):
        self.accounts.telegram_agent_project(user['id'],project_id)
        project=self.accounts.project(user['id'],project_id);blocks=project.get('blocks',[])
        statuses={key:sum(item.get('status')==key for item in blocks) for key in ('draft','review','approved')}
        state=self.agent.status() if self.agent else {'configured':False,'used_today':0,'daily_limit':20}
        content=(f'🤖 Агент · {project["name"]}\n\nБлоков: {len(blocks)} · BPMN: {sum(bool(item.get("bpmn")) for item in blocks)}\n'
                 f'Черновики: {statuses["draft"]} · На проверке: {statuses["review"]} · Одобрено: {statuses["approved"]}\n\n'
                 f'Лимит агента: {state["used_today"]} / {state["daily_limit"]}\n'
                 'Можно выполнить быстрый анализ или отправить /agent и свой вопрос.')
        return content,{'inline_keyboard':[[self.button('🔎 Анализ проекта',f'g:a:{project_id}')],
                                            [self.button('◇ Анализ BPMN',f'g:l:{project_id}')],
                                            [self.button('‹ Другой проект','m:g'),self.button('‹ Меню','m:m')]]}

    def agent_bpmn_view(self,user,project_id):
        project=self.accounts.project(user['id'],project_id);blocks=[item for item in project.get('blocks',[]) if item.get('bpmn')]
        lines=[f'◇ BPMN · {project["name"]}','','Выберите схему для анализа логики, ветвлений и исключений.']
        keyboard=[[self.button(f'{index+1}. {block["name"]}'[:52],f'g:b:{project_id}:{index}')]
                  for index,block in enumerate(blocks)]
        if not blocks: lines+=['','В проекте пока нет BPMN-схем.']
        keyboard.append([self.button('‹ Агент',f'g:p:{project_id}')])
        return '\n'.join(lines),{'inline_keyboard':keyboard}

    def agent_analysis_view(self,user,project_id,result,block_id=None):
        analysis=result['analysis'];icons={'error':'⛔','warning':'⚠','suggestion':'•'}
        lines=['🤖 Анализ завершён','',analysis['summary'][:1100]]
        findings=analysis.get('findings',[])[:4]
        if findings:
            lines+=['','Замечания:']
            for item in findings:
                lines.append(f'{icons.get(item["severity"],"•")} {item["title"][:180]}\n{item["recommendation"][:350]}')
        steps=analysis.get('next_steps',[])[:3]
        if steps:
            lines+=['','Следующие шаги:']+[f'{index}. {step[:300]}' for index,step in enumerate(steps,1)]
        keyboard=[]
        project=self.accounts.project(user['id'],project_id)
        if project.get('access') in ('editor','manager') and (steps or findings):
            title=(steps[0] if steps else findings[0]['title'])[:240]
            description=(findings[0]['recommendation'] if findings else analysis['summary'])[:4000]
            reference=self.accounts.create_telegram_agent_action(user['id'],project_id,title,description,block_id)
            keyboard.append([self.button('＋ Создать задачу',f'g:q:{reference}')])
        repeat=f'g:a:{project_id}'
        if block_id:
            bpmn_blocks=[item for item in project.get('blocks',[]) if item.get('bpmn')]
            repeat=f'g:b:{project_id}:{next((index for index,item in enumerate(bpmn_blocks) if item["id"]==block_id),0)}'
        keyboard.append([self.button('↻ Повторить анализ',repeat)])
        keyboard.append([self.button('‹ Агент',f'g:p:{project_id}'),self.button('‹ Меню','m:m')])
        return '\n\n'.join(lines)[:3900],{'inline_keyboard':keyboard}

    def run_agent_analysis(self,user,project_id,scope='project',block_index=None,prompt=''):
        if not self.agent: raise AccessError('Агент не подключён.',503,'agent_disabled')
        project=self.accounts.project(user['id'],project_id);block_id=None
        if scope=='bpmn':
            blocks=[item for item in project.get('blocks',[]) if item.get('bpmn')]
            if block_index is None or block_index<0 or block_index>=len(blocks): raise ValueError('BPMN-схема не найдена.')
            block_id=blocks[block_index]['id']
        self.accounts.limit_agent(user['id'])
        try:
            result=self.agent.analyze(project,scope,block_id,prompt,user['id'])
        except AgentError as error:
            if error.unbilled:
                self.accounts.refund_agent(user['id'])
                if error.global_reserved:
                    self.agent.refund()
            raise
        return self.agent_analysis_view(user,project_id,result,block_id)

    def approvals_view(self, user):
        approvals = self.accounts.telegram_approvals(user['id'], 10)
        lines = ['✅ Согласования']
        keyboard = []
        if not approvals:
            lines += ['', 'Нет блоков, ожидающих вашего решения.']
        for index, item in enumerate(approvals, 1):
            lines.append(f'\n{index}. {item["block_name"]}\n   {item["project_name"]}')
            keyboard.append([self.button(f'🔎 {index}. Что согласовываем', f'a:{item["ref"]}:v')])
        keyboard.append([self.button('↻ Обновить', 'm:a'), self.button('‹ Меню', 'm:m')])
        return ''.join(lines), {'inline_keyboard': keyboard}

    def approval_detail_view(self, user, reference):
        item = self.accounts.telegram_approval_detail(user['id'], reference)
        brief = lambda value, limit: (str(value).strip()[:limit] + ('…' if len(str(value).strip()) > limit else '')) or 'Не заполнено'
        lines = [f'✅ На согласовании: {item["block_name"]}',
                 f'Проект: {item["project_name"]} · версия {item["revision"]}',
                 '', f'Описание: {brief(item["description"], 500)}',
                 f'Требования: {brief(item["requirements"], 700)}',
                 f'BPMN: {item["bpmn_tasks"]} именованных действий' if item['has_bpmn'] else 'BPMN: нет',
                 f'UML: {item["uml_messages"]} сообщений',
                 'API и данные: заполнены' if item['has_technical'] else 'API и данные: не заполнены']
        if item['bpmn_examples']:
            lines.append('Действия: ' + '; '.join(brief(name, 65) for name in item['bpmn_examples']))
        lines += ['', 'Решение относится ко всему текущему содержимому блока. Если блок изменится, откройте согласование заново.']
        project_url = (f'{self.site}/?project={quote(item["project_id"])}'
                       f'&block={quote(item["block_id"])}')
        keyboard = {'inline_keyboard': [
            [self.button('↗ Открыть весь блок в Facet', url=project_url)],
            [self.button('✓ Одобрить эту версию', f'a:{reference}:y'),
             self.button('✕ Вернуть в черновик', f'a:{reference}:n')],
            [self.button('‹ К списку', 'm:a')]]}
        return '\n'.join(lines), keyboard

    def invites_view(self, user):
        spaces = self.accounts.telegram_invite_spaces(user['id'])
        lines = ['➕ Приглашение в команду', '', 'Выберите команду и роль. Ссылка будет одноразовой и действует 7 дней.']
        keyboard = []
        for space in spaces:
            keyboard.append([self.button(f'👤 {space["name"]} · участник', f'i:{space["id"]}:m')])
            if space['role'] == 'owner':
                keyboard.append([self.button(f'★ {space["name"]} · администратор', f'i:{space["id"]}:a')])
        if not spaces:
            lines += ['', 'У вас нет команды, в которой можно создавать приглашения.']
        keyboard.append([self.button('‹ Меню', 'm:m')])
        return '\n'.join(lines), {'inline_keyboard': keyboard}

    def teams_view(self,user):
        teams=[space for space in self.accounts.spaces(user['id']) if space['kind']=='team']
        lines=['👥 Команды','','Выберите команду для просмотра участников и управления доступом.']
        keyboard=[]
        roles={'owner':'владелец','admin':'администратор','member':'участник'}
        for index,team in enumerate(teams,1):
            lines.append(f'\n{index}. {team["name"]} · {roles.get(team["role"],team["role"])}')
            keyboard.append([self.button(f'{index}. {team["name"]}'[:52],f'c:p:{team["id"]}')])
        if not teams:lines+=['','Вы пока не состоите в команде.']
        keyboard.append([self.button('‹ Меню','m:m')])
        return '\n'.join(lines),{'inline_keyboard':keyboard}

    def team_view(self,user,space_id):
        self.accounts.telegram_team_context(user['id'],space_id);info=self.accounts.team(user['id'],space_id)
        roles={'owner':'владелец','admin':'администратор','member':'участник'}
        lines=[f'👥 {info["name"]}','',f'Участников: {len(info["members"])} · Ваша роль: {roles[info["role"]]}']
        keyboard=[]
        for index,member in enumerate(info['members'],1):
            lines.append(f'\n{index}. {member["name"]} · {roles[member["role"]]}')
            if info['role'] in ('owner','admin') and member['id']!=user['id'] and member['role']!='owner':
                keyboard.append([self.button(f'⚙ {index}. {member["name"]}'[:52],f'c:u:{member["id"]}')])
        pending=[*info.get('invitations',[]),*info.get('telegram_invitations',[])]
        if pending and info['role'] in ('owner','admin'):
            lines+=['',f'Активных приглашений: {len(pending)}']
            for index,invite in enumerate(pending,1):keyboard.append([self.button(f'Отозвать приглашение {index}',f'c:r:{invite["id"]}')])
        history=info.get('history',[])[:5]
        if history:
            labels={'team_created':'Команда создана','invite_created':'Создано приглашение','invite_revoked':'Приглашение отозвано','member_joined':'Участник вступил','member_removed':'Участник удалён','role_changed':'Роль изменена','profile_changed':'Структура обновлена','ownership_transferred':'Владение передано'}
            lines+=['','Последние события:']
            for event in history:lines.append(f'• {labels.get(event["kind"],event["kind"])} · {event["target_name"] or event["actor_name"]}')
        if info['role'] in ('owner','admin'):
            keyboard.append([self.button('＋ Ссылка участника',f'i:{space_id}:m')])
            if info['role']=='owner':keyboard.append([self.button('★ Ссылка администратора',f'i:{space_id}:a')])
        keyboard.append([self.button('↻ Обновить',f'c:p:{space_id}'),self.button('‹ Команды','m:c')])
        return '\n'.join(lines)[:3900],{'inline_keyboard':keyboard}

    def team_member_view(self,user,target):
        space=self.accounts.telegram_team_context(user['id']);
        if not space:raise ValueError('Сначала выберите команду.')
        info=self.accounts.team(user['id'],space);member=next((item for item in info['members'] if item['id']==target),None)
        if not member:raise ValueError('Участник больше не состоит в команде.')
        roles={'owner':'Владелец','admin':'Администратор','member':'Участник'}
        buttons=[]
        if info['role']=='owner':
            if member['role']=='member':buttons.append([self.button('★ Сделать администратором',f'c:a:{target}')])
            elif member['role']=='admin':buttons.append([self.button('Сделать участником',f'c:m:{target}')])
        buttons.append([self.button('Удалить из команды',f'c:q:{target}')])
        buttons.append([self.button('‹ Команда',f'c:p:{space}')])
        return f'⚙ {member["name"]}\n\nРоль: {roles[member["role"]]}\nСпециализация: {member["specialty"]}',{'inline_keyboard':buttons}

    def invite_ready_view(self, result):
        role = 'Администратор' if result['role'] == 'admin' else 'Участник'
        content = (f'Ссылка для команды «{result["space_name"]}» готова.\n\n'
                   f'Роль: {role}\nСрок: 7 дней\nИспользование: один раз\n\n'
                   f'{result["url"]}\n\nПерешлите это сообщение приглашённому пользователю.')
        return content, {'inline_keyboard': [[self.button('Открыть приглашение ↗', url=result['url'])],
                                             [self.button('Создать ещё', 'm:i'), self.button('‹ Меню', 'm:m')]]}

    def webhook(self, update):
        if not isinstance(update, dict):
            raise ValueError('Некорректное событие Telegram.')
        if update.get('callback_query'):
            return self.callback(update['callback_query'])
        message = update.get('message') or {}
        sender = message.get('from') or {}
        chat = message.get('chat') or {}
        if not chat.get('id') or chat.get('type') != 'private':
            return {'ok': True}
        body = str(message.get('text') or '').strip()
        match = re.fullmatch(r'/start(?:@\w+)?\s+([A-Za-z0-9_-]{20,100})', body)
        if match:
            try:
                start_token = match.group(1)
                identity = {
                    'id': sender.get('id'), 'chat_id': chat.get('id'),
                    'username': sender.get('username'), 'first_name': sender.get('first_name'),
                    'last_name': sender.get('last_name')}
                if start_token.startswith('team_'):
                    result = self.accounts.accept_telegram_team_invite(start_token[5:], identity)
                    user = self.accounts.telegram_user(sender.get('id'))
                    self.set_menu(chat['id'])
                    role = {'owner': 'владелец', 'admin': 'администратор', 'member': 'участник'}[result['role']]
                    content, markup = self.main_view(user)
                    self.send(chat['id'], f'Вы добавлены в команду «{result["space_name"]}» как {role}.\n\n'+content, markup)
                    self.flush_notifications()
                    return {'ok': True}
                result = self.accounts.telegram_confirm(start_token, identity)
                user = self.accounts.telegram_user(sender.get('id'))
                self.set_menu(chat['id'])
                heading = 'Аккаунт Facet создан.' if result['created'] else 'Telegram подтверждён.'
                content, markup = self.main_view(user)
                self.send(chat['id'], heading + '\n\n' + content, markup)
            except (ValueError, AccessError) as exc:
                self.send(chat['id'], str(exc))
            return {'ok': True}
        user = self.accounts.telegram_user(sender.get('id'))
        if not user:
            self.send(chat['id'], 'Сначала откройте Facet и нажмите «Продолжить через Telegram».',
                      {'inline_keyboard': [[self.button('Открыть Facet ↗', url=self.site)]]})
            return {'ok': True}
        try:
            if re.fullmatch(r'/(?:start|menu)(?:@\w+)?', body):
                self.set_menu(chat['id'])
                view = self.main_view(user)
            elif re.fullmatch(r'/tasks(?:@\w+)?', body):
                view = self.tasks_view(user)
            elif re.fullmatch(r'/projects(?:@\w+)?', body):
                view = self.projects_view(user)
            elif re.fullmatch(r'/approvals(?:@\w+)?', body):
                view = self.approvals_view(user)
            elif re.fullmatch(r'/invite(?:@\w+)?', body):
                view = self.invites_view(user)
            elif re.fullmatch(r'/agent(?:@\w+)?', body):
                project_id=self.accounts.telegram_agent_project(user['id'])
                view=self.agent_project_view(user,project_id) if project_id else self.agent_projects_view(user)
            else:
                agent_question=re.fullmatch(r'/agent(?:@\w+)?\s+(.{1,4000})',body,re.S)
                new_task = re.fullmatch(r'/new(?:@\w+)?\s+(.{1,240})', body, re.S)
                if agent_question:
                    project_id=self.accounts.telegram_agent_project(user['id'])
                    if not project_id: raise ValueError('Сначала выберите проект в меню «Агент».')
                    self.send(chat['id'],'🤖 Анализирую проект…')
                    view=self.run_agent_analysis(user,project_id,prompt=agent_question.group(1))
                elif new_task:
                    self.accounts.create_work_item(user['id'], new_task.group(1))
                    content, markup = self.tasks_view(user)
                    view = ('Задача создана.\n\n' + content, markup)
                else:
                    view = self.main_view(user)
            self.send(chat['id'], *view)
        except (ValueError, AccessError, AgentError, KeyError) as exc:
            self.send(chat['id'], str(exc), self.main_keyboard(user))
        return {'ok': True}

    def callback(self, query):
        callback_id = query.get('id')
        sender = query.get('from') or {}
        message = query.get('message') or {}
        chat = message.get('chat') or {}
        if not callback_id or not chat.get('id') or chat.get('type') != 'private':
            return {'ok': True}
        user = self.accounts.telegram_user(sender.get('id'))
        if not user:
            self.answer(callback_id, 'Сначала войдите через сайт.', True)
            return {'ok': True}
        data = str(query.get('data') or '')
        try:
            notice = ''
            answered=False
            if data in ('m:m', 'm:t', 'm:p', 'm:a', 'm:i', 'm:g', 'm:c'):
                view = {'m:m': self.main_view, 'm:t': self.tasks_view,
                        'm:p': self.projects_view, 'm:a': self.approvals_view,
                        'm:i': self.invites_view,'m:g':self.agent_projects_view,
                        'm:c':self.teams_view}[data](user)
            elif data == 'm:n':
                enabled = not self.accounts.telegram_notifications(user['id'])
                self.accounts.telegram_notifications(user['id'], enabled)
                notice = 'Уведомления включены.' if enabled else 'Уведомления выключены.'
                view = self.main_view(user)
            elif re.fullmatch(r't:[0-9a-f]{24}:[pdn]', data):
                _, identifier, action = data.split(':')
                status = {'p': 'in_progress', 'd': 'done', 'n': 'todo'}[action]
                self.accounts.update_work_item(user['id'], identifier, status)
                notice = {'in_progress': 'Задача взята в работу.', 'done': 'Задача выполнена.', 'todo': 'Задача возвращена.'}[status]
                view = self.tasks_view(user)
            elif re.fullmatch(r'a:[0-9a-f]{12}:[vyn]', data):
                _, reference, action = data.split(':')
                if action == 'v':
                    view = self.approval_detail_view(user, reference)
                else:
                    result = self.accounts.decide_telegram_approval(user['id'], reference,
                                                                     'approve' if action == 'y' else 'reject')
                    notice = 'Блок одобрен.' if result['status'] == 'approved' else 'Блок возвращён в черновик.'
                    view = self.approvals_view(user)
            elif re.fullmatch(r'p:[0-9a-f]{32}', data):
                view = self.project_view(user, data[2:])
            elif re.fullmatch(r'g:p:[0-9a-f]{32}',data):
                view=self.agent_project_view(user,data[4:])
            elif re.fullmatch(r'g:l:[0-9a-f]{32}',data):
                view=self.agent_bpmn_view(user,data[4:])
            elif re.fullmatch(r'g:a:[0-9a-f]{32}',data):
                project_id=data[4:];self.answer(callback_id,'Агент анализирует проект…');answered=True
                self.edit(chat['id'],message.get('message_id'),'🤖 Анализирую проект. Обычно это занимает несколько секунд…')
                view=self.run_agent_analysis(user,project_id)
            elif re.fullmatch(r'g:b:[0-9a-f]{32}:\d{1,3}',data):
                _,_,project_id,index=data.split(':');self.answer(callback_id,'Агент анализирует BPMN…');answered=True
                self.edit(chat['id'],message.get('message_id'),'🤖 Проверяю BPMN, ветвления и исключения…')
                view=self.run_agent_analysis(user,project_id,'bpmn',int(index))
            elif re.fullmatch(r'g:q:[0-9a-f]{12}',data):
                action=self.accounts.telegram_agent_action(user['id'],data[4:])
                view=(f'Создать задачу по рекомендации агента?\n\n{action["title"]}\n\nЗадача будет назначена вам.',
                      {'inline_keyboard':[[self.button('✓ Создать',f'g:c:{action["id"]}'),self.button('Отмена',f'g:x:{action["id"]}')]]})
            elif re.fullmatch(r'g:c:[0-9a-f]{12}',data):
                action=self.accounts.telegram_agent_action(user['id'],data[4:],True);notice='Задача создана.'
                view=self.tasks_view(user)
            elif re.fullmatch(r'g:x:[0-9a-f]{12}',data):
                action=self.accounts.telegram_agent_action(user['id'],data[4:]);notice='Создание отменено.'
                view=self.agent_project_view(user,action['project_id'])
            elif re.fullmatch(r'c:p:[0-9a-f]{32}',data):
                view=self.team_view(user,data[4:])
            elif re.fullmatch(r'c:u:[0-9a-f]{32}',data):
                view=self.team_member_view(user,data[4:])
            elif re.fullmatch(r'c:r:[0-9a-f]{32}',data):
                space=self.accounts.telegram_team_context(user['id'])
                if not space:raise ValueError('Сначала выберите команду.')
                self.accounts.revoke_invite(user['id'],space,data[4:]);notice='Приглашение отозвано.'
                view=self.team_view(user,space)
            elif re.fullmatch(r'c:[am]:[0-9a-f]{32}',data):
                _,action,target=data.split(':');space=self.accounts.telegram_team_context(user['id'])
                if not space:raise ValueError('Сначала выберите команду.')
                self.accounts.change_member(user['id'],space,target,'admin' if action=='a' else 'member');notice='Роль изменена.'
                view=self.team_member_view(user,target)
            elif re.fullmatch(r'c:q:[0-9a-f]{32}',data):
                target=data[4:];space=self.accounts.telegram_team_context(user['id'])
                if not space:raise ValueError('Сначала выберите команду.')
                info=self.accounts.team(user['id'],space);member=next((item for item in info['members'] if item['id']==target),None)
                if not member:raise ValueError('Участник не найден.')
                view=(f'Удалить {member["name"]} из команды?\n\nОн потеряет доступ ко всем проектам команды.',
                      {'inline_keyboard':[[self.button('Удалить',f'c:d:{target}'),self.button('Отмена',f'c:u:{target}')]]})
            elif re.fullmatch(r'c:d:[0-9a-f]{32}',data):
                target=data[4:];space=self.accounts.telegram_team_context(user['id'])
                if not space:raise ValueError('Сначала выберите команду.')
                self.accounts.change_member(user['id'],space,target,'remove');notice='Участник удалён.'
                view=self.team_view(user,space)
            elif re.fullmatch(r'i:[0-9a-f]{32}:[ma]', data):
                _, space_id, role = data.split(':')
                result = self.create_team_invite(user['id'], space_id, 'admin' if role == 'a' else 'member')
                notice = 'Ссылка создана.'
                view = self.invite_ready_view(result)
            else:
                raise ValueError('Кнопка устарела. Откройте меню заново.')
            self.edit(chat['id'], message.get('message_id'), *view)
            if not answered:self.answer(callback_id, notice or 'Готово')
            self.flush_notifications()
        except (ValueError, AccessError, AgentError, KeyError) as exc:
            if 'answered' in locals() and answered:
                self.edit(chat['id'],message.get('message_id'),f'Анализ не завершён.\n\n{exc}',
                          {'inline_keyboard':[[self.button('‹ Агент','m:g')]]})
            else:
                self.answer(callback_id, str(exc), True)
        return {'ok': True}

    def request(self, method, payload):
        request = Request(f'https://api.telegram.org/bot{self.token}/{method}',
                          data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            try:
                details = json.loads(exc.read()).get('description', str(exc))
            except (ValueError, UnicodeError):
                details = str(exc)
            raise RuntimeError('Telegram API: ' + details) from exc
        if not result.get('ok'):
            raise RuntimeError('Telegram API: ' + str(result.get('description') or 'сообщение отклонено'))
        return result.get('result')

    def send(self, chat_id, content, reply_markup=None):
        payload = {'chat_id': chat_id, 'text': content[:4000]}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self.request('sendMessage', payload)

    def flush_notifications(self,limit=20):
        """Deliver queued product events without making the originating request fail."""
        delivered=0
        for item in self.accounts.pending_telegram_notifications(limit):
            markup=None
            if item.get('button_text') and item.get('callback_data'):
                markup={'inline_keyboard':[[self.button(item['button_text'],item['callback_data'])]]}
            try:
                self.send(item['chat_id'],item['content'],markup)
                self.accounts.finish_telegram_notification(item['id'],True);delivered+=1
            except (RuntimeError,OSError,ValueError):
                self.accounts.finish_telegram_notification(item['id'],False)
        return delivered

    def set_menu(self, chat_id):
        """Pin the Mini App for this private chat; BotFather defaults may override the global button."""
        try:
            return self.request('setChatMenuButton', {'chat_id': int(chat_id), 'menu_button': {
                'type': 'web_app', 'text': 'Открыть Facet',
                'web_app': {'url': self.site + '/telegram-app?v=20260921-3'},
            }})
        except (RuntimeError, TypeError, ValueError):
            return False

    def edit(self, chat_id, message_id, content, reply_markup=None):
        payload = {'chat_id': chat_id, 'message_id': message_id, 'text': content[:4000]}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        try:
            return self.request('editMessageText', payload)
        except RuntimeError as exc:
            if 'message is not modified' in str(exc):
                return None
            raise

    def answer(self, callback_id, content='', alert=False):
        return self.request('answerCallbackQuery', {'callback_query_id': callback_id,
                                                     'text': content[:180], 'show_alert': bool(alert)})
