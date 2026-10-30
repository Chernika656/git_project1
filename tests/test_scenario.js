const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..', 'web');
const context = {structuredClone, Map, Set};
vm.createContext(context);
const parallel = fs.readFileSync(path.join(root, 'parallel.js'), 'utf8');
vm.runInContext(parallel.slice(0, parallel.indexOf('function moveBranch(')), context);
const features = fs.readFileSync(path.join(root, 'features.js'), 'utf8');
vm.runInContext(features.slice(features.indexOf('function projectScenarioGraph('), features.indexOf('function walkOptions(')), context);

function graphA() {
  const nodes = new Map([
    ['mainStart', {id:'mainStart', kind:'startEvent', scope:'Main', name:'Старт', events:[]}],
    ['call', {id:'call', kind:'callActivity', scope:'Main', called:'Child', name:'Вызов', events:[]}],
    ['mainEnd', {id:'mainEnd', kind:'endEvent', scope:'Main', name:'Конец', events:[]}],
    ['childStart', {id:'childStart', kind:'startEvent', scope:'Child', name:'Старт вызова', events:[]}],
    ['childTask', {id:'childTask', kind:'userTask', scope:'Child', name:'Внутренняя задача', events:[]}],
    ['childEnd', {id:'childEnd', kind:'endEvent', scope:'Child', name:'Конец вызова', events:[]}],
  ]);
  const edges = [['f1','mainStart','call'],['f2','call','mainEnd'],['f3','childStart','childTask'],['f4','childTask','childEnd']]
    .map(([id,source,target])=>({id,source,target}));
  return {nodes, edges, scopes:new Map([['Main',{id:'Main',parent:null}],['Child',{id:'Child',parent:null}]])};
}

const graph = graphA();
assert.deepEqual(Array.from(context.rootStarts(graph),node=>node.id), ['mainStart']);
let state = context.branchState();
state = context.advanceBranch(graph,state,null,'mainStart');
state = context.advanceBranch(graph,state,state.focus,'f1');
state = context.advanceBranch(graph,state,state.focus,'@enter:childStart');
assert.equal(state.tokens.find(token=>token.node==='call').phase,'waiting');
state = context.advanceBranch(graph,state,state.focus,'f3');
assert.equal(state.tokens.find(token=>token.node==='childTask').done,false);
state = context.advanceBranch(graph,state,state.focus,'f4');
state = context.advanceBranch(graph,state,state.focus,'@finish');
assert.equal(state.tokens.find(token=>token.node==='call').phase,'exit');

const graphB = {nodes:new Map([
  ['start',{id:'start',kind:'startEvent',scope:'Other',name:'Начало',events:[]}],
  ['end',{id:'end',kind:'endEvent',scope:'Other',name:'Конец',events:[]}],
]),edges:[{id:'f4',source:'start',target:'end'}],scopes:new Map([['Other',{id:'Other',parent:null}]])};
context.S={project:{blocks:[{id:'a',bpmn:'a'},{id:'b',bpmn:'b'}],links:[{id:'link',source:'a',target:'b'}]}};
context.processGraph=xml=>xml==='a'?graphA():graphB;
const project = context.projectScenarioGraph();
const projectEdges=project.edges.filter(edge=>edge.project);
assert.equal(projectEdges.length,1);
assert.equal(projectEdges[0].source,'a::mainEnd');
assert.equal(projectEdges[0].target,'b::start');

const implicit = {nodes:new Map([
  ['first',{id:'first',kind:'task',scope:'Implicit',name:'Первый шаг',events:[]}],
  ['last',{id:'last',kind:'userTask',scope:'Implicit',name:'Последний шаг',events:[]}],
  ['triggered',{id:'triggered',kind:'subProcess',scope:'Implicit',name:'Событийный подпроцесс',events:[],triggered:true}],
]),edges:[{id:'step',source:'first',target:'last'}],scopes:new Map([['Implicit',{id:'Implicit',parent:null}]])};
assert.deepEqual(Array.from(context.rootStarts(implicit),node=>node.id),['first']);
assert.deepEqual(Array.from(context.scopeEnds(implicit,'Implicit'),node=>node.id),['last']);
let implicitState=context.advanceBranch(implicit,context.branchState(),null,'first');
implicitState=context.advanceBranch(implicit,implicitState,implicitState.focus,'step');
assert.equal(context.branchOptions(implicit,implicitState,implicitState.tokens[0]).next[0].id,'@finish');
implicitState=context.advanceBranch(implicit,implicitState,implicitState.focus,'@finish');
assert.equal(implicitState.tokens[0].done,true);

