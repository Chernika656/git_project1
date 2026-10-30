"""Проверяем сохранение, контракты HTTP и редактирование BPMN независимо от браузера."""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from xml.dom import minidom

from workspace import Store, Conflict, new_project, new_block, validate_project, BASE
from web_app import make_handler
from bpmn_web import edit, analyze
from accounts import Accounts
from test_accounts import TestMail, PASSWORD
from diagram import load_diagram


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'test.sqlite3')
    def tearDown(self):
        self.tmp.cleanup()
    def test_demo_has_connected_blocks_and_real_bpmn_findings(self):
        p = self.store.get(self.store.list()[0]['id'])
        self.assertEqual(len(p['blocks']), 4)
        validate_project(p)
        self.assertEqual(analyze(p['blocks'][1]['bpmn'])['report']['errors'], 2)
    def test_project_roundtrip_and_restart(self):
        p = self.store.create('Тест')
        b = new_block('Оплата');b['technical']='{"amount": 100}'
        p['blocks'].append(b)
        saved=self.store.save(p['id'],p,1)
        reopened=Store(self.store.path).get(p['id'])
        self.assertEqual(reopened,saved)
        self.assertEqual(reopened['revision'],2)
        self.assertEqual(reopened['blocks'][0]['technical'],b['technical'])
    def test_stale_revision_does_not_overwrite(self):
        p=self.store.create('Оригинал');stale=copy.deepcopy(p)
        p['name']='Свежие правки';self.store.save(p['id'],p,1)
        with self.assertRaises(Conflict):self.store.save(p['id'],stale,1)
        self.assertEqual(self.store.get(p['id'])['name'],'Свежие правки')
    def test_import_is_independent_project(self):
        p=self.store.get(self.store.list()[0]['id'])
        imported=self.store.create('',copy.deepcopy(p))
        self.assertNotEqual(imported['id'],p['id'])
        self.assertEqual(imported['blocks'],p['blocks'])
    def test_invalid_graph_is_rejected(self):
        p=new_project();p['links']=[dict(id='l',source='missing',target='missing')]
        with self.assertRaises(ValueError):validate_project(p)
    def test_glossary_can_link_to_bpmn_element(self):
        p=new_project();b=new_block();p['blocks']=[b]
        p['glossary']=[{'id':'term','name':'Заказ','definition':'Заявка покупателя',
                        'blocks':[b['id']],'elements':[{'block_id':b['id'],'element_id':'Task_1'}]}]
        validate_project(p)
        p['glossary'][0]['elements'].append({'block_id':b['id'],'element_id':'Task_1'})
        with self.assertRaises(ValueError):validate_project(p)
        del p['glossary'][0]['elements']
        validate_project(p)
    def test_uml_cannot_reference_removed_participant(self):
        p=new_project();b=new_block();p['blocks']=[b]
        b['uml']['messages']=[dict(id='m',**{'from':'x','to':'y'},text='hi',kind='call')]
        with self.assertRaises(ValueError):validate_project(p)
    def test_invalid_coordinates_rejected(self):
        p=new_project();b=new_block();p['blocks']=[b];b['x']=float('nan')
        with self.assertRaises(ValueError):validate_project(p)
    def test_slide_content_is_saved_and_bounded(self):
        p=self.store.create('Презентация');b=new_block('Оплата')
        b['slide']={'title':'Решение','message':'Утвердить новый процесс','layout':'decision','bullets':['Срок — неделя'],'notes':'Уточнить сроки у владельца'}
        p['blocks'].append(b)
        saved=self.store.save(p['id'],p,1)
        self.assertEqual(saved['blocks'][0]['slide'],b['slide'])
        b['slide']['layout']='section'
        validate_project(p)
        b['slide']['bullets']=['пункт']*7
        with self.assertRaises(ValueError):validate_project(p)
        b['slide']['bullets']=[];b['slide']['notes']='x'*5001
        with self.assertRaises(ValueError):validate_project(p)
    def test_slide_order_cannot_repeat_a_block(self):
        p=new_project();b=new_block();p['blocks']=[b]
        p['presentation_order']=[b['id'],b['id']]
        with self.assertRaises(ValueError):validate_project(p)
    def test_invalid_import_types_are_readable_errors(self):
        for p in ([], {}, {'id':1}):
            with self.assertRaises(ValueError):self.store.create('',p)


