"""Готовые процессы и личная библиотека блоков пользователя."""
import copy
import json
import uuid
import xml.etree.ElementTree as ET

from facet.projects.workspace import new_block, new_project, validate_project

MODEL = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
DI = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
WAY = 'http://www.omg.org/spec/DD/20100524/DI'
for prefix, uri in [('bpmn', MODEL), ('bpmndi', DI), ('dc', DC), ('di', WAY)]:
    ET.register_namespace(prefix, uri)


def process_xml(title, tasks):
    root = ET.Element(f'{{{MODEL}}}definitions', id='Definitions', targetNamespace='urn:facet:template')
    process = ET.SubElement(root, f'{{{MODEL}}}process', id='Process', name=title, isExecutable='false')
    nodes = [('Start', 'startEvent', 'Начало')] + [(f'Task_{i}', 'task', task) for i, task in enumerate(tasks)] + [('End', 'endEvent', 'Готово')]
    diagram = ET.SubElement(root, f'{{{DI}}}BPMNDiagram', id='Diagram')
    plane = ET.SubElement(diagram, f'{{{DI}}}BPMNPlane', id='Plane', bpmnElement='Process')
    for i, (identifier, kind, name) in enumerate(nodes):
        node = ET.SubElement(process, f'{{{MODEL}}}{kind}', id=identifier, name=name)
        if i:
            ET.SubElement(node, f'{{{MODEL}}}incoming').text = f'Flow_{i-1}'
        if i < len(nodes)-1:
            ET.SubElement(node, f'{{{MODEL}}}outgoing').text = f'Flow_{i}'
        shape = ET.SubElement(plane, f'{{{DI}}}BPMNShape', id=identifier+'_di', bpmnElement=identifier)
        task = kind == 'task'
        ET.SubElement(shape, f'{{{DC}}}Bounds', x=str(80+i*210), y='100' if task else '122', width='140' if task else '36', height='80' if task else '36')
        if i:
            previous = nodes[i-1]
            flow = f'Flow_{i-1}'
            ET.SubElement(process, f'{{{MODEL}}}sequenceFlow', id=flow, sourceRef=previous[0], targetRef=identifier)
            edge = ET.SubElement(plane, f'{{{DI}}}BPMNEdge', id=flow+'_di', bpmnElement=flow)
            ET.SubElement(edge, f'{{{WAY}}}waypoint', x=str(80+(i-1)*210+(140 if previous[1]=='task' else 36)), y='140')
            ET.SubElement(edge, f'{{{WAY}}}waypoint', x=str(80+i*210), y='140')
    return ET.tostring(root, encoding='unicode')