const collaboration={nodes:new Map([
 ['buyerStart',{id:'buyerStart',kind:'startEvent',scope:'Buyer',name:'Начало покупателя',events:[]}],
 ['buyerEnd',{id:'buyerEnd',kind:'endEvent',scope:'Buyer',name:'Конец покупателя',events:[]}],
 ['sellerStart',{id:'sellerStart',kind:'startEvent',scope:'Seller',name:'Начало продавца',events:[]}],
 ['sellerEnd',{id:'sellerEnd',kind:'endEvent',scope:'Seller',name:'Конец продавца',events:[]}],
]),edges:[{id:'buyerFlow',source:'buyerStart',target:'buyerEnd'},
 {id:'sellerFlow',source:'sellerStart',target:'sellerEnd'}],
 scopes:new Map([['Buyer',{id:'Buyer',parent:null,name:'Покупатель'}],['Seller',{id:'Seller',parent:null,name:'Продавец'}]])};
let collaborationState=context.advanceBranch(collaboration,context.branchState(),null,'buyerStart');
assert.deepEqual(Array.from(context.unstartedRoots(collaboration,collaborationState),node=>node.id),['sellerStart']);
collaborationState=context.advanceBranch(collaboration,collaborationState,null,'sellerStart');
assert.equal(collaborationState.tokens.length,2);
assert.deepEqual(Array.from(context.unstartedRoots(collaboration,collaborationState),node=>node.id),[]);
assert.throws(()=>context.advanceBranch(collaboration,collaborationState,null,'sellerStart'));
const buyerToken=collaborationState.tokens.find(token=>token.node==='buyerStart');
collaborationState=context.advanceBranch(collaboration,collaborationState,buyerToken.id,'buyerFlow');
assert.equal(collaborationState.tokens.some(token=>token.node==='sellerStart'),true);

const messageScenario={nodes:new Map([
 ['senderStart',{id:'senderStart',kind:'startEvent',scope:'Sender',name:'Начало',events:[]}],
 ['send',{id:'send',kind:'sendTask',scope:'Sender',name:'Отправить заявку',events:[]}],
 ['senderEnd',{id:'senderEnd',kind:'endEvent',scope:'Sender',name:'Конец',events:[]}],
 ['receiverStart',{id:'receiverStart',kind:'startEvent',scope:'Receiver',name:'Начало',events:[]}],
 ['receive',{id:'receive',kind:'receiveTask',scope:'Receiver',name:'Получить заявку',events:[]}],
 ['receiverEnd',{id:'receiverEnd',kind:'endEvent',scope:'Receiver',name:'Конец',events:[]}],
]),edges:[['toSend','senderStart','send'],['sent','send','senderEnd'],['toReceive','receiverStart','receive'],['received','receive','receiverEnd']]
 .map(([id,source,target])=>({id,source,target})),messages:[{id:'message',source:'send',target:'receive'}],
 scopes:new Map([['Sender',{id:'Sender',parent:null}],['Receiver',{id:'Receiver',parent:null}]])};
let messageState=context.advanceBranch(messageScenario,context.branchState(),null,'receiverStart');
messageState=context.advanceBranch(messageScenario,messageState,messageState.focus,'toReceive');
const receivingToken=messageState.tokens.find(token=>token.node==='receive');
assert.equal(context.branchOptions(messageScenario,messageState,receivingToken).waiting,true);
messageState=context.advanceBranch(messageScenario,messageState,null,'senderStart');
messageState=context.advanceBranch(messageScenario,messageState,messageState.focus,'toSend');
assert.equal(context.branchOptions(messageScenario,messageState,receivingToken).waiting,true);
messageState=context.advanceBranch(messageScenario,messageState,messageState.focus,'sent');
assert.deepEqual(Array.from(messageState.messages.get('receive')),['message']);
assert.equal(context.branchOptions(messageScenario,messageState,receivingToken).waiting,undefined);
messageState=context.advanceBranch(messageScenario,messageState,receivingToken.id,'received');
assert.equal(messageState.messages.has('receive'),false);
assert.throws(()=>context.advanceBranch(messageScenario,messageState,receivingToken.id,'received'));

