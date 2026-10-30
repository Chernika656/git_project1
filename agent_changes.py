"""Строгие операции Facet Agent: модель предлагает, сервер проверяет и применяет."""
import copy
import json
import uuid
import xml.etree.ElementTree as ET

from block_templates import process_xml, process_graph_xml, relayout_xml, split_bpmn_xml
from workspace import new_block, validate_project


def object_schema(properties):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties)}


TEXT = {'type': 'string'}
PARTICIPANT = object_schema({'id': TEXT, 'name': TEXT})
MESSAGE = object_schema({'from': TEXT, 'to': TEXT, 'text': TEXT,
                         'kind': {'type': 'string', 'enum': ['call', 'return']}})
BPMN_NODE = object_schema({'id': TEXT, 'type': {'type': 'string', 'enum': ['startEvent', 'endEvent', 'task',
                           'exclusiveGateway', 'inclusiveGateway', 'parallelGateway']}, 'name': TEXT})
BPMN_FLOW = object_schema({'source': TEXT, 'target': TEXT, 'condition': TEXT})
STATUS = {'type': 'string', 'enum': ['', 'draft', 'review', 'approved']}
REQUIREMENT = object_schema({'id': TEXT, 'title': TEXT, 'text': TEXT, 'status': STATUS,
                             'elements': {'type': 'array', 'items': TEXT}})
TERM = object_schema({'id': TEXT, 'name': TEXT, 'definition': TEXT,
                      'blocks': {'type': 'array', 'items': TEXT}})
DETAIL = object_schema({'element_id': TEXT, 'description': TEXT, 'requirements': TEXT, 'acceptance': TEXT})
SPLIT_GROUP = object_schema({'block_id': TEXT, 'name': TEXT, 'description': TEXT, 'owner': TEXT,
                             'status': STATUS, 'element_ids': {'type': 'array', 'items': TEXT}})


def operation_schema(kind, properties):
    return object_schema({'type': {'type': 'string', 'enum': [kind]}, **properties})


OPERATION_SCHEMAS = [
    operation_schema('set_project', {'name': TEXT, 'description': TEXT}),
    operation_schema('split_bpmn', {'source_block_id': TEXT, 'groups': {'type': 'array', 'items': SPLIT_GROUP}}),
    operation_schema('create_block', {'block_id': TEXT, 'name': TEXT, 'description': TEXT, 'owner': TEXT, 'status': STATUS}),
    operation_schema('update_block', {'block_id': TEXT, 'name': TEXT, 'description': TEXT, 'owner': TEXT, 'status': STATUS}),
    operation_schema('set_requirements', {'block_id': TEXT, 'requirements': TEXT}),
    operation_schema('set_requirement_items', {'block_id': TEXT, 'requirement_items': {'type': 'array', 'items': REQUIREMENT}}),
    operation_schema('set_bpmn', {'block_id': TEXT, 'tasks': {'type': 'array', 'items': TEXT},
                                  'bpmn_nodes': {'type': 'array', 'items': BPMN_NODE},
                                  'bpmn_flows': {'type': 'array', 'items': BPMN_FLOW}}),
    operation_schema('relayout_bpmn', {'block_id': TEXT}),
    operation_schema('set_element_details', {'block_id': TEXT, 'element_details': {'type': 'array', 'items': DETAIL}}),
    operation_schema('set_uml', {'block_id': TEXT, 'participants': {'type': 'array', 'items': PARTICIPANT},
                                 'messages': {'type': 'array', 'items': MESSAGE}}),
    operation_schema('set_task_uml', {'block_id': TEXT, 'element_id': TEXT,
                                      'participants': {'type': 'array', 'items': PARTICIPANT},
                                      'messages': {'type': 'array', 'items': MESSAGE}}),
    operation_schema('set_api', {'block_id': TEXT, 'technical': TEXT}),
    operation_schema('set_slides', {'block_id': TEXT, 'description': TEXT, 'owner': TEXT, 'status': STATUS}),
    operation_schema('link_blocks', {'source_id': TEXT, 'target_id': TEXT}),
    operation_schema('unlink_blocks', {'source_id': TEXT, 'target_id': TEXT}),
    operation_schema('set_glossary', {'terms': {'type': 'array', 'items': TERM}}),
]
OPERATION_KEYS = ('type','block_id','element_id','source_block_id','source_id','target_id','name','description','owner','status',
                  'requirements','technical','tasks','bpmn_nodes','bpmn_flows','participants','messages',
                  'requirement_items','element_details','terms','groups')