def _flow_routes(positions, pairs, levels):
    """Orthogonal routes with separate ports, channels and return lanes."""
    outgoing={identifier:[] for identifier in positions};incoming={identifier:[] for identifier in positions}
    for index,(source,target) in enumerate(pairs):
        if source in outgoing and target in incoming:
            outgoing[source].append(index);incoming[target].append(index)
    adjacent={}
    for index,(source,target) in enumerate(pairs):
        if source in positions and target in positions and levels.get(target,0)==levels.get(source,0)+1:
            adjacent.setdefault((levels[source],levels[target]),[]).append(index)
    top=min((y for x,y,w,h in positions.values()),default=70)
    bottom=max((y+h for x,y,w,h in positions.values()),default=200)
    long_index=return_index=same_level_index=self_index=0;routes=[];return_channels=set()
    def slot(items,index):
        """A port fraction that never lands exactly on a node corner."""
        rank=items.index(index)+1
        return rank,len(items),rank/(len(items)+1)
    def compact(points):
        result=[]
        for point in points:
            if not result or point!=result[-1]: result.append(point)
        return result
    def unique_return_channel(value,direction):
        value=round(value,3)
        while value in return_channels: value=round(value+direction*8,3)
        return_channels.add(value)
        return value
    for index,(source,target) in enumerate(pairs):
        if source not in positions or target not in positions: routes.append([]);continue
        sx,sy,sw,sh=positions[source];tx,ty,tw,th=positions[target]
        out_slot,out_total,out_fraction=slot(outgoing[source],index);in_slot,in_total,in_fraction=slot(incoming[target],index)
        source_y=sy+sh*out_fraction;target_y=ty+th*in_fraction
        source_x=sx+sw;target_x=tx
        distance=levels.get(target,0)-levels.get(source,0)
        if source==target:
            channel=sx+sw+42+self_index*18;self_index+=1
            start=(sx+sw,sy+sh/3);end=(sx+sw,sy+sh*2/3)
            routes.append(compact([start,(channel,start[1]),(channel,end[1]),end]));continue
        if distance<0:
            # Backward connections leave the source to the left, travel below
            # the diagram and enter the target from below.  Short bottom stubs
            # prevent a return from sharing the left/right port of a normal
            # forward connection, while the long verticals stay in column gaps.
            return_number=return_index;track=bottom+70+return_number*42;return_index+=1
            exit_x=unique_return_channel(sx-28-(return_number%5)*9-out_slot*5,-1)
            entry_x=unique_return_channel(tx+tw+28+(return_number%5)*9+in_slot*5,1)
            source_bottom=(sx+sw*out_fraction,sy+sh);target_bottom=(tx+tw*in_fraction,ty+th)
            source_lane=source_bottom[1]+18+out_slot*7;target_lane=target_bottom[1]+18+in_slot*7
            routes.append(compact([source_bottom,(source_bottom[0],source_lane),(exit_x,source_lane),(exit_x,track),(entry_x,track),(entry_x,target_lane),(target_bottom[0],target_lane),target_bottom]));continue
        if distance==0:
            # Connections between nodes in one column get an individual route
            # on the right side rather than sharing a bottom return lane.
            channel=max(sx+sw,tx+tw)+45+same_level_index*26;same_level_index+=1
            routes.append(compact([(sx+sw,source_y),(channel,source_y),(channel,target_y),(tx+tw,target_y)]));continue
        if distance>1:
            track=top-58-long_index*42;long_index+=1
            exit_x=source_x+18+out_slot*10;entry_x=target_x-18-in_slot*10
            routes.append(compact([(source_x,source_y),(exit_x,source_y),(exit_x,track),(entry_x,track),(entry_x,target_y),(target_x,target_y)]));continue
        group=adjacent[(levels[source],levels[target])];channel_slot,channel_total,channel_fraction=slot(group,index)
        left=max(positions[pairs[item][0]][0]+positions[pairs[item][0]][2] for item in group)
        right=min(positions[pairs[item][1]][0] for item in group)
        # Keep the long horizontal part away from node-centre lines.  Each
        # connection gets its own small lane between the two columns; only the
        # first and last stubs remain at the element port height.
        usable_left=left+18;usable_right=right-18
        exit_x=usable_left+(usable_right-usable_left)*min(.34,channel_fraction*.42)
        entry_x=usable_right-(usable_right-usable_left)*min(.34,(1-channel_fraction)*.42)
        lane_offset=(channel_slot-(channel_total+1)/2)*13
        lane_y=(source_y+target_y)/2+lane_offset
        routes.append(compact([(source_x,source_y),(exit_x,source_y),(exit_x,lane_y),(entry_x,lane_y),(entry_x,target_y),(target_x,target_y)]))
    return routes


