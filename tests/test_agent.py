"""Проверки интеграции без ключей и платных обращений к OpenAI."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock

from facet.ai.agent import Agent, AgentError, validate_prototype
from facet.paths import ENV_FILE
from facet.projects.workspace import Store, new_project, validate_project


PROTOTYPE = {'title': 'Заявка', 'css': 'h1{color:purple}', 'pages': [
    {'id': 'form', 'title': 'Заявка', 'html': '<form data-go="done"><label>Имя<input name="name" required></label><button>Отправить</button></form>'},
    {'id': 'done', 'title': 'Готово', 'html': '<h1>Готово</h1><span data-value="name"></span>'}]}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.path = Path(self.tmp.name)
        self.store = Store(self.path/'test.db')
        self.config = self.path/'.env'
        self.agent = Agent(self.store, self.config)

    def test_default_config_is_loaded_from_repository_root(self):
        # Moving the package must not silently disconnect an existing root .env.
        with patch('facet.ai.agent.ENV_FILE', self.config):
            agent = Agent(self.store)
            self.config.write_text('OPENAI_API_KEY=secret-test\nOPENAI_MODEL=test-model\n')
            self.assertTrue(agent.status()['configured'])
            self.assertEqual(agent.status()['model'], 'test-model')
            self.assertNotIn('secret-test', json.dumps(agent.status()))
        self.assertEqual(ENV_FILE.parent, Path(__file__).resolve().parents[1])

    def test_no_key_does_not_make_request_or_consume_quota(self):
        with patch.object(self.agent, 'request') as request:
            with self.assertRaises(AgentError) as caught: self.agent.generate({}, 'Создай экран')
            request.assert_not_called()
        self.assertTrue(caught.exception.unbilled)
        self.assertFalse(caught.exception.global_reserved)
        self.assertEqual(self.agent.status()['used_today'], 0)
        self.assertFalse(self.agent.status()['configured'])

    def test_live_config_and_secret_not_returned(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\nOPENAI_MODEL=test-model\nFACET_AI_DAILY_LIMIT=1\n')
        status = self.agent.status()
        self.assertTrue(status['configured']); self.assertEqual(status['model'], 'test-model')
        self.assertNotIn('secret-test', json.dumps(status))
        self.agent.reserve(1)
        with self.assertRaises(AgentError): self.agent.reserve(1)
        self.assertEqual(Agent(self.store, self.config).status()['used_today'], 1)
        self.agent.refund()
        self.assertEqual(self.agent.status()['used_today'], 0)

    def test_region_rejection_has_specific_message(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        connection=MagicMock()
        connection.getresponse.return_value.status=403
        connection.getresponse.return_value.read.return_value=json.dumps({'error':{'code':'unsupported_country_region_territory'}}).encode()
        with patch('facet.ai.agent.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaisesRegex(AgentError,'IP-адреса этого сервера') as caught:
                self.agent.request('/v1/models')
        self.assertTrue(caught.exception.unbilled)
        self.assertTrue(caught.exception.global_reserved)

    def test_rejected_api_request_does_not_consume_quota(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        connection=MagicMock()
        connection.getresponse.return_value.status=429
        connection.getresponse.return_value.read.return_value=b'{}'
        with patch('facet.ai.agent.http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(AgentError) as caught:
                self.agent.request('/v1/responses',{'model':'test'})
        self.assertTrue(caught.exception.unbilled)
        self.assertTrue(caught.exception.global_reserved)
        with self.assertRaises(AgentError) as full:
            self.agent.reserve(0)
        self.assertTrue(full.exception.unbilled)
        self.assertFalse(full.exception.global_reserved)

    def test_global_limit_override(self):
        self.assertEqual(self.agent.status()['daily_limit'], 500)
        self.agent.set_global_limit(50)
        self.assertEqual(Agent(self.store, self.config).status()['daily_limit'], 50)
        with self.assertRaises(ValueError):
            self.agent.set_global_limit(501)
        self.assertEqual(self.agent.status()['daily_limit'], 50)

    def test_generation_contract_and_validation(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(PROTOTYPE)}]}]}
        with patch.object(self.agent, 'request', return_value=response) as request:
            result = self.agent.generate(new_project(demo=True)['blocks'][0], 'Сделай форму')
            payload = request.call_args.args[1]
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
            self.assertEqual(result['prototype']['title'], 'Заявка')
        self.assertEqual(self.agent.status()['used_today'], 1)

    def test_slide_suggestions_are_reviewable_and_not_applied(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        project=new_project(demo=True);before=copy.deepcopy(project)
        slides=[{'number':1,'title':'Оплата','lines':['Проверить заказ']}]
        match={'slide_number':1,'block_id':project['blocks'][0]['id'],'title':'Проверка заказа',
               'message':'Сверить заказ','bullets':['Проверить данные'],'reason':'Совпадает с шагом процесса'}
        response={'status':'completed','usage':{'input_tokens':100,'output_tokens':40},
                  'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'matches':[match]})}]}]}
        with patch.object(self.agent,'request',return_value=response) as request:
            result=self.agent.suggest_slides(project,slides,'user-1')
        self.assertEqual(result['matches'],[match]);self.assertEqual(project,before)
        self.assertEqual(request.call_args.args[1]['text']['format']['name'],'facet_slide_matches')
        with self.assertRaises(AgentError):
            self.agent.suggest_slides(project,[{'number':1,'title':'x','lines':['y'*501]}],'user-1')

    def test_refusal_and_incomplete_are_not_saved(self):
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        for response in ({'status': 'incomplete'}, {'status': 'completed', 'output': []}):
            with patch.object(self.agent, 'request', return_value=response):
                with self.assertRaises(AgentError): self.agent.generate({}, 'Прототип')

    def test_html_is_inert_and_links_must_exist(self):
        data = copy.deepcopy(PROTOTYPE)
        data['pages'][0]['html'] += '<script>alert(1)</script><iframe src="https://evil.test"></iframe><input onfocus="alert(1)" formaction="https://evil.test" type="password">'
        cleaned = validate_prototype(data)['pages'][0]['html']
        for forbidden in ('script', 'iframe', 'onfocus', 'formaction', 'password', 'evil.test'):
            self.assertNotIn(forbidden, cleaned)
        data['pages'][0]['html'] = '<button data-go="missing">Next</button>'
        with self.assertRaises(ValueError): validate_prototype(data)

    def test_css_escape_and_external_loads_rejected(self):
        for css in ('</style><script>alert(1)</script>', '@import "https://evil.test";', 'a{background:url(x)}', r'a{background:u\72l(x)}'):
            data = copy.deepcopy(PROTOTYPE);data['css'] = css
            with self.assertRaises(ValueError): validate_prototype(data)

    def test_project_roundtrip_with_prototype(self):
        p = new_project(demo=True);p['blocks'][0]['html_prototype'] = copy.deepcopy(PROTOTYPE)
        validate_project(p)
        saved = self.store.create('HTML', p)
        self.assertEqual(self.store.get(saved['id'])['blocks'][0]['html_prototype']['title'], 'Заявка')


if __name__ == '__main__': unittest.main()