ARRAY_KEYS = {'tasks','bpmn_nodes','bpmn_flows','participants','messages','requirement_items','element_details','terms','groups'}
ALLOWED = {schema['properties']['type']['enum'][0] for schema in OPERATION_SCHEMAS}
SCHEMA = object_schema({'reply': TEXT, 'summary': TEXT,
                        'operations': {'type': 'array', 'items': {'anyOf': OPERATION_SCHEMAS}}})


def schema_for_layer(layer):
    by_layer={
        'overview': {'set_project','create_block','update_block','link_blocks','unlink_blocks'},
        'requirements': {'create_block','update_block','set_requirements','set_requirement_items','set_glossary'},
        'bpmn': {'create_block','update_block','split_bpmn','set_bpmn','relayout_bpmn','set_element_details','set_requirements','set_requirement_items'},
        'uml': {'create_block','update_block','set_uml','set_task_uml'},
        'technical': {'create_block','update_block','set_api'},
        'slides': {'create_block','update_block','set_slides'},
    }
    allowed=by_layer.get(layer,ALLOWED);variants=[schema for schema in OPERATION_SCHEMAS if schema['properties']['type']['enum'][0] in allowed]
    return object_schema({'reply':TEXT,'summary':TEXT,'operations':{'type':'array','items':{'anyOf':variants}}})


