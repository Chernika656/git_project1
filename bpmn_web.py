"""Операции веб-редактора над BPMN. Использует существующий анализатор и DI-редактор."""
from dataclasses import asdict
import math
import re
from uuid import uuid4
from xml.dom import minidom
from checker import BPMN, MAX_BYTES, NODES, check_bytes
from diagram import load_diagram, Shape, Edge, ARTIFACTS
from editor import move_shape, updated_xml, route


def analyze(xml):
    data = xml.encode('utf-8')
    report = check_bytes(data).to_dict()
    return {'report': report, 'diagram': asdict(load_diagram(data)), 'xml': xml}


def empty_xml():
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<definitions xmlns="{BPMN}" id="Definitions_1" targetNamespace="urn:project-workspace"><process id="Process_1" isExecutable="false"/></definitions>'


def edit(xml, action):
    data = (xml or empty_xml()).encode('utf-8')
    report = check_bytes(data)
    if any(i.code in ('INVALID_XML', 'NOT_BPMN', 'FILE_TOO_LARGE', 'DUPLICATE_ID', 'MISSING_ID') for i in report.issues):
        raise ValueError('Сначала исправьте XML и идентификаторы элементов.')
    diagram = load_diagram(data)
    op = action.get('op')
    identifier = action.get('id', '')
    if op == 'move':
        dx, dy = action.get('dx'), action.get('dy')
        if any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 100000 for n in (dx, dy)):
            raise ValueError('Некорректное перемещение.')
        if not move_shape(diagram, identifier, dx, dy):
            raise ValueError('Элемент нельзя переместить в эту позицию.')
        return updated_xml(data, diagram).decode('utf-8')
    doc = minidom.parseString(data)
    root = doc.documentElement
    nodes = {el.getAttribute('id'): el for el in doc.getElementsByTagName('*') if el.namespaceURI == BPMN and el.hasAttribute('id')}
    processes = doc.getElementsByTagNameNS(BPMN, 'process')
    if not processes:
        raise ValueError('В документе нет процесса.')
    def make(local):
        prefix = processes[0].prefix
        return doc.createElementNS(BPMN, f'{prefix}:{local}' if prefix else local)
    def lane_set(process):
        return next((child for child in process.childNodes if child.nodeType==child.ELEMENT_NODE
                     and child.namespaceURI==BPMN and child.localName=='laneSet'),None)
    if op == 'add_pool':
        name=action.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>200:
            raise ValueError('Укажите название участника (до 200 символов).')
        collaborations=doc.getElementsByTagNameNS(BPMN,'collaboration')
        collaboration=collaborations[0] if collaborations else make('collaboration')
        if not collaborations:
            collaboration.setAttribute('id','Collaboration_'+uuid4().hex[:12])
            anchor=next((child for child in root.childNodes if child.nodeType==child.ELEMENT_NODE
                         and child.namespaceURI!=BPMN),None)
            root.insertBefore(collaboration,anchor) if anchor else root.appendChild(collaboration)
        participants=list(collaboration.getElementsByTagNameNS(BPMN,'participant'))
        represented={item.getAttribute('processRef') for item in participants}
        for process in processes:
            if process.getAttribute('id') not in represented:
                participant=make('participant');participant.setAttribute('id','Participant_'+uuid4().hex[:12])
                participant.setAttribute('name',process.getAttribute('name') or 'Основной участник')
                participant.setAttribute('processRef',process.getAttribute('id'))
                collaboration.appendChild(participant)
                process_ids={child.getAttribute('id') for child in process.getElementsByTagName('*') if child.hasAttribute('id')}
                visible=[shape for shape in diagram.shapes if shape.element_id in process_ids]
                if visible:
                    x=min(shape.x for shape in visible)-55;y=min(shape.y for shape in visible)-55
                    right=max(shape.x+shape.width for shape in visible)+45
                    bottom=max(shape.y+shape.height for shape in visible)+55
                else:x,y,right,bottom=75,45,675,245
                diagram.shapes.insert(0,Shape(participant.getAttribute('id'),'participant',participant.getAttribute('name'),x,y,max(600,right-x),max(200,bottom-y)))
        top=max((shape.y+shape.height for shape in diagram.shapes),default=200)+95
        left=min((shape.x for shape in diagram.shapes),default=75)
        process=make('process');process_id='Process_'+uuid4().hex[:12]
        process.setAttribute('id',process_id);process.setAttribute('isExecutable','false')
        root.insertBefore(process,collaboration)
        participant=make('participant');participant_id='Participant_'+uuid4().hex[:12]
        participant.setAttribute('id',participant_id);participant.setAttribute('name',name.strip())
        participant.setAttribute('processRef',process_id);collaboration.appendChild(participant)
        diagram.shapes.append(Shape(participant_id,'participant',name.strip(),left,top,700,210))
        for local,label,x,w,h in [('startEvent','Начало',left+65,42,42),('task','Действие',left+215,150,80),('endEvent','Конец',left+480,42,42)]:
            node=make(local);node.setAttribute('id','Node_'+uuid4().hex[:12]);node.setAttribute('name',label)
            process.appendChild(node)
            diagram.shapes.append(Shape(node.getAttribute('id'),local,label,x,top+85,w,h))
        steps=diagram.shapes[-3:]
        for source,target in zip(steps,steps[1:]):
            flow=make('sequenceFlow');flow_id='Flow_'+uuid4().hex[:12]
            flow.setAttribute('id',flow_id);flow.setAttribute('sourceRef',source.element_id);flow.setAttribute('targetRef',target.element_id)
            process.appendChild(flow)
            diagram.edges.append(Edge(flow_id,'sequenceFlow','',route(source,target),source_id=source.element_id,target_id=target.element_id))
        xml_with_di=updated_xml(doc.toxml(encoding='utf-8'),diagram)
        placed=minidom.parseString(xml_with_di)
        for plane in placed.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/DI','BPMNPlane'):
            plane.setAttribute('bpmnElement',collaboration.getAttribute('id'))
        return placed.toxml(encoding='utf-8').decode('utf-8')
    if op == 'add_lane':
        process=nodes.get(action.get('process_id')) if action.get('process_id') else processes[0]
        name=action.get('name')
        if process not in processes or not isinstance(name,str) or not name.strip() or len(name)>200:
            raise ValueError('Укажите процесс и название дорожки (до 200 символов).')
        lanes=lane_set(process)
        if lanes is None:
            lanes=make('laneSet');lanes.setAttribute('id','LaneSet_'+uuid4().hex[:12])
            anchor=next((child for child in process.childNodes if child.nodeType==child.ELEMENT_NODE
                         and child.namespaceURI==BPMN and child.localName not in ('extensionElements','auditing','monitoring','property','laneSet')),None)
            process.insertBefore(lanes,anchor) if anchor else process.appendChild(lanes)
        lane=make('lane');lane_id='Lane_'+uuid4().hex[:12]
        lane.setAttribute('id',lane_id);lane.setAttribute('name',name.strip());lanes.appendChild(lane)
        scope_ids={child.getAttribute('id') for child in process.childNodes
                   if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName in NODES | ARTIFACTS}
        scope_ids.update(child.getAttribute('id') for child in lanes.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='lane')
        visible=[shape for shape in diagram.shapes if shape.element_id in scope_ids and shape.element_id!=lane_id]
        x=min((shape.x for shape in visible),default=100)-40
        y=max((shape.y+shape.height for shape in visible),default=100)+40
        width=max(600,max((shape.x+shape.width for shape in visible),default=x+560)-x+40)
        participant=next((item for item in doc.getElementsByTagNameNS(BPMN,'participant')
                          if item.getAttribute('processRef')==process.getAttribute('id')),None)
        pool=next((shape for shape in diagram.shapes if participant and shape.element_id==participant.getAttribute('id')),None)
        if pool:
            needed_bottom=y+170+35
            following=sorted((shape for shape in diagram.shapes if shape.kind=='participant' and shape.y>pool.y),key=lambda shape:shape.y)
            shift=max(0,needed_bottom+25-following[0].y) if following else 0
            if shift:
                for shape in following:move_shape(diagram,shape.element_id,0,shift)
            pool.width=max(pool.width,x+width-pool.x+35)
            pool.height=max(pool.height,needed_bottom-pool.y)
        diagram.shapes.append(Shape(lane_id,'lane',name.strip(),x,y,width,170))
        return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
    if op == 'assign_lane':
        node=nodes.get(identifier);target_id=action.get('lane_id','')
        name=action.get('name')
        if not node or node.localName not in NODES-{'boundaryEvent'} or node.parentNode not in processes:
            raise ValueError('Выберите действие процесса для дорожки.')
        if not isinstance(name,str) or len(name)>300 or not isinstance(target_id,str):
            raise ValueError('Некорректное название или дорожка.')
        process=node.parentNode
        lanes=lane_set(process)
        candidates=[child for child in lanes.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='lane'] if lanes else []
        process_ids={child.getAttribute('id') for child in process.childNodes
                     if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName in NODES}
        lane_ids={item.getAttribute('id') for item in candidates}
        participant=next((item for item in doc.getElementsByTagNameNS(BPMN,'participant')
                          if item.getAttribute('processRef')==process.getAttribute('id')),None)
        pool=next((item for item in diagram.shapes if participant and item.element_id==participant.getAttribute('id')),None)
        target=next((item for item in candidates if item.getAttribute('id')==target_id),None)
        if target_id and target is None: raise ValueError('Дорожка не найдена в этом процессе.')
        shape=next((item for item in diagram.shapes if item.element_id==identifier),None)
        if shape is None: raise ValueError('Действие отсутствует на схеме.')
        for lane in candidates:
            for ref in list(lane.childNodes):
                if ref.nodeType==ref.ELEMENT_NODE and ref.namespaceURI==BPMN and ref.localName=='flowNodeRef' and ref.firstChild and ref.firstChild.nodeValue==identifier:
                    lane.removeChild(ref)
        if target:
            ref=make('flowNodeRef');ref.appendChild(doc.createTextNode(identifier));target.appendChild(ref)
            lane_shape=next((item for item in diagram.shapes if item.element_id==target_id),None)
            if lane_shape is None: raise ValueError('Дорожка отсутствует на схеме.')
            if shape.lane_id!=target_id:
                occupied=[item for item in diagram.shapes if item.lane_id==target_id and item.element_id!=identifier]
                x=max((item.x+item.width+30 for item in occupied),default=lane_shape.x+45)
                y=lane_shape.y+max(25,(lane_shape.height-shape.height)/2)
                shape.lane_id=''
                move_shape(diagram,identifier,x-shape.x,y-shape.y)
                lane_shape.width=max(lane_shape.width,shape.x+shape.width-lane_shape.x+35)
                lane_shape.height=max(lane_shape.height,shape.y+shape.height-lane_shape.y+25)
                if pool:
                    pool.width=max(pool.width,shape.x+shape.width-pool.x+35)
                    pool.height=max(pool.height,shape.y+shape.height-pool.y+35)
            shape.lane_id=target_id
        else:
            if shape.lane_id:
                lane_shapes=[item for item in diagram.shapes if item.element_id in lane_ids]
                top=min((item.y for item in lane_shapes),default=shape.y)
                right=max((item.x+item.width for item in diagram.shapes if item.element_id in process_ids and item.element_id!=identifier and not item.lane_id),default=(pool.x+30 if pool else shape.x))
                shape.lane_id=''
                move_shape(diagram,identifier,right+40-shape.x,max(pool.y+40 if pool else 60,top-shape.height-35)-shape.y)
                if pool:pool.width=max(pool.width,shape.x+shape.width-pool.x+35)
            shape.lane_id=''
        node.setAttribute('name',name)
        shape.name=name
        return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
    if op == 'rename':
        if identifier not in nodes:
            raise ValueError('Элемент не найден.')
        name = action.get('name')
        if not isinstance(name, str) or len(name) > 300:
            raise ValueError('Название должно быть короче 300 символов.')
        if nodes[identifier].localName == 'textAnnotation':
            node=nodes[identifier]
            for child in list(node.childNodes):
                if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='text':
                    node.removeChild(child)
            text=make('text');text.appendChild(doc.createTextNode(name));node.appendChild(text)
        else:
            nodes[identifier].setAttribute('name', name)
        for shape in diagram.shapes:
            if shape.element_id==identifier: shape.name=name
    elif op == 'configure_ad_hoc':
        node=nodes.get(identifier)
        name=action.get('name','')
        ordering=action.get('ad_hoc_ordering','Parallel')
        condition=action.get('ad_hoc_completion','')
        cancel=action.get('ad_hoc_cancel_remaining',True)
        if not node or node.localName!='adHocSubProcess' or not isinstance(name,str) or len(name)>300:
            raise ValueError('Выберите свободный подпроцесс и корректное название.')
        if ordering not in ('Parallel','Sequential') or not isinstance(condition,str) or len(condition)>1000 or type(cancel) is not bool:
            raise ValueError('Проверьте порядок действий и условие завершения.')
        node.setAttribute('name',name)
        node.setAttribute('ordering',ordering)
        node.setAttribute('cancelRemainingInstances','true' if cancel else 'false')
        completion=next((child for child in node.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='completionCondition'),None)
        if completion: node.removeChild(completion)
        if condition.strip():
            completion=make('completionCondition');completion.appendChild(doc.createTextNode(condition.strip()))
            node.appendChild(completion)
    elif op == 'expand':
        node=nodes.get(identifier)
        shape=next((item for item in diagram.shapes if item.element_id==identifier),None)
        if not node or node.localName not in ('subProcess','transaction','adHocSubProcess') or not shape:
            raise ValueError('Выберите подпроцесс на схеме.')
        shape.expanded=True
        shape.width=max(shape.width,440)
        shape.height=max(shape.height,250)
        visible={item.element_id:item for item in diagram.shapes}
        cursor=shape.x+35
        for child in node.childNodes:
            if child.nodeType!=child.ELEMENT_NODE or child.namespaceURI!=BPMN or child.localName not in NODES | ARTIFACTS:
                continue
            child_id=child.getAttribute('id')
            if not child_id: continue
            item=visible.get(child_id)
            if item:
                cursor=max(cursor,item.x+item.width+45)
                continue
            width,height=(42,42) if child.localName.endswith('Event') else (56,56) if child.localName.endswith('Gateway') else (95,115) if child.localName in ('dataObject','dataObjectReference') else (180,100) if child.localName=='textAnnotation' else (150,80)
            label=child.getAttribute('name')
            if child.localName=='textAnnotation':
                label=''.join(grandchild.firstChild.data for grandchild in child.childNodes if grandchild.nodeType==grandchild.ELEMENT_NODE and grandchild.namespaceURI==BPMN and grandchild.localName=='text' and grandchild.firstChild)
            item=Shape(child_id,child.localName,label,cursor,shape.y+95,width,height)
            diagram.shapes.append(item);visible[child_id]=item;cursor+=width+45
        shape.width=max(shape.width,cursor-shape.x+25)
        shape.height=max(shape.height,*(item.y+item.height-shape.y+35 for item in visible.values() if item.element_id!=identifier and shape.x<=item.x<shape.x+shape.width and shape.y<=item.y<shape.y+shape.height))
        existing_edges={item.element_id for item in diagram.edges}
        for child in node.childNodes:
            if child.nodeType!=child.ELEMENT_NODE or child.namespaceURI!=BPMN or child.localName!='sequenceFlow':
                continue
            flow_id=child.getAttribute('id');source=visible.get(child.getAttribute('sourceRef'));target=visible.get(child.getAttribute('targetRef'))
            if flow_id and flow_id not in existing_edges and source and target:
                diagram.edges.append(Edge(flow_id,'sequenceFlow',child.getAttribute('name'),route(source,target),source_id=source.element_id,target_id=target.element_id))
    elif op == 'add':
        node_kind = action.get('kind')
        if node_kind not in ('startEvent', 'endEvent', 'intermediateCatchEvent', 'intermediateThrowEvent', 'boundaryEvent',
                             'task', 'userTask', 'serviceTask', 'manualTask', 'scriptTask',
                             'businessRuleTask', 'sendTask', 'receiveTask', 'subProcess', 'transaction', 'adHocSubProcess', 'callActivity',
                             'exclusiveGateway', 'inclusiveGateway', 'parallelGateway', 'eventBasedGateway',
                             'complexGateway','dataObject','textAnnotation'):
            raise ValueError('Неподдерживаемый тип элемента.')
        triggered = action.get('triggered_by_event', False)
        if type(triggered) is not bool or (triggered and node_kind != 'subProcess'):
            raise ValueError('Событийным может быть только подпроцесс.')
        container_id=action.get('container_id') or ''
        container=nodes.get(container_id) if container_id else processes[0]
        if not container or container.localName not in ('process','subProcess','transaction','adHocSubProcess'):
            raise ValueError('Выберите процесс или раскрытый подпроцесс для нового элемента.')
        if container.localName!='process' and not any(shape.element_id==container_id and shape.expanded for shape in diagram.shapes):
            raise ValueError('Подпроцесс свёрнут. Сначала раскройте его на схеме.')
        if container.getAttribute('triggeredByEvent') == 'true' and node_kind == 'startEvent':
            raise ValueError('У событийного подпроцесса уже есть начальное событие.')
        if container.localName == 'adHocSubProcess' and node_kind in ('startEvent','endEvent'):
            raise ValueError('Свободный подпроцесс не содержит начальных и конечных событий.')
        identifier = 'Node_' + uuid4().hex[:12]
        node = make(node_kind); node.setAttribute('id', identifier)
        if node_kind == 'eventBasedGateway':
            instantiate = action.get('instantiate', False)
            gateway_type = action.get('event_gateway_type', 'Exclusive')
            if type(instantiate) is not bool or gateway_type not in ('Exclusive', 'Parallel'):
                raise ValueError('Выберите корректный режим событийного шлюза.')
            if gateway_type == 'Parallel' and not instantiate:
                raise ValueError('Параллельный событийный шлюз должен запускать процесс.')
            if instantiate and container.localName != 'process':
                raise ValueError('Запускающий событийный шлюз добавляется в основной процесс.')
            if instantiate: node.setAttribute('instantiate', 'true')
            if gateway_type == 'Parallel': node.setAttribute('eventGatewayType', 'Parallel')
        receive_instantiate = action.get('receive_instantiate', False)
        if type(receive_instantiate) is not bool or (receive_instantiate and node_kind != 'receiveTask'):
            raise ValueError('Запуск сообщением доступен только для задачи получения.')
        if receive_instantiate:
            if container.localName != 'process':
                raise ValueError('Задача получения запускает только основной процесс.')
            node.setAttribute('instantiate', 'true')
        event_kind = action.get('event', '')
        if event_kind not in ('', 'message', 'signal', 'timer', 'error', 'escalation', 'terminate', 'conditional', 'link', 'cancel', 'compensate') or (event_kind and not node_kind.endswith('Event')):
            raise ValueError('Неподдерживаемый тип события.')
        if event_kind == 'link' and node_kind not in ('intermediateCatchEvent','intermediateThrowEvent'):
            raise ValueError('Ссылка BPMN используется только между промежуточными событиями.')
        if event_kind == 'conditional' and node_kind not in ('startEvent','intermediateCatchEvent','boundaryEvent'):
            raise ValueError('Условие может начинать процесс или ожидаться в потоке/на границе действия.')
        if event_kind == 'terminate' and node_kind != 'endEvent':
            raise ValueError('Маркер завершения всех веток доступен только для конечного события.')
        if event_kind == 'timer' and node_kind not in ('startEvent','intermediateCatchEvent','boundaryEvent'):
            raise ValueError('Таймер может начинать процесс или ожидаться в потоке/на границе действия.')
        if event_kind == 'error' and node_kind not in ('boundaryEvent','endEvent'):
            raise ValueError('Ошибка BPMN создаётся как граничное или конечное событие.')
        if event_kind == 'escalation' and node_kind not in ('boundaryEvent','intermediateThrowEvent','endEvent'):
            raise ValueError('Эскалация BPMN создаётся на границе действия или как отправляющее/конечное событие.')
        if event_kind == 'compensate' and node_kind != 'intermediateThrowEvent':
            raise ValueError('Ручной сигнал компенсации добавляется как промежуточное отправляющее событие.')
        trigger_event=action.get('trigger_event', '')
        if triggered:
            if trigger_event not in ('message','signal','timer','conditional','error','escalation'):
                raise ValueError('Выберите событие, запускающее подпроцесс.')
            if type(action.get('interrupting', True)) is not bool:
                raise ValueError('Выберите режим прерывания событийного подпроцесса.')
            if trigger_event == 'error' and not action.get('interrupting', True):
                raise ValueError('Событие ошибки должно прерывать основной процесс.')
        transaction_scope=None
        if event_kind == 'cancel' and node_kind == 'endEvent':
            transaction_scope=nodes.get(action.get('scope'))
            if not transaction_scope or transaction_scope.localName!='transaction' or transaction_scope.parentNode is not processes[0]:
                raise ValueError('Конечное событие отмены должно находиться внутри транзакции.')
        elif event_kind == 'cancel' and node_kind != 'boundaryEvent':
            raise ValueError('Отмена BPMN доступна внутри транзакции или на её границе.')
        attached = ''
        if node_kind == 'boundaryEvent':
            attached = action.get('attached_to')
            host = nodes.get(attached)
            if not event_kind or not host or host.parentNode.localName not in ('process','subProcess','transaction','adHocSubProcess') or host.localName not in (
                    'task','userTask','serviceTask','manualTask','scriptTask','businessRuleTask',
                    'sendTask','receiveTask','subProcess','transaction','adHocSubProcess','callActivity'):
                raise ValueError('Граничное событие должно быть привязано к действию и иметь тип.')
            if container_id and host.parentNode is not container:
                raise ValueError('Граничное событие и действие должны находиться в одном подпроцессе.')
            container=host.parentNode
            if type(action.get('interrupting', True)) is not bool:
                raise ValueError('Выберите режим прерывания события.')
            if event_kind == 'error' and not action.get('interrupting', True):
                raise ValueError('Граничное событие ошибки должно прерывать действие.')
            if event_kind == 'cancel' and (host.localName != 'transaction' or not action.get('interrupting', True)):
                raise ValueError('Отмена должна прерывать транзакцию BPMN.')
            node.setAttribute('attachedToRef', attached)
            if not action.get('interrupting', True):
                node.setAttribute('cancelActivity', 'false')
        if event_kind:
            definition = make(event_kind + 'EventDefinition')
            definition.setAttribute('id', 'EventDef_' + uuid4().hex[:12])
            if event_kind == 'link':
                link_name=action.get('link_name')
                if not isinstance(link_name,str) or not link_name.strip() or len(link_name)>100:
                    raise ValueError('Укажите название ссылки BPMN (до 100 символов).')
                link_name=link_name.strip()
                if node_kind == 'intermediateCatchEvent' and any(
                    existing.parentNode is container and existing.localName == 'intermediateCatchEvent'
                    and any(child.localName == 'linkEventDefinition' and child.getAttribute('name') == link_name
                            for child in existing.childNodes if child.nodeType == child.ELEMENT_NODE)
                    for existing in nodes.values()):
                    raise ValueError('Принимающее событие с таким названием ссылки уже есть в процессе.')
                definition.setAttribute('name', link_name)
            if event_kind == 'timer':
                duration=action.get('duration')
                match=re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?',duration) if isinstance(duration,str) and len(duration)<=40 else None
                seconds=sum(int(value or 0)*unit for value,unit in zip(match.groups(),(86400,3600,60,1))) if match else 0
                if not 0<seconds<=31536000:
                    raise ValueError('Укажите длительность таймера ISO 8601, например PT15M или P1DT2H (до года).')
                expression=make('timeDuration');expression.appendChild(doc.createTextNode(duration));definition.appendChild(expression)
            if event_kind == 'conditional':
                condition=action.get('condition')
                if not isinstance(condition,str) or not condition.strip() or len(condition)>1000:
                    raise ValueError('Опишите условие события (до 1000 символов).')
                expression=make('condition');expression.appendChild(doc.createTextNode(condition.strip()));definition.appendChild(expression)
            node.appendChild(definition)
        name = action.get('name', '')
        if not isinstance(name, str) or len(name) > 300:
            raise ValueError('Слишком длинное название.')
        if node_kind == 'textAnnotation':
            text=make('text');text.appendChild(doc.createTextNode(name));node.appendChild(text)
        else: node.setAttribute('name', name)
        multi_count = action.get('multi_instance_count')
        multi_completion = action.get('multi_instance_completion', '')
        standard_loop = action.get('standard_loop', False)
        standard_condition = action.get('standard_loop_condition', '')
        standard_maximum = action.get('standard_loop_maximum')
        standard_test_before = action.get('standard_loop_test_before', False)
        if type(standard_loop) is not bool or type(standard_test_before) is not bool or not isinstance(standard_condition, str) or len(standard_condition) > 1000:
            raise ValueError('Некорректное условие цикла.')
        if standard_loop and multi_count not in (None, ''):
            raise ValueError('Выберите один тип повторения действия.')
        if not isinstance(multi_completion, str) or len(multi_completion) > 1000:
            raise ValueError('Условие завершения должно быть текстом до 1000 символов.')
        if multi_count not in (None, ''):
            sequential = action.get('multi_instance_sequential', False)
            if triggered or node_kind not in ('task','userTask','serviceTask','manualTask','scriptTask',
                                 'businessRuleTask','sendTask','receiveTask','subProcess','transaction','callActivity') or type(multi_count) is not int or not 1 <= multi_count <= 20 or type(sequential) is not bool:
                raise ValueError('Повторение доступно для задач и обычных подпроцессов: от 1 до 20 экземпляров.')
            loop = make('multiInstanceLoopCharacteristics')
            loop.setAttribute('isSequential', 'true' if sequential else 'false')
            cardinality = make('loopCardinality')
            cardinality.appendChild(doc.createTextNode(str(multi_count)))
            loop.appendChild(cardinality)
            if multi_completion.strip():
                completion = make('completionCondition')
                completion.appendChild(doc.createTextNode(multi_completion.strip()))
                loop.appendChild(completion)
            node.appendChild(loop)
        elif multi_completion.strip():
            raise ValueError('Для условия завершения задайте количество экземпляров.')
        if standard_loop:
            if triggered or node_kind not in ('task','userTask','serviceTask','manualTask','scriptTask',
                                 'businessRuleTask','sendTask','receiveTask','subProcess','transaction','callActivity') or (standard_maximum not in (None, '') and (type(standard_maximum) is not int or not 1 <= standard_maximum <= 20)) or (not standard_condition.strip() and standard_maximum in (None, '')):
                raise ValueError('Для цикла действия укажите условие или предел от 1 до 20 повторов.')
            loop = make('standardLoopCharacteristics')
            loop.setAttribute('testBefore', 'true' if standard_test_before else 'false')
            if standard_maximum not in (None, ''):
                loop.setAttribute('loopMaximum', str(standard_maximum))
            if standard_condition.strip():
                condition = make('loopCondition')
                condition.appendChild(doc.createTextNode(standard_condition.strip()))
                loop.appendChild(condition)
            node.appendChild(loop)
        elif standard_condition.strip() or standard_maximum not in (None, '') or standard_test_before:
            raise ValueError('Сначала выберите обычный цикл.')
        if node_kind == 'callActivity':
            called = action.get('called_element', '')
            if not isinstance(called, str) or len(called) > 200:
                raise ValueError('Некорректный вызываемый процесс.')
            if called:
                available = {process.getAttribute('id') for process in processes[1:]}
                if called not in available:
                    raise ValueError('Вызываемый процесс должен быть указан в этой BPMN-схеме.')
                node.setAttribute('calledElement', called)
        if node_kind in ('subProcess','transaction'):
            if triggered: node.setAttribute('triggeredByEvent','true')
            start=make('startEvent');start.setAttribute('id','Start_'+uuid4().hex[:12]);start.setAttribute('name','Начало подпроцесса')
            if triggered:
                start.setAttribute('name','Событие: '+trigger_event)
                if not action.get('interrupting', True): start.setAttribute('isInterrupting','false')
                trigger_definition=make(trigger_event+'EventDefinition')
                trigger_definition.setAttribute('id','EventDef_'+uuid4().hex[:12])
                if trigger_event == 'timer':
                    duration=action.get('duration')
                    match=re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?',duration) if isinstance(duration,str) and len(duration)<=40 else None
                    seconds=sum(int(value or 0)*unit for value,unit in zip(match.groups(),(86400,3600,60,1))) if match else 0
                    if not 0<seconds<=31536000:
                        raise ValueError('Укажите длительность таймера ISO 8601, например PT15M (до года).')
                    expression=make('timeDuration');expression.appendChild(doc.createTextNode(duration));trigger_definition.appendChild(expression)
                if trigger_event == 'conditional':
                    condition=action.get('condition')
                    if not isinstance(condition,str) or not condition.strip() or len(condition)>1000:
                        raise ValueError('Опишите условие события (до 1000 символов).')
                    expression=make('condition');expression.appendChild(doc.createTextNode(condition.strip()));trigger_definition.appendChild(expression)
                start.appendChild(trigger_definition)
            end=make('endEvent');end.setAttribute('id','End_'+uuid4().hex[:12]);end.setAttribute('name','Конец подпроцесса')
            flow=make('sequenceFlow');flow.setAttribute('id','Flow_'+uuid4().hex[:12]);flow.setAttribute('sourceRef',start.getAttribute('id'));flow.setAttribute('targetRef',end.getAttribute('id'))
            node.appendChild(start);node.appendChild(end);node.appendChild(flow)
        if node_kind == 'adHocSubProcess':
            ad_hoc_condition = action.get('ad_hoc_completion', '')
            ad_hoc_ordering = action.get('ad_hoc_ordering', 'Parallel')
            if not isinstance(ad_hoc_condition, str) or len(ad_hoc_condition) > 1000 or ad_hoc_ordering not in ('Parallel','Sequential'):
                raise ValueError('Укажите корректное условие и порядок свободного подпроцесса.')
            node.setAttribute('ordering', ad_hoc_ordering)
            starter = make('task');starter.setAttribute('id','Task_'+uuid4().hex[:12]);starter.setAttribute('name','Первое действие')
            node.appendChild(starter)
            if ad_hoc_condition.strip():
                completion = make('completionCondition')
                completion.appendChild(doc.createTextNode(ad_hoc_condition.strip()))
                node.appendChild(completion)
        if transaction_scope:
            children=[child for child in transaction_scope.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN]
            starts=[child for child in children if child.localName=='startEvent']
            ends=[child for child in children if child.localName=='endEvent']
            flows=[child for child in children if child.localName=='sequenceFlow']
            if len(starts)!=1 or len(ends)!=1 or len(flows)!=1 or flows[0].getAttribute('sourceRef')!=starts[0].getAttribute('id') or flows[0].getAttribute('targetRef')!=ends[0].getAttribute('id'):
                raise ValueError('Автоматическая ветка отмены доступна только для новой транзакции без изменений внутри.')
            gateway=make('exclusiveGateway');gateway.setAttribute('id','Gateway_'+uuid4().hex[:12]);gateway.setAttribute('name','Результат транзакции')
            flows[0].setAttribute('sourceRef',gateway.getAttribute('id'))
            added_flows=[]
            for source,target in ((starts[0],gateway),(gateway,node)):
                flow=make('sequenceFlow');flow.setAttribute('id','Flow_'+uuid4().hex[:12]);flow.setAttribute('sourceRef',source.getAttribute('id'));flow.setAttribute('targetRef',target.getAttribute('id'));transaction_scope.appendChild(flow);added_flows.append(flow)
            transaction_scope.appendChild(gateway)
            transaction_scope.appendChild(node)
            transaction_shape=next((shape for shape in diagram.shapes if shape.element_id==transaction_scope.getAttribute('id')),None)
            start_shape=next((shape for shape in diagram.shapes if shape.element_id==starts[0].getAttribute('id')),None)
            end_shape=next((shape for shape in diagram.shapes if shape.element_id==ends[0].getAttribute('id')),None)
            if transaction_shape and start_shape and end_shape:
                gateway_shape=Shape(gateway.getAttribute('id'),'exclusiveGateway',gateway.getAttribute('name'),transaction_shape.x+175,transaction_shape.y+99,56,56)
                cancel_shape=Shape(identifier,node_kind,name,transaction_shape.x+305,transaction_shape.y+180,42,42)
                diagram.shapes.extend((gateway_shape,cancel_shape))
                existing=next((edge for edge in diagram.edges if edge.element_id==flows[0].getAttribute('id')),None)
                if existing:
                    existing.source_id=gateway_shape.element_id;existing.points=route(gateway_shape,end_shape)
                by_id={shape.element_id:shape for shape in (start_shape,gateway_shape,cancel_shape)}
                for added in added_flows:
                    source=by_id[added.getAttribute('sourceRef')];target=by_id[added.getAttribute('targetRef')]
                    diagram.edges.append(Edge(added.getAttribute('id'),'sequenceFlow','',route(source,target),source_id=source.element_id,target_id=target.element_id))
            return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
        completion = next((child for child in container.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='completionCondition'),None) if container.localName=='adHocSubProcess' else None
        first_artifact=next((child for child in container.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName in ('textAnnotation','association','group')),None)
        anchor=(first_artifact or completion) if node_kind!='textAnnotation' else completion
        container.insertBefore(node,anchor) if anchor else container.appendChild(node)
        x, y = action.get('x', 100), action.get('y', 100)
        parent_shape=next((shape for shape in diagram.shapes if shape.element_id==container.getAttribute('id')),None) if container.localName in ('subProcess','transaction','adHocSubProcess') else None
        pool_shape=None
        if container.localName=='process':
            participant=next((item for item in doc.getElementsByTagNameNS(BPMN,'participant')
                              if item.getAttribute('processRef')==container.getAttribute('id')),None)
            pool_shape=next((shape for shape in diagram.shapes if participant and shape.element_id==participant.getAttribute('id')),None)
            if pool_shape:
                sibling_ids={child.getAttribute('id') for child in container.childNodes
                             if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child is not node}
                siblings=[shape for shape in diagram.shapes if shape.element_id in sibling_ids]
                x=max((shape.x+shape.width for shape in siblings),default=pool_shape.x+55)+40
                y=pool_shape.y+80
        if parent_shape and not attached:
            direct_ids={child.getAttribute('id') for child in container.childNodes
                        if child.nodeType==child.ELEMENT_NODE and child is not node}
            previous=[shape for shape in diagram.shapes if shape.element_id in direct_ids and not shape.attached_to]
            x=max((shape.x+shape.width for shape in previous),default=parent_shape.x+35)+40
            y=parent_shape.y+95
        if attached:
            shape = next((item for item in diagram.shapes if item.element_id == attached), None)
            if not shape:
                raise ValueError('На схеме не найдено действие для события.')
            x, y = shape.x + shape.width / 2 - 21, shape.y + shape.height - 21
        if any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 100000 for n in (x, y)):
            raise ValueError('Некорректные координаты.')
        w, h = (42, 42) if node_kind.endswith('Event') else (56, 56) if node_kind.endswith('Gateway') else (440, 250) if node_kind in ('subProcess','transaction','adHocSubProcess') else (95, 115) if node_kind=='dataObject' else (180, 100) if node_kind=='textAnnotation' else (150, 80)
        shape=Shape(identifier,node_kind,name,x,y,w,h,expanded=node_kind in ('subProcess','transaction','adHocSubProcess'),attached_to=attached)
        diagram.shapes.append(shape)
        if (parent_shape or pool_shape) and not attached and not triggered and node_kind not in ('startEvent','endEvent','boundaryEvent','eventBasedGateway','dataObject','textAnnotation'):
            children=[child for child in container.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN]
            ends=[child for child in children if child.localName=='endEvent']
            flows=[child for child in children if child.localName=='sequenceFlow']
            incoming=[flow for flow in flows if len(ends)==1 and flow.getAttribute('targetRef')==ends[0].getAttribute('id')]
            if len(incoming)==1:
                previous_id=incoming[0].getAttribute('sourceRef')
                previous_node=next((item for item in children if item.getAttribute('id')==previous_id),None)
                outgoing=[flow for flow in flows if flow.getAttribute('sourceRef')==previous_id]
            else:
                previous_node=None;outgoing=[]
            if previous_node and previous_node.localName!='eventBasedGateway' and len(outgoing)==1:
                previous_shape=next((item for item in diagram.shapes if item.element_id==previous_id),None)
                end_shape=next((item for item in diagram.shapes if item.element_id==ends[0].getAttribute('id')),None)
                old_edge=next((item for item in diagram.edges if item.element_id==incoming[0].getAttribute('id')),None)
                if previous_shape and end_shape and old_edge:
                    shape.x=previous_shape.x+previous_shape.width+45
                    end_shape.x=max(end_shape.x,shape.x+shape.width+65)
                    incoming[0].setAttribute('targetRef',identifier)
                    old_edge.target_id=identifier;old_edge.points=route(previous_shape,shape)
                    next_flow=make('sequenceFlow');next_flow.setAttribute('id','Flow_'+uuid4().hex[:12]);next_flow.setAttribute('sourceRef',identifier);next_flow.setAttribute('targetRef',ends[0].getAttribute('id'));container.appendChild(next_flow)
                    for reference in ends[0].childNodes:
                        if reference.nodeType==reference.ELEMENT_NODE and reference.localName=='incoming' and reference.namespaceURI==BPMN and reference.firstChild and reference.firstChild.nodeValue==incoming[0].getAttribute('id'):
                            reference.firstChild.nodeValue=next_flow.getAttribute('id')
                    diagram.edges.append(Edge(next_flow.getAttribute('id'),'sequenceFlow','',route(shape,end_shape),source_id=identifier,target_id=end_shape.element_id))
        if parent_shape and not attached:
            parent_shape.width=max(parent_shape.width,shape.x+shape.width-parent_shape.x+35,
                                   *(item.x+item.width-parent_shape.x+35 for item in diagram.shapes if item.element_id in {child.getAttribute('id') for child in container.childNodes if child.nodeType==child.ELEMENT_NODE}))
            parent_shape.height=max(parent_shape.height,shape.y+shape.height-parent_shape.y+35)
        if pool_shape and not attached:
            pool_shape.width=max(pool_shape.width,shape.x+shape.width-pool_shape.x+40)
            pool_shape.height=max(pool_shape.height,shape.y+shape.height-pool_shape.y+40)
        if node_kind in ('subProcess','transaction'):
            begin=Shape(start.getAttribute('id'),'startEvent',start.getAttribute('name'),shape.x+45,shape.y+105,42,42)
            finish=Shape(end.getAttribute('id'),'endEvent',end.getAttribute('name'),shape.x+w-87,shape.y+105,42,42)
            diagram.shapes.extend((begin,finish))
            diagram.edges.append(Edge(flow.getAttribute('id'),'sequenceFlow','',route(begin,finish),
                                      source_id=begin.element_id,target_id=finish.element_id))
        if node_kind == 'adHocSubProcess':
            diagram.shapes.append(Shape(starter.getAttribute('id'),'task',starter.getAttribute('name'),shape.x+45,shape.y+105,150,80))
    elif op == 'connect':
        source, target = nodes.get(action.get('source')), nodes.get(action.get('target'))
        shapes = {s.element_id:s for s in diagram.shapes}
        if source is None or target is None:
            raise ValueError('Выберите два элемента процесса.')
        a, b = source.getAttribute('id'), target.getAttribute('id')
        if a not in shapes or b not in shapes or shapes[a].kind in ('participant', 'lane') or shapes[b].kind in ('participant', 'lane'):
            raise ValueError('Выберите два элемента процесса.')
        def enclosing_process(node):
            while node and node is not root:
                if node.namespaceURI==BPMN and node.localName=='process':return node
                node=node.parentNode
            return None
        source_process,target_process=enclosing_process(source),enclosing_process(target)
        if source_process is not target_process and source_process and target_process:
            if source.localName not in NODES or target.localName not in NODES:
                raise ValueError('Сообщение связывает действия или события разных участников.')
            collaboration=next(iter(doc.getElementsByTagNameNS(BPMN,'collaboration')),None)
            refs={item.getAttribute('processRef') for item in collaboration.getElementsByTagNameNS(BPMN,'participant')} if collaboration else set()
            if source_process.getAttribute('id') not in refs or target_process.getAttribute('id') not in refs:
                raise ValueError('Для связи сообщений сначала создайте пулы обоих участников.')
            flow=make('messageFlow');flow_id='MessageFlow_'+uuid4().hex[:12]
            flow.setAttribute('id',flow_id);flow.setAttribute('sourceRef',a);flow.setAttribute('targetRef',b)
            collaboration.appendChild(flow)
            diagram.edges.append(Edge(flow_id,'messageFlow','',route(shapes[a],shapes[b]),source_id=a,target_id=b))
            return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
        if source.parentNode is not target.parentNode or source.parentNode.localName not in ('process','subProcess','transaction','adHocSubProcess'):
            raise ValueError('Поток последовательности связывает элементы внутри одного процесса.')
        if source.localName in ('dataObject','dataObjectReference','textAnnotation') or target.localName in ('dataObject','dataObjectReference','textAnnotation'):
            if a==b:
                raise ValueError('Артефакт нельзя связать с самим собой.')
            association=make('association');association_id='Association_'+uuid4().hex[:12]
            association.setAttribute('id',association_id)
            association.setAttribute('sourceRef',a);association.setAttribute('targetRef',b)
            association.setAttribute('associationDirection','None')
            parent=source.parentNode
            completion=next((child for child in parent.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='completionCondition'),None) if parent.localName=='adHocSubProcess' else None
            parent.insertBefore(association,completion) if completion else parent.appendChild(association)
            diagram.edges.append(Edge(association_id,'association','',route(shapes[a],shapes[b]),source_id=a,target_id=b))
            return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
        if source.localName == 'endEvent' or target.localName in ('startEvent','boundaryEvent'):
            raise ValueError('Поток не может выходить из завершения или входить в начало/граничное событие.')
        if target.localName == 'eventBasedGateway' and target.getAttribute('instantiate') == 'true':
            raise ValueError('Запускающий событийный шлюз не принимает входящие потоки.')
        if target.localName == 'receiveTask' and target.getAttribute('instantiate') == 'true':
            raise ValueError('Задача получения, запускающая процесс, не принимает входящие потоки.')
        if any(node.localName == 'subProcess' and node.getAttribute('triggeredByEvent') == 'true'
               for node in (source,target)):
            raise ValueError('Событийный подпроцесс не соединяется с основным потоком.')
        if source.localName == 'eventBasedGateway' and target.localName not in ('intermediateCatchEvent','receiveTask'):
            raise ValueError('После шлюза событий ожидается промежуточное событие или задача получения сообщения.')
        sequence_flows = list(doc.getElementsByTagNameNS(BPMN, 'sequenceFlow'))
        target_incoming = [flow for flow in sequence_flows if flow.getAttribute('targetRef') == b]
        if source.localName == 'eventBasedGateway':
            if target_incoming:
                raise ValueError('У события после шлюза может быть только один входящий поток — от этого шлюза.')
            if target.localName == 'intermediateCatchEvent':
                triggers = {child.localName for child in target.childNodes
                            if child.nodeType == child.ELEMENT_NODE and child.namespaceURI == BPMN}
                if not triggers.intersection({'messageEventDefinition', 'signalEventDefinition',
                                              'timerEventDefinition', 'conditionalEventDefinition',
                                              'multipleEventDefinition', 'eventDefinitionRef'}):
                    raise ValueError('После шлюза выберите сообщение, сигнал, таймер или условие.')
            else:
                if any(node.localName == 'boundaryEvent' and node.getAttribute('attachedToRef') == b
                       for node in nodes.values()):
                    raise ValueError('Задача получения после шлюза не может иметь граничное событие.')
            existing_targets = [nodes.get(flow.getAttribute('targetRef')) for flow in sequence_flows
                                if flow.getAttribute('sourceRef') == a]
            has_receive = target.localName == 'receiveTask' or any(
                node is not None and node.localName == 'receiveTask' for node in existing_targets)
            has_message = any(node is not None and node.localName == 'intermediateCatchEvent' and any(
                child.nodeType == child.ELEMENT_NODE and child.localName == 'messageEventDefinition'
                for child in node.childNodes) for node in [target, *existing_targets])
            if has_receive and has_message:
                raise ValueError('В одном шлюзе нельзя смешивать событие сообщения и задачу получения.')
        elif any(nodes.get(flow.getAttribute('sourceRef')) is not None and
                 nodes[flow.getAttribute('sourceRef')].localName == 'eventBasedGateway'
                 for flow in target_incoming):
            raise ValueError('У события после шлюза не может быть другого входящего потока.')
        identifier = 'Flow_' + uuid4().hex[:12]
        flow = make('sequenceFlow')
        for key, value in [('id', identifier), ('sourceRef', a), ('targetRef', b)]:
            flow.setAttribute(key, value)
        parent=source.parentNode
        completion=next((child for child in parent.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName=='completionCondition'),None) if parent.localName=='adHocSubProcess' else None
        first_artifact=next((child for child in parent.childNodes if child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN and child.localName in ('textAnnotation','association','group')),None)
        anchor=first_artifact or completion
        parent.insertBefore(flow,anchor) if anchor else parent.appendChild(flow)
        for parent, local in [(source, 'outgoing'), (target, 'incoming')]:
            ref = make(local); ref.appendChild(doc.createTextNode(identifier)); parent.appendChild(ref)
        diagram.edges.append(Edge(identifier, 'sequenceFlow', '', route(shapes[a], shapes[b]), source_id=a, target_id=b))
    elif op == 'delete':
        node = nodes.get(identifier)
        if node is None or node.localName=='process':
            raise ValueError('Выберите элемент схемы для удаления.')
        if node.localName=='lane':
            if any(child.nodeType==child.ELEMENT_NODE and child.namespaceURI==BPMN for child in node.childNodes):
                raise ValueError('Сначала перенесите действия из дорожки.')
            parent=node.parentNode;parent.removeChild(node)
            if not any(child.nodeType==child.ELEMENT_NODE for child in parent.childNodes):
                parent.parentNode.removeChild(parent)
            for visual in list(doc.getElementsByTagName('*')):
                if visual.getAttribute('bpmnElement')==identifier and visual.parentNode: visual.parentNode.removeChild(visual)
            diagram.shapes=[shape for shape in diagram.shapes if shape.element_id!=identifier]
            return updated_xml(doc.toxml(encoding='utf-8'),diagram).decode('utf-8')
        if node.localName == 'startEvent' and node.parentNode.getAttribute('triggeredByEvent') == 'true':
            raise ValueError('Начальное событие обязательно для событийного подпроцесса.')
        removed = {identifier}
        if node.localName=='participant':
            process=nodes.get(node.getAttribute('processRef'))
            if process is None or process.localName!='process' or len(processes)<2:
                raise ValueError('Нельзя удалить последний процесс схемы.')
            removed.add(process.getAttribute('id'))
            removed |= {child.getAttribute('id') for child in process.getElementsByTagName('*') if child.hasAttribute('id')}
        if node.localName in ('subProcess','transaction','adHocSubProcess'):
            removed |= {child.getAttribute('id') for child in node.getElementsByTagName('*') if child.hasAttribute('id')}
        removed |= {k for k,v in nodes.items() if v.getAttribute('attachedToRef') in removed}
        removed |= {k for k,v in nodes.items() if v.getAttribute('sourceRef') in removed or v.getAttribute('targetRef') in removed}
        for el in list(doc.getElementsByTagName('*')):
            if el.getAttribute('id') in removed or el.getAttribute('bpmnElement') in removed:
                if el.parentNode: el.parentNode.removeChild(el)
            elif el.namespaceURI == BPMN and el.localName in ('incoming', 'outgoing', 'flowNodeRef'):
                if ''.join(n.data for n in el.childNodes if n.nodeType == n.TEXT_NODE) in removed and el.parentNode:
                    el.parentNode.removeChild(el)
            elif el.getAttribute('default') in removed:
                el.removeAttribute('default')
        diagram.shapes = [s for s in diagram.shapes if s.element_id not in removed]
        diagram.edges = [e for e in diagram.edges if e.element_id not in removed]
    else:
        raise ValueError('Неизвестная операция.')
    return updated_xml(doc.toxml(encoding='utf-8'), diagram).decode('utf-8')