def process_graph_xml(title, nodes, flows):
    """Build a validated, readable BPMN graph supplied by the agent."""
    root = ET.Element(f'{{{MODEL}}}definitions', id='Definitions', targetNamespace='urn:facet:agent')
    process = ET.SubElement(root, f'{{{MODEL}}}process', id='Process', name=title, isExecutable='false')
    diagram = ET.SubElement(root, f'{{{DI}}}BPMNDiagram', id='Diagram')
    plane = ET.SubElement(diagram, f'{{{DI}}}BPMNPlane', id='Plane', bpmnElement='Process')
    by_id = {node['id']: node for node in nodes}
    incoming = {identifier: [] for identifier in by_id}; outgoing = {identifier: [] for identifier in by_id}
    for index, flow in enumerate(flows, 1):
        flow['xml_id'] = f'Flow_{index}';outgoing[flow['source']].append(flow);incoming[flow['target']].append(flow)
    # Уровни считаются по первому достижению от старта. Обратные связи не
    # участвуют в ранжировании, поэтому цикл не раздувает схему бесконечно.
    roots = [node['id'] for node in nodes if node['type'] == 'startEvent'] or [identifier for identifier in by_id if not incoming[identifier]]
    queue = list(roots);levels = {identifier: 0 for identifier in roots};seen = []
    while queue:
        current = queue.pop(0);seen.append(current)
        for flow in outgoing[current]:
            target = flow['target']
            if target not in levels: levels[target] = levels[current]+1;queue.append(target)
    for identifier in by_id: levels.setdefault(identifier,max(levels.values(),default=0)+1)
    columns = {}
    for node in nodes: columns.setdefault(levels[node['id']], []).append(node)
    rows = {}
    for level in sorted(columns):
        column=columns[level]
        desired=[sum(rows[f['source']] for f in incoming[node['id']] if f['source'] in rows)/max(1,len([f for f in incoming[node['id']] if f['source'] in rows])) for node in column]
        order=sorted(range(len(column)),key=lambda index:desired[index]);placed={};last=None
        for index in order:
            row=desired[index] if last is None else max(desired[index],last+1);placed[index]=row;last=row
        shift=(sum(desired)/len(desired)-sum(placed.values())/len(placed)) if placed else 0
        for index,node in enumerate(column): rows[node['id']]=placed[index]+shift
    min_row=min(rows.values(),default=0);positions = {}
    for node in nodes:
        kind=node['type'];width=150 if kind=='task' else (52 if 'Gateway' in kind else 38);height=76 if kind=='task' else (52 if 'Gateway' in kind else 38)
        positions[node['id']] = (65+levels[node['id']]*265, 70+(rows[node['id']]-min_row)*150, width, height)
    for node in nodes:
        attrs={'id':node['id']}
        if node['name']: attrs['name']=node['name']
        element=ET.SubElement(process,f'{{{MODEL}}}{node["type"]}',attrs)
        for flow in incoming[node['id']]: ET.SubElement(element,f'{{{MODEL}}}incoming').text=flow['xml_id']
        for flow in outgoing[node['id']]: ET.SubElement(element,f'{{{MODEL}}}outgoing').text=flow['xml_id']
        shape=ET.SubElement(plane,f'{{{DI}}}BPMNShape',id=node['id']+'_di',bpmnElement=node['id'])
        x,y,width,height=positions[node['id']];ET.SubElement(shape,f'{{{DC}}}Bounds',x=str(x),y=str(y),width=str(width),height=str(height))
    routes=_flow_routes(positions,[(flow['source'],flow['target']) for flow in flows],levels)
    for flow,points in zip(flows,routes):
        attrs={'id':flow['xml_id'],'sourceRef':flow['source'],'targetRef':flow['target']}
        if flow['condition']: attrs['name']=flow['condition']
        element=ET.SubElement(process,f'{{{MODEL}}}sequenceFlow',attrs)
        if flow['condition'] and by_id[flow['source']]['type'] in ('exclusiveGateway','inclusiveGateway'):
            condition=ET.SubElement(element,f'{{{MODEL}}}conditionExpression');condition.text=flow['condition']
        edge=ET.SubElement(plane,f'{{{DI}}}BPMNEdge',id=flow['xml_id']+'_di',bpmnElement=flow['xml_id'])
        for x,y in points: ET.SubElement(edge,f'{{{WAY}}}waypoint',x=str(x),y=str(y))
    return ET.tostring(root, encoding='unicode')


