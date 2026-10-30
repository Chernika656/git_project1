"""Регрессии безопасности: чужие проекты, роли, отзыв доступа и одноразовые токены."""
import copy
import json
import re
import tempfile
import time
import unittest
import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from facet.identity.accounts import Accounts, AccessError, password_hash, password_matches, digest
from facet.ai.agent import Agent
from facet.integrations.telegram import TelegramBot
from facet.projects.workspace import Store, Conflict, new_block

PASSWORD = 'a long test password 2026!'


class TestMail:
    mode='local'
    base_url='http://127.0.0.1:8765'
    def __init__(self): self.sent=[]
    def send(self,email,subject,content,html_content=None): self.sent.append((email,subject,content))
    def token(self,kind,email=None):
        for recipient,subject,body in reversed(self.sent):
            match=re.search(r'#'+kind+r'=([^\s]+)',body)
            if match and (email is None or recipient==email): return match[1]
        raise AssertionError('Письмо не найдено.')


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.encoded=password_hash(PASSWORD)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite3')
        self.mail=TestMail();self.a=Accounts(self.store,self.mail)
        # Фабрика тестовых пользователей экономит хеширование в тестах ACL.
        with self.a.db() as db:
            for uid in ('owner','admin','member','outsider'):
                db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',(uid,uid+'@example.test',uid,self.encoded,1,'business','purple'))
                db.execute('INSERT INTO spaces VALUES (?,?,?,?)',('personal-'+uid,'Личное','personal',uid))
                db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)',('personal-'+uid,uid,'owner'))
        self.team='team-fixture'
        with self.a.db() as db:
            db.execute('INSERT INTO spaces VALUES (?,?,?,?)',(self.team,'Команда','team','owner'))
            db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)',(self.team,'owner','owner'))
            db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)',(self.team,'admin','admin'))
            db.execute('INSERT INTO members (space_id,user_id,role) VALUES (?,?,?)',(self.team,'member','member'))
        self.p=self.a.create_project('owner',self.team,'Секретный проект')
    def tearDown(self): self.tmp.cleanup()
    def test_registration_and_email_verification(self):
        self.a.register(dict(name='Новый',email=' NEW@example.test ',password=PASSWORD,specialty='system'))
        with self.assertRaises(AccessError): self.a.login('new@example.test',PASSWORD)
        token=self.mail.token('verify')
        self.a.use_token(token,'verify')
        session,user,csrf=self.a.login('new@example.test',PASSWORD)
        self.assertEqual(user['email'],'new@example.test');self.assertEqual(user['specialty'],'system')
        self.assertEqual(self.a.session(session)['id'],user['id']);self.assertTrue(csrf)
        self.assertEqual(len(self.a.spaces(user['id'])),1)
        with self.assertRaises(ValueError): self.a.use_token(token,'verify')
    def test_password_hash_is_salted_and_checkable(self):
        encoded=password_hash(PASSWORD)
        self.assertNotEqual(encoded,self.encoded);self.assertNotIn(PASSWORD,encoded)
        self.assertTrue(password_matches(PASSWORD,encoded))
        self.assertFalse(password_matches('wrong long password!',encoded))
    def test_password_policy(self):
        for value in ('short','a'*129,None):
            with self.assertRaises(ValueError): password_hash(value)
    def test_existing_registration_does_not_replace_account(self):
        self.a.register(dict(name='Attacker',email='owner@example.test',password='another long password!',specialty='qa'))
        with self.a.db() as db:self.assertEqual(db.execute("SELECT name FROM users WHERE id='owner'").fetchone()['name'],'owner')
        self.assertEqual(self.mail.sent,[])
    def test_session_logout_and_expiry(self):
        token,_,_=self.a.login('owner@example.test',PASSWORD)
        self.assertIsNotNone(self.a.session(token));self.a.logout(token);self.assertIsNone(self.a.session(token))
        token,_,_=self.a.login('owner@example.test',PASSWORD)
        with self.a.db() as db:db.execute('UPDATE sessions SET seen=0 WHERE token=?',(digest(token),))
        self.assertIsNotNone(self.a.session(token))
        self.a.login('member@example.test',PASSWORD)
        self.assertIsNotNone(self.a.session(token))
        with self.a.db() as db:db.execute('UPDATE sessions SET expires=0 WHERE token=?',(digest(token),))
        self.assertIsNone(self.a.session(token))
    def test_telegram_registration_and_link_are_single_use(self):
        raw=self.a.telegram_start()
        result=self.a.telegram_confirm(raw,dict(id=1001,chat_id=1001,username='facet_user',first_name='Facet'))
        self.assertTrue(result['created'])
        session,user,csrf=self.a.telegram_complete(raw)
        self.assertEqual(self.a.session(session)['id'],user['id']);self.assertTrue(csrf)
        self.assertEqual(self.a.telegram_account(user['id'])['username'],'facet_user')
        with self.assertRaises(AccessError):self.a.telegram_complete(raw)
        link=self.a.telegram_start('owner')
        result=self.a.telegram_confirm(link,dict(id=2002,chat_id=2002,first_name='Owner'))
        self.assertFalse(result['created']);self.assertEqual(result['user_id'],'owner')

    def test_telegram_webapp_signature_creates_session(self):
        link=self.a.telegram_start('owner')
        self.a.telegram_confirm(link,dict(id=2002,chat_id=2002,first_name='Owner'))
        token='123456:test-token'
        params={'auth_date':str(int(time.time())),'query_id':'AAE-test',
                'user':json.dumps({'id':2002,'first_name':'Owner'},separators=(',',':'))}
        check='\n'.join(f'{key}={params[key]}' for key in sorted(params))
        secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        params['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':token,'TELEGRAM_BOT_USERNAME':'facet_test',
                                    'TELEGRAM_WEBHOOK_SECRET':'test-secret'}):
            session,user,csrf=TelegramBot(self.a).webapp_login(urlencode(params))
        self.assertEqual(user['id'],'owner');self.assertTrue(csrf)
        self.assertEqual(self.a.session(session)['id'],'owner')

    def test_telegram_account_can_add_verified_email_and_keep_telegram(self):
        raw=self.a.telegram_start()
        created=self.a.telegram_confirm(raw,dict(id=5100,chat_id=5100,first_name='Telegram'))
        user_id=created['user_id']
        self.a.start_email_link(user_id,' connected@example.test ',PASSWORD)
        token=self.mail.token('email','connected@example.test')
        updated=self.a.complete_email_link(token)
        self.assertEqual(updated['email'],'connected@example.test');self.assertFalse(updated['telegram_only'])
        _,logged_in,_=self.a.login('connected@example.test',PASSWORD)
        self.assertEqual(logged_in['id'],user_id)
        self.assertEqual(self.a.telegram_user(5100)['id'],user_id)
        with self.assertRaises(ValueError):self.a.complete_email_link(token)

    def test_email_link_cannot_take_existing_address(self):
        raw=self.a.telegram_start()
        created=self.a.telegram_confirm(raw,dict(id=5200,chat_id=5200,first_name='Telegram'))
        with self.assertRaises(AccessError):
            self.a.start_email_link(created['user_id'],'owner@example.test',PASSWORD)
    def test_telegram_work_items_are_private_and_change_status(self):
        identifier=self.a.create_work_item('owner','Подготовить BPMN')
        self.assertEqual(self.a.work_items('owner')[0]['title'],'Подготовить BPMN')
        self.assertEqual(self.a.update_work_item('owner',identifier,'in_progress'),'in_progress')
        self.assertEqual(self.a.work_items('owner')[0]['status'],'in_progress')
        with self.assertRaises(AccessError):self.a.update_work_item('member',identifier,'done')

    def test_completed_tasks_remain_available_after_many_active_tasks(self):
        completed = self.a.create_work_item('owner', 'Закрытая задача')
        self.a.update_work_item('owner', completed, 'done')
        for number in range(32):
            self.a.create_work_item('owner', f'Активная {number}')
        page = self.a.work_items_page('owner', 'done')
        self.assertEqual(page['counts']['active'], 32)
        self.assertEqual(page['counts']['done'], 1)
        self.assertEqual([item['id'] for item in page['items']], [completed])
        self.assertTrue(self.a.work_items_page('owner', 'active')['has_more'])
        self.assertEqual(len(self.a.work_items_page('owner', 'active', 2)['items']), 8)

    def test_team_task_can_be_assigned_to_colleague_but_not_outsider(self):
        identifier=self.a.create_work_item('owner','Проверить процесс',assignee_id='member')
        delegated=self.a.work_items('owner',include_created=True)[0]
        self.assertEqual(delegated['id'],identifier);self.assertFalse(delegated['can_update'])
        self.assertEqual(delegated['assignee_name'],'member')
        self.assertEqual(self.a.work_items('member')[0]['id'],identifier)
        self.assertEqual(self.a.update_work_item('member',identifier,'in_progress'),'in_progress')
        self.assertEqual([person['id'] for person in self.a.work_assignees('owner')],['owner','admin','member'])
        with self.assertRaises(AccessError):
            self.a.create_work_item('owner','Чужая задача',assignee_id='outsider')

    def test_project_analytics_explains_process_and_task_health(self):
        project=copy.deepcopy(self.p)
        approved=new_block('Согласованный процесс')
        approved.update(status='approved',owner='owner',description='Описание',requirements='R1',
                        technical='GET /ok',uml={'participants':[{'id':'client','name':'Клиент'}],'messages':[]},
                        bpmn='<?xml version="1.0"?><definitions><process><startEvent/><task/><endEvent/><sequenceFlow/></process></definitions>')
        draft=new_block('Черновик')
        project['blocks']=[approved,draft]
        self.a.save_project('owner',project['id'],project,project['revision'])
        first=self.a.create_work_item('owner','Скоро срок',project_id=project['id'],due=time.time()+86400)
        second=self.a.create_work_item('owner','Готово',project_id=project['id'])
        self.a.update_work_item('owner',second,'done')
        data=self.a.project_analytics('owner',self.team,30);summary=data['summary']
        self.assertEqual(summary['readiness'],50)
        self.assertEqual(summary['block_statuses'],{'draft':1,'review':0,'approved':1})
        self.assertEqual(summary['task_statuses'],{'todo':1,'in_progress':0,'done':1})
        self.assertEqual(summary['due_soon'],1)
        self.assertGreater(summary['completeness'],0)
    def test_telegram_approval_requires_manager_and_updates_latest_project(self):
        project=copy.deepcopy(self.p);block=new_block('Проверка оплаты');block['status']='review';project['blocks']=[block]
        self.a.save_project('owner',project['id'],project,1)
        self.a.grant('owner',project['id'],'member','editor')
        self.assertEqual(self.a.telegram_approvals('member'),[])
        approval=self.a.telegram_approvals('owner')[0]
        result=self.a.decide_telegram_approval('owner',approval['ref'],'approve')
        self.assertEqual(result['status'],'approved')
        self.assertEqual(self.a.project('owner',project['id'])['blocks'][0]['status'],'approved')
        with self.assertRaises(AccessError):self.a.decide_telegram_approval('owner',approval['ref'],'approve')
    def test_telegram_approval_preview_is_bound_to_reviewed_content(self):
        project=copy.deepcopy(self.p);block=new_block('Оплата');block.update(status='review',description='Старая версия')
        project['blocks']=[block];self.a.save_project('owner',project['id'],project,1)
        reference=self.a.telegram_approvals('owner')[0]['ref']
        self.assertEqual(self.a.telegram_approval_detail('owner',reference)['description'],'Старая версия')
        _,keyboard=TelegramBot(self.a).approval_detail_view({'id':'owner'},reference)
        self.assertIn('project='+project['id'],keyboard['inline_keyboard'][0][0]['url'])
        self.assertIn('block='+block['id'],keyboard['inline_keyboard'][0][0]['url'])
        changed=self.a.project('owner',project['id']);changed['blocks'][0]['description']='Новая версия'
        self.a.save_project('owner',project['id'],changed,changed['revision'])
        with self.assertRaises(AccessError):self.a.decide_telegram_approval('owner',reference,'approve')
        current=self.a.telegram_approvals('owner')[0]['ref']
        self.assertNotEqual(reference,current)
        self.assertEqual(self.a.telegram_approval_detail('owner',current)['description'],'Новая версия')
    def test_telegram_team_invite_registers_user_with_fixed_role_and_is_single_use(self):
        invite=self.a.create_telegram_team_invite('owner',self.team,'admin')
        result=self.a.accept_telegram_team_invite(invite['token'],dict(id=3003,chat_id=3003,first_name='Новый'))
        self.assertTrue(result['created']);self.assertEqual(result['role'],'admin')
        with self.a.db() as db:
            role=db.execute('SELECT role FROM members WHERE space_id=? AND user_id=?',(self.team,result['user_id'])).fetchone()['role']
        self.assertEqual(role,'admin')
        with self.assertRaises(AccessError):self.a.accept_telegram_team_invite(invite['token'],dict(id=3003,chat_id=3003))
        with self.assertRaises(AccessError):self.a.create_telegram_team_invite('admin',self.team,'admin')
    def test_telegram_team_invite_adds_existing_account_without_escalating_member(self):
        link=self.a.telegram_start('member')
        self.a.telegram_confirm(link,dict(id=4004,chat_id=4004,first_name='Участник'))
        invite=self.a.create_telegram_team_invite('owner',self.team,'admin')
        result=self.a.accept_telegram_team_invite(invite['token'],dict(id=4004,chat_id=4004,first_name='Участник'))
        self.assertFalse(result['created']);self.assertEqual(result['role'],'member')
    def test_telegram_invite_assigns_team_specialty_only_on_first_join(self):
        invite=self.a.create_telegram_team_invite('owner',self.team,'member','qa')
        result=self.a.accept_telegram_team_invite(invite['token'],dict(id=5005,chat_id=5005,first_name='Тестер'))
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']==result['user_id'])
        self.assertEqual((member['specialty'],member['role']),('qa','member'))
        self.assertEqual(member['email'],'')
        next_invite=self.a.create_telegram_team_invite('owner',self.team,'admin','leader')
        self.a.accept_telegram_team_invite(next_invite['token'],dict(id=5005,chat_id=5005,first_name='Тестер'))
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']==result['user_id'])
        self.assertEqual((member['specialty'],member['role']),('qa','member'))
    def test_telegram_invite_assigns_manager_only_on_first_join(self):
        invite=self.a.create_telegram_team_invite('owner',self.team,'member','qa','admin')
        result=self.a.accept_telegram_team_invite(invite['token'],dict(id=5105,chat_id=5105,first_name='Тестер'))
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']==result['user_id'])
        self.assertEqual(member['manager_id'],'admin')
        next_invite=self.a.create_telegram_team_invite('owner',self.team,'member','leader','owner')
        self.a.accept_telegram_team_invite(next_invite['token'],dict(id=5105,chat_id=5105,first_name='Тестер'))
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']==result['user_id'])
        self.assertEqual(member['manager_id'],'admin')
        with self.assertRaises(AccessError):
            self.a.create_telegram_team_invite('owner',self.team,'member','qa','outsider')
    def test_password_reset_revokes_sessions_and_is_single_use(self):
        session,_,_=self.a.login('owner@example.test',PASSWORD)
        self.a.issue_mail('owner@example.test','reset');token=self.mail.token('reset')
        new='a changed test password 2027!';self.a.use_token(token,'reset',new)
        self.assertIsNone(self.a.session(session))
        with self.assertRaises(AccessError):self.a.login('owner@example.test',PASSWORD)
        self.assertTrue(self.a.login('owner@example.test',new)[0])
        with self.assertRaises(ValueError):self.a.use_token(token,'reset',new)
    def test_expired_reset_and_unknown_email(self):
        self.a.issue_mail('missing@example.test','reset');self.assertEqual(self.mail.sent,[])
        self.a.issue_mail('owner@example.test','reset');token=self.mail.token('reset')
        with self.a.db() as db:db.execute('UPDATE tokens SET expires=0')
        with self.assertRaises(ValueError):self.a.use_token(token,'reset',PASSWORD)
    def test_profile_does_not_change_permissions(self):
        self.a.update_profile('member',dict(name='Руководитель',specialty='leader',color='blue'))
        with self.assertRaises(AccessError):self.a.project('member',self.p['id'])
    def test_team_specialty_is_separate_from_access_role(self):
        self.a.update_member_org('owner',self.team,'member',
                                 dict(specialty='qa',seniority='senior',department='Тестирование',manager_id='owner'))
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']=='member')
        self.assertEqual((member['specialty'],member['role'],member['manager_id']),('qa','member','owner'))
        team_space=next(item for item in self.a.spaces('member') if item['id']==self.team)
        self.assertEqual((team_space['team_specialty'],team_space['role']),('qa','member'))
        with self.a.db() as db:
            self.assertNotEqual(db.execute('SELECT specialty FROM users WHERE id=?',('member',)).fetchone()['specialty'],'qa')
        with self.assertRaises(ValueError):
            self.a.update_member_org('owner',self.team,'member',dict(specialty='unknown',seniority='senior'))
    def test_agent_usage_tokens_are_attributed_to_user(self):
        agent=Agent(self.store,Path(self.tmp.name)/'.env')
        agent.record_usage('test-model',{'usage':{'input_tokens':120,'output_tokens':30}},'member')
        agent.record_usage('test-model',{'usage':{'input_tokens':80,'output_tokens':20}},'owner')
        quota=self.a.agent_quota('member')
        self.assertEqual((quota['input_tokens_month'],quota['output_tokens_month']),(120,30))
        admin_user=next(item for item in self.a.admin_dashboard()['users'] if item['id']=='member')
        self.assertEqual((admin_user['agent_input_month'],admin_user['agent_output_month']),(120,30))
    def test_admin_dashboard_shows_telegram_delivery_backlog(self):
        with self.a.db() as db:
            db.execute('INSERT INTO telegram_accounts (telegram_id,user_id,chat_id,linked) VALUES (?,?,?,?)',
                       (123,'member',123,time.time()))
            self.a._queue_telegram(db,'queued','member','Waiting')
            self.a._queue_telegram(db,'failed','member','Failed')
            db.execute("UPDATE telegram_notification_outbox SET attempts=5 WHERE event_key='failed'")
        operations=self.a.admin_dashboard()['operations']
        self.assertEqual((operations['telegram_pending'],operations['telegram_failed']),(1,1))
        self.assertGreaterEqual(operations['telegram_oldest_pending_seconds'],0)
    def test_private_spaces_are_isolated(self):
        p=self.a.create_project('owner','personal-owner','Личный')
        for who in ('admin','member','outsider'):
            with self.assertRaises(AccessError):self.a.project(who,p['id'])
        with self.assertRaises(AccessError):self.a.projects('outsider','personal-owner')
    def test_team_members_require_explicit_project_access(self):
        self.assertEqual(self.a.projects('member',self.team),[])
        with self.assertRaises(AccessError):self.a.project('member',self.p['id'])
        self.assertEqual(self.a.project('admin',self.p['id'])['access'],'manager')
    def test_viewer_and_commenter_cannot_save_or_manage_acl(self):
        for role in ('viewer','commenter'):
            self.a.grant('owner',self.p['id'],'member',role)
            self.assertEqual(self.a.project('member',self.p['id'])['access'],role)
            with self.assertRaises(AccessError):self.a.save_project('member',self.p['id'],copy.deepcopy(self.p),1)
            with self.assertRaises(AccessError):self.a.grant('member',self.p['id'],'member','manager')
    def test_editor_saves_but_cannot_grant(self):
        self.a.grant('owner',self.p['id'],'member','editor')
        p=copy.deepcopy(self.p);p['goal']='Новая цель';p['access']='manager';p['space_id']='personal-member'
        saved=self.a.save_project('member',p['id'],p,1)
        self.assertEqual(saved['access'],'editor');self.assertEqual(saved['space_id'],self.team)
        with self.assertRaises(AccessError):self.a.access_list('member',p['id'])
        with self.assertRaises(Conflict):self.a.save_project('member',p['id'],p,1)
    def test_grant_requires_membership_in_same_space(self):
        with self.assertRaises(AccessError):self.a.grant('owner',self.p['id'],'outsider','viewer')
    def test_revoked_access_is_immediate(self):
        self.a.grant('owner',self.p['id'],'member','editor')
        self.a.grant('owner',self.p['id'],'member','none')
        with self.assertRaises(AccessError):self.a.save_project('member',self.p['id'],copy.deepcopy(self.p),1)
    def test_remove_member_also_removes_old_project_grants(self):
        self.a.grant('owner',self.p['id'],'member','editor')
        self.a.change_member('admin',self.team,'member','remove')
        self.a.invite('owner',self.team,'member@example.test','member')
        self.a.accept_invite('member',self.mail.token('invite'))
        with self.assertRaises(AccessError):self.a.project('member',self.p['id'])
    def test_removing_manager_preserves_reporting_chain(self):
        self.a.update_member_org('owner',self.team,'admin',
                                 dict(seniority='lead',manager_id='owner'))
        self.a.update_member_org('owner',self.team,'member',
                                 dict(seniority='middle',manager_id='admin'))
        self.a.change_member('owner',self.team,'admin','remove')
        member=next(item for item in self.a.team('owner',self.team)['members'] if item['id']=='member')
        self.assertEqual(member['manager_id'],'owner')
    def test_admin_cannot_promote_or_remove_admin_or_owner(self):
        for target,role in [('member','admin'),('owner','remove'),('owner','member'),('admin','remove')]:
            with self.assertRaises(AccessError):self.a.change_member('admin',self.team,target,role)
        with self.assertRaises(AccessError):self.a.invite('admin',self.team,'new@example.test','admin')
    def test_invite_requires_matching_verified_identity(self):
        self.a.invite('owner',self.team,'outsider@example.test','member');token=self.mail.token('invite')
        with self.assertRaises(AccessError):self.a.accept_invite('member',token)
        self.assertEqual(self.a.accept_invite('outsider',token),self.team)
        with self.assertRaises(AccessError):self.a.accept_invite('outsider',token)
    def test_revoked_and_expired_invites_fail(self):
        self.a.invite('owner',self.team,'outsider@example.test','member');token=self.mail.token('invite')
        invitation=self.a.team('owner',self.team)['invitations'][0]
        self.a.revoke_invite('owner',self.team,invitation['id'])
        with self.assertRaises(AccessError):self.a.accept_invite('outsider',token)
        self.a.invite('owner',self.team,'outsider@example.test','member');token=self.mail.token('invite')
        with self.a.db() as db:db.execute('UPDATE invitations SET expires=0')
        with self.assertRaises(AccessError):self.a.accept_invite('outsider',token)
    def test_reissued_invite_invalidates_old_link(self):
        self.a.invite('owner',self.team,'outsider@example.test','member');old=self.mail.token('invite')
        self.a.invite('owner',self.team,'outsider@example.test','member');new=self.mail.token('invite')
        with self.assertRaises(AccessError):self.a.accept_invite('outsider',old)
        self.a.accept_invite('outsider',new)
    def test_transfer_owner_preserves_one_owner(self):
        with self.assertRaises(AccessError):self.a.transfer('admin',self.team,'member',PASSWORD)
        self.a.transfer('owner',self.team,'member',PASSWORD)
        team=self.a.team('member',self.team)
        self.assertEqual(team['owner_id'],'member')
        self.assertEqual([m['id'] for m in team['members'] if m['role']=='owner'],['member'])
        self.assertEqual(self.a.team('owner',self.team)['role'],'admin')
    def test_legacy_requires_local_key_and_claim_is_single_use(self):
        legacy=next(p['id'] for p in self.store.list() if p['id']!=self.p['id'])
        for user in ('owner','admin'):
            with self.assertRaises(AccessError):self.a.project(user,legacy)
        with self.assertRaises(AccessError):self.a.claim_legacy('owner','bad-key')
        key=self.a.claim_path.read_text();count=self.a.claim_legacy('owner',key)
        self.assertEqual(count,1);self.assertEqual(self.a.project('owner',legacy)['space_id'],'personal-owner')
        with self.assertRaises(AccessError):self.a.claim_legacy('admin',key)
        with self.assertRaises(AccessError):self.a.project('admin',legacy)
    def test_import_cannot_copy_access_grants(self):
        p=self.a.create_project('member','personal-member','Imported',copy.deepcopy(self.p))
        self.assertNotEqual(p['id'],self.p['id'])
        with self.assertRaises(AccessError):self.a.project('owner',p['id'])
    def test_rate_limit_persists_between_instances(self):
        self.a.limit('login','x',1)
        another=Accounts(self.store,self.mail)
        with self.assertRaises(AccessError):another.limit('login','x',1)
    def test_agent_daily_limit_allows_twenty_requests(self):
        for _ in range(20):self.a.limit_agent('owner')
        with self.assertRaises(AccessError) as blocked:self.a.limit_agent('owner')
        self.assertEqual(blocked.exception.status,429)
        self.assertIn('20 запросов',str(blocked.exception))
        quota=self.a.agent_quota('owner')
        tomorrow=(datetime.now(timezone.utc).date()+timedelta(days=1)).isoformat()
        self.assertEqual(datetime.fromtimestamp(quota['resets_at'],timezone.utc).isoformat(),tomorrow+'T00:00:00+00:00')
    def test_admin_can_change_personal_agent_limit_and_refund_region_failure(self):
        self.a.admin_user_action('owner','member','set_agent_limit',50)
        self.assertEqual(self.a.agent_quota('member')['daily_limit'],50)
        for _ in range(21):self.a.limit_agent('member')
        self.assertEqual(self.a.agent_quota('member')['used_today'],21)
        self.a.refund_agent('member')
        self.assertEqual(self.a.agent_quota('member')['used_today'],20)
        with self.assertRaises(ValueError):self.a.admin_user_action('owner','member','set_agent_limit',201)
        self.a.admin_user_action('owner','member','set_agent_limit',0)
        with self.assertRaises(AccessError):self.a.limit_agent('member')
    def test_monthly_token_quota_and_admin_grant(self):
        self.assertEqual(self.a.agent_quota('member')['monthly_token_limit'],1_000_000)
        self.a.admin_user_action('owner','member','set_agent_tokens',monthly_limit=100)
        today=datetime.now(timezone.utc).date().isoformat()
        with self.a.db() as db:
            db.execute('INSERT INTO ai_usage (day,model,input_tokens,output_tokens,cost,created,user_id) VALUES (?,?,?,?,?,?,?)',
                       (today,'test',60,50,0,time.time(),'member'))
        quota=self.a.agent_quota('member')
        self.assertEqual((quota['tokens_used_month'],quota['monthly_token_limit'],quota['token_percent_month']),(110,100,100))
        with self.assertRaises(AccessError) as blocked:self.a.limit_agent('member')
        self.assertEqual(blocked.exception.code,'agent_monthly_limit')
        member=next(item for item in self.a.admin_dashboard()['users'] if item['id']=='member')
        self.assertEqual(member['agent_monthly_limit'],100)
    def test_admin_plan_entitlement_expires_and_custom_limits_survive(self):
        self.assertEqual(self.a.agent_quota('member')['plan'],'free')
        self.a.admin_user_action('owner','member','set_plan',plan='pro',duration_days=30)
        quota=self.a.agent_quota('member')
        self.assertEqual((quota['plan'],quota['daily_limit'],quota['monthly_token_limit']),('pro',100,5_000_000))
        self.assertEqual(self.a.admin_dashboard()['plans']['counts']['pro'],1)
        self.assertEqual(next(item for item in self.a.admin_dashboard()['users'] if item['id']=='member')['plan_source'],'admin')
        self.a.admin_user_action('owner','member','set_agent_limit',50)
        self.assertEqual(self.a.agent_quota('member')['daily_limit'],50)
        with self.a.db() as db:
            db.execute('UPDATE user_plans SET expires=? WHERE user_id=?',(time.time()-1,'member'))
        quota=self.a.agent_quota('member')
        self.assertEqual((quota['plan'],quota['daily_limit'],quota['monthly_token_limit']),('free',50,1_000_000))
        with self.assertRaises(ValueError):
            self.a.admin_user_action('owner','member','set_plan',plan='team',duration_days=366)
    def test_demo_purchase_unlocks_team_creation_and_can_renew(self):
        with self.assertRaises(AccessError) as blocked:
            self.a.create_space('outsider','Новая команда')
        self.assertEqual(blocked.exception.code,'team_plan_required')
        purchase=self.a.demo_purchase_plan('outsider','team')
        self.assertEqual(self.a.agent_quota('outsider')['plan'],'team')
        self.assertEqual(self.a.admin_dashboard()['plans']['demo_active'],1)
        self.assertEqual(next(item for item in self.a.admin_dashboard()['users'] if item['id']=='outsider')['plan_source'],'demo')
        self.assertTrue(self.a.create_space('outsider','Новая команда'))
        switched=self.a.demo_purchase_plan('outsider','pro')
        self.assertEqual(switched['expires'],purchase['expires'])
        with self.a.db() as db:
            db.execute('UPDATE plan_demo_claims SET expires=? WHERE user_id=?',(time.time()-1,'outsider'))
            db.execute('UPDATE user_plans SET expires=? WHERE user_id=?',(time.time()-1,'outsider'))
        renewed=self.a.demo_purchase_plan('outsider','team')
        self.assertGreater(renewed['expires'],time.time()+29*86400)
        self.assertEqual(self.a.agent_quota('outsider')['plan'],'team')
    def test_bpmn_history_and_restore(self):
        p=copy.deepcopy(self.p);block=new_block('Оплата');block['bpmn']=(Path(__file__).parents[1]/'examples'/'simple.bpmn').read_text()
        p['blocks']=[block];saved=self.a.save_project('owner',p['id'],p,1)
        changed=copy.deepcopy(saved);changed['blocks'][0]['bpmn']=changed['blocks'][0]['bpmn'].replace('Проверить заявку','Проверить оплату')
        saved=self.a.save_project('owner',p['id'],changed,2)
        history=self.a.bpmn_history('owner',p['id'],block['id'])
        self.assertEqual(len(history['versions']),1)
        version=history['versions'][0]
        detail=self.a.bpmn_version('owner',p['id'],block['id'],version['id'])
        self.assertTrue(detail['diff']['renamed'])
        restored=self.a.restore_bpmn('owner',p['id'],block['id'],version['id'],saved['revision'])
        self.assertIn('Проверить заявку',restored['blocks'][0]['bpmn'])