class BpmnWebTests(unittest.TestCase):
    def setUp(self):self.xml=(BASE/'examples'/'simple.bpmn').read_text()
    def test_pools_create_separate_processes_and_message_flow(self):
        xml=edit(self.xml,{'op':'add_pool','name':'Клиент'})
        namespace='http://www.omg.org/spec/BPMN/20100524/MODEL'
        doc=minidom.parseString(xml)
        processes=doc.getElementsByTagNameNS(namespace,'process')
        participants=doc.getElementsByTagNameNS(namespace,'participant')
        self.assertEqual(len(processes),2)
        self.assertEqual({p.getAttribute('processRef') for p in participants},
                         {p.getAttribute('id') for p in processes})
        source=processes[0].getElementsByTagNameNS(namespace,'task')[0].getAttribute('id')
        target=processes[1].getElementsByTagNameNS(namespace,'task')[0].getAttribute('id')
        xml=edit(xml,{'op':'connect','source':source,'target':target})
        xml=edit(xml,{'op':'add','kind':'userTask','name':'Уточнить','container_id':processes[1].getAttribute('id')})
        doc=minidom.parseString(xml)
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'messageFlow')),1)
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'sequenceFlow')),5)
        diagram=load_diagram(xml.encode())
        self.assertEqual(len([shape for shape in diagram.shapes if shape.kind=='participant']),2)
        self.assertEqual(len([edge for edge in diagram.edges if edge.kind=='messageFlow']),1)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'connect','source':source,'target':participants[1].getAttribute('id')})
        xml=edit(xml,{'op':'delete','id':participants[1].getAttribute('id')})
        doc=minidom.parseString(xml)
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'process')),1)
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'messageFlow')),0)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'delete','id':participants[0].getAttribute('id')})
    def test_lane_assignment_updates_semantics_and_diagram(self):
        xml=edit(self.xml,{'op':'add_lane','name':'Согласование'})
        namespace='http://www.omg.org/spec/BPMN/20100524/MODEL'
        doc=minidom.parseString(xml)
        process=doc.getElementsByTagNameNS(namespace,'process')[0]
        lane=doc.getElementsByTagNameNS(namespace,'lane')[0]
        lane_id=lane.getAttribute('id')
        task=next(shape for shape in load_diagram(xml.encode()).shapes if shape.kind=='task')
        children=[item.localName for item in process.childNodes if item.nodeType==item.ELEMENT_NODE]
        self.assertLess(children.index('laneSet'),children.index('startEvent'))
        xml=edit(xml,{'op':'assign_lane','id':task.element_id,'lane_id':lane_id,'name':'Проверить заявку'})
        doc=minidom.parseString(xml)
        lane=doc.getElementsByTagNameNS(namespace,'lane')[0]
        self.assertEqual(lane.getElementsByTagNameNS(namespace,'flowNodeRef')[0].firstChild.data,task.element_id)
        diagram=load_diagram(xml.encode())
        placed=next(shape for shape in diagram.shapes if shape.element_id==task.element_id)
        boundary=next(shape for shape in diagram.shapes if shape.element_id==lane_id)
        self.assertEqual(placed.lane_id,lane_id)
        self.assertGreaterEqual(placed.y,boundary.y)
        self.assertLessEqual(placed.y+placed.height,boundary.y+boundary.height)
        with self.assertRaises(ValueError): edit(xml,{'op':'delete','id':lane_id})
        xml=edit(xml,{'op':'assign_lane','id':task.element_id,'lane_id':'','name':'Проверить заявку'})
        self.assertFalse(next(shape for shape in load_diagram(xml.encode()).shapes if shape.element_id==task.element_id).lane_id)
        xml=edit(xml,{'op':'delete','id':lane_id})
        self.assertEqual(len(minidom.parseString(xml).getElementsByTagNameNS(namespace,'laneSet')),0)
        self.assertEqual(analyze(xml)['report']['errors'],0)
    def test_lanes_belong_to_selected_pools_without_overlap(self):
        namespace='http://www.omg.org/spec/BPMN/20100524/MODEL'
        xml=edit(self.xml,{'op':'add_pool','name':'Клиент'})
        doc=minidom.parseString(xml)
        processes=doc.getElementsByTagNameNS(namespace,'process')
        first_id,second_id=(process.getAttribute('id') for process in processes)
        first_task=processes[0].getElementsByTagNameNS(namespace,'task')[0].getAttribute('id')
        second_task=processes[1].getElementsByTagNameNS(namespace,'task')[0].getAttribute('id')
        xml=edit(xml,{'op':'add_lane','process_id':first_id,'name':'Продавец'})
        xml=edit(xml,{'op':'add_lane','process_id':second_id,'name':'Поддержка'})
        doc=minidom.parseString(xml)
        first_lane=doc.getElementsByTagNameNS(namespace,'process')[0].getElementsByTagNameNS(namespace,'lane')[0].getAttribute('id')
        second_lane=doc.getElementsByTagNameNS(namespace,'process')[1].getElementsByTagNameNS(namespace,'lane')[0].getAttribute('id')
        with self.assertRaises(ValueError):
            edit(xml,{'op':'assign_lane','id':first_task,'lane_id':second_lane,'name':'Проверить'})
        xml=edit(xml,{'op':'assign_lane','id':first_task,'lane_id':first_lane,'name':'Проверить'})
        xml=edit(xml,{'op':'assign_lane','id':second_task,'lane_id':second_lane,'name':'Ответить'})
        diagram=load_diagram(xml.encode())
        shapes={shape.element_id:shape for shape in diagram.shapes}
        self.assertEqual(shapes[first_task].lane_id,first_lane)
        self.assertEqual(shapes[second_task].lane_id,second_lane)
        for task_id,lane_id in ((first_task,first_lane),(second_task,second_lane)):
            task,lane=shapes[task_id],shapes[lane_id]
            self.assertLessEqual(lane.y,task.y)
            self.assertLessEqual(task.y+task.height,lane.y+lane.height)
        pools=sorted((shape for shape in diagram.shapes if shape.kind=='participant'),key=lambda shape:shape.y)
        self.assertGreaterEqual(pools[1].y,pools[0].y+pools[0].height)
        self.assertEqual(analyze(xml)['report']['errors'],0)
    def test_data_and_annotation_are_artifacts_not_sequence_steps(self):
        xml=edit(self.xml,{'op':'add','kind':'dataObject','name':'Заявка'})
        xml=edit(xml,{'op':'add','kind':'textAnnotation','name':'Проверить источник данных'})
        diagram=load_diagram(xml.encode())
        data=next(shape for shape in diagram.shapes if shape.kind=='dataObject')
        note=next(shape for shape in diagram.shapes if shape.kind=='textAnnotation')
        task=next(shape for shape in diagram.shapes if shape.kind=='task')
        self.assertEqual(note.name,'Проверить источник данных')
        xml=edit(xml,{'op':'connect','source':task.element_id,'target':data.element_id})
        xml=edit(xml,{'op':'connect','source':task.element_id,'target':note.element_id})
        doc=minidom.parseString(xml)
        namespace='http://www.omg.org/spec/BPMN/20100524/MODEL'
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'association')),2)
        self.assertEqual(len(doc.getElementsByTagNameNS(namespace,'sequenceFlow')),2)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        xml=edit(xml,{'op':'add','kind':'userTask','name':'Следующая проверка'})
        doc=minidom.parseString(xml)
        process=doc.getElementsByTagNameNS(namespace,'process')[0]
        children=[element.localName for element in process.childNodes if element.nodeType==element.ELEMENT_NODE]
        self.assertLess(children.index('userTask'),children.index('textAnnotation'))
        self.assertLess(children.index('dataObject'),children.index('textAnnotation'))
        xml=edit(xml,{'op':'rename','id':note.element_id,'name':'Проверено'})
        self.assertEqual(next(shape for shape in load_diagram(xml.encode()).shapes if shape.element_id==note.element_id).name,'Проверено')
        xml=edit(xml,{'op':'delete','id':note.element_id})
        self.assertEqual(len(minidom.parseString(xml).getElementsByTagNameNS(namespace,'association')),1)
    def test_ad_hoc_subprocess_can_be_edited_and_has_valid_structure(self):
        xml=edit('',{'op':'add','kind':'adHocSubProcess','name':'Разбор случая',
                     'ad_hoc_ordering':'Sequential','ad_hoc_completion':'Вывод согласован'})
        doc=minidom.parseString(xml)
        namespace='http://www.omg.org/spec/BPMN/20100524/MODEL'
        subprocess=doc.getElementsByTagNameNS(namespace,'adHocSubProcess')[0]
        scope_id=subprocess.getAttribute('id')
        self.assertEqual(subprocess.getAttribute('ordering'),'Sequential')
        self.assertEqual(subprocess.getElementsByTagNameNS(namespace,'completionCondition')[0].firstChild.data,'Вывод согласован')
        self.assertEqual(len(subprocess.getElementsByTagNameNS(namespace,'task')),1)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        xml=edit(xml,{'op':'add','kind':'userTask','name':'Проверить результат','container_id':scope_id})
        doc=minidom.parseString(xml)
        subprocess=doc.getElementsByTagNameNS(namespace,'adHocSubProcess')[0]
        self.assertEqual([node.localName for node in subprocess.childNodes if node.nodeType==node.ELEMENT_NODE][-1],'completionCondition')
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'startEvent','container_id':scope_id})
        xml=edit(xml,{'op':'configure_ad_hoc','id':scope_id,'name':'Новый разбор',
                      'ad_hoc_ordering':'Parallel','ad_hoc_completion':'Готово',
                      'ad_hoc_cancel_remaining':False})
        doc=minidom.parseString(xml)
        subprocess=doc.getElementsByTagNameNS(namespace,'adHocSubProcess')[0]
        self.assertEqual(subprocess.getAttribute('ordering'),'Parallel')
        self.assertEqual(subprocess.getAttribute('cancelRemainingInstances'),'false')
        self.assertEqual(subprocess.getElementsByTagNameNS(namespace,'completionCondition')[0].firstChild.data,'Готово')
        self.assertEqual(analyze(xml)['report']['errors'],0)
        deleted=edit(xml,{'op':'delete','id':scope_id})
        self.assertEqual(analyze(deleted)['report']['errors'],0)
    def test_event_subprocess_has_trigger_and_stays_out_of_main_flow(self):
        xml=edit('',{'op':'add','kind':'subProcess','name':'Пришло сообщение',
                     'triggered_by_event':True,'trigger_event':'message','interrupting':False})
        doc=minidom.parseString(xml)
        subprocess=doc.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/MODEL','subProcess')[0]
        start=subprocess.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/MODEL','startEvent')[0]
        self.assertEqual(subprocess.getAttribute('triggeredByEvent'),'true')
        self.assertEqual(start.getAttribute('isInterrupting'),'false')
        self.assertEqual(len(start.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/MODEL','messageEventDefinition')),1)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'startEvent','container_id':subprocess.getAttribute('id')})
        xml=edit(xml,{'op':'add','kind':'task','name':'Обычная работа'})
        task=next(shape.element_id for shape in load_diagram(xml.encode()).shapes if shape.kind=='task')
        with self.assertRaises(ValueError):
            edit(xml,{'op':'connect','source':task,'target':subprocess.getAttribute('id')})
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'subProcess','triggered_by_event':True,
                     'trigger_event':'error','interrupting':False})
        for trigger,extra in [('signal',{}),('timer',{'duration':'PT5M'}),
                              ('conditional',{'condition':'Счёт оплачен'}),
                              ('error',{}),('escalation',{})]:
            with self.subTest(trigger=trigger):
                candidate=edit('',{'op':'add','kind':'subProcess','triggered_by_event':True,
                                   'trigger_event':trigger,**extra})
                self.assertEqual(analyze(candidate)['report']['errors'],0)
    def test_extended_editor_elements_remain_valid_bpmn(self):
        for kind in ('manualTask','scriptTask','businessRuleTask','sendTask','receiveTask',
                     'inclusiveGateway','eventBasedGateway','complexGateway',
                     'intermediateCatchEvent','intermediateThrowEvent'):
            with self.subTest(kind=kind):
                xml=edit('',{'op':'add','kind':kind,'name':'Новый элемент'})
                self.assertIn(kind,xml)
                self.assertEqual(analyze(xml)['report']['errors'],0)
    def test_call_activity_can_reference_another_local_process(self):
        xml = edit('', {'op':'add','kind':'callActivity','name':'Проверка партнёра'})
        self.assertIn('callActivity', xml)
        with self.assertRaises(ValueError):
            edit(xml, {'op':'add','kind':'callActivity','called_element':'missing','name':'Ошибка'})
        xml = xml.replace('</definitions>', '<process id="Process_2" name="Партнёр" isExecutable="false"/></definitions>')
        linked = edit(xml, {'op':'add','kind':'callActivity','called_element':'Process_2','name':'Партнёр'})
        self.assertIn('calledElement="Process_2"', linked)
    def test_event_markers_are_kept_in_bpmn_and_rejected_on_tasks(self):
        xml=edit('',{'op':'add','kind':'intermediateCatchEvent','event':'message','name':'Ответ получен'})
        self.assertIn('messageEventDefinition',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'task','event':'message','name':'Нельзя'})
    def test_terminate_marker_is_only_available_on_end_event(self):
        xml=edit('',{'op':'add','kind':'endEvent','event':'terminate','name':'Остановить процесс'})
        self.assertIn('terminateEventDefinition',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'intermediateThrowEvent','event':'terminate'})
    def test_timer_event_has_duration_and_valid_position(self):
        xml=edit('',{'op':'add','kind':'intermediateCatchEvent','event':'timer','duration':'PT15M','name':'Ожидание'})
        self.assertIn('<timeDuration>PT15M</timeDuration>',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        for kind,duration in (('intermediateThrowEvent','PT15M'),('intermediateCatchEvent','PT'),('boundaryEvent','P0D')):
            with self.subTest(kind=kind,duration=duration),self.assertRaises(ValueError):
                edit('',{'op':'add','kind':kind,'event':'timer','duration':duration})
    def test_conditional_event_requires_expression_and_catching_position(self):
        xml=edit('',{'op':'add','kind':'intermediateCatchEvent','event':'conditional',
                     'condition':'Сумма заказа > 100000','name':'Крупный заказ'})
        self.assertIn('<condition>Сумма заказа &gt; 100000</condition>',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        for kind,condition in (('intermediateThrowEvent','Готово'),('endEvent','Готово'),('startEvent','')):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                edit('',{'op':'add','kind':kind,'event':'conditional','condition':condition})
    def test_link_events_share_name_and_have_one_receiver(self):
        xml=edit('',{'op':'add','kind':'intermediateCatchEvent','event':'link','link_name':'Повторить'})
        xml=edit(xml,{'op':'add','kind':'intermediateThrowEvent','event':'link','link_name':'Повторить'})
        self.assertEqual(xml.count('name="Повторить"'),2)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        for kind,name in (('endEvent','Повторить'),('intermediateCatchEvent',''),
                          ('intermediateCatchEvent','Повторить')):
            with self.subTest(kind=kind,name=name),self.assertRaises(ValueError):
                edit(xml,{'op':'add','kind':kind,'event':'link','link_name':name})
    def test_error_and_escalation_events_use_valid_positions(self):
        xml=edit('',{'op':'add','kind':'task','name':'Оплатить'})
        task=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'add','kind':'boundaryEvent','event':'error','attached_to':task,'name':'Ошибка'})
        self.assertIn('errorEventDefinition',xml)
        xml=edit(xml,{'op':'add','kind':'intermediateThrowEvent','event':'escalation','name':'Передать выше'})
        self.assertIn('escalationEventDefinition',xml)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'boundaryEvent','event':'error','attached_to':task,'interrupting':False})
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'startEvent','event':'error'})
    def test_editable_subprocess_has_runnable_inner_flow_and_can_be_removed(self):
        xml=edit('',{'op':'add','kind':'subProcess','name':'Проверить оплату'})
        report=analyze(xml)['report']
        self.assertEqual(report['errors'],0)
        self.assertEqual(report['flows'],1)
        identifier=load_diagram(xml.encode()).shapes[0].element_id
        self.assertTrue(load_diagram(xml.encode()).shapes[0].expanded)
        xml=edit(xml,{'op':'add','kind':'userTask','name':'Сверить платёж','container_id':identifier})
        shapes=load_diagram(xml.encode()).shapes
        task=next(shape for shape in shapes if shape.kind=='userTask')
        self.assertLess(shapes[0].x,task.x)
        self.assertLess(task.x+task.width,shapes[0].x+shapes[0].width)
        self.assertEqual(analyze(xml)['report']['flows'],2)
        xml=edit(xml,{'op':'add','kind':'serviceTask','name':'Записать результат','container_id':identifier})
        diagram=load_diagram(xml.encode())
        second=next(shape for shape in diagram.shapes if shape.name=='Записать результат')
        self.assertTrue(any(edge.source_id==task.element_id and edge.target_id==second.element_id for edge in diagram.edges))
        self.assertEqual(analyze(xml)['report']['flows'],3)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'connect','source':task.element_id,'target':identifier})
        xml=edit(xml,{'op':'delete','id':identifier})
        self.assertNotIn('subProcess',xml)
        self.assertEqual(analyze(xml)['report']['flows'],0)
    def test_old_collapsed_subprocess_can_be_expanded(self):
        xml=edit('',{'op':'add','kind':'subProcess','name':'Старый подпроцесс'})
        identifier=load_diagram(xml.encode()).shapes[0].element_id
        doc=minidom.parseString(xml)
        namespace='http://www.omg.org/spec/BPMN/20100524/DI'
        for visual in list(doc.getElementsByTagNameNS(namespace,'BPMNShape')):
            if visual.getAttribute('bpmnElement')!=identifier:
                visual.parentNode.removeChild(visual)
            else:
                visual.setAttribute('isExpanded','false')
        for visual in list(doc.getElementsByTagNameNS(namespace,'BPMNEdge')):
            visual.parentNode.removeChild(visual)
        xml=edit(doc.toxml(),{'op':'expand','id':identifier})
        diagram=load_diagram(xml.encode())
        self.assertTrue(diagram.shapes[0].expanded)
        self.assertEqual((len(diagram.shapes),len(diagram.edges)),(3,1))
    def test_transaction_contains_inner_flow_and_can_be_removed(self):
        xml=edit('',{'op':'add','kind':'transaction','name':'Подтвердить оплату'})
        self.assertEqual(analyze(xml)['report']['errors'],0)
        self.assertEqual(analyze(xml)['report']['flows'],1)
        identifier=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'delete','id':identifier})
        self.assertNotIn('<transaction ',xml)
        self.assertEqual(analyze(xml)['report']['flows'],0)
    def test_cancel_boundary_only_interrupts_transaction(self):
        xml=edit('',{'op':'add','kind':'transaction','name':'Оплата'})
        transaction=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'add','kind':'boundaryEvent','event':'cancel',
                      'attached_to':transaction,'name':'Отменить оплату'})
        self.assertIn('cancelEventDefinition',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'boundaryEvent','event':'cancel',
                      'attached_to':transaction,'interrupting':False})
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'endEvent','event':'cancel'})
        xml=edit(xml,{'op':'add','kind':'task','name':'Обычная задача'})
        task=load_diagram(xml.encode()).shapes[-1].element_id
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'boundaryEvent','event':'cancel','attached_to':task})
    def test_cancel_end_creates_exclusive_choice_inside_transaction(self):
        xml=edit('',{'op':'add','kind':'transaction','name':'Оплата'})
        transaction=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'add','kind':'endEvent','event':'cancel','scope':transaction,'name':'Отказ'})
        report=analyze(xml)['report']
        self.assertEqual((report['errors'],report['flows']),(0,3))
        self.assertIn('exclusiveGateway',xml)
        self.assertIn('cancelEventDefinition',xml)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'endEvent','event':'cancel','scope':transaction,'name':'Ещё отказ'})
    def test_boundary_event_attaches_to_activity(self):
        xml=edit('',{'op':'add','kind':'task','name':'Оплатить'})
        task=load_diagram(xml.encode()).shapes[0]
        xml=edit(xml,{'op':'add','kind':'boundaryEvent','event':'message',
                      'attached_to':task.element_id,'interrupting':False,'name':'Отмена'})
        boundary=load_diagram(xml.encode()).shapes[-1]
        self.assertEqual(boundary.attached_to,task.element_id)
        self.assertIn('cancelActivity="false"',xml)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        with self.assertRaises(ValueError):
            edit(xml,{'op':'add','kind':'boundaryEvent','event':'message','attached_to':'missing'})
    def test_deleting_activity_removes_boundary_outgoing_flow(self):
        xml=edit('',{'op':'add','kind':'task','name':'Оплатить'})
        task=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'add','kind':'boundaryEvent','event':'message',
                      'attached_to':task,'name':'Сообщение'})
        boundary=load_diagram(xml.encode()).shapes[-1].element_id
        xml=edit(xml,{'op':'add','kind':'endEvent','name':'Остановить'})
        end=load_diagram(xml.encode()).shapes[-1].element_id
        xml=edit(xml,{'op':'connect','source':boundary,'target':end})
        self.assertEqual(analyze(xml)['report']['flows'],1)
        xml=edit(xml,{'op':'delete','id':task})
        self.assertEqual(analyze(xml)['report']['flows'],0)
        self.assertNotIn('sourceRef=',xml)
        self.assertNotIn('attachedToRef=',xml)
    def test_new_document_add_connect_delete(self):
        xml=edit('',{'op':'add','kind':'startEvent','name':'Старт'})
        a=load_diagram(xml.encode()).shapes[0].element_id
        xml=edit(xml,{'op':'add','kind':'endEvent','name':'Конец','x':350})
        b=load_diagram(xml.encode()).shapes[-1].element_id
        xml=edit(xml,{'op':'connect','source':a,'target':b})
        self.assertEqual(analyze(xml)['report']['errors'],0)
        self.assertEqual(analyze(xml)['report']['flows'],1)
        xml=edit(xml,{'op':'delete','id':b})
        self.assertEqual(analyze(xml)['report']['flows'],0)
        self.assertNotIn('targetRef=',xml)
    def test_editor_rejects_invalid_event_connections(self):
        xml=''
        ids={}
        for kind in ('startEvent','endEvent','task','boundaryEvent','eventBasedGateway','intermediateCatchEvent'):
            action={'op':'add','kind':kind,'name':kind}
            if kind=='boundaryEvent':action.update(event='message',attached_to=ids['task'])
            if kind=='intermediateCatchEvent':action['event']='signal'
            xml=edit(xml,action);ids[kind]=load_diagram(xml.encode()).shapes[-1].element_id
        for source,target in (('endEvent','task'),('task','startEvent'),('task','boundaryEvent'),('eventBasedGateway','task')):
            with self.subTest(source=source,target=target),self.assertRaises(ValueError):
                edit(xml,{'op':'connect','source':ids[source],'target':ids[target]})
        self.assertIn('sequenceFlow',edit(xml,{'op':'connect','source':ids['eventBasedGateway'],'target':ids['intermediateCatchEvent']}))
    def test_event_gateway_connection_rejects_invalid_waits(self):
        xml='';ids={}
        for kind,event in (('eventBasedGateway',''),('intermediateCatchEvent','message'),
                           ('receiveTask',''),('intermediateCatchEvent','link')):
            xml=edit(xml,{'op':'add','kind':kind,'name':kind,'event':event,'link_name':'Переход'})
            ids[(kind,event)]=load_diagram(xml.encode()).shapes[-1].element_id
        gateway=ids[('eventBasedGateway','')]
        message=ids[('intermediateCatchEvent','message')]
        receive=ids[('receiveTask','')]
        link=ids[('intermediateCatchEvent','link')]
        xml=edit(xml,{'op':'connect','source':gateway,'target':message})
        for source,target in ((gateway,receive),(gateway,link),(receive,message)):
            with self.subTest(source=source,target=target),self.assertRaises(ValueError):
                edit(xml,{'op':'connect','source':source,'target':target})
    def test_parallel_event_gateway_starts_without_incoming_flow(self):
        xml=edit('',{'op':'add','kind':'eventBasedGateway','name':'Ожидать два сообщения',
                     'instantiate':True,'event_gateway_type':'Parallel'})
        self.assertIn('eventGatewayType="Parallel"',xml)
        self.assertIn('instantiate="true"',xml)
        gateway=load_diagram(xml.encode()).shapes[-1].element_id
        xml=edit(xml,{'op':'add','kind':'task','name':'Подготовить'})
        task=load_diagram(xml.encode()).shapes[-1].element_id
        with self.assertRaises(ValueError):
            edit(xml,{'op':'connect','source':task,'target':gateway})
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'eventBasedGateway','name':'Неверный',
                     'event_gateway_type':'Parallel'})
    def test_receive_task_can_start_process_without_incoming_flow(self):
        xml=edit('',{'op':'add','kind':'receiveTask','name':'Получить заявку',
                     'receive_instantiate':True})
        self.assertIn('instantiate="true"',xml)
        receive=load_diagram(xml.encode()).shapes[-1].element_id
        xml=edit(xml,{'op':'add','kind':'task','name':'Подготовить'})
        task=load_diagram(xml.encode()).shapes[-1].element_id
        with self.assertRaises(ValueError):
            edit(xml,{'op':'connect','source':task,'target':receive})
    def test_multi_instance_task_keeps_count_and_order(self):
        xml=edit('',{'op':'add','kind':'userTask','name':'Проверить заявки',
                     'multi_instance_count':3,'multi_instance_sequential':True,
                     'multi_instance_completion':'Одна заявка согласована'})
        self.assertIn('multiInstanceLoopCharacteristics isSequential="true"',xml)
        self.assertIn('<loopCardinality>3</loopCardinality>',xml)
        self.assertIn('<completionCondition>Одна заявка согласована</completionCondition>',xml)
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'userTask','name':'Слишком много',
                     'multi_instance_count':21})
        subprocess=edit('',{'op':'add','kind':'subProcess','name':'Проверить пакет',
                            'multi_instance_count':2,'multi_instance_sequential':False})
        self.assertIn('<loopCardinality>2</loopCardinality>',subprocess)
    def test_standard_loop_task_can_be_created(self):
        xml=edit('',{'op':'add','kind':'userTask','name':'Повторять проверку',
                     'standard_loop':True,'standard_loop_condition':'Есть заявки & время',
                     'standard_loop_maximum':3,'standard_loop_test_before':True})
        self.assertIn('standardLoopCharacteristics testBefore="true" loopMaximum="3"',xml)
        self.assertIn('<loopCondition>Есть заявки &amp; время</loopCondition>',xml)
        with self.assertRaises(ValueError):
            edit('',{'op':'add','kind':'userTask','name':'Два режима',
                     'multi_instance_count':2,'standard_loop':True,'standard_loop_maximum':3})
        subprocess=edit('',{'op':'add','kind':'subProcess','name':'Повторять обработку',
                            'standard_loop':True,'standard_loop_maximum':2})
        self.assertIn('standardLoopCharacteristics testBefore="false" loopMaximum="2"',subprocess)
    def test_move_reroutes_and_preserves_semantics(self):
        before=load_diagram(self.xml.encode());s=next(s for s in before.shapes if s.kind=='task')
        xml=edit(self.xml,{'op':'move','id':s.element_id,'dx':50,'dy':70})
        after=load_diagram(xml.encode());m=next(x for x in after.shapes if x.element_id==s.element_id)
        self.assertEqual((m.x,m.y),(s.x+50,s.y+70))
        self.assertNotEqual(before.edges[0].points,after.edges[0].points)
        self.assertEqual(analyze(xml)['report']['errors'],0)
        self.assertEqual(analyze(xml)['report']['flows'],2)
    def test_rename_escapes_xml(self):
        s=load_diagram(self.xml.encode()).shapes[1]
        xml=edit(self.xml,{'op':'rename','id':s.element_id,'name':'<Оплата & "заказ">'})
        self.assertEqual(load_diagram(xml.encode()).shapes[1].name,'<Оплата & "заказ">')
    def test_dtd_rejected(self):
        xml='<!DOCTYPE x [<!ENTITY y "oops">]><definitions/>'
        with self.assertRaises(ValueError):edit(xml,{'op':'add','kind':'task'})
    def test_no_cross_scope_or_container_sequence_flow(self):
        with self.assertRaises(ValueError):edit(self.xml,{'op':'connect','source':'missing','target':'missing'})
    def test_invalid_move_fails_without_mutation(self):
        with self.assertRaises(ValueError):edit(self.xml,{'op':'move','id':'task','dx':float('inf'),'dy':0})
    def test_add_preserves_vendor_extension(self):
        xml=self.xml.replace('</bpmn:definitions>','<!-- vendor metadata --></bpmn:definitions>')
        result=edit(xml,{'op':'add','kind':'task','name':'Test'})
        self.assertIn('vendor metadata',result)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.store=Store(Path(cls.tmp.name)/'http.sqlite3')
        cls.mail=TestMail();cls.accounts=Accounts(cls.store,cls.mail)
        cls.accounts.register(dict(name='HTTP',email='http@example.test',password=PASSWORD,specialty='business'))
        cls.accounts.use_token(cls.mail.token('verify'),'verify')
        token,user,cls.csrf=cls.accounts.login('http@example.test',PASSWORD)
        cls.cookie='workspace_session='+token
        cls.space=cls.accounts.spaces(user['id'])[0]['id']
        cls.project=cls.accounts.create_project(user['id'],cls.space,'Test')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.store,cls.accounts))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
    def req(self,path,method='GET',data=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        body=json.dumps(data) if data is not None else None
        h={'Content-Type':'application/json'} if data is not None else {}
        h.update({'Cookie':self.cookie,'X-CSRF-Token':self.csrf});h.update(headers or {});conn.request(method,path,body,h);r=conn.getresponse();result=r.read();status=r.status;conn.close()
        return status,result
    def test_assets_and_projects_load(self):
        for path in ('/','/style.css','/app.js','/account.js','/account.css','/api/projects?space='+self.space):
            status,data=self.req(path);self.assertEqual(status,200);self.assertTrue(data)
    def test_agent_permissions_and_isolated_frame(self):
        from unittest.mock import patch
        self.assertEqual(self.req('/api/agent/status',headers={'Cookie':''})[0],401)
        with patch('ai_agent.Agent.generate') as generate:
            self.assertEqual(self.req('/api/agent/generate','POST',{'project_id':'missing','block_id':'missing','prompt':'test'})[0],403)
            self.assertEqual(self.req('/api/agent/generate','POST',{'project_id':self.project['id']},headers={'X-CSRF-Token':''})[0],403)
            generate.assert_not_called()
        with patch('ai_agent.Agent.analyze', return_value={'analysis': {'summary': 'ok'}}) as analyze_agent:
            self.assertEqual(self.req('/api/agent/analyze','POST',{'project_id':'missing','scope':'project'})[0],404)
            self.assertEqual(self.req('/api/agent/analyze','POST',{'project_id':self.project['id']},headers={'X-CSRF-Token':''})[0],403)
            analyze_agent.assert_not_called()
            self.assertEqual(self.req('/api/agent/analyze','POST',{'project_id':self.project['id'],'scope':'project'})[0],200)
            self.assertEqual(analyze_agent.call_args.args[0]['id'],self.project['id'])
        opaque={'Origin':'null','Sec-Fetch-Site':'cross-site'}
        self.assertEqual(self.req('/prototype-bridge.js',headers=opaque)[0],200)
        self.assertEqual(self.req('/',headers=opaque)[0],200)
        self.assertEqual(self.req('/api/agent/status',headers=opaque)[0],403)
        self.assertEqual(self.req('/.env')[0],404)
    def test_local_agent_action_does_not_spend_daily_request(self):
        from unittest.mock import patch
        user=self.accounts.session(self.cookie.split('=',1)[1])['id']
        before=self.accounts.agent_quota(user)['used_today']
        with patch('ai_agent.Agent.chat',return_value={'model':'Facet local','message':'Готово'}):
            status,_=self.req('/api/agent/chat','POST',{'project_id':self.project['id'],'prompt':'Выровняй BPMN'})
        self.assertEqual(status,200)
        self.assertEqual(self.accounts.agent_quota(user)['used_today'],before)
    def test_slide_agent_endpoint_requires_project_edit_access(self):
        from unittest.mock import patch
        with patch('ai_agent.Agent.suggest_slides',return_value={'matches':[]}) as suggest:
            status,_=self.req('/api/presentation/suggest','POST',{'project_id':'missing','slides':[]})
            self.assertEqual(status,404);suggest.assert_not_called()
            status,_=self.req('/api/presentation/suggest','POST',{'project_id':self.project['id'],'slides':[{'number':1,'title':'Слайд','lines':[]}]})
            self.assertEqual(status,200);suggest.assert_called_once()
    def test_http_save_and_conflict(self):
        code,data=self.req('/api/projects','POST',{'name':'HTTP test','space_id':self.space});self.assertEqual(code,201);p=json.loads(data)
        path='/api/projects/'+p['id'];p['name']='Изменено'
        self.assertEqual(self.req(path,'PUT',{'project':p,'revision':1})[0],200)
        self.assertEqual(self.req(path,'PUT',{'project':p,'revision':1})[0],409)
    def test_cross_origin_writes_blocked(self):
        self.assertEqual(self.req('/api/projects','POST',{'name':'x'},{'Origin':'https://untrusted.example'})[0],403)
    def test_rebinding_host_blocked(self):
        self.assertEqual(self.req('/api/projects',headers={'Host':'evil.example'})[0],403)
    def test_analyze_malformed_xml_is_report(self):
        status,data=self.req('/api/bpmn/analyze','POST',{'xml':'<broken'})
        self.assertEqual(status,200);self.assertGreater(json.loads(data)['report']['errors'],0)
    def test_invalid_edit_and_request(self):
        self.assertEqual(self.req('/api/bpmn/edit','POST',{'xml':'','action':[],'project_id':self.project['id']})[0],400)
        self.assertEqual(self.req('/api/projects','POST',{'name':None})[0],400)
    def test_static_path_traversal_not_served(self):
        self.assertEqual(self.req('/../checker.py')[0],404)

    def test_anonymous_project_and_bpmn_endpoints_are_closed(self):
        for path,method,data in [('/api/projects?space='+self.space,'GET',None),('/api/projects/'+self.project['id'],'GET',None),('/api/bpmn/analyze','POST',{'xml':''})]:
            self.assertEqual(self.req(path,method,data,{'Cookie':''})[0],401)
    def test_authenticated_mutations_require_csrf(self):
        self.assertEqual(self.req('/api/projects','POST',{'name':'csrf','space_id':self.space},{'X-CSRF-Token':'bad'})[0],403)
    def test_login_sets_http_only_session_cookie(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('POST','/api/auth/login',json.dumps({'email':'http@example.test','password':PASSWORD}),{'Content-Type':'application/json'})
        r=conn.getresponse();cookie=r.getheader('Set-Cookie');r.read();conn.close()
        self.assertEqual(r.status,200);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
    def test_auth_status_never_exposes_secrets(self):
        status,body=self.req('/api/auth/me');data=json.loads(body)
        self.assertEqual(status,200);self.assertNotIn('password',data['user']);self.assertNotIn('session',data)
        status,body=self.req('/api/auth/me',headers={'Cookie':''});self.assertIsNone(json.loads(body)['user'])