const nestedImplicit={nodes:new Map([
  ['root',{id:'root',kind:'startEvent',scope:'Outer',name:'Начало',events:[]}],
  ['sub',{id:'sub',kind:'subProcess',scope:'Outer',name:'Вложенный процесс',events:[]}],
  ['end',{id:'end',kind:'endEvent',scope:'Outer',name:'Конец',events:[]}],
  ['work',{id:'work',kind:'task',scope:'sub',name:'Работа внутри',events:[]}],
]),edges:[{id:'outer-a',source:'root',target:'sub'},{id:'outer-b',source:'sub',target:'end'}],
scopes:new Map([['Outer',{id:'Outer',parent:null}],['sub',{id:'sub',parent:'Outer'}]])};
let nestedState=context.advanceBranch(nestedImplicit,context.branchState(),null,'root');
nestedState=context.advanceBranch(nestedImplicit,nestedState,nestedState.focus,'outer-a');
nestedState=context.advanceBranch(nestedImplicit,nestedState,nestedState.focus,'@enter:work');
nestedState=context.advanceBranch(nestedImplicit,nestedState,nestedState.focus,'@finish');
assert.equal(nestedState.tokens.find(token=>token.node==='sub').phase,'exit');

function eventProcess(interrupting){
 const nodes=new Map([
  ['start',{id:'start',kind:'startEvent',scope:'Main',name:'Старт',events:[]}],
  ['work',{id:'work',kind:'task',scope:'Main',name:'Работа',events:[]}],
  ['end',{id:'end',kind:'endEvent',scope:'Main',name:'Конец',events:[]}],
  ['eventSub',{id:'eventSub',kind:'subProcess',scope:'Main',name:'Обработать сообщение',events:[],triggered:true}],
  ['eventStart',{id:'eventStart',kind:'startEvent',scope:'eventSub',name:'Сообщение',events:[{type:'message'}],interrupting}],
  ['eventEnd',{id:'eventEnd',kind:'endEvent',scope:'eventSub',name:'Готово',events:[]}],
 ]);
 const edges=[['main-a','start','work'],['main-b','work','end'],['event-a','eventStart','eventEnd']]
  .map(([id,source,target])=>({id,source,target}));
 return {nodes,edges,scopes:new Map([['Main',{id:'Main',parent:null}],['eventSub',{id:'eventSub',parent:'Main'}]])};
}
for(const interrupting of [false,true]){
 const graph=eventProcess(interrupting);
 let state=context.advanceBranch(graph,context.branchState(),null,'start');
 state=context.advanceBranch(graph,state,state.focus,'main-a');
 const work=state.tokens.find(token=>token.node==='work');
 state=context.advanceBranch(graph,state,work.id,'@scopeevent:eventStart');
 assert.equal(!!state.tokens.find(token=>token.node==='work'),!interrupting);
 const eventStart=state.tokens.find(token=>token.node==='eventStart');
 state=context.advanceBranch(graph,state,eventStart.id,'event-a');
 const eventEnd=state.tokens.find(token=>token.node==='eventEnd');
 state=context.advanceBranch(graph,state,eventEnd.id,'@finish');
 assert.equal(state.tokens.find(token=>token.node==='eventSub').done,true);
}

