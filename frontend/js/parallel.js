'use strict';
// Чистая модель: каждый токен помнит входящий поток, данные и текущую задачу.
function branchState(){return {tokens:[],serial:0,focus:null,started:false,scopes:new Map(),messages:new Map()};}
function scopeStarts(graph,scope){
 const nodes=[...graph.nodes.values()].filter(n=>n.scope===scope&&n.kind!=='boundaryEvent'&&!n.triggered);
 const incoming=new Set(graph.edges.filter(e=>graph.nodes.get(e.source)?.scope===scope&&graph.nodes.get(e.target)?.scope===scope).map(e=>e.target));
 const starters=nodes.filter(n=>n.instantiate&&['eventBasedGateway','receiveTask'].includes(n.kind)&&!incoming.has(n.id));
 const explicit=nodes.filter(n=>n.kind==='startEvent');if(explicit.length)return [...explicit,...starters];
 return nodes.filter(n=>!incoming.has(n.id)&&n.kind!=='endEvent'&&
  (n.kind!=='eventBasedGateway'||n.instantiate));
}
function scopeEnds(graph,scope){
 const outgoing=new Set(graph.edges.filter(e=>graph.nodes.get(e.source)?.scope===scope&&graph.nodes.get(e.target)?.scope===scope).map(e=>e.source));
 return [...graph.nodes.values()].filter(n=>n.scope===scope&&!n.triggered&&(n.kind==='endEvent'||!outgoing.has(n.id)&&n.kind!=='startEvent'&&n.kind!=='boundaryEvent'&&!n.kind.endsWith('Gateway')));
}
function rootStarts(graph){const called=new Set([...graph.nodes.values()].filter(n=>n.kind==='callActivity'&&graph.scopes?.has(n.called)).map(n=>n.called));return [...(graph.scopes?.values()||[])].filter(scope=>!scope.parent&&!called.has(scope.id)).flatMap(scope=>scopeStarts(graph,scope.id)).filter(n=>!graph.project||n.projectRoot);}
function unstartedRoots(graph,state){
 const started=new Set([...state.scopes.values()].filter(scope=>!scope.parent).map(scope=>scope.definition));
 return rootStarts(graph).filter(node=>!started.has(node.scope));
}
const eventNames={timer:'Таймер сработал',message:'Сообщение получено',signal:'Сигнал получен',conditional:'Условие выполнено',error:'Возникла ошибка',escalation:'Эскалация',cancel:'Отмена транзакции',compensate:'Компенсация подтверждена',terminate:'Завершить все ветки',link:'Перейти по ссылке'};
function eventLabel(node){return (node.events||[]).map(e=>e.type==='timer'&&e.duration?'Таймер '+e.duration:e.type==='conditional'&&e.condition?'Условие: '+e.condition.slice(0,120):e.type==='link'&&e.name?'Ссылка: '+e.name:eventNames[e.type]||e.type).join(' + ');}
function scopeTokens(state,token){return state.tokens.filter(t=>t.scope===token.scope);}
function reachable(graph,source,target,stop){
 const seen=new Set(),queue=[source];
 while(queue.length){const id=queue.pop();if(id===target)return true;if(id===stop||seen.has(id))continue;seen.add(id);for(const e of graph.edges)if(e.source===id)queue.push(e.target);}
 return false;
}
function incomingMessages(graph,node){return (graph.messages||[]).filter(flow=>flow.target===node.id);}
function receivesMessage(node){return node.kind==='receiveTask'||(['startEvent','intermediateCatchEvent'].includes(node.kind)&&(node.events||[]).some(event=>event.type==='message'));}
function completeMessageStep(graph,state,node){
 const inbound=incomingMessages(graph,node);
 if(receivesMessage(node)&&inbound.length){
  const pending=state.messages.get(node.id)||[];
  if(!pending.length)throw Error('Сообщение для этого действия ещё не отправлено.');
  pending.shift();if(!pending.length)state.messages.delete(node.id);
 }
 for(const flow of graph.messages||[]){
  if(flow.source!==node.id)continue;
  const pending=state.messages.get(flow.target)||[];
  if(pending.length>=64)throw Error('Очередь сообщений сценария переполнена.');
  pending.push(flow.id);state.messages.set(flow.target,pending);
 }
}
function branchOptions(graph,state,token){
 const node=graph.nodes.get(token.node),empty=message=>({next:[],consume:[],message});
 if(!node)return empty('Элемент отсутствует в схеме.');
 if(token.fault)return empty(token.fault);
 if(token.done)return {...empty('Ветка завершена.'),complete:true};
 const inbound=incomingMessages(graph,node);
 if(receivesMessage(node)&&inbound.length&&!(state.messages?.get(node.id)||[]).length)
  return {...empty('Ожидаем сообщение от другого участника. Подтвердите отправку в его ветке сценария.'),waiting:true};
 const peers=scopeTokens(state,token),outgoing=graph.edges.filter(e=>e.source===node.id),incoming=graph.edges.filter(e=>e.target===node.id);
 const available=token.pendingEvents?outgoing.filter(e=>token.pendingEvents.includes(e.id)):outgoing;
 const base={next:available,consume:[token.id],message:'Продолжить процесс.'};
 const virtual=(op,name,target=node.id)=>({...base,next:[{id:'@'+op,target,name,op}]});
 if(token.instanceOf&&((node.kind==='task'||node.kind.endsWith('Task'))||token.phase==='exit'))return virtual('multi-complete',`Завершить экземпляр ${token.instanceIndex} из ${token.instanceTotal}`);
 if(node.loop?.kind==='multi'&&!token.instanceOf&&(node.kind==='task'||node.kind.endsWith('Task')||['subProcess','transaction','callActivity','adHocSubProcess'].includes(node.kind))&&token.phase!=='exit'){
  if(token.phase==='waiting'){
   const completed=state.tokens.some(item=>item.instanceOf===token.id&&item.done);
   return completed&&node.loop.completion?
    {...virtual('multi-condition','Условие выполнено — отменить оставшиеся экземпляры'),message:`Условие завершения: ${node.loop.completion.slice(0,160)}. Подтвердите его вручную, когда оно выполнено.`}:
    {...empty('Ожидаем завершения всех экземпляров задачи.'),waiting:true};
  }
  const count=node.loop.cardinality;
  return Number.isInteger(count)&&count>=0&&count<=20?
   virtual('multi-start',count?`Начать ${count} ${node.loop.sequential?'последовательных':'параллельных'} экземпляров`:'Пропустить задачу: экземпляров 0'):
   virtual('multi-manual','Подтвердить выполнение экземпляров вручную: количество задано выражением или превышает 20');
 }
 if(node.loop?.kind==='standard'&&(node.kind==='task'||node.kind.endsWith('Task')||['subProcess','transaction','callActivity','adHocSubProcess'].includes(node.kind))&&!['exit','loop-running','waiting'].includes(token.phase)){
  const iterations=token.loopIterations||0,maximum=node.loop.maximum;
  const finish={id:'@loop-finish',target:node.id,name:'Завершить цикл',op:'loop-finish'};
  const run={id:'@loop-run',target:node.id,name:`Выполнить итерацию ${iterations+1}`,op:'loop-run'};
  const canRun=maximum===null||iterations<maximum;
  const canFinish=iterations>0||node.loop.testBefore||!canRun;
  return {...base,next:[...(canRun?[run]:[]),...(canFinish?[finish]:[])],
   message:`Цикл выполнен ${iterations} раз${node.loop.condition?' · условие: '+node.loop.condition.slice(0,120):''}. Подтвердите результат условия вручную.`};
 }
 if(node.kind==='adHocSubProcess'&&token.phase!=='exit'){
  if(token.phase!=='ad-hoc')return virtual('adhoc-start','Открыть свободный подпроцесс');
  const scope=[...state.scopes].find(([,item])=>item.adHoc&&item.owner===token.id)?.[0];
  if(!scope)return empty('Свободный подпроцесс потерял внутренние действия.');
  const children=state.tokens.filter(item=>item.scope===scope),active=children.filter(item=>!item.done);
  const enabled=scopeStarts(graph,node.id).filter(item=>item.kind==='task'||item.kind.endsWith('Task')||['subProcess','transaction','callActivity','adHocSubProcess'].includes(item.kind));
  const run=node.adHocOrdering==='Sequential'&&active.length?[]:enabled.map(item=>({id:'@adhoc-run:'+item.id,target:item.id,name:'Выполнить: '+item.name,op:'adhoc-run'}));
  const finish=children.some(item=>item.done)&&(!active.length||node.adHocCancelRemaining!==false)?[{id:'@adhoc-finish',target:node.id,name:'Подтвердить завершение свободного подпроцесса',op:'adhoc-finish'}]:[];
  return {...base,next:[...run,...finish],message:`Свободный подпроцесс: завершено ${children.filter(item=>item.done).length} действий${node.adHocCompletion?' · условие: '+node.adHocCompletion.slice(0,120):''}. Действия можно выполнять повторно; завершение подтвердите вручную.`};
 }
 if(token.phase==='waiting')return {...empty('Выполняется вложенный процесс. Ожидаем завершения его веток.'),waiting:true};
 if(['subProcess','transaction','callActivity','adHocSubProcess'].includes(node.kind)&&token.phase!=='exit'){
  const scope=node.kind==='callActivity'?node.called:node.id;
  if(node.triggered)return empty('Событийный подпроцесс запускается событием из панели процесса.');
  if(!graph.scopes?.has(scope))return virtual('opaque','Подтвердить результат внешнего процесса');
  const starts=scopeStarts(graph,scope);
  if(!starts.length)return empty('Во вложенном процессе нет доступного начального шага.');
  return {...base,message:node.kind==='transaction'?'Открыть транзакцию. Отмена и откат внешних действий выполняются вручную; Facet только показывает ветки сценария.':'Открыть вложенный процесс. После завершения вернёмся к этому шагу.',next:starts.map(n=>({id:'@enter:'+n.id,target:n.id,name:'Войти: '+n.name,op:'enter'}))};
 }
 const events=node.events||[],thrown=node.kind==='intermediateThrowEvent'||node.kind==='endEvent';
 if(events.some(e=>e.type==='terminate'))return virtual('terminate','Завершить все ветки текущего процесса');
 if(thrown&&token.phase!=='raised'&&events.some(e=>['error','cancel','escalation'].includes(e.type)))return virtual('raise',eventLabel(node));
 const link=events.find(e=>e.type==='link');
 if(link&&node.kind==='intermediateThrowEvent'){
  const matches=[...graph.nodes.values()].filter(n=>n.scope===node.scope&&n.kind==='intermediateCatchEvent'&&(n.id===link.target||(n.events||[]).some(e=>e.type==='link'&&e.name===link.name&&link.name)));
  return matches.length===1?virtual('link','Перейти: '+matches[0].name,matches[0].id):empty('Не найдено однозначное принимающее событие ссылки.');
 }
 if(node.kind==='endEvent'){
  const projectFlows=outgoing.filter(edge=>edge.project);
  if(projectFlows.length)return {...base,next:projectFlows,message:projectFlows.length>1?'Выберите следующий блок проекта.':'Перейти к следующему блоку проекта.'};
  return outgoing.length?empty('У конечного события не должно быть исходящих связей.'):virtual('finish',eventLabel(node)||'Завершить ветку');
 }
 if(!outgoing.length)return node.kind.endsWith('Gateway')?empty('Тупик: у шлюза нет исходящего перехода.'):virtual('finish',node.kind==='receiveTask'?'Подтвердить получение сообщения и завершить ветку':events.length?'Подтвердить событие и завершить ветку':'Завершить ветку');
 if(['parallelGateway','inclusiveGateway','complexGateway'].includes(node.kind)&&incoming.length>1){
  const group=incoming.map(e=>peers.find(t=>!t.done&&t.node===node.id&&t.via===e.id));
  const arrived=group.filter(Boolean);
  let wait=false;
  if(node.kind==='parallelGateway')wait=arrived.length<incoming.length;
  if(node.kind==='inclusiveGateway')wait=incoming.some((e,i)=>!group[i]&&peers.some(t=>!t.done&&!t.fault&&t.node!==node.id&&reachable(graph,t.node,e.source,node.id)));
  if(wait)return {...empty(`Ожидаем ветки: пришло ${arrived.length} из ${incoming.length}.`),waiting:true};
  if(arrived[0]?.id!==token.id)return {...empty('Ветка готова. Продолжите через карточку объединения.'),waiting:true};
  base.consume=arrived.map(t=>t.id);
  base.message=node.kind==='complexGateway'?'Сложный шлюз: вручную подтвердите условие объединения пришедших веток. Выражение BPMN не вычисляется.':'Нужные ветки пришли. Продолжить общий процесс.';
 }
 if(node.kind==='parallelGateway')return {...base,all:true};
 if(node.kind==='inclusiveGateway'||node.kind==='complexGateway')return {...base,multiple:outgoing.length>1,message:node.kind==='inclusiveGateway'?'Выберите все подходящие ветки. Условия подтверждаются вручную.':base.message.startsWith('Сложный')?base.message:'Сложный шлюз: выберите ветки вручную по условию процесса.'};
 if(node.kind==='eventBasedGateway'){
  if(node.eventGatewayType==='Parallel'&&!node.instantiate)return empty('Параллельный событийный шлюз может только запускать процесс.');
  return {...base,message:node.eventGatewayType==='Parallel'?'Подтвердите событие. Остальные события останутся в ожидании до завершения процесса.':'Выберите событие, которое произошло первым. Остальные варианты этого ожидания отменяются.',next:available.map(e=>({...e,name:eventLabel(graph.nodes.get(e.target))||graph.nodes.get(e.target).name}))};
 }
 if(node.kind==='receiveTask')return {...base,message:inbound.length?'Сообщение от другого участника получено. Подтвердите обработку.':'Подтвердите получение сообщения вручную. Сценарий не ожидает внешнюю доставку.',next:outgoing.map(e=>({...e,name:'Сообщение получено → '+(graph.nodes.get(e.target)?.name||e.name)}))};
 if(events.length)return {...base,message:inbound.length&&receivesMessage(node)?'Сообщение от другого участника получено. Подтвердите обработку.':events.some(e=>e.type==='compensate')?'Подтвердите компенсацию вручную. Facet не отменяет внешние операции.':'Ручная имитация события. Внешние сообщения и реальное время не ожидаются.',next:outgoing.map(e=>({...e,name:token.eventConfirmed?'Продолжить после события':node.kind==='intermediateThrowEvent'?'Подтвердить отправку: '+(node.name||eventLabel(node)):eventLabel(node)||e.name}))};
 if(node.kind==='exclusiveGateway')base.message='Выберите одну ветку вручную.';
 else if(outgoing.length>1)return outgoing.some(e=>e.conditional)?{...base,multiple:true,message:'Выберите потоки, условия которых выполнены.'}:{...base,all:true,message:'Все безусловные исходящие потоки запускаются параллельно.'};
 return base;
}
function addToken(state,source,overrides){const id=String(++state.serial);const t={...structuredClone(source),id,phase:null,done:false,fault:null,...overrides};state.tokens.push(t);state.focus=id;return t;}
function childScopes(state,id){const ids=new Set([id]);let changed=true;while(changed){changed=false;for(const [key,scope] of state.scopes)if(ids.has(scope.parent)&&!ids.has(key)){ids.add(key);changed=true;}}return ids;}
function cancelToken(state,token){
 const scopes=new Set();for(const [id,scope] of state.scopes)if(scope.owner===token.id)for(const child of childScopes(state,id))scopes.add(child);
 state.tokens=state.tokens.filter(t=>t.id!==token.id&&!scopes.has(t.scope));for(const id of scopes)state.scopes.delete(id);
}
function cancelInstances(state,ownerId){for(const instance of [...state.tokens].filter(token=>token.instanceOf===ownerId))cancelToken(state,instance);}
function settleScopes(state){
 let changed=true;while(changed){changed=false;for(const [id,scope] of state.scopes){
 if(!scope.owner)continue;const children=state.tokens.filter(t=>t.scope===id);if(!children.length||!children.every(t=>t.done))continue;
  if(scope.adHoc)continue;
  const owner=state.tokens.find(t=>t.id===scope.owner);state.tokens=state.tokens.filter(t=>t.scope!==id);state.scopes.delete(id);
  if(owner){for(const child of children)for(const [key,value] of child.values)owner.values.set(key,value);owner.phase=owner.loopActive?'loop-check':'exit';owner.loopActive=false;if(scope.event)owner.done=true;state.focus=owner.id;}
  changed=true;break;
 }}
}
function boundaries(graph,token){return token.done||token.phase==='exit'?[]:[...graph.nodes.values()].filter(n=>n.kind==='boundaryEvent'&&n.attached===token.node);}
function triggerBoundary(graph,state,owner,boundary){
 const activity=owner.instanceOf?state.tokens.find(token=>token.id===owner.instanceOf):owner;
 if(!activity)throw Error('Действие для граничного события недоступно.');
 if(boundary.interrupting!==false){
  cancelInstances(state,activity.id);
  cancelToken(state,activity);
 }
 addToken(state,activity,{node:boundary.id,via:null,phase:null,multi:null,instanceOf:null,pendingEvents:null,
  label:'Событие: '+boundary.name});
}
function scopeEvents(graph,state,token){
 const definition=state.scopes.get(token.scope)?.definition;
 const subs=[...graph.nodes.values()].filter(n=>n.scope===definition&&n.triggered);
 return [...graph.nodes.values()].filter(n=>n.kind==='startEvent'&&subs.some(s=>s.id===n.scope));
}
function triggerScopeEvent(graph,state,token,start){
 if(state.scopes.size>=20)throw Error('Достигнут предел вложенных процессов.');
 const sub=graph.nodes.get(start.scope),parent=token.scope;
 if(start.interrupting){const children=childScopes(state,parent);state.tokens=state.tokens.filter(t=>!children.has(t.scope));for(const id of children)if(id!==parent)state.scopes.delete(id);}
 const owner=addToken(state,token,{node:sub.id,scope:parent,phase:'waiting',instanceOf:null,multi:null,pendingEvents:null,
  label:'Событийный процесс: '+sub.name});
 const scope='scope-'+(++state.serial);state.scopes.set(scope,{definition:sub.id,parent,owner:owner.id,event:true});
 addToken(state,token,{node:start.id,scope,phase:null,instanceOf:null,multi:null,pendingEvents:null,eventConfirmed:true,label:sub.name,via:null});
}
function advanceBranch(graph,state,tokenId,choice){
 const next=structuredClone(state);
 if(!state.started){
  const start=rootStarts(graph).find(n=>n.id===choice);if(!start)throw Error('Выберите старт основного процесса.');
  next.started=true;next.scopes.set('root',{definition:start.scope,parent:null,owner:null});addToken(next,{values:new Map()},{node:start.id,scope:'root',via:null,label:'Основной процесс'});return next;
 }
 if(tokenId===null){
  const start=unstartedRoots(graph,next).find(n=>n.id===choice);
  if(!start)throw Error('Участник уже запущен или его начало недоступно.');
  if(next.scopes.size>=20||next.tokens.length>=64)throw Error('Достигнут предел одновременно запущенных процессов.');
  const scope='root-'+(++next.serial);
  next.scopes.set(scope,{definition:start.scope,parent:null,owner:null});
  addToken(next,{values:new Map()},{node:start.id,scope,via:null,label:graph.scopes.get(start.scope)?.name||'Участник процесса'});
  return next;
 }
 const token=next.tokens.find(t=>t.id===tokenId);if(!token)throw Error('Ветка уже изменилась.');
 const node=graph.nodes.get(token.node),options=branchOptions(graph,next,token);
 if(typeof choice==='string'&&choice.startsWith('@scopeevent:')){
  const start=scopeEvents(graph,next,token).find(n=>n.id===choice.slice(12));if(!start)throw Error('Событие процесса недоступно.');triggerScopeEvent(graph,next,token,start);return next;
 }
 if(typeof choice==='string'&&choice.startsWith('@boundary:')){
  const boundary=boundaries(graph,token).find(n=>n.id===choice.slice(10));if(!boundary)throw Error('Событие больше недоступно.');triggerBoundary(graph,next,token,boundary);settleScopes(next);return next;
 }
 if(!options.next.length)throw Error(options.message);
 const selected=Array.isArray(choice)?choice:[choice];
 const flows=options.all?options.next:options.next.filter(e=>selected.includes(e.id));
 if(!flows.length||(!options.multiple&&!options.all&&flows.length!==1))throw Error('Выберите допустимый переход.');
 if(flows.length>1&&flows.some(e=>e.id===node.default))throw Error('Ветка по умолчанию выбирается отдельно от остальных.');
 const action=flows[0];
 if(action.op==='multi-start'){
  const count=node.loop.cardinality;
  if(!count){token.phase='exit';return next;}
  if(next.tokens.length+(node.loop.sequential?1:count)>64)throw Error('Достигнут предел: 64 активные ветки.');
  token.phase='waiting';token.multi={total:count,sequential:node.loop.sequential};
  const launched=node.loop.sequential?1:count;
  for(let index=1;index<=launched;index++)addToken(next,token,{instanceOf:token.id,instanceIndex:index,instanceTotal:count,multi:null,phase:null,label:`${node.name} · ${index}/${count}`});
  return next;
 }
 if(action.op==='multi-manual'){token.phase='exit';return next;}
 if(action.op==='adhoc-start'){
  if(next.scopes.size>=20)throw Error('Достигнут предел вложенности процессов.');
  const scope='scope-'+(++next.serial);next.scopes.set(scope,{definition:node.id,parent:token.scope,owner:token.id,adHoc:true});token.phase='ad-hoc';return next;
 }
 if(action.op==='adhoc-run'){
  const scope=[...next.scopes].find(([,item])=>item.adHoc&&item.owner===token.id)?.[0];
  if(!scope||next.tokens.length>=64)throw Error('Свободный подпроцесс недоступен или достигнут предел веток.');
  addToken(next,token,{node:action.target,scope,phase:null,instanceOf:null,multi:null,loopActive:false,loopIterations:0,via:null,label:graph.nodes.get(action.target).name});return next;
 }
 if(action.op==='adhoc-finish'){
  const scope=[...next.scopes].find(([,item])=>item.adHoc&&item.owner===token.id)?.[0];
  if(!scope)throw Error('Свободный подпроцесс больше недоступен.');
  const children=next.tokens.filter(item=>item.scope===scope);
  if(!children.some(item=>item.done)||children.some(item=>!item.done)&&node.adHocCancelRemaining===false)throw Error('Условие завершения ещё не подтверждено.');
  for(const child of children.filter(item=>item.done))for(const [key,value] of child.values)token.values.set(key,value);
  for(const child of children)cancelToken(next,child);
  next.scopes.delete(scope);token.phase=token.loopActive?'loop-check':'exit';token.loopActive=false;next.focus=token.id;return next;
 }
 if(action.op==='multi-condition'){
  if(!node.loop?.completion||!next.tokens.some(item=>item.instanceOf===token.id&&item.done))throw Error('Условие нельзя подтвердить до завершения экземпляра.');
  cancelInstances(next,token.id);
  token.phase='exit';next.focus=token.id;return next;
 }
 if(action.op==='loop-run'){token.loopIterations=(token.loopIterations||0)+1;token.loopActive=['subProcess','transaction','callActivity','adHocSubProcess'].includes(node.kind);token.phase=token.loopActive?'loop-running':'loop-check';return next;}
 if(action.op==='loop-finish'){token.phase='exit';return next;}
 if(action.op==='multi-complete'){
  const owner=next.tokens.find(item=>item.id===token.instanceOf);
  if(!owner)throw Error('Экземпляр задачи потерял основной поток.');
  completeMessageStep(graph,next,node);
  token.done=true;
  const instances=next.tokens.filter(item=>item.instanceOf===owner.id);
  if(owner.multi.sequential&&instances.length<owner.multi.total){
   const index=instances.length+1;
   addToken(next,owner,{instanceOf:owner.id,instanceIndex:index,instanceTotal:owner.multi.total,multi:null,phase:null,label:`${node.name} · ${index}/${owner.multi.total}`});
  }else if(instances.length===owner.multi.total&&instances.every(item=>item.done)){
   next.tokens=next.tokens.filter(item=>item.instanceOf!==owner.id);
   owner.phase='exit';next.focus=owner.id;
  }
  return next;
 }
 if(node.kind==='eventBasedGateway'&&node.instantiate&&node.eventGatewayType==='Parallel'){
  const remaining=options.next.map(edge=>edge.id).filter(id=>id!==action.id);
  if(remaining.length)token.pendingEvents=remaining;
  else next.tokens=next.tokens.filter(item=>item.id!==token.id);
  addToken(next,token,{node:action.target,via:action.id,pendingEvents:null,eventConfirmed:true,label:graph.nodes.get(action.target).name});
  return next;
 }
 if(action.project){
  const consumed=next.tokens.filter(t=>options.consume.includes(t.id)),values=new Map(consumed.flatMap(t=>[...t.values]));next.tokens=next.tokens.filter(t=>!options.consume.includes(t.id));
  const scope='project-'+(++next.serial);next.scopes.set(scope,{definition:graph.nodes.get(action.target).scope,parent:null,owner:null});addToken(next,token,{node:action.target,scope,via:action.id,values,label:graph.nodes.get(action.target).blockName});return next;
 }
 if(action.op==='enter'){
  if(next.scopes.size>=20)throw Error('Достигнут предел вложенности процессов.');
  const scope='scope-'+(++next.serial);next.scopes.set(scope,{definition:graph.nodes.get(action.target).scope,parent:token.scope,owner:token.id});token.phase='waiting';addToken(next,token,{node:action.target,scope,via:null,instanceOf:null,multi:null,loopActive:false,loopIterations:0,label:node.name});return next;
 }
 if(action.op==='opaque'){token.phase=token.loopActive?'loop-check':'exit';token.loopActive=false;return next;}
 if(action.op==='finish'){completeMessageStep(graph,next,node);token.done=true;settleScopes(next);return next;}
 if(action.op==='terminate'){
  const scopes=childScopes(next,token.scope);next.tokens=next.tokens.filter(t=>!scopes.has(t.scope)||t.id===token.id);for(const id of scopes)if(id!==token.scope)next.scopes.delete(id);token.done=true;settleScopes(next);return next;
 }
 if(action.op==='link'){token.node=action.target;token.via=null;return next;}
 if(action.op==='raise'){
  const event=node.events.find(e=>['error','cancel','escalation'].includes(e.type));let scope=next.scopes.get(token.scope),handled=false;
  const handler=scopeEvents(graph,next,token).find(n=>(n.events||[]).some(e=>e.type===event.type&&(!e.ref||e.ref===event.ref)));
  if(handler){triggerScopeEvent(graph,next,token,handler);handled=true;}
  while(!handled&&scope?.owner){const owner=next.tokens.find(t=>t.id===scope.owner);const boundary=owner&&boundaries(graph,owner).find(n=>(n.events||[]).some(e=>e.type===event.type&&(!e.ref||e.ref===event.ref)));if(boundary){triggerBoundary(graph,next,owner,boundary);handled=true;break;}scope=next.scopes.get(scope.parent);}
  if((handled&&next.tokens.includes(token))||(!handled&&event.type==='escalation')){if(node.kind==='endEvent')token.done=true;else token.phase='raised';}
  else if(!handled){const scopes=childScopes(next,token.scope);next.tokens=next.tokens.filter(t=>!scopes.has(t.scope)||t.id===token.id);for(const id of scopes)if(id!==token.scope)next.scopes.delete(id);token.fault='Нет обработчика события: '+eventLabel(node)+'. Выполнение этого процесса остановлено.';}
  settleScopes(next);return next;
 }
 if(next.tokens.length-options.consume.length+flows.length>64)throw Error('Достигнут предел: 64 активные ветки.');
 completeMessageStep(graph,next,node);
 const consumed=next.tokens.filter(t=>options.consume.includes(t.id)),values=new Map(consumed.flatMap(t=>[...t.values]));
 next.tokens=next.tokens.filter(t=>!options.consume.includes(t.id));
 for(const [index,flow] of flows.entries())addToken(next,token,{node:flow.target,via:flow.id,eventConfirmed:node.kind==='eventBasedGateway',values:structuredClone(values),label:flows.length>1?`${token.label} / ${index+1}`:options.consume.length>1?'Общий процесс':token.label});
 return next;
}
function moveBranch(tokenId,choice){
 try{
  if(!walk||(!walk.project&&walk.xml!==block()?.bpmn)||walk.project&&walk.projectId!==S.project?.id)return stopWalk();
  if(walk.history.length>=200)return toast('Пройдено 200 шагов. Завершите запуск и начните новый.',true);
  const next=advanceBranch(walk.graph,walk.engine,tokenId,choice);
  walk.history.push(structuredClone(walk.engine));walk.engine=next;showWalk();
 }catch(err){toast(err.message,true);}
}
function renderParallelWalk(){
 walk.engine??=branchState();walk.history??=[];
 walk.panelMode??='side';
 const state=walk.engine,graph=walk.graph;
 const focus=state.tokens.find(t=>t.id===state.focus)||state.tokens[0];
 if(walk.project&&focus){const targetBlock=graph.nodes.get(focus.node)?.blockId;if(targetBlock&&targetBlock!==S.selected){S.selected=targetBlock;S.detailId=null;S.view='bpmn';S.element=null;S.connect=null;S.camera=null;render();}}
 if(focus){const shapes=S.analyses.get(S.selected)?.diagram.shapes||[],current=graph.nodes.get(focus.node);let target=walk.project?current?.originalId:focus.node;if(!shapes.some(s=>s.element_id===target)&&walk.project&&current?.scope)target=current.scope.slice(current.blockId.length+2);while(!walk.project&&!shapes.some(s=>s.element_id===target)&&graph.nodes.has(target))target=graph.nodes.get(target).scope;if(shapes.some(s=>s.element_id===target))focusElement(target);}
 const workspace=$('#workspace');workspace.classList.add('walking');workspace.classList.toggle('prototyping',!!walk.prototype);workspace.classList.toggle('walk-side',walk.panelMode==='side');workspace.classList.toggle('walk-window-mode',walk.panelMode==='window');
 refreshWalkHighlight();
 walk.panelCleanup?.();$('#walk-panel')?.remove();const panel=document.createElement('section');panel.id='walk-panel';panel.className=`parallel-panel ${walk.panelMode==='side'?'walk-side-panel':'walk-window-panel'}`;panel.setAttribute('aria-label',walk.prototype?'Прототип с ветками':'Сценарий с ветками');
 const done=t=>!!t.done;
 const waitingRoots=unstartedRoots(graph,state);
 const completed=state.started&&state.tokens.length&&!waitingRoots.length&&state.tokens.every(done);
 const queued=[...state.messages.values()].reduce((count,items)=>count+items.length,0);
 panel.innerHTML=`<div class="walk-heading"><span>${walk.prototype?'◈ ПРОТОТИП':walk.project?'▶ СЦЕНАРИЙ ПРОЕКТА':'▶ СЦЕНАРИЙ'} · ШАГОВ: ${walk.history.length}</span><button type="button" data-feature="walk-stop">Завершить</button></div><p role="status">${completed?'Все ветки завершены.':state.tokens.length>1?'Ветки выполняются независимо. Общий шлюз ждёт все входящие связи.':walk.project?'Проходите внутренние BPMN и переходите между блоками проекта.':'Пройдите процесс шаг за шагом.'}${queued?' · Сообщений в ожидании: '+queued+'.':''}</p><div class="branch-tabs" role="group" aria-label="Активные ветки">${state.tokens.map((t,i)=>`<button type="button" data-branch-focus="${t.id}" aria-pressed="${t.id===state.focus}">${i+1}. ${esc(graph.nodes.get(t.node)?.blockName?graph.nodes.get(t.node).blockName+' · ':'')}${esc(graph.nodes.get(t.node)?.name||t.node)}${done(t)?' ✓':branchOptions(graph,state,t).waiting?' · ждёт':''}</button>`).join('')}</div><div class="branch-cards ${state.tokens.length>2?'many-branches':''}"></div><div class="walk-buttons"><button type="button" data-feature="walk-back" ${walk.history.length?'':'disabled'}>← Назад</button><small>Назад восстанавливает состояние всех веток и переходы между блоками.</small></div>`;
 const cards=panel.querySelector('.branch-cards');
 panel.querySelector('.walk-heading').insertAdjacentHTML('beforeend',`<button type="button" class="walk-window" data-walk-mode>${walk.panelMode==='side'?'Открыть окном':'Вернуть в панель'}</button><button type="button" class="walk-window" data-walk-fullscreen>${document.fullscreenElement?'Уменьшить окно':'На весь экран'}</button>`);
 panel.querySelector('[data-walk-mode]').onclick=()=>{walk.panelMode=walk.panelMode==='side'?'window':'side';showWalk();};
 panel.querySelector('[data-walk-fullscreen]').onclick=fullscreen;
 if(waitingRoots.length)cards.innerHTML=`<div class="branch-card focused"><h3>${state.started?'Запустить ещё участника':'Выберите начало процесса'}</h3><p>Процессы участников выполняются независимо. Подтверждённая отправка по связи сообщений разблокирует принимающий шаг.</p>${waitingRoots.map(n=>`<button type="button" class="soft" data-branch-start="${esc(n.id)}">${esc(graph.scopes.get(n.scope)?.name||n.blockName||'Процесс')} · ${esc(n.name)}${eventLabel(n)?' · '+esc(eventLabel(n)):''} →</button>`).join('')}</div>`;
 for(const token of state.tokens){
  const node=graph.nodes.get(token.node),options=branchOptions(graph,state,token),card=document.createElement('article');
  card.className='branch-card'+(token.id===state.focus?' focused':'');card.dataset.branch=token.id;
  card.innerHTML=`<small class="eyebrow">${esc(walk.project?(node?.blockName||'Проект')+' · '+token.label:token.label)}</small><h3>${esc(node?.name||token.node)}</h3><p>${esc(options.message)}</p><div class="branch-actions"></div>`;
  const actions=card.querySelector('.branch-actions');
  const screen=walk.prototype?walk.screens.get(token.node):null;
  if(screen&&options.next.length===1&&!options.next[0].op&&(node.kind==='task'||node.kind.endsWith('Task'))){
   const form=document.createElement('form');form.className='prototype-screen';
   form.innerHTML=screenMarkup(screen,token.values.get(token.node)||{});
   const persist=()=>{token.values.set(token.node,Object.fromEntries(new FormData(form)));};
   form.oninput=e=>{e.target.setCustomValidity?.('');persist();};
   form.onsubmit=e=>{
    e.preventDefault();if(!form.reportValidity())return;
    for(const input of form.querySelectorAll('[required]'))if(!input.value.trim()){input.setCustomValidity('Заполните поле.');input.reportValidity();return;}
    persist();moveBranch(token.id,options.next[0].id);
   };
   card.insertBefore(form,actions);
  }else if(options.next.length){
   if(options.all)actions.innerHTML=`<button type="button" class="primary" data-branch-go="${token.id}">${options.next.length>1?'Запустить все ветки':'Продолжить общий процесс'} →</button>`;
   else if(options.multiple)actions.innerHTML=`<div class="branch-selection">${options.next.map(e=>`<label><input type="checkbox" value="${esc(e.id)}">${esc(e.name||graph.nodes.get(e.target)?.name||e.target)}${e.id===node.default?' (по умолчанию)':''}</label>`).join('')}<button type="button" class="primary" data-branch-many="${token.id}">Запустить выбранные ветки</button></div>`;
   else actions.innerHTML=options.next.map(e=>`<button type="button" class="soft" data-branch-go="${token.id}" data-flow="${esc(e.id)}">${esc(e.name||graph.nodes.get(e.target)?.name||e.target)} →</button>`).join('');
  }
  const boundary=boundaries(graph,token);if(boundary.length)card.insertAdjacentHTML('beforeend',`<details class="branch-events"><summary>События на этом шаге</summary>${boundary.map(n=>`<button type="button" data-branch-go="${token.id}" data-flow="@boundary:${esc(n.id)}">${esc(eventLabel(n)||n.name)}${n.interrupting?' · прервать шаг':''}</button>`).join('')}</details>`);
  const scopeTriggers=token.done||token.fault?[]:scopeEvents(graph,state,token);if(scopeTriggers.length)card.insertAdjacentHTML('beforeend',`<details class="branch-events"><summary>События процесса</summary>${scopeTriggers.map(n=>`<button type="button" data-branch-go="${token.id}" data-flow="@scopeevent:${esc(n.id)}">${esc(eventLabel(n)||n.name)}${n.interrupting?' · прервать процесс':''}</button>`).join('')}</details>`);
  cards.append(card);
 }
 if(walk.prototype)panel.insertAdjacentHTML('beforeend','<p class="prototype-session-note">Тестовые данные живут только в этом запуске. Внешние системы не вызываются.</p>');
 $('#workspace').append(panel);
 if(walk.panelMode==='side')attachWalkSide(panel);else attachWalkWindow(panel);
 panel.onclick=e=>{const start=e.target.closest('[data-branch-start]'),go=e.target.closest('[data-branch-go]'),many=e.target.closest('[data-branch-many]'),tab=e.target.closest('[data-branch-focus]');if(start)moveBranch(null,start.dataset.branchStart);else if(go)moveBranch(go.dataset.branchGo,go.dataset.flow);else if(many)moveBranch(many.dataset.branchMany,[...many.closest('.branch-selection').querySelectorAll('input:checked')].map(el=>el.value));else if(tab){state.focus=tab.dataset.branchFocus;showWalk();}};
}

