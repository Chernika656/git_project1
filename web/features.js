'use strict';
$('.workspace-navigation [data-view="requirements"]').insertAdjacentHTML('afterend','<button class="nav" data-view="glossary"><span>Аа</span>Словарь проекта</button>');

function glossaryBlockTerms(){
 const terms=(S.project?.glossary||[]).filter(t=>(t.blocks||[]).includes(S.selected)||(t.elements||[]).some(ref=>ref.block_id===S.selected));
 return `<section class="linked-requirements"><h3>Термины блока <span>${terms.length}</span></h3>${terms.map(t=>`<button type="button" class="term-chip" data-feature="open-term" data-term="${esc(t.id)}">Аа ${esc(t.name)}</button>`).join('')||'<p class="inspector-note">Привяжите термины в словаре проекта.</p>'}<button type="button" class="text-button" data-view="glossary">Открыть словарь ↗</button></section>`;
}
function termLinks(term){
 const blocks=(term.blocks||[]).map(id=>{const b=S.project.blocks.find(b=>b.id===id);return b?`<button type="button" class="term-chip" data-feature="term-block" data-target="${esc(id)}" title="Показать блок на карте проекта">◇ ${esc(b.name)} ↗</button>`:`<span class="missing-link">Блок недоступен: ${esc(id)}</span>`;});
 const elements=(term.elements||[]).map(ref=>{const b=S.project.blocks.find(b=>b.id===ref.block_id);if(!b)return `<span class="missing-link">Блок BPMN недоступен: ${esc(ref.block_id)}</span>`;const d=S.analyses.get(b.id)?.diagram,object=d?.shapes?.find(s=>s.element_id===ref.element_id)||d?.edges?.find(e=>e.element_id===ref.element_id);return d&&!object?`<span class="missing-link">Элемент BPMN недоступен: ${esc(b.name)} · ${esc(ref.element_id)}</span>`:`<button type="button" class="term-chip" data-feature="term-element" data-block="${esc(b.id)}" data-target="${esc(ref.element_id)}" title="Показать элемент BPMN">◇ ${esc(b.name)} · ${esc(object?.name||ref.element_id)} ↗</button>`;});
 return [...blocks,...elements].join('')||'<span class="inspector-note">Связанные блоки и элементы не выбраны</span>';
}
function renderGlossary(){
 $('#content').innerHTML=`<div class="document-view glossary-view"><div class="section-toolbar"><input id="glossary-search" aria-label="Поиск терминов" placeholder="Найти термин или определение…"><span id="glossary-count"></span></div><div id="glossary-cards" class="glossary-cards"></div></div>`;
 const draw=()=>{
  const query=$('#glossary-search').value.trim().toLocaleLowerCase();
  const all=S.project.glossary||[],terms=all.filter(t=>(t.name+' '+t.definition).toLocaleLowerCase().includes(query)).sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  $('#glossary-count').textContent=`Показано ${terms.length} из ${all.length}`;
  $('#glossary-cards').innerHTML=terms.map(t=>`<article class="term-card" data-term-id="${esc(t.id)}"><span class="term-symbol">Аа</span><h3>${esc(t.name)}</h3><p class="preserve-text">${esc(t.definition)}</p><div class="requirement-links">${termLinks(t)}</div>${canEdit()?`<button type="button" class="text-button" data-feature="edit-term" data-term="${esc(t.id)}">Изменить определение и связи</button>`:''}</article>`).join('')||`<div class="requirements-empty">${query?'Ничего не найдено. Попробуйте другой запрос.':'Добавьте первый термин — например, «Заказ», «Клиент» или «Оплачен».'}</div>`;
 };draw();$('#glossary-search').oninput=draw;
}
function focusTerm(id){
 if(S.view!=='glossary')setView('glossary');
 const search=$('#glossary-search');if(search?.value){search.value='';search.dispatchEvent(new Event('input'));}
 const card=[...document.querySelectorAll('#glossary-cards [data-term-id]')].find(item=>item.dataset.termId===id);
 if(!card)return toast('Термин больше не найден в словаре.',true);
 card.scrollIntoView({behavior:'smooth',block:'center'});card.classList.add('glossary-target');
 setTimeout(()=>card.classList.remove('glossary-target'),5000);
}
function openTerm(id){
 const t=S.project.glossary?.find(t=>t.id===id);if(!t)return;
 modal(t.name,`<p class="preserve-text">${esc(t.definition)}</p><h3>Связи с проектом</h3><div class="requirement-links">${termLinks(t)}</div>${canEdit()?`<button type="button" class="soft" data-feature="edit-term" data-term="${esc(t.id)}">Изменить</button>`:''}`,()=>{});
 $('#submit-modal').hidden=true;
}
function termDialog(id){
 if(!canEdit())return;
 const project=S.project,existing=project.glossary?.find(t=>t.id===id);
 const term=existing||{id:uid(),name:'',definition:'',blocks:[],elements:[]};
 const selectedElements=new Set((term.elements||[]).map(ref=>JSON.stringify([ref.block_id,ref.element_id])));
 const availableElements=new Set();
 const elementChoices=project.blocks.map(b=>{const d=S.analyses.get(b.id)?.diagram,objects=[...(d?.shapes||[]),...(d?.edges||[])].filter(item=>item.element_id);if(!objects.length)return '';return `<details class="term-element-group"><summary>${esc(b.name)} · ${objects.length} элементов</summary><div class="requirement-choices">${objects.map(item=>{const value=JSON.stringify([b.id,item.element_id]);availableElements.add(value);return `<label><input type="checkbox" name="elements" value="${esc(value)}" ${selectedElements.has(value)?'checked':''}>${esc(item.name||item.element_id)} <small>${esc(item.kind||'связь')}</small></label>`;}).join('')}</div></details>`;}).join('');
 const missingElements=[...selectedElements].filter(value=>!availableElements.has(value)).map(value=>`<label class="missing-link"><input type="checkbox" name="elements" value="${esc(value)}" checked>Недоступный элемент: ${esc(value)}</label>`).join('');
 modal(existing?'Изменить термин':'Новый термин',field('Термин','name',term.name)+field('Определение','definition',term.definition,'textarea')+`<h3>Где используется</h3><div class="requirement-choices">${project.blocks.map(b=>`<label><input type="checkbox" name="blocks" value="${esc(b.id)}" ${term.blocks.includes(b.id)?'checked':''}>${esc(b.name)}</label>`).join('')||'<p>Можно добавить связи после создания блоков.</p>'}${term.blocks.filter(id=>!project.blocks.some(b=>b.id===id)).map(id=>`<label class="missing-link"><input type="checkbox" name="blocks" value="${esc(id)}" checked>Недоступный блок: ${esc(id)}</label>`).join('')}</div><h3>Элементы BPMN</h3><p class="modal-note">Укажите конкретные объекты схемы. Переход из словаря откроет BPMN и выделит выбранный объект.</p>${elementChoices||'<p>В проекте пока нет элементов BPMN.</p>'}${missingElements}`,async data=>{
  if(!canEdit()||S.project!==project)throw Error('Проект изменился. Откройте термин заново.');
  const name=String(data.get('name')).trim(),definition=String(data.get('definition')).trim();
  if(!name||!definition)throw Error('Укажите термин и его определение.');
  if((project.glossary||[]).some(t=>t.id!==term.id&&t.name.trim().toLocaleLowerCase()===name.toLocaleLowerCase()))throw Error('Такой термин уже есть в словаре.');
  const updated={id:term.id,name,definition,blocks:data.getAll('blocks'),elements:data.getAll('elements').map(value=>{const [block_id,element_id]=JSON.parse(value);return {block_id,element_id};})};
  const found=project.glossary?.find(t=>t.id===term.id);
  if(found)Object.assign(found,updated);else {if((project.glossary?.length||0)>=500)throw Error('Максимум 500 терминов в проекте.');(project.glossary??=[]).push(updated);}
  if(!await save())throw Error('Термин остался в текущей сессии, но не сохранился. Экспортируйте проект перед перезагрузкой.');
  render();toast('Термин сохранён.');
 });
 $('#modal-body [name="name"]').maxLength=200;$('#modal-body [name="definition"]').maxLength=20000;
}
async function chooseBlockTemplate(){
 if(!canEdit())return toast('Выберите проект с правом редактирования.',true);
 try{
  const templates=await api('/api/templates');
  modal('Добавить блок',`<p class="modal-note">Начните с готового процесса или создайте пустой блок. В шаблонах уже связаны BPMN, UML, требования и критерии приёмки.</p><label class="field">Основа блока<select name="template" id="template-choice"><option value="">Пустой блок</option>${templates.map(t=>`<option value="${esc(t.id)}">${t.builtin?'Готовый':'Мой'} · ${esc(t.name)}</option>`).join('')}</select></label><div id="template-preview" class="linked-requirements">Свободный блок для вашего процесса.</div>${field('Название блока','name','Новый блок')}`,async data=>{
   if(!canEdit())throw Error('Нет права редактирования.');
   if(S.project.blocks.length>=200)throw Error('Максимум 200 блоков в проекте.');
   const title=String(data.get('name')).trim();if(!title)throw Error('Укажите название блока.');
   const template=templates.find(t=>t.id===data.get('template'));
   const b=template?structuredClone(template.block):{description:'',requirements:'',owner:'',bpmn:'',uml:{participants:[],messages:[]},technical:''};
   b.id=uid();b.name=title;b.status='draft';const i=S.project.blocks.length;b.x=70+(i%3)*310;b.y=100+Math.floor(i/3)*240;
   for(const d of b.element_details||[])delete d.uml_review;
   for(const r of b.requirement_items||[]){r.id=uid();r.status='draft';}
   S.project.blocks.push(b);S.selected=b.id;S.detailId=null;S.view=b.bpmn?'bpmn':'overview';S.camera=null;
   render();await save();if(b.bpmn){await analyzeBlock(b);render();}
  },'Добавить в проект');
  $('#template-choice').onchange=e=>{const t=templates.find(t=>t.id===e.target.value);$('#modal-body [name="name"]').value=t?.name||'Новый блок';$('#template-preview').innerHTML=t?`<strong>${esc(t.name)}</strong><p>${esc(t.description)}</p><small>BPMN · UML · Требований: ${t.block.requirement_items?.length||0} · Детализаций: ${t.block.element_details?.length||0}</small>`:'Свободный блок для вашего процесса.';};
 }catch(err){toast(err.message,true);}
}
function saveBlockTemplate(){
 if(!canEdit()||!block())return;
 const b=block(),projectId=S.project.id;
 modal('Сохранить блок как шаблон',`<p class="modal-note">Шаблон будет доступен вашему аккаунту в других проектах. Сохраняются схемы, описания и связи требований. Новые блоки создаются как черновики.</p>`+field('Название шаблона','name',b.name),async data=>{
  if(!await save())throw Error('Сначала сохраните изменения проекта.');
  await api('/api/templates','POST',{project_id:projectId,block_id:b.id,name:data.get('name')});toast('Шаблон сохранён. Откройте «Добавить блок», чтобы использовать его.');
 });
}
// Требования хранят ссылки на стабильные ID задач BPMN.
function taskShapes(){return (S.analyses.get(S.selected)?.diagram.shapes||[]).filter(n=>n.kind==='task'||n.kind.endsWith('Task'));}
function requirementCode(r){return 'REQ-'+r.id.slice(0,6).toUpperCase();}
function linkedRequirementPanel(id){
 const items=(block().requirement_items||[]).filter(r=>r.elements.includes(id));
 return `<section class="linked-requirements"><h3>Связанные требования <span>${items.length}</span></h3>${items.map(r=>`<details><summary><small>${esc(requirementCode(r))}</small> ${esc(r.title)}</summary><span class="role-pill">${statusNames[r.status]}</span><p class="preserve-text">${esc(r.text||'Описание пока не заполнено.')}</p></details>`).join('')||'<p class="inspector-note">Свяжите эту задачу с записью в разделе «Требования».</p>'}</section>`;
}
function renderRequirements(){
 const doc=$('.document-view');if(!doc)return;
 const shapes=taskShapes(),items=block().requirement_items||[];
 doc.insertAdjacentHTML('beforeend',`<section class="requirements-register"><div class="section-card-heading"><div><div class="eyebrow">СВЯЗЬ С ПРОЦЕССОМ</div><h2>Реестр требований</h2></div><button type="button" class="primary" data-feature="new-requirement" ${canEdit()?'':'disabled'}>+ Требование</button></div><p>Каждая запись может относиться к нескольким задачам BPMN. Общие заметки выше сохраняются отдельно.</p>${items.map(r=>`<article class="requirement-card"><div class="section-card-heading"><small>${esc(requirementCode(r))}</small><span class="role-pill">${statusNames[r.status]}</span></div><h3>${esc(r.title)}</h3><p class="preserve-text">${esc(r.text||'Добавьте подробное описание.')}</p><div class="requirement-links">${r.elements.map(id=>{const n=shapes.find(n=>n.element_id===id);return n?`<button type="button" data-feature="requirement-target" data-target="${esc(id)}">◇ ${esc(n.name||id)} ↗</button>`:`<span class="missing-link">Задача недоступна: ${esc(id)}</span>`;}).join('')||'<span class="inspector-note">Пока не связано с задачами</span>'}</div>${canEdit()?`<button type="button" class="text-button" data-feature="edit-requirement" data-requirement="${esc(r.id)}">Изменить требование и связи</button>`:''}</article>`).join('')||'<div class="requirements-empty">Добавьте первое требование и укажите задачи, которые его реализуют.</div>'}</section>`);
}
function requirementDialog(id){
 if(!canEdit())return;
 const b=block(),old=b.requirement_items?.find(r=>r.id===id),shapes=taskShapes();
 const r=old||{id:uid(),title:'',text:'',status:'draft',elements:[]};
 modal(old?'Изменить требование':'Новое требование',field('Краткое название','title',r.title)+field('Описание и ожидаемый результат','text',r.text,'textarea')+`<label class="field">Статус<select name="status">${optionList(statusNames,r.status)}</select></label><h3>Задачи BPMN</h3><div class="requirement-choices">${shapes.map(n=>`<label><input type="checkbox" name="elements" value="${esc(n.element_id)}" ${r.elements.includes(n.element_id)?'checked':''}>${esc(n.name||n.element_id)}</label>`).join('')||'<p>Сначала добавьте задачи в BPMN-схему.</p>'}${r.elements.filter(id=>!shapes.some(n=>n.element_id===id)).map(id=>`<label class="missing-link"><input type="checkbox" name="elements" value="${esc(id)}" checked>Недоступная задача: ${esc(id)}</label>`).join('')}</div>`,async data=>{
  const title=String(data.get('title')).trim();if(!title)throw Error('Укажите название требования.');
  const updated={id:r.id,title,text:String(data.get('text')),status:String(data.get('status')),elements:data.getAll('elements')};
  const saved=b.requirement_items?.find(x=>x.id===r.id);if(saved)Object.assign(saved,updated);else {if((b.requirement_items?.length||0)>=300)throw Error('Максимум 300 требований в блоке.');(b.requirement_items??=[]).push(updated);}
  if(!await save())throw Error('Сохранение не удалось. Правки остаются в текущей сессии; экспортируйте проект.');
  render();
 });
 $('#modal-body [name="title"]').maxLength=200;$('#modal-body [name="text"]').maxLength=20000;
}