const startGateway={nodes:new Map([
 ['regular',{id:'regular',kind:'startEvent',scope:'Main',name:'Обычный старт',events:[]}],
 ['gateway',{id:'gateway',kind:'eventBasedGateway',scope:'Main',name:'Все сообщения',events:[],instantiate:true,eventGatewayType:'Parallel'}],
 ['first',{id:'first',kind:'intermediateCatchEvent',scope:'Main',name:'Первое',events:[{type:'message'}]}],
 ['second',{id:'second',kind:'intermediateCatchEvent',scope:'Main',name:'Второе',events:[{type:'message'}]}],
 ['endA',{id:'endA',kind:'endEvent',scope:'Main',name:'Конец A',events:[]}],
 ['endB',{id:'endB',kind:'endEvent',scope:'Main',name:'Конец B',events:[]}],
]),edges:[['a','gateway','first'],['b','gateway','second'],['c','first','endA'],['d','second','endB']]
 .map(([id,source,target])=>({id,source,target})),scopes:new Map([['Main',{id:'Main',parent:null}]])};
assert.deepEqual(Array.from(context.rootStarts(startGateway),node=>node.id),['regular','gateway']);
let parallelStart=context.advanceBranch(startGateway,context.branchState(),null,'gateway');
parallelStart=context.advanceBranch(startGateway,parallelStart,parallelStart.focus,'a');
assert.deepEqual(Array.from(context.branchOptions(startGateway,parallelStart,parallelStart.tokens.find(token=>token.node==='gateway')).next,edge=>edge.id),['b']);
const firstToken=parallelStart.tokens.find(token=>token.node==='first');
parallelStart=context.advanceBranch(startGateway,parallelStart,firstToken.id,'c');
parallelStart=context.advanceBranch(startGateway,parallelStart,parallelStart.tokens.find(token=>token.node==='endA').id,'@finish');
assert.equal(parallelStart.tokens.find(token=>token.node==='gateway').done,false);
parallelStart=context.advanceBranch(startGateway,parallelStart,parallelStart.tokens.find(token=>token.node==='gateway').id,'b');
assert.equal(parallelStart.tokens.some(token=>token.node==='gateway'),false);
assert.equal(parallelStart.tokens.some(token=>token.node==='second'),true);
const receiveStart=structuredClone(startGateway);
receiveStart.nodes.set('receive',{id:'receive',kind:'receiveTask',scope:'Main',name:'Получить заявку',events:[],instantiate:true});
receiveStart.edges.push({id:'received',source:'receive',target:'endA'});
assert.deepEqual(Array.from(context.rootStarts(receiveStart),node=>node.id),['regular','gateway','receive']);
let receiveState=context.advanceBranch(receiveStart,context.branchState(),null,'receive');
assert.equal(context.branchOptions(receiveStart,receiveState,receiveState.tokens[0]).next[0].name.startsWith('Сообщение получено'),true);
receiveState=context.advanceBranch(receiveStart,receiveState,receiveState.focus,'received');
assert.equal(receiveState.tokens[0].node,'endA');
const loneReceive=structuredClone(receiveStart);loneReceive.edges=loneReceive.edges.filter(edge=>edge.id!=='received');
const loneState=context.advanceBranch(loneReceive,context.branchState(),null,'receive');
assert.equal(context.branchOptions(loneReceive,loneState,loneState.tokens[0]).next[0].name.includes('получение сообщения'),true);

