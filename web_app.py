"""Локальная проектная среда: python3 web_app.py. Аккаунты и права проверяются сервером."""
import argparse
import hmac
import ipaddress
import json
import mimetypes
import os
import threading
import time
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from workspace import Store, Conflict, BASE
from bpmn_web import analyze, edit
from accounts import Accounts, AccessError, Mailer, SESSION_AGE
from block_templates import Templates
from ai_agent import Agent, AgentError
from telegram_bot import TelegramBot
from presentation import extract_pptx

MAX_REQUEST = 12 * 1024 * 1024
COOKIE = 'workspace_session'


def make_handler(store, accounts=None):
    started = time.time()
    templates = Templates(store)
    agent = Agent(store)
    accounts = accounts or Accounts(store, Mailer(Path(store.path).parent/'mailbox', 'http://127.0.0.1:8765'))
    telegram = TelegramBot(accounts, agent)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'ProjectWorkspace/2.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, format, *args):
            # Тела, cookies и ссылки с токенами в журнал не записываем.
            if args and isinstance(args[0],str) and '/api/auth/' in args[0]:
                return
            try:
                super().log_message(format,*args)
            except OSError:
                pass  # Закрытый вывод терминала не должен прерывать HTTP-ответ.

        def client_ip(self):
            if os.environ.get('WORKSPACE_TRUST_PROXY') == '1':
                forwarded=self.headers.get('X-Real-IP','').strip()
                try:
                    return str(ipaddress.ip_address(forwarded))
                except ValueError:
                    pass
            return self.client_address[0]

        def charged_agent(self, user, callback, free=False):
            if free:
                return callback()
            accounts.limit_agent(user)
            try:
                result=callback()
                if isinstance(result,dict) and result.get('model')=='Facet local':
                    accounts.refund_agent(user)
                return result
            except AgentError as error:
                if error.unbilled:
                    accounts.refund_agent(user)
                    if error.global_reserved:
                        agent.refund()
                raise

        def reply(self, status, body, content_type='application/json; charset=utf-8', cookie=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Permissions-Policy', 'camera=(), geolocation=(), payment=(), usb=()')
            if accounts.mailer.base_url.startswith('https://'):
                self.send_header('Strict-Transport-Security', 'max-age=31536000')
            response_path = urlsplit(self.path).path
            if response_path == '/prototype-frame.html':
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'")
            elif response_path in ('/telegram-app','/admin-app'):
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org; form-action 'self'")
            else:
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if cookie is not None:
                secure = '; Secure' if accounts.mailer.base_url.startswith('https://') else ''
                self.send_header('Set-Cookie',f'{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_AGE if cookie else 0}{secure}')
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            self.session_token = ''
            host = self.headers.get('Host','')
            allowed = {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            configured = urlsplit(accounts.mailer.base_url)
            allowed.add(configured.netloc)
            if host not in allowed:
                return self.reply(403,{'error':'Неизвестный адрес сервера.'})
            origin = self.headers.get('Origin')
            origins = {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}',accounts.mailer.base_url}
            # Переход по ссылке из почты является cross-site navigation. Разрешаем
            # только публичную оболочку и bridge; API сохраняет строгую проверку.
            request_path = urlsplit(self.path).path
            is_public_navigation = self.command in ('GET', 'HEAD') and request_path in ('/', '/telegram-app', '/admin-app')
            is_bridge = self.command == 'GET' and request_path == '/prototype-bridge.js'
            if not (is_public_navigation or is_bridge) and ((origin and origin not in origins) or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                return self.reply(403,{'error':'Запрос с другого сайта отклонён.'})
            url = urlsplit(self.path)
            path, query = url.path, parse_qs(url.query)
            body={}
            if self.command in ('POST','PUT','DELETE'):
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    return self.reply(415,{'error':'Ожидается application/json.'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0 < length <= MAX_REQUEST:
                        return self.reply(413,{'error':'Запрос больше 12 МБ или пуст.'})
                    body=json.loads(self.rfile.read(length))
                    if not isinstance(body,dict):
                        raise ValueError('Ожидается JSON-объект.')
                except (ValueError,UnicodeError,RecursionError) as exc:
                    return self.reply(400,{'error':'Некорректный JSON.'})
            try:
                assets={'/':'index.html','/telegram-app':'telegram-app.html','/telegram-app.css':'telegram-app.css','/telegram-app.js':'telegram-app.js','/admin-app':'admin-app.html','/admin-app.css':'admin-app.css','/admin-app.js':'admin-app.js','/logo.svg':'logo.svg','/runtime.css':'runtime.css','/parallel.js':'parallel.js','/prototype.js':'prototype.js','/features.js':'features.js','/app.js':'app.js','/auth-transition.js':'auth-transition.js','/account.js':'account.js','/sections.js':'sections.js','/style.css':'style.css','/account.css':'account.css'}
                assets.update({name: name[1:] for name in ('/agent.js','/agent.css','/prototype-frame.html','/prototype-bridge.js','/pptx-export.js','/vendor/jszip.min.js','/vendor/pptxgen.min.js')})
                if self.command=='GET' and path in assets:
                    file=BASE/'web'/assets[path]
                    return self.reply(200,file.read_bytes(),(mimetypes.guess_type(file.name)[0] or 'application/octet-stream')+'; charset=utf-8')
                if self.command=='GET' and path=='/api/health':
                    return self.reply(200,{'app':'ProjectWorkspace','version':2})
                if not path.startswith('/api/'):
                    return self.reply(404,{'error':'Не найдено.'})
                cookie=SimpleCookie()
                try: cookie.load(self.headers.get('Cookie',''))
                except CookieError: pass
                self.session_token=cookie[COOKIE].value if COOKIE in cookie else ''
                principal=accounts.session(self.session_token)
                if self.command=='GET' and path=='/api/auth/me':
                    return self.reply(200,{'user':{k:v for k,v in principal.items() if k!='csrf'} if principal else None,
                                          'csrf':principal['csrf'] if principal else None,'delivery':accounts.mailer.mode,
                                          'telegram':telegram.public_status(principal['id'] if principal else None),
                                          'security_events':accounts.security_events(principal['id']) if principal else [],
                                          'notification_count':accounts.web_notifications(principal['id'],100)['unread'] if principal else 0,
                                          'spaces':accounts.spaces(principal['id']) if principal else [],
                                          'migration_available':accounts.migration_available() if principal else False})
                if self.command=='POST' and path=='/api/auth/telegram/start':
                    accounts.limit('telegram-start',self.client_ip(),10,900)
                    if principal:
                        csrf=self.headers.get('X-CSRF-Token','')
                        if not hmac.compare_digest(csrf,principal['csrf']):
                            raise AccessError('Обновите страницу и повторите действие.',403,'csrf')
                    return self.reply(200,telegram.start(principal['id'] if principal else None))
                if self.command=='POST' and path=='/api/auth/telegram/complete':
                    accounts.limit('telegram-complete',self.client_ip(),60,900)
                    result=accounts.telegram_complete(body.get('token'))
                    if not result:
                        return self.reply(202,{'state':'pending'})
                    token,user,csrf=result
                    if self.session_token: accounts.logout(self.session_token)
                    return self.reply(200,{'state':'confirmed','user':user,'csrf':csrf},cookie=token)
                if self.command=='POST' and path=='/api/auth/telegram/webapp':
                    accounts.limit('telegram-webapp',self.client_ip(),30,900)
                    token,user,csrf=telegram.webapp_login(body.get('init_data'))
                    if self.session_token: accounts.logout(self.session_token)
                    return self.reply(200,{'user':user,'csrf':csrf},cookie=token)
                if self.command=='POST' and path=='/api/auth/telegram/admin-webapp':
                    accounts.limit('telegram-admin-webapp',self.client_ip(),30,900)
                    token,user,csrf=telegram.admin_webapp_login(body.get('init_data'))
                    if self.session_token: accounts.logout(self.session_token)
                    return self.reply(200,{'user':user,'csrf':csrf},cookie=token)
                if self.command=='POST' and path=='/api/auth/email/confirm':
                    accounts.limit('email-confirm',self.client_ip(),15,900)
                    linked_user=accounts.complete_email_link(body.get('token'))
                    return self.reply(200,{'message':'Почта подтверждена. Теперь можно входить по почте или через Telegram.',
                                           'user':linked_user})
                if self.command=='POST' and path=='/api/telegram/webhook':
                    if not telegram.check_secret(self.headers.get('X-Telegram-Bot-Api-Secret-Token','')):
                        raise AccessError('Событие Telegram отклонено.',403,'telegram_secret')
                    return self.reply(200,telegram.webhook(body))
                if self.command=='POST' and path in ('/api/auth/register','/api/auth/login','/api/auth/forgot','/api/auth/resend','/api/auth/verify','/api/auth/reset'):
                    accounts.limit('auth-ip',self.client_ip(),80,900)
                    if path.endswith(('/login','/register','/forgot','/resend')):
                        identity=str(body.get('email','')).strip().lower()[:254]
                        accounts.limit(path,identity,12 if path.endswith('/login') else 5,900)
                    message='Если адрес подходит для этого действия, письмо отправлено.'
                    if path.endswith('/register'):
                        accounts.register(body)
                    elif path.endswith('/login'):
                        token,user,csrf=accounts.login(body.get('email'),body.get('password'))
                        if self.session_token: accounts.logout(self.session_token)
                        return self.reply(200,{'user':user,'csrf':csrf},cookie=token)
                    elif path.endswith('/forgot'):
                        accounts.issue_mail(body.get('email'),'reset')
                    elif path.endswith('/resend'):
                        accounts.issue_mail(body.get('email'),'verify')
                    else:
                        kind='verify' if path.endswith('/verify') else 'reset'
                        accounts.use_token(body.get('token'),kind,body.get('password'))
                        message='Почта подтверждена. Можно войти.' if kind=='verify' else 'Пароль изменён. Войдите заново.'
                    return self.reply(200,{'message':message,'delivery':accounts.mailer.mode})
                if not principal:
                    raise AccessError('Войдите в аккаунт.',401,'login_required')
                user=principal['id']
                if path=='/api/billing/demo-purchase' and self.command=='POST':
                    csrf=self.headers.get('X-CSRF-Token','')
                    if not hmac.compare_digest(csrf,principal['csrf']):
                        raise AccessError('Обновите страницу и повторите действие.',403,'csrf')
                    return self.reply(200,accounts.demo_purchase_plan(user,body.get('plan')))
                if path=='/api/admin/dashboard' and self.command=='GET':
                    telegram.require_admin(user)
                    result=accounts.admin_dashboard();result['agent']=agent.status();result['system']={
                        'uptime_seconds':int(time.time()-started),'database_bytes':Path(store.path).stat().st_size,
                        'server_time':time.time(),'version':2,'mail_mode':accounts.mailer.mode,
                        'mail_configured':bool(accounts.mailer.host),'telegram_enabled':telegram.enabled,
                        'telegram_username':telegram.username}
                    return self.reply(200,result)
                if self.command in ('POST','PUT','DELETE'):
                    csrf=self.headers.get('X-CSRF-Token','')
                    if not hmac.compare_digest(csrf,principal['csrf']):
                        raise AccessError('Обновите страницу и повторите действие.',403,'csrf')
                if path=='/api/admin/agent/limit' and self.command=='POST':
                    telegram.require_admin(user)
                    value=agent.set_global_limit(body.get('daily_limit'))
                    accounts.admin_system_action(user,'set_global_agent_limit',value)
                    return self.reply(200,agent.status())
                admin_parts=path.strip('/').split('/')
                if len(admin_parts)==5 and admin_parts[:3]==['api','admin','users'] and self.command=='POST':
                    telegram.require_admin(user)
                    return self.reply(200,accounts.admin_user_action(user,admin_parts[3],body.get('action'),body.get('daily_limit'),body.get('monthly_limit'),body.get('plan'),body.get('duration_days')))
                if path=='/api/auth/logout' and self.command=='POST':
                    accounts.logout(self.session_token)
                    return self.reply(200,{'ok':True},cookie='')
                if path=='/api/mobile/summary' and self.command=='GET':
                    task_page=accounts.work_items_page(user,'active');tasks=task_page['items'];approvals=accounts.telegram_approvals(user,30);projects=accounts.telegram_projects(user,20)
                    return self.reply(200,{'user':{k:v for k,v in principal.items() if k!='csrf'},'counts':{
                        'todo':task_page['counts']['todo'],
                        'in_progress':task_page['counts']['in_progress'],
                        'done':task_page['counts']['done'],
                        'approvals':len(approvals),'projects':len(projects)},
                        'tasks':tasks[:4],'approvals':approvals[:4],'projects':projects[:4]})
                if path=='/api/notifications' and self.command=='GET':
                    return self.reply(200,accounts.web_notifications(user))
                if path=='/api/notifications/count' and self.command=='GET':
                    return self.reply(200,{'unread':accounts.web_notifications(user,100)['unread']})
                if path=='/api/notifications/read' and self.command=='POST':
                    keys=body.get('keys')
                    if keys is not None and not isinstance(keys,list): raise ValueError('Некорректный список уведомлений.')
                    return self.reply(200,{'unread':accounts.mark_web_notifications(user,keys)})
                if path=='/api/search' and self.command=='GET':
                    return self.reply(200,{'items':accounts.global_search(user,query.get('q',[''])[0])})
                if path=='/api/analytics' and self.command=='GET':
                    return self.reply(200,accounts.project_analytics(user,query.get('space',[''])[0],query.get('period',['30'])[0]))
                if path=='/api/mobile/tasks':
                    if self.command=='GET':
                        if query.get('paged',[''])[0]=='1':
                            return self.reply(200,accounts.work_items_page(user,
                                query.get('filter',['active'])[0],query.get('page',['1'])[0]))
                        return self.reply(200,accounts.work_items(user,30,True))
                    if self.command=='POST':
                        task_id=accounts.create_work_item(user,body.get('title'),
                            project_id=body.get('project_id'),block_id=body.get('block_id'),
                            assignee_id=body.get('assignee_id'),description=body.get('description',''),due=body.get('due'))
                        telegram.flush_notifications()
                        return self.reply(201,{'id':task_id})
                if path=='/api/mobile/assignees' and self.command=='GET':
                    return self.reply(200,accounts.work_assignees(user))
                if path=='/api/mobile/projects' and self.command=='GET':
                    return self.reply(200,accounts.telegram_projects(user,20))
                if path=='/api/mobile/approvals' and self.command=='GET':
                    return self.reply(200,accounts.telegram_approvals(user,20))
                mobile_parts=path.strip('/').split('/')
                if len(mobile_parts)==4 and mobile_parts[:3]==['api','mobile','approvals'] and self.command=='GET':
                    return self.reply(200,accounts.telegram_approval_detail(user,mobile_parts[3]))
                if len(mobile_parts)==4 and mobile_parts[:3]==['api','mobile','tasks'] and self.command=='PUT':
                    return self.reply(200,{'status':accounts.update_work_item(user,mobile_parts[3],body.get('status'))})
                if len(mobile_parts)==4 and mobile_parts[:3]==['api','mobile','approvals'] and self.command=='POST':
                    result=accounts.decide_telegram_approval(user,mobile_parts[3],body.get('decision'));telegram.flush_notifications()
                    return self.reply(200,result)
                if len(mobile_parts)==4 and mobile_parts[:3]==['api','mobile','projects'] and self.command=='GET':
                    project=accounts.project(user,mobile_parts[3]);statuses={'draft':0,'review':0,'approved':0}
                    for block in project.get('blocks',[]):
                        if block.get('status') in statuses: statuses[block['status']]+=1
                    return self.reply(200,{'id':project['id'],'name':project['name'],'goal':project.get('goal',''),
                        'access':project['access'],'updated':project['updated'],'blocks':len(project.get('blocks',[])),
                        'bpmn':sum(bool(block.get('bpmn')) for block in project.get('blocks',[])),'statuses':statuses})
                if path == '/api/agent/status' and self.command == 'GET':
                    status=agent.status();status['global_daily_limit']=status['daily_limit'];status['global_used_today']=status['used_today']
                    status.update(accounts.agent_quota(user))
                    return self.reply(200,status)
                if path == '/api/agent/chat' and self.command == 'GET':
                    project_id=query.get('project_id',[None])[0]
                    with accounts.db() as db: accounts.permission(db,user,project_id,'viewer')
                    return self.reply(200,{'messages':agent.history(user,project_id)})
                if path == '/api/agent/chat' and self.command == 'POST':
                    project=accounts.project(user,body.get('project_id'))
                    prompt=body.get('prompt');block_id=body.get('block_id');layer=body.get('layer','all')
                    free=agent.is_local_layout(project,prompt,block_id,layer)
                    specialty=next((space['team_specialty'] for space in accounts.spaces(user)
                                    if space['id']==project['space_id'] and space['team_specialty']),principal['specialty'])
                    result=self.charged_agent(user,lambda:agent.chat(project,user,project['access'],specialty,prompt,block_id,layer,body.get('mode','auto')),free=free)
                    return self.reply(200,result)
                if path == '/api/agent/apply' and self.command == 'POST':
                    from agent_changes import apply_plan
                    project_id=body.get('project_id')
                    with accounts.db() as db: accounts.permission(db,user,project_id,'editor')
                    project=accounts.project(user,project_id)
                    draft=agent.draft(user,project_id,body.get('draft_id'))
                    if draft['revision']!=project['revision']:
                        raise Conflict('Проект изменился после предложения агента. Попросите подготовить изменения заново.')
                    updated,touched=apply_plan(project,draft['operations'])
                    saved=accounts.save_project(user,project_id,updated,project['revision'])
                    telegram.flush_notifications()
                    agent.consume_draft(user,body.get('draft_id'))
                    return self.reply(200,{'project':saved,'touched':touched,'summary':draft['summary']})
                if path in ('/api/agent/check', '/api/agent/generate', '/api/agent/analyze') and self.command == 'POST':
                    with accounts.db() as db:
                        accounts.permission(db, user, body.get('project_id'), 'editor' if path.endswith('/generate') else 'viewer')
                    if path.endswith('/check'):
                        return self.reply(200, agent.check())
                    project = accounts.project(user, body.get('project_id'))
                    if path.endswith('/analyze'):
                        result=self.charged_agent(user,lambda:agent.analyze(project, body.get('scope', 'project'), body.get('block_id'), body.get('prompt', ''),user))
                        return self.reply(200,result)
                    block = next((b for b in project['blocks'] if b['id'] == body.get('block_id')), None)
                    if block is None: raise KeyError('block')
                    return self.reply(200,self.charged_agent(user,lambda:agent.generate(block, body.get('prompt'),user)))
                if path=='/api/templates':
                    if self.command=='GET':
                        return self.reply(200,templates.list(user))
                    if self.command=='POST':
                        with accounts.db() as db:
                            accounts.permission(db,user,body.get('project_id'),'editor')
                        project=accounts.project(user,body.get('project_id'))
                        block=next((b for b in project['blocks'] if b['id']==body.get('block_id')),None)
                        if block is None: raise KeyError('block')
                        return self.reply(201,templates.save(user,body.get('name'),block))
                if path=='/api/auth/profile' and self.command=='PUT':
                    accounts.update_profile(user,body)
                    return self.reply(200,{'ok':True})
                if path=='/api/auth/telegram/notifications' and self.command=='POST':
                    if type(body.get('enabled')) is not bool:
                        raise ValueError('Выберите режим уведомлений.')
                    return self.reply(200,{'enabled':accounts.telegram_notifications(user,body['enabled'])})
                if path=='/api/auth/email/start' and self.command=='POST':
                    accounts.limit('email-start',user,5,3600)
                    accounts.start_email_link(user,body.get('email'),body.get('password'))
                    return self.reply(200,{'message':'Письмо для подтверждения отправлено.','delivery':accounts.mailer.mode})
                if path=='/api/auth/methods/unlink' and self.command=='POST':
                    accounts.limit('method-unlink',user,8,3600)
                    updated=accounts.unlink_login_method(user,body.get('method'),body.get('password'),self.session_token)
                    return self.reply(200,{'user':updated})
                if path=='/api/legacy/claim' and self.command=='POST':
                    accounts.limit('migration',user,5,900)
                    return self.reply(200,{'count':accounts.claim_legacy(user,body.get('key'))})
                if path=='/api/spaces':
                    if self.command=='GET': return self.reply(200,accounts.spaces(user))
                    if self.command=='POST': return self.reply(201,{'id':accounts.create_space(user,body.get('name'))})
                if path=='/api/invitations/accept' and self.command=='POST':
                    accounts.limit('invite-accept',user,20,900)
                    return self.reply(200,{'space_id':accounts.accept_invite(user,body.get('token'))})
                parts=path.strip('/').split('/')
                if len(parts)>=3 and parts[:2]==['api','spaces']:
                    space=parts[2]
                    if len(parts)==3 and self.command=='GET': return self.reply(200,accounts.team(user,space))
                    if len(parts)==4 and self.command=='POST':
                        op=parts[3]
                        if op=='invite':
                            accounts.limit('invite-send',user,20,3600)
                            accounts.invite(user,space,body.get('email'),body.get('role'))
                        elif op=='telegram-invite':
                            accounts.limit('telegram-invite-create',user,25,3600)
                            return self.reply(201,telegram.create_team_invite(user,space,body.get('role'),body.get('specialty'),body.get('manager_id')))
                        elif op=='revoke': accounts.revoke_invite(user,space,body.get('id'))
                        elif op=='member': accounts.change_member(user,space,body.get('user_id'),body.get('role'))
                        elif op=='organization': accounts.update_member_org(user,space,body.get('user_id'),body)
                        elif op=='transfer':
                            accounts.limit('transfer',user,5,900)
                            accounts.transfer(user,space,body.get('user_id'),body.get('password'))
                        else: return self.reply(404,{'error':'Не найдено.'})
                        telegram.flush_notifications()
                        return self.reply(200,{'ok':True,'delivery':accounts.mailer.mode})
                if path=='/api/presentation/extract' and self.command=='POST':
                    project=accounts.project(user,body.get('project_id'))
                    if project['access'] not in ('editor','manager'):
                        raise AccessError('Нет права редактировать презентацию.',403)
                    accounts.limit('pptx-upload',user,10,3600)
                    return self.reply(200,{'slides':extract_pptx(body.get('content'))})
                if path=='/api/presentation/suggest' and self.command=='POST':
                    project=accounts.project(user,body.get('project_id'))
                    if project['access'] not in ('editor','manager'):
                        raise AccessError('Нет права редактировать презентацию.',403)
                    return self.reply(200,self.charged_agent(user,lambda:agent.suggest_slides(project,body.get('slides'),user)))
                if path=='/api/projects':
                    if self.command=='GET':
                        space=query.get('space',[None])[0]
                        return self.reply(200,accounts.projects(user,space))
                    if self.command=='POST':
                        return self.reply(201,accounts.create_project(user,body.get('space_id'),body.get('name','Новый проект'),body.get('project'),body.get('demo') is True))
                if len(parts)>=3 and parts[:2]==['api','projects']:
                    identifier=parts[2]
                    if len(parts)==4 and parts[3]=='bpmn-history':
                        block_id=query.get('block',[None])[0]
                        if self.command=='GET':
                            version=query.get('version',[None])[0]
                            return self.reply(200,accounts.bpmn_version(user,identifier,block_id,version) if version else accounts.bpmn_history(user,identifier,block_id))
                    if len(parts)==4 and parts[3]=='bpmn-restore' and self.command=='POST':
                        return self.reply(200,accounts.restore_bpmn(user,identifier,body.get('block_id'),body.get('version_id'),body.get('revision')))
                    if len(parts)==4 and parts[3]=='access':
                        if self.command=='GET': return self.reply(200,accounts.access_list(user,identifier))
                        if self.command=='PUT':
                            accounts.grant(user,identifier,body.get('user_id'),body.get('role'))
                            return self.reply(200,{'ok':True})
                    if len(parts)==3:
                        if self.command=='GET': return self.reply(200,accounts.project(user,identifier))
                        if self.command=='PUT':
                            saved=accounts.save_project(user,identifier,body.get('project'),body.get('revision'));telegram.flush_notifications()
                            return self.reply(200,saved)
                        if self.command=='DELETE':
                            accounts.delete_project(user,identifier)
                            return self.reply(200,{'ok':True})
                if path in ('/api/bpmn/analyze','/api/bpmn/edit') and self.command=='POST':
                    xml=body.get('xml','')
                    if not isinstance(xml,str) or len(xml.encode('utf-8'))>5*1024*1024:
                        raise ValueError('Нужен BPMN XML размером до 5 МБ.')
                    if path.endswith('/edit'):
                        with accounts.db() as db: accounts.permission(db,user,body.get('project_id'),'editor')
                        if not isinstance(body.get('action'),dict): raise ValueError('Ожидается операция редактора.')
                        xml=edit(xml,body['action'])
                    return self.reply(200,analyze(xml))
                return self.reply(404,{'error':'Не найдено.'})
            except AgentError as exc:
                self.reply(exc.status, {'error': str(exc)})
            except AccessError as exc:
                self.reply(exc.status,{'error':str(exc),'code':exc.code})
            except Conflict as exc:
                self.reply(409,{'error':str(exc),'code':'conflict'})
            except KeyError:
                self.reply(404,{'error':'Не найдено.'})
            except (ValueError,TypeError,sqlite3.IntegrityError) as exc:
                self.reply(400,{'error':str(exc) if not isinstance(exc,sqlite3.IntegrityError) else 'Запись уже существует. Обновите страницу.'})
            except Exception:
                import traceback
                traceback.print_exc()
                self.reply(500,{'error':'Действие не завершено из-за внутренней ошибки сервера. Обновите страницу и повторите попытку.'})

        do_GET=dispatch
        do_POST=dispatch
        do_PUT=dispatch
        do_DELETE=dispatch
    return Handler


import sqlite3


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',choices=('127.0.0.1','localhost','0.0.0.0'),default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',type=Path,default=BASE/'data'/'workspace.sqlite3')
    args=parser.parse_args()
    store=Store(args.data)
    origin=os.environ.get('WORKSPACE_PUBLIC_URL',f'http://127.0.0.1:{args.port}').rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit('WORKSPACE_PUBLIC_URL должен содержать только схему и адрес сервера.')
    if parsed.hostname not in ('127.0.0.1','localhost') and parsed.scheme!='https':
        raise SystemExit('Для внешнего адреса требуется HTTPS.')
    mailer=Mailer(args.data.parent/'mailbox',origin)
    if parsed.hostname not in ('127.0.0.1','localhost') and mailer.mode!='smtp':
        raise SystemExit('Для внешнего адреса настройте SMTP.')
    accounts=Accounts(store,mailer)
    notification_stop=threading.Event()
    notification_bot=TelegramBot(accounts)
    def notification_loop():
        while not notification_stop.wait(60):
            try:
                accounts.queue_due_task_reminders();notification_bot.flush_notifications(50)
            except Exception:
                pass
    threading.Thread(target=notification_loop,name='facet-notifications',daemon=True).start()
    server=ThreadingHTTPServer((args.host,args.port),make_handler(store,accounts))
    print(f'Проектная среда: {origin}\nСлушает: {args.host}:{args.port}\nДанные: {args.data}\nПочта: {mailer.mode}\nCtrl+C — остановить',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: notification_stop.set();server.server_close()


if __name__=='__main__':
    main()