// Условия выбираются вручную; параллельные шлюзы синхронизируют входящие потоки.
let walk=null;
function processGraph(xml){
 const doc=new DOMParser().parseFromString(xml,'application/xml');
 if(doc.querySelector('parsererror'))throw Error('Сначала исправьте XML схемы.');
 const ns='http://www.omg.org/spec/BPMN/20100524/MODEL';
 const nodes=new Map(),edges=[],messages=[],scopes=new Map(),ids=new Set();
 const local=value=>(value||'').split(':').at(-1);
 function visit(container,parent=null){
  const scope=container.getAttribute('id');if(!scope)return;
  scopes.set(scope,{id:scope,parent,name:container.getAttribute('name')||scope});
  for(const n of container.children){
   if(n.namespaceURI!==ns)continue;
   const id=n.getAttribute('id'),kind=n.localName;if(!id)continue;
   if(kind!=='sequenceFlow'&&!kind.endsWith('Event')&&!kind.endsWith('Gateway')&&!kind.endsWith('Task')&&!['task','subProcess','transaction','callActivity','adHocSubProcess'].includes(kind))continue;
   if(ids.has(id))throw Error('Повторный ID элемента: '+id);ids.add(id);
   if(kind==='sequenceFlow'){edges.push({id,scope,source:n.getAttribute('sourceRef'),target:n.getAttribute('targetRef'),name:n.getAttribute('name')||'',conditional:[...n.children].some(c=>c.localName==='conditionExpression')});continue;}
   const defs=[...n.children].filter(c=>c.localName.endsWith('EventDefinition'));
   for(const ref of [...n.children].filter(c=>c.localName==='eventDefinitionRef')){const found=[...doc.getElementsByTagName('*')].find(c=>c.getAttribute('id')===local(ref.textContent.trim()));if(found)defs.push(found);}
   const events=defs.map(d=>({type:d.localName.replace('EventDefinition',''),ref:local(d.getAttribute('errorRef')||d.getAttribute('escalationRef')||d.getAttribute('messageRef')||d.getAttribute('signalRef')),name:d.getAttribute('name')||'',target:local([...d.children].find(c=>c.localName==='target')?.textContent?.trim()),duration:[...d.children].find(c=>c.localName==='timeDuration')?.textContent?.trim()||'',condition:[...d.children].find(c=>c.localName==='condition')?.textContent?.trim()||''}));
   const loopElement=[...n.children].find(c=>['multiInstanceLoopCharacteristics','standardLoopCharacteristics'].includes(c.localName));
   const cardinalityText=[...(loopElement?.children||[])].find(c=>c.localName==='loopCardinality')?.textContent?.trim()||'';
   const maximumText=loopElement?.getAttribute('loopMaximum')||'';
   const conditionText=[...(loopElement?.children||[])].find(c=>c.localName==='loopCondition')?.textContent?.trim()||'';
   const completionText=[...(loopElement?.children||[])].find(c=>c.localName==='completionCondition')?.textContent?.trim()||'';
   const loop=loopElement?{kind:loopElement.localName==='multiInstanceLoopCharacteristics'?'multi':'standard',sequential:loopElement.getAttribute('isSequential')==='true',cardinality:/^\d+$/.test(cardinalityText)?Number(cardinalityText):null,expression:cardinalityText,testBefore:loopElement.getAttribute('testBefore')==='true',maximum:/^\d+$/.test(maximumText)?Number(maximumText):null,condition:conditionText,completion:completionText}:null;
   const adHocCompletion=[...n.children].find(c=>c.localName==='completionCondition')?.textContent?.trim()||'';
   nodes.set(id,{id,kind,scope,name:n.getAttribute('name')||id,events,special:!!events.length,default:n.getAttribute('default'),attached:n.getAttribute('attachedToRef'),interrupting:n.getAttribute('cancelActivity')!=='false',triggered:n.getAttribute('triggeredByEvent')==='true',instantiate:n.getAttribute('instantiate')==='true',eventGatewayType:n.getAttribute('eventGatewayType')||'Exclusive',called:local(n.getAttribute('calledElement')),loop,adHocCompletion,adHocOrdering:n.getAttribute('ordering')||'Parallel',adHocCancelRemaining:n.getAttribute('cancelRemainingInstances')!=='false'});
   if(kind==='startEvent')nodes.get(id).interrupting=n.getAttribute('isInterrupting')!=='false';
   if(['subProcess','transaction','adHocSubProcess'].includes(kind))visit(n,scope);
  }
 }
 for(const process of doc.getElementsByTagNameNS(ns,'process'))visit(process);
 for(const participant of doc.getElementsByTagNameNS(ns,'participant')){
  const scope=scopes.get(participant.getAttribute('processRef'));
  if(scope&&participant.getAttribute('name'))scope.name=participant.getAttribute('name');
 }
 for(const flow of doc.getElementsByTagNameNS(ns,'messageFlow')){
  const source=flow.getAttribute('sourceRef'),target=flow.getAttribute('targetRef');
  if(nodes.has(source)&&nodes.has(target))messages.push({id:flow.getAttribute('id'),source,target,name:flow.getAttribute('name')||''});
 }
 for(const edge of edges)if(!nodes.has(edge.source)||!nodes.has(edge.target)||nodes.get(edge.source).scope!==edge.scope||nodes.get(edge.target).scope!==edge.scope)throw Error('Некорректная связь процесса: '+edge.id);
 return {nodes,edges,messages,scopes};
}
function projectScenarioGraph(){
 const candidates=S.project.blocks.filter(b=>b.bpmn&&!b.last_split?.block_ids?.some(id=>S.project.blocks.some(item=>item.id===id)));
 if(!candidates.length)throw Error('В проекте нет BPMN-схем для запуска.');
 const nodes=new Map(),edges=[],messages=[],scopes=new Map(),blocks=new Map();
 const key=(blockId,id)=>blockId+'::'+id;
 for(const b of candidates){
  const graph=processGraph(b.bpmn),runnableStarts=rootStarts(graph),runnableScopes=new Set(runnableStarts.map(node=>node.scope));
  const starts=runnableStarts.map(node=>key(b.id,node.id)),ends=[...runnableScopes].flatMap(scope=>scopeEnds(graph,scope)).map(node=>key(b.id,node.id));
  blocks.set(b.id,{block:b,graph,starts,ends});
  for(const [id,scope] of graph.scopes)scopes.set(key(b.id,id),{...scope,id:key(b.id,id),parent:scope.parent?key(b.id,scope.parent):null});
  for(const [id,node] of graph.nodes){
   const events=(node.events||[]).map(event=>({...event,target:event.target&&graph.nodes.has(event.target)?key(b.id,event.target):event.target}));
   nodes.set(key(b.id,id),{...node,id:key(b.id,id),originalId:id,blockId:b.id,blockName:b.name,scope:key(b.id,node.scope),attached:node.attached?key(b.id,node.attached):null,called:node.called&&graph.scopes.has(node.called)?key(b.id,node.called):node.called,events});
  }
  edges.push(...graph.edges.map(edge=>({...edge,id:key(b.id,edge.id),source:key(b.id,edge.source),target:key(b.id,edge.target),scope:key(b.id,edge.scope),blockId:b.id})));
  messages.push(...(graph.messages||[]).map(flow=>({...flow,id:key(b.id,flow.id),source:key(b.id,flow.source),target:key(b.id,flow.target)})));
 }
 const links=S.project.links.filter(link=>blocks.has(link.source)&&blocks.has(link.target));
 for(const link of links){
  const source=blocks.get(link.source),target=blocks.get(link.target),traced=Array.isArray(link.bpmn_flows)&&link.bpmn_flows.length;
  if(traced){
   for(const flow of link.bpmn_flows){
    const from=key(link.source,'FacetEnd_'+flow.id),to=key(link.target,'FacetStart_'+flow.id);
    if(nodes.has(from)&&nodes.has(to))edges.push({id:'@project:'+link.id+':'+flow.id,source:from,target:to,name:flow.name||target.block.name,conditional:false,project:true,sourceBlock:link.source,targetBlock:link.target});
   }
  }else for(const from of source.ends)for(const to of target.starts)edges.push({id:'@project:'+link.id+':'+from+':'+to,source:from,target:to,name:target.block.name,conditional:false,project:true,sourceBlock:link.source,targetBlock:link.target});
 }
 const incoming=new Set(edges.filter(edge=>edge.project).map(edge=>edge.targetBlock)),roots=candidates.filter(block=>!incoming.has(block.id));
 const rootBlocks=roots.length?roots:[candidates[0]];
 for(const b of rootBlocks)for(const id of blocks.get(b.id).starts)nodes.get(id).projectRoot=true;
 return {nodes,edges,messages,scopes,project:true,blocks};
}
function walkOptions(graph,id){
 const n=graph.nodes.get(id);if(!n)return {message:'Элемент не найден. Завершите сценарий и проверьте схему.',next:[]};
 const supported=['startEvent','endEvent','exclusiveGateway','parallelGateway','task','userTask','serviceTask','manualTask','sendTask','receiveTask','scriptTask','businessRuleTask'];
 if(!supported.includes(n.kind)||n.special)return {message:'Подпроцессы, специальные события и этот тип развилки пока не поддерживаются.',next:[]};
 const outgoing=graph.edges.filter(e=>e.source===id);
 if(n.kind==='endEvent')return {message:outgoing.length?'У конечного события есть исходящие связи — проверьте схему.':'Сценарий завершён.',next:[]};
 if(!outgoing.length)return {message:'Тупик: нет исходящей связи к следующему шагу.',next:[]};
 if(outgoing.length>1&&!['exclusiveGateway','parallelGateway'].includes(n.kind))return {message:'Несколько исходящих связей вне шлюза пока не поддерживаются.',next:[]};
 if(outgoing.some(e=>!graph.nodes.has(e.target)))return {message:'Связь ведёт к отсутствующему элементу. Проверьте схему.',next:[]};
 return {message:n.kind==='exclusiveGateway'?'Выберите ветку вручную — условия не вычисляются.':'Переход к следующему шагу процесса.',next:outgoing};
}
function stopWalk(){walk?.panelCleanup?.();walk=null;$('#walk-panel')?.remove();$('#workspace').classList.remove('walking','prototyping','walk-side','walk-window-mode');$('#workspace').style.removeProperty('--walk-panel-top');document.querySelectorAll('.walk-current').forEach(n=>n.classList.remove('walk-current'));}
function showWalk(){
 if(!walk)return;
 if(walk.project){if(walk.projectId!==S.project?.id)return stopWalk();return renderParallelWalk();}
 if(walk.blockId!==S.selected||walk.xml!==block()?.bpmn){stopWalk();return toast('Схема изменилась. Запустите сценарий заново.');}
 return renderParallelWalk();
}
function launchScenario(){
 try{
  if(!block()?.bpmn)return toast('Сначала создайте BPMN-схему.');
  const graph=processGraph(block().bpmn);
  if(!rootStarts(graph).length)return toast('В основном процессе нет доступного начального шага.');
  stopWalk();S.connect=null;
  walk={graph,path:[],blockId:S.selected,xml:block().bpmn,panelMode:'side'};
  showWalk();
 }catch(err){toast(err.message,true);}
}
function launchProjectScenario(){
 try{
  const graph=projectScenarioGraph();if(!rootStarts(graph).length)return toast('Не найден стартовый блок проекта.');
  stopWalk();S.connect=null;walk={project:true,projectId:S.project.id,graph,history:[],engine:branchState(),panelPositions:{},panelMode:'side'};showWalk();
 }catch(err){toast(err.message,true);}
}
// Панель остаётся внутри fullscreen-элемента; запуск обрабатываем на ней.
$('#view-actions').addEventListener('click',e=>{
 const button=e.target.closest('[data-feature="walk"]');
 if(!button||button.disabled)return;
 e.preventDefault();e.stopPropagation();
 launchScenario();
});
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-feature]');if(!el)return;
 const action=el.dataset.feature;
 if(action==='new-term')return termDialog();
 if(action==='edit-term')return termDialog(el.dataset.term);
 if(action==='open-term')return openTerm(el.dataset.term);
 if(action==='term-element'){
  const target=S.project?.blocks.find(item=>item.id===el.dataset.block);
  if(!target)return toast('Связанный блок больше не существует.',true);
  if($('#modal').open)$('#modal').close();
  if(typeof activateSection==='function')activateSection('workspace');
  selectBlock(target.id,'bpmn');
  try{
   if(!S.analyses.has(target.id))await analyzeBlock(target);
   if(S.selected===target.id){
    if(!S.analyses.has(target.id))throw Error('В связанном блоке нет схемы BPMN.');
    focusElement(el.dataset.target);
   }
  }catch(error){toast(error.message,true);}
  return;
 }
 if(action==='term-block'){
  const target=S.project?.blocks.find(item=>item.id===el.dataset.target);
  if(!target)return toast('Связанный блок больше не существует.',true);
  if($('#modal').open)$('#modal').close();
  if(typeof activateSection==='function')activateSection('workspace');
  selectBlock(target.id,'overview');
  requestAnimationFrame(()=>{
   if(S.selected!==target.id||S.view!=='overview')return;
   fit({x:target.x,y:target.y,w:260,h:170});
   const card=[...document.querySelectorAll('.block-card')].find(item=>item.dataset.id===target.id);
   const nav=[...document.querySelectorAll('#block-list [data-block]')].find(item=>item.dataset.block===target.id);
   card?.classList.add('glossary-target');nav?.classList.add('glossary-target');
   nav?.scrollIntoView({block:'nearest'});
   setTimeout(()=>{card?.classList.remove('glossary-target');nav?.classList.remove('glossary-target');},5000);
  });
  return;
 }
 if(action==='save-template')return saveBlockTemplate();
 if(action==='new-requirement')return requirementDialog();
 if(action==='edit-requirement')return requirementDialog(el.dataset.requirement);
 if(action==='requirement-target'){setView('bpmn');focusElement(el.dataset.target);return;}
 if(action==='walk-stop')return stopWalk();
 if(action==='walk')return launchScenario();
 if(action==='project-walk')return launchProjectScenario();
 if(action==='walk-back'&&walk){if(walk.history?.length){walk.engine=walk.history.pop();showWalk();}}
});
// Двойной клик во время сценария не открывает карточку элемента: одинарное
// перетаскивание остаётся доступным в режиме «Редактирование».
$('#content').addEventListener('dblclick',e=>{if(walk)e.stopImmediatePropagation();},true);