function multiGraph(sequential,cardinality){return {nodes:new Map([
 ['start',{id:'start',kind:'startEvent',scope:'Main',name:'Начало',events:[]}],
 ['repeat',{id:'repeat',kind:'userTask',scope:'Main',name:'Проверить заявки',events:[],loop:{kind:'multi',sequential,cardinality}}],
 ['end',{id:'end',kind:'endEvent',scope:'Main',name:'Конец',events:[]}],
]),edges:[{id:'in',source:'start',target:'repeat'},{id:'out',source:'repeat',target:'end'}],scopes:new Map([['Main',{id:'Main',parent:null}]])};}
for(const sequential of [false,true]){
 const graph=multiGraph(sequential,3);
 let state=context.advanceBranch(graph,context.branchState(),null,'start');
 state=context.advanceBranch(graph,state,state.focus,'in');
 const owner=state.tokens[0].id;
 state=context.advanceBranch(graph,state,owner,'@multi-start');
 assert.equal(state.tokens.filter(token=>token.instanceOf===owner).length,sequential?1:3);
 for(let index=1;index<=3;index++){
  const instance=state.tokens.find(token=>token.instanceOf===owner&&!token.done);
  state=context.advanceBranch(graph,state,instance.id,'@multi-complete');
  if(index<3)assert.equal(state.tokens.find(token=>token.id===owner).phase,'waiting');
 }
 assert.equal(state.tokens.length,1);
 assert.equal(state.tokens[0].phase,'exit');
 state=context.advanceBranch(graph,state,owner,'out');
 assert.equal(state.tokens[0].node,'end');
}
const dynamic=multiGraph(true,null);
let dynamicState=context.advanceBranch(dynamic,context.branchState(),null,'start');
dynamicState=context.advanceBranch(dynamic,dynamicState,dynamicState.focus,'in');
assert.equal(context.branchOptions(dynamic,dynamicState,dynamicState.tokens[0]).next[0].id,'@multi-manual');
for(const sequential of [false,true]){
 const graph=multiGraph(sequential,3);graph.nodes.get('repeat').loop.completion='Согласована хотя бы одна заявка';
 let state=context.advanceBranch(graph,context.branchState(),null,'start');
 state=context.advanceBranch(graph,state,state.focus,'in');
 const owner=state.tokens[0].id;
 state=context.advanceBranch(graph,state,owner,'@multi-start');
 assert.equal(context.branchOptions(graph,state,state.tokens.find(token=>token.id===owner)).next.length,0);
 const first=state.tokens.find(token=>token.instanceOf===owner);
 state=context.advanceBranch(graph,state,first.id,'@multi-complete');
 assert.equal(context.branchOptions(graph,state,state.tokens.find(token=>token.id===owner)).next[0].id,'@multi-condition');
 state=context.advanceBranch(graph,state,owner,'@multi-condition');
 assert.equal(state.tokens.length,1);
 assert.equal(state.tokens[0].phase,'exit');
 state=context.advanceBranch(graph,state,owner,'out');
 assert.equal(state.tokens[0].node,'end');
}

for(const early of [false,true]){
 const graph=structuredClone(nestedImplicit);
 graph.nodes.get('sub').loop={kind:'multi',sequential:false,cardinality:2,completion:early?'Готов первый экземпляр':''};
 let state=context.advanceBranch(graph,context.branchState(),null,'root');
 state=context.advanceBranch(graph,state,state.focus,'outer-a');
 const owner=state.tokens[0].id;
 state=context.advanceBranch(graph,state,owner,'@multi-start');
 const instances=state.tokens.filter(token=>token.instanceOf===owner).map(token=>token.id);
 for(const instance of instances){
  state=context.advanceBranch(graph,state,instance,'@enter:work');
  assert.equal(state.tokens.find(token=>token.id===instance).phase,'waiting');
  assert.equal(state.tokens.find(token=>token.scope!=='root').instanceOf,null);
  if(early&&instance===instances[1])break;
  const inner=state.tokens.find(token=>token.scope!=='root'&&!token.done);
  state=context.advanceBranch(graph,state,inner.id,'@finish');
  assert.equal(state.tokens.find(token=>token.id===instance).phase,'exit');
  state=context.advanceBranch(graph,state,instance,'@multi-complete');
 }
 if(early){
  assert.equal(state.scopes.size,2);
  state=context.advanceBranch(graph,state,owner,'@multi-condition');
  assert.equal(state.scopes.size,1);
 }else assert.equal(state.tokens.find(token=>token.id===owner).phase,'exit');
 assert.equal(state.tokens.length,1);
 state=context.advanceBranch(graph,state,owner,'outer-b');
 assert.equal(state.tokens[0].node,'end');
}
const interruptedSub=structuredClone(nestedImplicit);
interruptedSub.nodes.get('sub').loop={kind:'multi',sequential:false,cardinality:2};
interruptedSub.nodes.set('timeout',{id:'timeout',kind:'boundaryEvent',scope:'Outer',name:'Время истекло',events:[{type:'timer'}],attached:'sub',interrupting:true});
let interrupted=context.advanceBranch(interruptedSub,context.branchState(),null,'root');
interrupted=context.advanceBranch(interruptedSub,interrupted,interrupted.focus,'outer-a');
interrupted=context.advanceBranch(interruptedSub,interrupted,interrupted.focus,'@multi-start');
const interruptedInstance=interrupted.tokens.find(token=>token.instanceOf);
interrupted=context.advanceBranch(interruptedSub,interrupted,interruptedInstance.id,'@enter:work');
interrupted=context.advanceBranch(interruptedSub,interrupted,interruptedInstance.id,'@boundary:timeout');
assert.equal(interrupted.scopes.size,1);
assert.deepEqual(Array.from(interrupted.tokens,token=>token.node),['timeout']);

