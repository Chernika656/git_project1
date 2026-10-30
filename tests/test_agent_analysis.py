import json
from unittest.mock import patch
import unittest
import test_agent
from ai_agent import AgentError
from agent_analysis import project_context, validate_analysis
from workspace import new_project

class AnalysisTests(unittest.TestCase):
    setUp = test_agent.AgentTests.setUp
    def test_context(self):
        project = new_project(demo=True)
        project['glossary'] = [{'name': 'Заказ', 'definition': 'Заявка покупателя'}]
        content, refs = project_context(project, 'project')
        data = json.loads(content)
        self.assertEqual(len(data['blocks']), 4)
        self.assertEqual(data['links'], project['links'])
        self.assertEqual(data['glossary'], project['glossary'])
        self.assertTrue(data['blocks'][1]['checker']['errors'])
        self.assertTrue(data['blocks'][1]['technical'])
        self.assertTrue(refs[project['blocks'][0]['id']])
        self.assertNotIn('BPMNShape', content)
        single, _ = project_context(project, 'bpmn', project['blocks'][0]['id'])
        self.assertEqual(len(json.loads(single)['blocks']), 1)

    def test_contract(self):
        project = new_project(demo=True)
        self.config.write_text('OPENAI_API_KEY=secret-test\n')
        report = {'summary': 'Проверьте оплату', 'findings': [], 'questions': ['Что при отказе?'], 'next_steps': []}
        response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(report)}]}]}
        with patch.object(self.agent, 'request', return_value=response) as request:
            result = self.agent.analyze(project, 'project', None, '')
            self.assertEqual(result['blocks_analyzed'], 4)
            self.assertEqual(result['revision'], project['revision'])
            self.assertFalse(request.call_args.args[1]['store'])
        report['findings'] = [dict(severity='error',block_id='missing',element_id='',title='x',explanation='x',recommendation='x')]
        with self.assertRaises(ValueError): validate_analysis(report, {})
        report['findings'][0]['block_id'] = 'b'
        report['findings'][0]['element_id'] = 'missing'
        with self.assertRaises(ValueError): validate_analysis(report, {'b': {'real'}})
        with patch.object(self.agent, 'request', return_value={'status':'incomplete'}):
            with self.assertRaises(AgentError): self.agent.analyze(project, 'project', None, '')

    def test_limits(self):
        project = new_project(demo=True)
        with patch.object(self.agent, 'request') as request:
            for scope, block in [('bad', None), ('bpmn', 'missing')]:
                with self.assertRaises(ValueError): self.agent.analyze(project, scope, block, '')
            project['blocks'][0]['description'] = 'x' * 180001
            with self.assertRaises(ValueError): self.agent.analyze(project, 'project', None, '')
            request.assert_not_called()
        self.assertEqual(self.agent.status()['used_today'], 0)

    def test_invalid_xml_is_reported_not_parsed_again(self):
        project = new_project(demo=True)
        project['blocks'][0]['bpmn'] = '<!DOCTYPE x><bad>'
        content, _ = project_context(project, 'project')
        self.assertIn('INVALID_XML', content)