def split_bpmn_xml(xml, groups):
    """Split one process by original top-level element IDs without regenerating semantics."""
    from facet.bpmn.checker import kind, NODES
    try:
        source_root=ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('Исходную BPMN невозможно прочитать.') from exc
    processes=[element for element in source_root.iter() if kind(element)=='process']
    if not processes: raise ValueError('В исходной BPMN нет процесса.')
    process=max(processes,key=lambda item:sum(kind(child) in NODES for child in item))
    nodes={child.get('id'):child for child in process if kind(child) in NODES and child.get('id')}
    flows=[child for child in process if kind(child)=='sequenceFlow' and child.get('id')]
    if not nodes: raise ValueError('В исходном процессе нет элементов для разбиения.')
    assignments={identifier:group['block_id'] for group in groups for identifier in group['element_ids']}
    if set(assignments)!=set(nodes):
        missing=set(nodes)-set(assignments);extra=set(assignments)-set(nodes)
        raise ValueError(f'Разбиение не покрывает исходную BPMN: пропущено {len(missing)}, неизвестных ID {len(extra)}.')
    fragments=[]
    for group in groups:
        chosen=set(group['element_ids']);root=copy.deepcopy(source_root)
        # Внутри фрагмента остаётся только один исполняемый процесс. Глобальные
        # определения событий и сообщений сохраняются, а старая DI перестраивается.
        for child in list(root):
            if kind(child)=='process' or child.tag.rsplit('}',1)[-1] in ('BPMNDiagram','collaboration'):
                root.remove(child)
        fragment=ET.SubElement(root,process.tag,dict(process.attrib));fragment.set('name',group['name'])
        included=set(chosen)
        for identifier in chosen:
            included.update(element.get('id') for element in nodes[identifier].iter() if element.get('id') and kind(element) in NODES)
        for original_lane_set in [child for child in process if kind(child)=='laneSet']:
            lane_set=copy.deepcopy(original_lane_set)
            for lane in [element for element in lane_set.iter() if kind(element)=='lane']:
                for ref in [element for element in list(lane) if kind(element)=='flowNodeRef' and (element.text or '').strip() not in included]: lane.remove(ref)
            fragment.append(lane_set)
        copied={}
        for identifier in group['element_ids']:
            node=copy.deepcopy(nodes[identifier]);copied[identifier]=node
            for ref in [child for child in list(node) if kind(child) in ('incoming','outgoing')]: node.remove(ref)
            fragment.append(node)
        fragment_flows=[]
        for flow in flows:
            source,target=flow.get('sourceRef'),flow.get('targetRef')
            if source in chosen and target in chosen:
                fragment_flows.append(copy.deepcopy(flow))
            elif source in chosen and target in nodes:
                proxy_id='FacetEnd_'+flow.get('id');proxy=ET.Element(f'{{{MODEL}}}endEvent',id=proxy_id,name='Далее: '+(nodes[target].get('name') or target));fragment.append(proxy)
                proxy_flow=copy.deepcopy(flow);proxy_flow.set('id','FacetOut_'+flow.get('id'));proxy_flow.set('targetRef',proxy_id);fragment_flows.append(proxy_flow)
            elif target in chosen and source in nodes:
                proxy_id='FacetStart_'+flow.get('id');proxy=ET.Element(f'{{{MODEL}}}startEvent',id=proxy_id,name='Продолжение: '+(nodes[source].get('name') or source));fragment.append(proxy)
                proxy_flow=copy.deepcopy(flow);proxy_flow.set('id','FacetIn_'+flow.get('id'));proxy_flow.set('sourceRef',proxy_id)
                for condition in [child for child in list(proxy_flow) if kind(child)=='conditionExpression']: proxy_flow.remove(condition)
                fragment_flows.append(proxy_flow)
        for flow in fragment_flows:
            fragment.append(flow);source,target=flow.get('sourceRef'),flow.get('targetRef')
            source_node=next((item for item in fragment if item.get('id')==source),None);target_node=next((item for item in fragment if item.get('id')==target),None)
            if source_node is not None: ET.SubElement(source_node,f'{{{MODEL}}}outgoing').text=flow.get('id')
            if target_node is not None: ET.SubElement(target_node,f'{{{MODEL}}}incoming').text=flow.get('id')
        raw=ET.tostring(root,encoding='unicode')
        fragments.append({'block_id':group['block_id'],'xml':relayout_xml(raw),
                          'element_ids':list(group['element_ids']),
                          'flow_ids':[flow.get('id') for flow in flows if flow.get('sourceRef') in chosen or flow.get('targetRef') in chosen]})
    connections={}
    for flow in flows:
        source_group,target_group=assignments.get(flow.get('sourceRef')),assignments.get(flow.get('targetRef'))
        if source_group and target_group and source_group!=target_group:
            connections.setdefault((source_group,target_group),[]).append({'id':flow.get('id'),'name':flow.get('name',''),
                'source_element':flow.get('sourceRef'),'target_element':flow.get('targetRef')})
    nested=sum(1 for element in process.iter() if element is not process and kind(element) in NODES)
    return fragments,[{'source_id':source,'target_id':target,'flows':items} for (source,target),items in connections.items()],{'elements':nested,'flows':len(flows)}