const standard=multiGraph(true,null);
standard.nodes.get('repeat').loop={kind:'standard',testBefore:false,maximum:3,condition:'Есть ещё заявки'};
let standardState=context.advanceBranch(standard,context.branchState(),null,'start');
standardState=context.advanceBranch(standard,standardState,standardState.focus,'in');
assert.deepEqual(Array.from(context.branchOptions(standard,standardState,standardState.tokens[0]).next,option=>option.id),['@loop-run']);
for(let index=1;index<=3;index++)standardState=context.advanceBranch(standard,standardState,standardState.focus,'@loop-run');
assert.deepEqual(Array.from(context.branchOptions(standard,standardState,standardState.tokens[0]).next,option=>option.id),['@loop-finish']);
standardState=context.advanceBranch(standard,standardState,standardState.focus,'@loop-finish');
standardState=context.advanceBranch(standard,standardState,standardState.focus,'out');
assert.equal(standardState.tokens[0].node,'end');

const repeatedSub=structuredClone(nestedImplicit);
repeatedSub.nodes.get('sub').loop={kind:'standard',testBefore:false,maximum:2,condition:'Есть ещё пакеты'};
let repeated=context.advanceBranch(repeatedSub,context.branchState(),null,'root');
repeated=context.advanceBranch(repeatedSub,repeated,repeated.focus,'outer-a');
const repeatedOwner=repeated.tokens[0].id;
for(let iteration=1;iteration<=2;iteration++){
 repeated=context.advanceBranch(repeatedSub,repeated,repeatedOwner,'@loop-run');
 assert.equal(context.branchOptions(repeatedSub,repeated,repeated.tokens.find(token=>token.id===repeatedOwner)).next[0].id,'@enter:work');
 repeated=context.advanceBranch(repeatedSub,repeated,repeatedOwner,'@enter:work');
 const inner=repeated.tokens.find(token=>token.scope!=='root');
 repeated=context.advanceBranch(repeatedSub,repeated,inner.id,'@finish');
 assert.equal(repeated.tokens.find(token=>token.id===repeatedOwner).phase,'loop-check');
}
assert.deepEqual(Array.from(context.branchOptions(repeatedSub,repeated,repeated.tokens[0]).next,option=>option.id),['@loop-finish']);
repeated=context.advanceBranch(repeatedSub,repeated,repeatedOwner,'@loop-finish');
repeated=context.advanceBranch(repeatedSub,repeated,repeatedOwner,'outer-b');
assert.equal(repeated.tokens[0].node,'end');