def _text(value, limit=20000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Агент вернул слишком большое или некорректное поле.')
    return value.strip()


def validate_plan(value, project, editable):
    if not isinstance(value, dict):
        raise ValueError('Некорректный ответ агента.')
    reply, summary = _text(value.get('reply'), 12000), _text(value.get('summary'), 1000)
    raw = value.get('operations')
    if not isinstance(raw, list) or len(raw) > 60:
        raise ValueError('Агент предложил слишком много операций.')
    if not editable and raw:
        raise ValueError('Агент попытался изменить проект без права редактирования.')
    existing, aliases, clean = {b['id'] for b in project['blocks']}, set(), []
    for item in raw:
        if not isinstance(item, dict) or item.get('type') not in ALLOWED:
            raise ValueError('Неизвестная операция агента.')
        op = {key: ([] if key in ARRAY_KEYS else '') for key in OPERATION_KEYS};op.update(item)
        for key in ('block_id','element_id','source_block_id','source_id','target_id','name','description','owner','requirements','technical'):
            op[key] = _text(op[key], 20000 if key in ('description','requirements','technical') else 200)
        if op['status'] not in ('','draft','review','approved'):
            raise ValueError('Некорректный статус от агента.')
        if not isinstance(op['tasks'], list) or len(op['tasks']) > 30:
            raise ValueError('В BPMN допускается до 30 шагов за одну генерацию.')
        op['tasks'] = [_text(task, 200) for task in op['tasks'] if _text(task, 200)]
        if not isinstance(op['bpmn_nodes'], list) or len(op['bpmn_nodes']) > 40 or not isinstance(op['bpmn_flows'], list) or len(op['bpmn_flows']) > 80:
            raise ValueError('BPMN агента слишком большой.')
        raw_nodes, raw_flows = op['bpmn_nodes'], op['bpmn_flows']
        node_ids=set();op['bpmn_nodes']=[]
        for node in raw_nodes:
            identifier,name,node_type=_text(node.get('id'),80),_text(node.get('name'),200),node.get('type')
            if not identifier or not identifier.replace('_','').isalnum() or identifier in node_ids or node_type not in BPMN_NODE['properties']['type']['enum']:
                raise ValueError('Некорректный элемент BPMN агента.')
            if node_type=='task' and not name: raise ValueError('Задача BPMN должна иметь название.')
            node_ids.add(identifier);op['bpmn_nodes'].append({'id':identifier,'type':node_type,'name':name})
        op['bpmn_flows']=[]
        for flow in raw_flows:
            source,target,condition=_text(flow.get('source'),80),_text(flow.get('target'),80),_text(flow.get('condition'),200)
            if source not in node_ids or target not in node_ids or source==target: raise ValueError('Некорректная связь BPMN агента.')
            op['bpmn_flows'].append({'source':source,'target':target,'condition':condition})
        if op['bpmn_nodes']:
            starts=[n for n in op['bpmn_nodes'] if n['type']=='startEvent'];ends=[n for n in op['bpmn_nodes'] if n['type']=='endEvent']
            if len(starts)!=1 or not ends: raise ValueError('BPMN агента требует одно начало и хотя бы одно завершение.')
            incoming={i:[] for i in node_ids};outgoing={i:[] for i in node_ids}
            for flow in op['bpmn_flows']: outgoing[flow['source']].append(flow);incoming[flow['target']].append(flow)
            if incoming[starts[0]['id']] or any(outgoing[n['id']] for n in ends): raise ValueError('Некорректные связи начального или конечного события BPMN.')
            for node in op['bpmn_nodes']:
                ins,outs=incoming[node['id']],outgoing[node['id']]
                if node['type'] not in ('exclusiveGateway','inclusiveGateway','parallelGateway') and len(outs)>1: raise ValueError('Ветвление BPMN должно начинаться шлюзом.')
                if 'Gateway' in node['type'] and len(ins)<2 and len(outs)<2: raise ValueError('Шлюз BPMN не создаёт и не объединяет ветки.')
                if node['type'] in ('exclusiveGateway','inclusiveGateway') and len(outs)>1 and any(not f['condition'] for f in outs): raise ValueError('Подпишите условия всех веток шлюза.')
            reached=set();stack=[starts[0]['id']]
            while stack:
                current=stack.pop()
                if current in reached: continue
                reached.add(current);stack.extend(flow['target'] for flow in outgoing[current])
            if reached!=node_ids: raise ValueError('В BPMN агента есть недостижимые элементы.')
            finishable=set();stack=[node['id'] for node in ends]
            while stack:
                current=stack.pop()
                if current in finishable: continue
                finishable.add(current);stack.extend(flow['source'] for flow in incoming[current])
            if finishable!=node_ids: raise ValueError('Некоторые ветки BPMN агента не приводят к завершению.')
        participants = op['participants']
        if not isinstance(participants, list) or len(participants) > 30:
            raise ValueError('Некорректные участники UML.')
        ids = set(); op['participants'] = []
        for actor in participants:
            identifier, name = _text(actor.get('id'), 80), _text(actor.get('name'), 200)
            if not identifier or identifier in ids or not name:
                raise ValueError('Участникам UML нужны уникальные ID и имена.')
            ids.add(identifier);op['participants'].append({'id':identifier,'name':name})
        messages = op['messages']
        if not isinstance(messages, list) or len(messages) > 200:
            raise ValueError('Некорректные сообщения UML.')
        op['messages'] = []
        for message in messages:
            source, target = _text(message.get('from'),80), _text(message.get('to'),80)
            text, kind = _text(message.get('text'),2000), message.get('kind')
            if source not in ids or target not in ids or kind not in ('call','return') or not text:
                raise ValueError('Некорректная связь UML.')
            op['messages'].append({'from':source,'to':target,'text':text,'kind':kind})
        requirement_ids=set();clean_requirements=[]
        if len(op['requirement_items'])>300: raise ValueError('Слишком много требований агента.')
        for requirement in op['requirement_items']:
            identifier,title,text,status=_text(requirement.get('id'),80),_text(requirement.get('title'),200),_text(requirement.get('text'),20000),requirement.get('status')
            elements=requirement.get('elements')
            if not identifier or identifier in requirement_ids or not title or status not in ('draft','review','approved') or not isinstance(elements,list) or len(elements)>100:
                raise ValueError('Некорректное структурированное требование агента.')
            requirement_ids.add(identifier);clean_requirements.append({'id':identifier,'title':title,'text':text,'status':status,'elements':[_text(x,200) for x in elements]})
        op['requirement_items']=clean_requirements
        if len(op['element_details'])>200: raise ValueError('Слишком много детализаций BPMN.')
        detail_ids=set();clean_details=[]
        for detail in op['element_details']:
            identifier=_text(detail.get('element_id'),200)
            if not identifier or identifier in detail_ids: raise ValueError('Некорректная детализация BPMN агента.')
            detail_ids.add(identifier);clean_details.append({'element_id':identifier,'description':_text(detail.get('description'),20000),'requirements':_text(detail.get('requirements'),20000),'acceptance':_text(detail.get('acceptance'),20000)})
        op['element_details']=clean_details
        if len(op['terms'])>500: raise ValueError('Слишком много терминов агента.')
        term_ids=set();term_names=set();clean_terms=[]
        for term in op['terms']:
            identifier,name,definition=_text(term.get('id'),80),_text(term.get('name'),200),_text(term.get('definition'),20000);blocks=term.get('blocks')
            if not identifier or identifier in term_ids or not name or name.casefold() in term_names or not definition or not isinstance(blocks,list): raise ValueError('Некорректный термин агента.')
            term_ids.add(identifier);term_names.add(name.casefold());clean_terms.append({'id':identifier,'name':name,'definition':definition,'blocks':[_text(x,200) for x in blocks]})
        op['terms']=clean_terms
        if op['type'] == 'split_bpmn':
            source=next((block for block in project['blocks'] if block['id']==op['source_block_id']),None)
            if not source or not source.get('bpmn'): raise ValueError('Исходный BPMN-блок для разбиения не найден.')
            if not isinstance(op['groups'],list) or not 2<=len(op['groups'])<=6: raise ValueError('Разбиение должно содержать от 2 до 6 блоков.')
            try:
                root=ET.fromstring(source['bpmn']);process=max((element for element in root.iter() if element.tag.rsplit('}',1)[-1]=='process'),key=lambda item:len(list(item)))
            except (ET.ParseError,ValueError): raise ValueError('Исходную BPMN невозможно разобрать.') from None
            from checker import kind, NODES
            expected={child.get('id') for child in process if kind(child) in NODES and child.get('id')};used=set();clean_groups=[]
            for group in op['groups']:
                alias,name=_text(group.get('block_id'),200),_text(group.get('name'),200);ids=group.get('element_ids');status=group.get('status')
                if not alias or alias in existing|aliases or not name or status not in ('draft','review','approved') or not isinstance(ids,list) or not ids: raise ValueError('Некорректная группа разбиения BPMN.')
                ids=[_text(identifier,200) for identifier in ids]
                if len(ids)!=len(set(ids)) or used.intersection(ids): raise ValueError('Элемент BPMN попал в несколько блоков.')
                used.update(ids);aliases.add(alias);clean_groups.append({'block_id':alias,'name':name,'description':_text(group.get('description'),20000),'owner':_text(group.get('owner'),200),'status':status,'element_ids':ids})
            if used!=expected: raise ValueError(f'Агент не сохранил точный состав BPMN: распределено {len(used)} из {len(expected)} элементов.')
            assignment={identifier:group['block_id'] for group in clean_groups for identifier in group['element_ids']}
            for identifier,node in ((child.get('id'),child) for child in process if kind(child)=='boundaryEvent'):
                attached=node.get('attachedToRef')
                if attached in assignment and assignment.get(identifier)!=assignment[attached]: raise ValueError('Граничное событие должно остаться с исходной задачей.')
            op['groups']=clean_groups
        elif op['type'] == 'create_block':
            if not op['block_id'] or op['block_id'] in existing or op['block_id'] in aliases or not op['name']:
                raise ValueError('Новому блоку нужны уникальный временный ID и название.')
            aliases.add(op['block_id'])
        elif op['type'] not in ('set_project','link_blocks','unlink_blocks','set_glossary') and op['block_id'] not in existing|aliases:
            raise ValueError('Агент сослался на отсутствующий блок.')
        if op['type'] in ('link_blocks','unlink_blocks') and (op['source_id'] not in existing|aliases or op['target_id'] not in existing|aliases):
            raise ValueError('Агент сослался на отсутствующий блок связи.')
        if op['type']=='set_glossary' and any(identifier not in existing|aliases for term in op['terms'] for identifier in term['blocks']): raise ValueError('Термин ссылается на отсутствующий блок.')
        clean.append(op)
    return {'reply': reply, 'summary': summary, 'operations': clean}


def apply_plan(project, operations):
    result = copy.deepcopy(project)
    result.pop('access', None); result.pop('space_id', None)
    aliases, touched = {}, []
    def resolve(identifier): return aliases.get(identifier, identifier)
    def target(identifier):
        found = next((b for b in result['blocks'] if b['id'] == resolve(identifier)), None)
        if not found: raise ValueError('Блок из предложения агента больше не существует.')
        return found
    def common(block, op):
        for key in ('name','description','owner','requirements','technical','status'):
            if op[key] != '': block[key] = op[key]
    for op in operations:
        kind = op['type']
        if kind == 'set_project':
            if op['name']: result['name'] = op['name']
            if op['description']: result['goal'] = op['description']
            continue
        if kind == 'split_bpmn':
            source=target(op['source_block_id']);fragments,connections,stats=split_bpmn_xml(source['bpmn'],op['groups']);fragment_by_alias={item['block_id']:item for item in fragments};created=[]
            for group in op['groups']:
                block=new_block(group['name'],len(result['blocks']));block.update(description=group['description'],owner=group['owner'],status=group['status'])
                fragment=fragment_by_alias[group['block_id']];block['bpmn']=fragment['xml'];block['source_trace']={'source_block_id':source['id'],'element_ids':fragment['element_ids'],'flow_ids':fragment['flow_ids']}
                aliases[group['block_id']]=block['id'];result['blocks'].append(block);created.append(block['id']);touched.append(block['id'])
            for connection in connections:
                source_id,target_id=resolve(connection['source_id']),resolve(connection['target_id'])
                existing_link=next((link for link in result['links'] if link['source']==source_id and link['target']==target_id),None)
                if existing_link is None:
                    result['links'].append({'id':uuid.uuid4().hex,'source':source_id,'target':target_id,'bpmn_flows':copy.deepcopy(connection['flows'])})
                else: existing_link['bpmn_flows']=copy.deepcopy(connection['flows'])
            source['last_split']={'block_ids':created,'source_elements':stats['elements'],'source_flows':stats['flows'],'preserved_elements':stats['elements'],'preserved_flows':stats['flows']}
            continue
        if kind == 'set_glossary':
            result['glossary']=[{**term,'blocks':[resolve(identifier) for identifier in term['blocks']]} for term in op['terms']]
            continue
        if kind == 'create_block':
            block = new_block(op['name'], len(result['blocks']));common(block,op)
            aliases[op['block_id']] = block['id'];result['blocks'].append(block)
        elif kind == 'link_blocks':
            source,target_id=resolve(op['source_id']),resolve(op['target_id'])
            if source!=target_id and not any(l['source']==source and l['target']==target_id for l in result['links']):
                result['links'].append({'id':uuid.uuid4().hex,'source':source,'target':target_id})
            continue
        elif kind == 'unlink_blocks':
            source,target_id=resolve(op['source_id']),resolve(op['target_id']);result['links']=[link for link in result['links'] if not (link['source']==source and link['target']==target_id)]
            continue
        else: block = target(op['block_id'])
        if kind in ('create_block','update_block','set_slides'): common(block,op)
        if kind in ('create_block','set_requirements') and op['requirements']: block['requirements']=op['requirements']
        if kind == 'set_requirement_items': block['requirement_items']=copy.deepcopy(op['requirement_items'])
        if kind in ('create_block','set_api') and op['technical']: block['technical']=op['technical']
        if kind in ('create_block','set_bpmn'):
            if op['bpmn_nodes']: block['bpmn']=process_graph_xml(block['name'],op['bpmn_nodes'],op['bpmn_flows'])
            elif op['tasks']: block['bpmn']=process_xml(block['name'],op['tasks'])
        if kind == 'relayout_bpmn':
            if not block.get('bpmn'): raise ValueError('В блоке нет BPMN для выравнивания.')
            block['bpmn']=relayout_xml(block['bpmn'])
        if kind in ('create_block','set_uml') and op['participants']:
            block['uml']={'participants':copy.deepcopy(op['participants']),'messages':[{'id':'m'+str(i+1),**m} for i,m in enumerate(op['messages'])]}
        if kind == 'set_task_uml':
            if not block.get('bpmn'): raise ValueError('В блоке нет BPMN для UML задачи.')
            try: identifiers={element.get('id') for element in ET.fromstring(block['bpmn']).iter()}
            except ET.ParseError: raise ValueError('BPMN блока невозможно прочитать.') from None
            if op['element_id'] not in identifiers: raise ValueError('Элемент BPMN для отдельной UML не найден.')
            details=block.setdefault('element_details',[]);detail=next((item for item in details if item['element_id']==op['element_id']),None)
            if detail is None:
                detail={'element_id':op['element_id'],'description':'','requirements':'','acceptance':'','uml':{'participants':[],'messages':[]}};details.append(detail)
            detail['uml']={'participants':copy.deepcopy(op['participants']),'messages':[{'id':'m'+str(i+1),**m} for i,m in enumerate(op['messages'])]}
            detail.pop('uml_review',None)
        if kind == 'set_element_details':
            old={detail['element_id']:detail for detail in block.get('element_details',[])};merged=[]
            for detail in op['element_details']:
                value=copy.deepcopy(old.get(detail['element_id'],{}));value.update(detail);value.setdefault('uml',{'participants':[],'messages':[]});merged.append(value)
            block['element_details']=merged
        touched.append(block['id'])
    validate_project(result)
    return result, list(dict.fromkeys(touched))