function refreshWalkHighlight(){
 const tokens=walk?.engine?.tokens||[],graph=walk?.graph,active=new Set();
 for(const token of tokens){active.add(token.node);const node=graph?.nodes?.get(token.node);if(node?.originalId)active.add(node.originalId);}
 document.querySelectorAll('#content .node').forEach(el=>el.classList.toggle('walk-current',active.has(el.dataset.id)));
}

function attachWalkSide(panel){
 const session=walk,workspace=$('#workspace'),bar=workspace.querySelector('.workspace-bar');
 const align=()=>{if(panel.isConnected&&walk===session)workspace.style.setProperty('--walk-panel-top',bar.offsetHeight+'px');};
 const resize=new ResizeObserver(align);resize.observe(bar);resize.observe(workspace);session.panelCleanup=()=>resize.disconnect();align();
}

// Геометрия окна принадлежит запуску, а не отдельному шагу или снимку «Назад».
function attachWalkWindow(panel){
 const session=walk,workspace=$('#workspace'),header=panel.querySelector('.walk-heading');
 session.panelGeometry??={};let gesture=null,lastMode=null;
 const mode=()=>document.fullscreenElement===workspace?'fullscreen':'window';
 header.classList.add('prototype-drag-handle');header.tabIndex=0;
 header.title='Перетащите окно за заголовок. Размер меняется за края и углы.';
 header.setAttribute('aria-label','Переместить окно сценария');
 for(const direction of ['n','ne','e','se','s','sw','w','nw'])panel.insertAdjacentHTML('beforeend',`<span class="walk-resize-handle walk-resize-${direction}" data-walk-resize="${direction}" aria-hidden="true"></span>`);
 function place(value,remember=true){
  const margin=8,minY=workspace.querySelector('.workspace-bar').offsetHeight+margin;
  const width=Math.max(Math.min(340,workspace.clientWidth-margin*2),Math.min(value.width,workspace.clientWidth-margin*2));
  const height=Math.max(Math.min(220,workspace.clientHeight-minY-margin),Math.min(value.height,workspace.clientHeight-minY-margin));
  const geometry={width,height,x:Math.max(margin,Math.min(workspace.clientWidth-width-margin,value.x)),y:Math.max(minY,Math.min(workspace.clientHeight-height-margin,value.y))};
  Object.assign(panel.style,{left:geometry.x+'px',top:geometry.y+'px',right:'auto',bottom:'auto',width:geometry.width+'px',height:geometry.height+'px'});
  if(remember)session.panelGeometry[mode()]=geometry;
 }
 function restore(){
  if(!panel.isConnected||walk!==session)return;
  const current=mode();if(current!==lastMode){for(const key of ['left','top','right','bottom','width','height'])panel.style.removeProperty(key);lastMode=current;}
  const saved=session.panelGeometry[current];
  if(saved)place(saved,false);else{const p=currentGeometry();place(p);}
 }
 function currentGeometry(){const r=panel.getBoundingClientRect(),p=workspace.getBoundingClientRect();return {x:r.left-p.left-workspace.clientLeft,y:r.top-p.top-workspace.clientTop,width:r.width,height:r.height};}
 header.addEventListener('pointerdown',e=>{
  if(e.button!==0||e.target.closest('button,a,input,select'))return;
  e.preventDefault();e.stopPropagation();
  gesture={kind:'move',pointer:e.pointerId,x:e.clientX,y:e.clientY,origin:currentGeometry()};
  header.setPointerCapture(e.pointerId);header.classList.add('dragging');
 });
 header.addEventListener('pointermove',e=>{if(!gesture||gesture.kind!=='move'||e.pointerId!==gesture.pointer)return;e.preventDefault();place({...gesture.origin,x:gesture.origin.x+e.clientX-gesture.x,y:gesture.origin.y+e.clientY-gesture.y});});
 const release=()=>{gesture=null;header.classList.remove('dragging');panel.classList.remove('resizing');};
 header.addEventListener('pointerup',release);header.addEventListener('pointercancel',release);header.addEventListener('lostpointercapture',release);
 header.addEventListener('keydown',e=>{if(e.target!==header||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();e.stopPropagation();const p=currentGeometry(),step=e.shiftKey?30:10;place({...p,x:p.x+(e.key==='ArrowRight'?step:e.key==='ArrowLeft'?-step:0),y:p.y+(e.key==='ArrowDown'?step:e.key==='ArrowUp'?-step:0)});});
 panel.querySelectorAll('[data-walk-resize]').forEach(handle=>{
  handle.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();e.stopPropagation();gesture={kind:'resize',direction:handle.dataset.walkResize,pointer:e.pointerId,x:e.clientX,y:e.clientY,origin:currentGeometry()};handle.setPointerCapture(e.pointerId);panel.classList.add('resizing');});
  handle.addEventListener('pointermove',e=>{if(!gesture||gesture.kind!=='resize'||e.pointerId!==gesture.pointer)return;e.preventDefault();const dx=e.clientX-gesture.x,dy=e.clientY-gesture.y,d=gesture.direction,g={...gesture.origin};if(d.includes('e'))g.width+=dx;if(d.includes('s'))g.height+=dy;if(d.includes('w')){g.x+=dx;g.width-=dx;}if(d.includes('n')){g.y+=dy;g.height-=dy;}place(g);});
  handle.addEventListener('pointerup',release);handle.addEventListener('pointercancel',release);handle.addEventListener('lostpointercapture',release);
 });
 const resize=new ResizeObserver(restore);resize.observe(workspace);
 document.addEventListener('fullscreenchange',restore);
 session.panelCleanup=()=>{resize.disconnect();document.removeEventListener('fullscreenchange',restore);};
 restore();
}