for(const interrupting of [false,true]){
 const graph=multiGraph(false,2);
 graph.nodes.set('boundary',{id:'boundary',kind:'boundaryEvent',scope:'Main',name:'Тайм-аут',events:[{type:'timer'}],attached:'repeat',interrupting});
 graph.nodes.set('timeout',{id:'timeout',kind:'endEvent',scope:'Main',name:'Конец по таймеру',events:[]});
 graph.edges.push({id:'timeout-flow',source:'boundary',target:'timeout'});
 let state=context.advanceBranch(graph,context.branchState(),null,'start');
 state=context.advanceBranch(graph,state,state.focus,'in');
 state=context.advanceBranch(graph,state,state.focus,'@multi-start');
 const instance=state.tokens.find(token=>token.instanceOf);
 state=context.advanceBranch(graph,state,instance.id,'@boundary:boundary');
 const boundary=state.tokens.find(token=>token.node==='boundary');
 assert.equal(boundary.phase,null);
 assert.equal(context.branchOptions(graph,state,boundary).next[0].id,'timeout-flow');
 assert.equal(state.tokens.some(token=>token.node==='repeat'),!interrupting);
}
const eventDuringMulti=multiGraph(false,2);
eventDuringMulti.nodes.set('eventSub',{id:'eventSub',kind:'subProcess',scope:'Main',name:'Уведомление',events:[],triggered:true});
eventDuringMulti.nodes.set('eventStart',{id:'eventStart',kind:'startEvent',scope:'eventSub',name:'Сообщение',events:[{type:'message'}],interrupting:false});
eventDuringMulti.scopes.set('eventSub',{id:'eventSub',parent:'Main'});
let duringMulti=context.advanceBranch(eventDuringMulti,context.branchState(),null,'start');
duringMulti=context.advanceBranch(eventDuringMulti,duringMulti,duringMulti.focus,'in');
duringMulti=context.advanceBranch(eventDuringMulti,duringMulti,duringMulti.focus,'@multi-start');
duringMulti=context.advanceBranch(eventDuringMulti,duringMulti,duringMulti.tokens.find(token=>token.instanceOf).id,'@scopeevent:eventStart');
assert.equal(duringMulti.tokens.find(token=>token.node==='eventSub').instanceOf,null);
assert.equal(duringMulti.tokens.find(token=>token.node==='eventStart').instanceOf,null);

const adHocGraph={nodes:new Map([
 ['start',{id:'start',kind:'startEvent',scope:'Main',name:'Начало',events:[]}],
 ['adHoc',{id:'adHoc',kind:'adHocSubProcess',scope:'Main',name:'Свободный подпроцесс',events:[],adHocOrdering:'Sequential',adHocCompletion:'Оба действия проверены',adHocCancelRemaining:false}],
 ['end',{id:'end',kind:'endEvent',scope:'Main',name:'Конец',events:[]}],
 ['first',{id:'first',kind:'userTask',scope:'adHoc',name:'Первое',events:[]}],
 ['second',{id:'second',kind:'task',scope:'adHoc',name:'Второе',events:[]}],
]),edges:[{id:'in',source:'start',target:'adHoc'},{id:'out',source:'adHoc',target:'end'}],
scopes:new Map([['Main',{id:'Main',parent:null}],['adHoc',{id:'adHoc',parent:'Main'}]])};
let adHoc=context.advanceBranch(adHocGraph,context.branchState(),null,'start');
adHoc=context.advanceBranch(adHocGraph,adHoc,adHoc.focus,'in');
const adHocOwner=adHoc.focus;
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'@adhoc-start');
assert.deepEqual(Array.from(context.branchOptions(adHocGraph,adHoc,adHoc.tokens.find(token=>token.id===adHocOwner)).next,option=>option.id),['@adhoc-run:first','@adhoc-run:second']);
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'@adhoc-run:first');
assert.deepEqual(Array.from(context.branchOptions(adHocGraph,adHoc,adHoc.tokens.find(token=>token.id===adHocOwner)).next,option=>option.id),[]);
adHoc=context.advanceBranch(adHocGraph,adHoc,adHoc.focus,'@finish');
assert.deepEqual(Array.from(context.branchOptions(adHocGraph,adHoc,adHoc.tokens.find(token=>token.id===adHocOwner)).next,option=>option.id),['@adhoc-run:first','@adhoc-run:second','@adhoc-finish']);
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'@adhoc-run:first');
adHoc=context.advanceBranch(adHocGraph,adHoc,adHoc.focus,'@finish');
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'@adhoc-run:second');
assert.equal(context.branchOptions(adHocGraph,adHoc,adHoc.tokens.find(token=>token.id===adHocOwner)).next.some(option=>option.id==='@adhoc-finish'),false);
adHoc=context.advanceBranch(adHocGraph,adHoc,adHoc.focus,'@finish');
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'@adhoc-finish');
assert.equal(adHoc.scopes.size,1);
assert.equal(adHoc.tokens.length,1);
adHoc=context.advanceBranch(adHocGraph,adHoc,adHocOwner,'out');
assert.equal(adHoc.tokens[0].node,'end');