def relayout_xml(xml):
    """Rebuild BPMN DI while preserving process semantics and element IDs."""
    from facet.bpmn.checker import kind, NODES, ACTIVITIES
    def local_name(element):
        return element.tag.rsplit('}', 1)[-1]

    root=ET.fromstring(xml);process=next((element for element in root.iter() if kind(element)=='process'),None)
    if process is None: raise ValueError('В BPMN нет процесса для выравнивания.')
    nodes=[element for element in process if kind(element) in NODES]
    flows=[element for element in process if kind(element)=='sequenceFlow']
    if not nodes: raise ValueError('В BPMN нет элементов для выравнивания.')
    by_id={node.get('id'):node for node in nodes if node.get('id')};incoming={identifier:[] for identifier in by_id};outgoing={identifier:[] for identifier in by_id}
    for flow in flows:
        source,target=flow.get('sourceRef'),flow.get('targetRef')
        if source in by_id and target in by_id: outgoing[source].append(target);incoming[target].append(source)
    indegree={identifier:len(incoming[identifier]) for identifier in by_id};queue=[identifier for identifier,count in indegree.items() if count==0];levels={identifier:0 for identifier in queue};ordered=[]
    while queue:
        current=queue.pop(0);ordered.append(current)
        for target in outgoing[current]:
            levels[target]=max(levels.get(target,0),levels[current]+1);indegree[target]-=1
            if indegree[target]==0: queue.append(target)
    if len(ordered)!=len(by_id):
        levels={identifier:0 for identifier,node in by_id.items() if kind(node)=='startEvent' or not incoming[identifier]};queue=list(levels)
        while queue:
            current=queue.pop(0)
            for target in outgoing[current]:
                if target not in levels: levels[target]=levels[current]+1;queue.append(target)
        for identifier in by_id: levels.setdefault(identifier,max(levels.values(),default=0)+1)
    columns={}
    for identifier in by_id: columns.setdefault(levels[identifier],[]).append(identifier)
    rows={}
    for level in sorted(columns):
        column=columns[level];desired=[sum(rows[parent] for parent in incoming[identifier] if parent in rows)/max(1,len([p for p in incoming[identifier] if p in rows])) for identifier in column]
        order=sorted(range(len(column)),key=lambda index:desired[index]);placed={};last=None
        for index in order:
            row=desired[index] if last is None else max(desired[index],last+1);placed[index]=row;last=row
        shift=(sum(desired)/len(desired)-sum(placed.values())/len(placed)) if placed else 0
        for index,identifier in enumerate(column): rows[identifier]=placed[index]+shift
    min_row=min(rows.values(),default=0);positions={}
    for identifier,node in by_id.items():
        node_kind=kind(node);activity=node_kind in ACTIVITIES;width=150 if activity else (52 if 'Gateway' in node_kind else 38);height=76 if activity else (52 if 'Gateway' in node_kind else 38)
        positions[identifier]=(65+levels[identifier]*265,70+(rows[identifier]-min_row)*150,width,height)
    # ``kind`` intentionally recognises only semantic BPMN elements, so DI
    # elements must be matched by their local XML name.  Otherwise the old
    # diagram remains beside the new one and duplicates every visual id.
    for diagram in [element for element in root if local_name(element)=='BPMNDiagram']:
        root.remove(diagram)
    used_ids={element.get('id') for element in root.iter() if element.get('id')}
    def visual_id(base):
        candidate=base;index=2
        while candidate in used_ids:
            candidate=f'{base}_{index}';index+=1
        used_ids.add(candidate)
        return candidate
    diagram=ET.SubElement(root,f'{{{DI}}}BPMNDiagram',id=visual_id('Diagram_layout'))
    plane=ET.SubElement(diagram,f'{{{DI}}}BPMNPlane',id=visual_id('Plane_layout'),bpmnElement=process.get('id'))
    for identifier in by_id:
        x,y,width,height=positions[identifier];shape=ET.SubElement(plane,f'{{{DI}}}BPMNShape',id=visual_id(identifier+'_di'),bpmnElement=identifier);ET.SubElement(shape,f'{{{DC}}}Bounds',x=str(x),y=str(y),width=str(width),height=str(height))
    routes=_flow_routes(positions,[(flow.get('sourceRef'),flow.get('targetRef')) for flow in flows],levels)
    for flow,points in zip(flows,routes):
        source,target=flow.get('sourceRef'),flow.get('targetRef')
        if source not in positions or target not in positions: continue
        edge=ET.SubElement(plane,f'{{{DI}}}BPMNEdge',id=visual_id(flow.get('id')+'_di'),bpmnElement=flow.get('id'))
        for x,y in points: ET.SubElement(edge,f'{{{WAY}}}waypoint',x=str(x),y=str(y))
    return ET.tostring(root,encoding='unicode')


def builtins():
    recipes = [
        ('registration', 'Регистрация пользователя', 'Создать аккаунт и подтвердить контакт пользователя.', ['Проверить данные', 'Подтвердить почту', 'Активировать аккаунт'], ['Некорректные данные не создают аккаунт.', 'Неподтверждённый адрес не даёт доступа к аккаунту.', 'Повторное подтверждение не создаёт второй аккаунт.'], 'Сервис аккаунтов'),
        ('payment', 'Оплата заказа', 'Принять оплату и отразить результат в заказе.', ['Проверить заказ', 'Запросить оплату', 'Подтвердить результат'], ['Сумма и валюта совпадают с заказом.', 'Повторный запрос с тем же ключом не создаёт второй платёж.', 'Статус «Оплачен» устанавливается только после подтверждения провайдера.'], 'Платёжный провайдер'),
        ('approval', 'Согласование заявки', 'Передать заявку ответственному и зафиксировать решение.', ['Проверить заявку', 'Рассмотреть заявку', 'Зафиксировать решение'], ['Заявка содержит все обязательные поля.', 'Решение принимает назначенный согласующий.', 'Автор получает решение и комментарий согласующего.'], 'Сервис заявок'),
    ]
    result = []
    for identifier, title, goal, tasks, criteria, service in recipes:
        block = new_block(title)
        block.update(description=goal, owner='Бизнес-аналитик', bpmn=process_xml(title, tasks), requirements='\n'.join(criteria))
        actors = [{'id':'user','name':'Пользователь'}, {'id':'app','name':'Приложение'}, {'id':'service','name':service}]
        block['uml'] = {'participants':actors, 'messages':[
            {'id':'m1','from':'user','to':'app','text':title,'kind':'call'},
            {'id':'m2','from':'app','to':'service','text':'Обработать запрос','kind':'call'},
            {'id':'m3','from':'service','to':'app','text':'Результат обработки','kind':'return'},
            {'id':'m4','from':'app','to':'user','text':'Показать результат','kind':'return'}]}
        block['element_details'] = []
        block['requirement_items'] = []
        for i, (task, criterion) in enumerate(zip(tasks, criteria)):
            block['element_details'].append({'element_id':f'Task_{i}', 'description':task, 'requirements':criterion, 'acceptance':criterion, 'uml':{'participants':copy.deepcopy(actors), 'messages':[
                {'id':'request','from':'app','to':'service','text':task,'kind':'call'},
                {'id':'response','from':'service','to':'app','text':'Результат шага','kind':'return'}]}})
            block['requirement_items'].append({'id':f'{identifier}-{i}', 'title':task, 'text':criterion, 'status':'draft', 'elements':[f'Task_{i}']})
        result.append({'id':identifier, 'name':title, 'description':goal+' Базовый путь — исключения нужно дополнить.', 'block':block, 'builtin':True})
    return result


class Templates:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS block_templates (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, block TEXT NOT NULL)')

    def list(self, user):
        with self.store.connect() as db:
            rows = db.execute('SELECT id,name,block FROM block_templates WHERE user_id=? ORDER BY rowid DESC', (user,)).fetchall()
        return builtins()+[dict(id=i, name=n, block=json.loads(b), description='Личный шаблон', builtin=False) for i,n,b in rows]

    def save(self, user, name, block):
        if not isinstance(name, str) or not name.strip() or len(name)>200:
            raise ValueError('Укажите название шаблона до 200 символов.')
        block = copy.deepcopy(block)
        # Это новый черновик; согласования и актуальность не переносятся.
        block.update(name=name.strip(), status='draft', owner='')
        for detail in block.get('element_details', []):
            detail.pop('uml_review', None)
        for item in block.get('requirement_items', []):
            item['status'] = 'draft'
        project = new_project(); project['blocks'] = [block]; validate_project(project)
        identifier = uuid.uuid4().hex
        with self.store.connect() as db:
            if db.execute('SELECT COUNT(*) FROM block_templates WHERE user_id=?', (user,)).fetchone()[0]>=100:
                raise ValueError('В личной библиотеке уже 100 шаблонов.')
            db.execute('INSERT INTO block_templates VALUES (?,?,?,?)', (identifier,user,name.strip(),json.dumps(block, ensure_ascii=False)))
        return {'id':identifier}
