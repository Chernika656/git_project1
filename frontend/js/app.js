'use strict';
// Интерфейс хранит текущий проект; Python проверяет и сохраняет его целиком.
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => crypto.randomUUID();
const statusNames = {draft:'Черновик', review:'На согласовании', approved:'Согласовано'};
const viewNames = {overview:'Обзор', bpmn:'BPMN', uml:'UML sequence', technical:'API и данные', slides:'Слайды', requirements:'Требования', glossary:'Словарь проекта'};
const compactSectionMeta={workspace:['▦','Рабочая область'],projects:['▱','Проекты'],analytics:['◫','Аналитика'],tasks:['✓','Задачи'],team:['♧','Команда'],agent:['✦','Агент'],account:['◎','Аккаунт'],settings:['⚙','Настройки']};
const compactViewIcons={overview:'▦',requirements:'≡',glossary:'Aa',bpmn:'◇',uml:'⇄',technical:'⌘',slides:'▣'};
const S = {project:null, selected:null, view:'overview', analyses:new Map(), element:null, camera:null, queue:Promise.resolve(), pending:0, failed:false, busy:false, undo:new Map(), slide:0, connect:null};
let toastTimer, modalHandler;
let canvasMode='pan',spacePan=false;
const compactNav=document.createElement('button');
compactNav.type='button';compactNav.id='compact-nav-toggle';compactNav.setAttribute('aria-expanded','false');
compactNav.innerHTML='<span class="compact-nav-icon">▦</span><span><small>НАВИГАЦИЯ</small><strong id="compact-nav-label">Рабочая область · Обзор</strong></span><span class="compact-nav-chevron">⌄</span>';
document.querySelector('.space-picker').after(compactNav);
function compactNavLabel(section='workspace',view=S.view){
 const meta=compactSectionMeta[section]||compactSectionMeta.workspace;
 const icon=$('.compact-nav-icon'),label=$('#compact-nav-label');
 if(icon)icon.textContent=section==='workspace'?(compactViewIcons[view]||meta[0]):meta[0];
 if(label)label.textContent=section==='workspace'?meta[1]+' · '+(viewNames[view]||'Обзор'):meta[1];
}
compactNav.onclick=()=>{const open=$('.sidebar').classList.toggle('compact-open');compactNav.setAttribute('aria-expanded',String(open));};
document.addEventListener('click',event=>{
 const item=event.target.closest('.sidebar [data-view],.sidebar [data-section]');if(!item)return;
 compactNavLabel(item.dataset.section||'workspace',item.dataset.view||S.view);
 if(matchMedia('(max-width:1050px)').matches){$('.sidebar').classList.remove('compact-open');compactNav.setAttribute('aria-expanded','false');}
});
function updateCanvasMode(){
 $('#workspace').classList.toggle('pan-mode',S.view==='bpmn'&&(canvasMode==='pan'||spacePan));
 document.querySelectorAll('[data-canvas-mode]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.canvasMode===canvasMode)));
}
function toast(message, error=false){const el=$('#toast');el.textContent=message;el.className=error?'error':'';el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?10000:3500);}
async function api(path, method='GET', body){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json',...(typeof A!=='undefined'&&A.csrf?{'X-CSRF-Token':A.csrf}:{})}:{},body:body?JSON.stringify(body):undefined});const result=await r.json();if(!r.ok){if(r.status===401&&result.code==='login_required'&&typeof showAuth==='function')showAuth('login','Сессия завершена. Войдите заново.');const error=new Error(result.error||'Не удалось выполнить запрос');error.status=r.status;throw error;}return result;}
const taskTextFields={description:'Описание задачи',requirements:'Требования',acceptance:'Критерии приёмки'};
function taskFields(detail){return Object.entries(taskTextFields).map(([key,label])=>field(label,key,detail?.[key]||'','textarea')).join('');}
function readTaskFields(data){return Object.fromEntries(Object.keys(taskTextFields).map(key=>[key,String(data.get(key)||'')]));}
function reviewBasis(detail){return Object.fromEntries(Object.keys(taskTextFields).map(key=>[key,detail?.[key]||'']));}
function umlIsCurrent(detail){return !!detail?.uml_review&&Object.keys(taskTextFields).every(key=>(detail[key]||'')===detail.uml_review[key]);}
function reviewPanel(detail,allowConfirm=false){return `<div class="uml-review ${umlIsCurrent(detail)?'current':'pending'}"><strong>${umlIsCurrent(detail)?'✓ UML актуальна':'! UML требует проверки'}</strong><small>Относительно описания, требований и критериев приёмки.</small>${allowConfirm&&canEdit()?button('Подтвердить актуальность','confirm-uml','soft'):''}</div>`;}
function refreshReview(){const panel=$('#task-review');if(panel)panel.innerHTML=reviewPanel(taskDetail(),true);}
function taskDetail(b=block(),create=false){
 if(!b||!S.detailId)return null;
 const found=b.element_details?.find(d=>d.element_id===S.detailId);
 if(found||!create)return found;
 const detail={element_id:S.detailId,description:'',uml:{participants:[],messages:[]}};
 (b.element_details??=[]).push(detail);return detail;
}
function activeUml(b=block()){return S.detailId?taskDetail(b)?.uml||{participants:[],messages:[]}:b.uml;}
function taskName(){return S.analyses.get(S.selected)?.diagram.shapes.find(n=>n.element_id===S.detailId)?.name||S.detailId;}
async function openTaskUml(id){
 S.detailId=id;
 if(!taskDetail()){if(!canEdit()){S.detailId=null;return toast('Детализация ещё не создана.');}taskDetail(block(),true);if(!await save())return;}
 S.view='uml';S.camera=null;S.element=id;render();
}
function block(){return S.project?.blocks.find(b=>b.id===S.selected);}
function download(name, data, type='application/json'){const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);}
function save(){
  if(!canEdit()){clearTimeout(S.timer);S.timer=null;toast('У вас нет права редактировать этот проект.',true);return Promise.resolve(false);}
  clearTimeout(S.timer); S.timer=null;
  if(S.failed){toast('Сохранение приостановлено. Экспортируйте проект через меню ⋯ и перезагрузите страницу.',true);return Promise.resolve(false);}
  const snapshot=structuredClone(S.project);S.pending++;$('#save-state').textContent='Сохраняется…';
  S.queue=S.queue.then(async()=>{try{if(S.failed)return false;const p=await api('/api/projects/'+snapshot.id,'PUT',{revision:S.project.revision,project:snapshot});S.project.revision=p.revision;S.project.updated=p.updated;return true;}catch(e){S.failed=true;toast(e.message,true);return false;}finally{S.pending--;$('#save-state').textContent=S.failed?'Не сохранено · меню ⋯':S.pending?'Сохраняется…':'Сохранено на компьютере';}});return S.queue;
}
async function refreshProjects(){const list=await api('/api/projects?space='+encodeURIComponent(A.space));$('#project-select').innerHTML=list.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')+(list.length?'':'<option value="" disabled selected>Выберите проект</option>')+'<option value="__new">＋ Новый проект</option>';if(S.project)$('#project-select').value=S.project.id;return list;}
async function openProject(id){if(S.timer)save();if(S.pending)await S.queue;if(S.failed){$('#project-select').value=S.project.id;return toast('Сначала экспортируйте несохранённые правки и перезагрузите страницу.',true);}S.detailId=null;S.project=await api('/api/projects/'+id);if(typeof activateSection==='function')activateSection('workspace');S.selected=S.project.blocks[0]?.id;S.analyses.clear();S.undo.clear();const preferred=typeof getPreferences==='function'?getPreferences().startView:'auto';S.view=['overview','bpmn','requirements','uml','technical','slides'].includes(preferred)?preferred:(({leader:'slides',product:'overview',business:'bpmn',system:'uml',developer:'technical',qa:'requirements',designer:'slides',manager:'overview'})[currentSpecialty()]||'overview');S.element=null;S.camera=null;S.connect=null;S.slide=0;localStorage.setItem('workspace.lastProject',id);$('#project-select').value=id;$('#save-state').textContent='Сохранено на компьютере';render();await analyzeAll();renderIssues();if(['overview','bpmn'].includes(S.view)){S.camera=null;renderView();}}
async function analyzeBlock(b){if(!b.bpmn){S.analyses.delete(b.id);return;}const xml=b.bpmn;const result=await api('/api/bpmn/analyze','POST',{xml});if(b.bpmn===xml)S.analyses.set(b.id,result);}
async function analyzeAll(){await Promise.all(S.project.blocks.filter(b=>b.bpmn).map(b=>analyzeBlock(b)));}
function selectBlock(id,view){S.detailId=null;if(S.timer)save();S.selected=id;S.element=null;S.connect=null;if(view)S.view=view;S.camera=null;render();}
function setView(view){S.detailId=null;if(!S.project)return;if(S.timer)save();S.view=view;S.element=null;S.connect=null;S.camera=null;if(view==='slides')S.slide=Math.max(0,presentationBlocks().findIndex(b=>(b.block_id||b.id)===S.selected));render();}
function button(label,action,cls=''){return `<button type="button" data-action="${action}" class="${cls}">${label}</button>`;}
function field(label,name,value='',type='input'){return `<label class="field">${label}${type==='textarea'?`<textarea name="${name}">${esc(value)}</textarea>`:`<input name="${name}" value="${esc(value)}" maxlength="${name==='name'?200:20000}">`}</label>`;}
function modal(title,html,onSubmit,label='Сохранить'){$('#submit-modal').hidden=false;if($('#modal').open)$('#modal').close();(document.fullscreenElement||document.body).append($('#modal'));$('#modal-title').textContent=title;$('#modal-body').innerHTML=html;$('#submit-modal').textContent=label;modalHandler=onSubmit;$('#modal').showModal();}
$('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const data=new FormData(e.target);$('#submit-modal').disabled=true;try{const result=await modalHandler(data);if(result!==false)$('#modal').close();}catch(err){toast(err.message,true);}finally{$('#submit-modal').disabled=false;}});
$('#close-modal').onclick=$('#cancel-modal').onclick=()=>$('#modal').close();
function newProjectDialog(){
 modal('Новый проект',field('Название проекта','name','Новый проект')+'<div class="project-import-option"><span><strong>Уже есть схема?</strong><small>Создадим проект с одним BPMN-блоком.</small></span><button type="button" id="new-project-bpmn">↑ Импортировать BPMN</button></div>',async data=>{if(S.pending)await S.queue;if(S.failed)throw new Error('Сначала сохраните резервную копию своих правок.');const p=await api('/api/projects','POST',{name:data.get('name'),space_id:A.space});await refreshProjects();await openProject(p.id);},'Создать пустой проект');
 $('#new-project-bpmn').onclick=()=>chooseFile('.bpmn,.xml',async(xml,file)=>{
  if(file.size>5*1024*1024)throw new Error('BPMN должен быть меньше 5 МБ.');
  const analysis=await api('/api/bpmn/analyze','POST',{xml}),fatal=new Set(['INVALID_XML','NOT_BPMN','FILE_TOO_LARGE','DUPLICATE_ID','MISSING_ID']);
  if(analysis.report.issues.some(issue=>fatal.has(issue.code)))throw new Error('Файл не удалось импортировать: исправьте XML и идентификаторы BPMN.');
  if(S.pending)await S.queue;if(S.failed)throw new Error('Сначала сохраните резервную копию своих правок.');
  const base=file.name.replace(/\.(bpmn|xml)$/i,'').trim()||'BPMN-процесс',entered=$('#modal-form [name="name"]').value.trim(),name=entered&&entered!=='Новый проект'?entered:base;
  const project={id:uid(),name,goal:'',blocks:[{id:uid(),name:base,description:'',requirements:'',owner:'',status:'draft',x:80,y:110,bpmn:xml,uml:{participants:[],messages:[]},technical:''}],links:[],revision:1,updated:new Date().toISOString()};
  const created=await api('/api/projects','POST',{project,space_id:A.space});$('#modal').close();await refreshProjects();await openProject(created.id);S.view='bpmn';S.camera=null;render();toast('Проект создан из BPMN.');
 });
}
function addBlock(){return chooseBlockTemplate();}
function render(){
 const b=block(),projectLayer=['overview','glossary','slides'].includes(S.view);
 $('#page-title').textContent=S.view==='glossary'?'Словарь проекта':S.view==='slides'?'Презентация проекта':projectLayer?S.project.name:(b?.name||S.project.name);
 $('#page-subtitle').textContent=S.view==='overview'?(S.project.goal||'Добавьте цель проекта в меню ⋯'):S.view==='glossary'?S.project.name+' · общее понимание терминов':S.view==='slides'?S.project.name+' · материалы для презентации':`${viewNames[S.view]} · содержание выбранного блока`;
 $('#layer-block-name').textContent=b?`БЛОК · ${b.name}`:'ВЫБЕРИТЕ БЛОК';$('#layer-block-name').title=b?.name||'';
 document.querySelectorAll('.view-tab-group[data-layer-scope="block"] button').forEach(button=>button.disabled=!b);
 $('#delete-block-top').hidden=!b;
 compactNavLabel('workspace',S.view);
 $('#context-label').textContent=S.view==='overview'?'ОБЩАЯ КАРТА':viewNames[S.view].toUpperCase();
 document.querySelectorAll('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===S.view);if(el.getAttribute('role')==='tab')el.setAttribute('aria-selected',String(el.dataset.view===S.view));});
 $('#block-list').innerHTML=S.project.blocks.map(b=>`<button class="block-nav ${b.id===S.selected?'active':''}" data-block="${esc(b.id)}"><span class="tiny-square"></span>${esc(b.name)}</button>`).join('')||'<p class="inspector-note">Добавьте первый блок</p>';
 if(S.detailId&&S.view==='uml')$('#page-subtitle').textContent=block().name+' → '+taskName()+' → UML';renderInspector();renderView();renderIssues();if(typeof renderLayerAgentActions==='function')renderLayerAgentActions();applyAccess();
}
// Проверка наличия содержания, а не качества или согласования.
function blockCompleteness(b){
 const filled=value=>typeof value==='string'&&!!value.trim();
 const hasUml=u=>!!(u?.participants?.length&&u?.messages?.length);
 return [
  {key:'description',label:'Описание',done:filled(b.description)},
  {key:'owner',label:'Ответственный',done:filled(b.owner)},
  {key:'requirements',label:'Требования и условия',done:filled(b.requirements)||!!b.requirement_items?.length},
  {key:'bpmn',label:'BPMN-схема',done:filled(b.bpmn)},
  {key:'uml',label:'UML: участники и сообщения',done:hasUml(b.uml)}
 ];
}
function viewCompleteness(b){
 const filled=value=>typeof value==='string'&&!!value.trim();
 const analysis=S.analyses.get(b.id),shapes=analysis?.diagram?.shapes||[],edges=analysis?.diagram?.edges||[];
 const kinds=new Set(shapes.map(shape=>shape.kind));
 const uml=activeUml(b)||{participants:[],messages:[]},technical=b.technical||'';
 const panels={
  overview:{title:'Наполнение блока',caption:'разделов заполнено',note:'Подсказки по заполнению, не оценка качества. UML здесь — представление всего блока.',checks:blockCompleteness(b)},
  bpmn:{title:'Готовность BPMN',caption:'элементов готовности',note:'Проверяется базовая структура схемы. Логические замечания находятся под полотном.',checks:[
   {key:'bpmn-file',label:'Схема создана',done:filled(b.bpmn),target:'bpmn'},
   {key:'bpmn-start',label:'Начальное событие',done:kinds.has('startEvent'),target:'bpmn'},
   {key:'bpmn-end',label:'Завершающее событие',done:kinds.has('endEvent'),target:'bpmn'},
   {key:'bpmn-task',label:'Задачи процесса',done:shapes.some(s=>s.kind.endsWith('Task')||s.kind==='task'),target:'bpmn'},
   {key:'bpmn-flow',label:'Связи между элементами',done:edges.some(e=>e.kind==='sequenceFlow'),target:'bpmn'}]},
  uml:{title:'Готовность UML',caption:'частей диаграммы',note:'Участники и сообщения относятся к выбранному блоку. Для задачи BPMN можно открыть отдельную UML.',checks:[
   {key:'uml-actors',label:'Участники',done:uml.participants.length>=2,target:'uml'},
   {key:'uml-messages',label:'Сообщения',done:uml.messages.length>0,target:'uml'},
   {key:'uml-call',label:'Вызовы',done:uml.messages.some(m=>m.kind==='call'),target:'uml'},
   {key:'uml-return',label:'Ответы',done:uml.messages.some(m=>m.kind==='return'),target:'uml'},
   {key:'uml-names',label:'Названия взаимодействий',done:uml.messages.length>0&&uml.messages.every(m=>filled(m.text)),target:'uml'}]},
  technical:{title:'Готовность API и данных',caption:'частей контракта',note:'Проверяется наличие основных частей технического описания, без строгой проверки OpenAPI.',checks:[
   {key:'api-description',label:'Описание контракта',done:filled(technical),target:'technical'},
   {key:'api-method',label:'HTTP-метод',done:/\b(GET|POST|PUT|PATCH|DELETE)\b/i.test(technical),target:'technical'},
   {key:'api-path',label:'Путь API',done:/\/[a-z0-9_{}\-/.]+/i.test(technical),target:'technical'},
   {key:'api-data',label:'Структура данных',done:/request|schema|properties|payload|данн/i.test(technical),target:'technical'},
   {key:'api-response',label:'Ответы и статусы',done:/response|responses|status|\b[1-5]\d\d\b|ответ/i.test(technical),target:'technical'}]},
  slides:{title:'Готовность слайда',caption:'частей презентации',note:'Эти данные формируют слайд выбранного блока.',checks:[
   {key:'slide-title',label:'Заголовок',done:filled(b.name),field:'name'},
   {key:'slide-description',label:'Описание результата',done:filled(b.description),field:'description'},
   {key:'slide-owner',label:'Ответственный',done:filled(b.owner),field:'owner'},
   {key:'slide-status',label:'Статус определён',done:b.status!=='draft',field:'status'},
   {key:'slide-requirements',label:'Требования',done:filled(b.requirements)||!!b.requirement_items?.length,target:'requirements'}]},
  requirements:{title:'Готовность требований',caption:'частей описания',note:'Панель показывает наличие исходных данных. Качество формулировок оценивает аналитик.',checks:[
   {key:'req-description',label:'Контекст блока',done:filled(b.description),field:'description'},
   {key:'req-main',label:'Требования',done:filled(b.requirements),target:'requirements'},
   {key:'req-items',label:'Структурированные пункты',done:!!b.requirement_items?.length,target:'requirements'},
   {key:'req-owner',label:'Ответственный',done:filled(b.owner),field:'owner'},
   {key:'req-bpmn',label:'Связь с процессом',done:filled(b.bpmn),target:'bpmn'}]}
 };
 return panels[S.view]||panels.overview;
}
function refreshCompleteness(){
 const target=$('#block-completeness'),b=block();if(!target||!b)return;
 const panel=viewCompleteness(b),checks=panel.checks,count=checks.filter(c=>c.done).length;
 const signature=S.view+checks.map(c=>Number(c.done)).join('');
 if(target.dataset.checks===signature)return;
 target.dataset.checks=signature;
 target.className=`block-completeness completeness-${S.view}`;
target.innerHTML=`<div class="completeness-title"><strong>${panel.title}</strong></div><div class="completeness-gauge-row"><div class="completeness-gauge" role="progressbar" aria-label="${panel.title}" aria-valuemin="0" aria-valuemax="${checks.length}" aria-valuenow="${count}" aria-valuetext="${count} из ${checks.length}"><svg viewBox="0 0 64 64" aria-hidden="true"><circle class="gauge-track" cx="32" cy="32" r="27"/><circle class="gauge-arc" cx="32" cy="32" r="27" pathLength="100" style="--gauge-offset:${100-count/checks.length*100}"/></svg><span class="gauge-center" aria-hidden="true">${Math.round(count/checks.length*100)}<small>%</small></span></div><div class="gauge-caption"><strong>${count}<span> / ${checks.length}</span></strong><small>${panel.caption}</small></div></div><div>${checks.map(c=>`<button class="completeness-item ${c.done?'complete':''}" data-completeness="${c.key}" ${c.target?`data-completeness-view="${c.target}"`:''} ${c.field?`data-completeness-field="${c.field}"`:''}><span>${c.done?'✓':'○'}</span><span>${c.label}</span><small>${c.done?'Есть':'Добавить'} ›</small></button>`).join('')}</div><p>${panel.note}</p>`;
}
document.addEventListener('click',e=>{
 const item=e.target.closest('[data-completeness]');if(!item)return;
 const fieldName=item.dataset.completenessField,view=item.dataset.completenessView,key=item.dataset.completeness;
 if(fieldName)return $('#inspector [name="'+fieldName+'"]')?.focus();
 if(view)return setView(view);
 if(['description','owner'].includes(key))$('#inspector [name="'+key+'"]')?.focus();
 else if(['requirements','bpmn','uml'].includes(key))setView(key);
});
function inspectorViewData(b,opts){
 const analysis=S.analyses.get(b.id),report=analysis?.report||{},shapes=analysis?.diagram?.shapes||[],edges=analysis?.diagram?.edges||[];
 const uml=activeUml(b)||{participants:[],messages:[]},items=b.requirement_items||[];
 const metric=(value,label)=>`<div class="inspector-metric"><strong>${value}</strong><small>${label}</small></div>`;
 if(S.view==='bpmn'){
  const tasks=shapes.filter(s=>s.kind==='task'||s.kind.endsWith('Task')).length;
  return `<section class="inspector-view-data"><h3>Структура BPMN</h3><div class="inspector-metrics">${metric(report.processes||0,'процессов')}${metric(tasks,'задач')}${metric(report.flows||edges.length,'связей')}${metric((report.errors||0)+(report.warnings||0),'замечаний')}</div><p class="inspector-note">Элементов на схеме: ${shapes.length}. Выберите элемент на полотне, чтобы открыть его детали.</p>${button('Редактировать XML','edit-xml','soft')}</section>`;
 }
 if(S.view==='uml'){
  const names=Object.fromEntries(uml.participants.map(p=>[p.id,p.name]));
  return `<section class="inspector-view-data"><h3>Участники</h3><div class="inspector-chips">${uml.participants.map(p=>`<span>${esc(p.name)}</span>`).join('')||'<small>Участники ещё не добавлены</small>'}</div><h3>Сообщения</h3><div class="inspector-sequence">${uml.messages.slice(0,6).map((m,i)=>`<div><small>${i+1}</small><span>${esc(names[m.from]||'—')} → ${esc(names[m.to]||'—')}<strong>${esc(m.text)}</strong></span></div>`).join('')||'<p class="inspector-note">Добавьте первое взаимодействие.</p>'}</div><div class="inspector-data-actions">${button('Участники','uml-actors','soft')}${button('+ Сообщение','uml-message')}</div></section>`;
 }
 if(S.view==='technical'){
  const method=(b.technical||'').match(/\b(GET|POST|PUT|PATCH|DELETE)\b/i)?.[1]?.toUpperCase()||'—';
  const path=(b.technical||'').match(/\/[a-z0-9_{}\-/.]+/i)?.[0]||'Не указан';
  const statuses=[...(b.technical||'').matchAll(/\b([1-5]\d\d)\b/g)].map(x=>x[1]).filter((x,i,a)=>a.indexOf(x)===i);
  return `<section class="inspector-view-data"><h3>Контракт блока</h3><div class="api-summary"><span class="api-method">${esc(method)}</span><code>${esc(path)}</code></div><div class="inspector-metrics">${metric((b.technical||'').length,'символов')}${metric(statuses.length,'статусов')}</div><h3>Ответы</h3><div class="inspector-chips">${statuses.map(s=>`<span>${s}</span>`).join('')||'<small>Коды ответов не указаны</small>'}</div><p class="inspector-note">Полный контракт редактируется в центральной области.</p></section>`;
 }
 if(S.view==='requirements'){
  const linked=items.reduce((sum,item)=>sum+(item.elements?.length||0),0),approved=items.filter(item=>item.status==='approved').length;
  return `<section class="inspector-view-data"><h3>Реестр требований</h3><div class="inspector-metrics">${metric(items.length,'требований')}${metric(linked,'связей с BPMN')}${metric(approved,'согласовано')}</div><div class="inspector-requirements">${items.slice(0,5).map(item=>`<article><small>${esc(requirementCode(item))}</small><strong>${esc(item.title)}</strong><span>${statusNames[item.status]||item.status}</span></article>`).join('')||'<p class="inspector-note">Структурированных требований пока нет.</p>'}</div><p class="inspector-note">Общие заметки и полный реестр находятся в центральной области.</p></section>`;
 }
 if(S.view==='slides')return `${field('Заголовок слайда','name',b.name)}<label class="field">Статус на слайде<select name="status">${opts}</select></label>${field('Описание результата','description',b.description,'textarea')}${field('Ответственный на слайде','owner',b.owner)}`;
 return `${field('Название','name',b.name)}<label class="field">Статус<select name="status">${opts}</select></label>${field('Описание','description',b.description,'textarea')}${field('Ответственный / роль','owner',b.owner)}`;
}
function renderInspector(){
 if(S.view==='glossary'){$('#inspector').innerHTML='<div class="inspector-heading"><h2>Единый язык проекта</h2></div><p class="inspector-note">Опишите понятия, сущности и статусы. Свяжите термин с блоками, где он используется. Эти связи отображаются и в карточке блока.</p>';return;}
 const b=block();if(!b){$('#inspector').innerHTML='<div class="empty-state"><span class="empty-icon">▦</span><h3>Начните с блока</h3><p>Процесс, функция или часть вашего проекта.</p></div>';return;}
 if(S.detailId&&S.view==='uml'){
  const detail=taskDetail();$('#inspector').innerHTML=`<div class="inspector-heading"><span class="block-icon">⇄</span><div><h2>${esc(taskName())}</h2><small>Детализация задачи BPMN</small></div></div><div id="task-review">${reviewPanel(detail,true)}</div>${taskFields(detail)}<p class="inspector-note">Связь хранится по ID элемента. Переименование и перемещение её сохраняют.</p>${button('← К BPMN','task-back')}`;
  $('#inspector').querySelectorAll('textarea').forEach(input=>{input.maxLength=20000;input.readOnly=!canEdit();input.oninput=()=>{detail[input.name]=input.value;refreshReview();clearTimeout(S.timer);S.timer=setTimeout(save,650);$('#save-state').textContent='Есть правки…';};input.onchange=()=>save();});return;
 }
 const opts=Object.entries(statusNames).map(([v,n])=>`<option value="${v}" ${b.status===v?'selected':''}>${n}</option>`).join('');
 const inspectorViews={overview:['▱','Блок проекта'],requirements:['≡','Требования блока'],bpmn:['◇','Процесс BPMN'],uml:['⇄','Взаимодействия UML'],technical:['⌘','API и данные'],slides:['▣','Слайд презентации']},meta=inspectorViews[S.view]||inspectorViews.overview;
 const trace=b.source_trace?`<section class="split-trace"><strong>✓ Фрагмент исходной BPMN</strong><span>${b.source_trace.element_ids.length} исходных элементов · ID сохранены</span></section>`:b.last_split?`<section class="split-trace"><strong>✓ Точное разбиение выполнено</strong><span>${b.last_split.preserved_elements}/${b.last_split.source_elements} элементов · ${b.last_split.preserved_flows}/${b.last_split.source_flows} связей учтено</span></section>`:'';
 $('#inspector').innerHTML=`<div class="inspector-heading"><span class="block-icon">${meta[0]}</span><div><h2>${esc(b.name)}</h2><small>${meta[1]}</small></div></div><section id="block-completeness" class="block-completeness"></section>${trace}${inspectorViewData(b,opts)}<div class="inspector-divider"></div><h3>Открыть представление</h3>`+
 [['slides','▷','Презентация','Цель, результат, статус'],['bpmn','◇','BPMN','Процесс и участники'],['uml','⇄','UML sequence','Взаимодействия систем'],['technical','⌘','API и данные','Контракты и структуры']].map(([v,i,t,s])=>`<button class="view-link" data-view="${v}"><span>${i}</span><span><strong>${t}</strong><small>${s}</small></span><span class="chevron">›</span></button>`).join('')+
 `<div class="inspector-divider"></div><div class="section-heading"><h3>Следующие блоки</h3>${button('+','link-block','icon')}</div>`+
 S.project.links.filter(l=>l.source===b.id).map(l=>`<div class="link-row"><span>${esc(S.project.blocks.find(x=>x.id===l.target)?.name)}</span><button class="icon" data-unlink="${esc(l.id)}" aria-label="Удалить связь">×</button></div>`).join('')+
 `<p class="inspector-note">Представления связаны с этим блоком. BPMN и UML редактируются отдельно.</p><div class="inspector-footer">${canEdit()?'<button type="button" class="soft" data-feature="save-template">Сохранить как шаблон</button>':''}${button('Удалить блок','delete-block','danger')}</div>`;
 refreshCompleteness();
 $('#inspector').insertAdjacentHTML('beforeend',glossaryBlockTerms());
 $('#inspector').querySelectorAll('[name]').forEach(el=>el.disabled=!canEdit());
 $('#inspector').querySelectorAll('[name]').forEach(el=>el.addEventListener('change',()=>{if(el.name==='name'&&!el.value.trim()){el.value=b.name;return toast('Название не может быть пустым.',true);}b[el.name]=el.value;refreshCompleteness();save();if(S.view==='overview')renderCanvas();else if(S.view==='slides')renderView();$('#page-title').textContent=S.view==='overview'?S.project.name:b.name;$('#inspector h2').textContent=b.name;const nav=[...document.querySelectorAll('[data-block]')].find(n=>n.dataset.block===b.id);if(nav)nav.innerHTML=`<span class="tiny-square"></span>${esc(b.name)}`;}));
}
const toolbarGroups={
 'add-node':'Создать','add-lane':'Создать','add-pool':'Создать','connect-node':'Создать','link-block':'Создать','uml-actors':'Создать','uml-message':'Создать',
 'import-bpmn':'Процесс','undo-bpmn':'Процесс','bpmn-history':'Процесс','uml-messages':'Процесс',
 'edit-xml':'Данные','export-bpmn':'Данные','export-svg':'Данные','export-text':'Данные','export-slides':'Данные','print-slides':'Данные'
};
function organizeActionToolbar(){
 const root=$('#view-actions');if(!root||root.dataset.organized==='true')return;root.dataset.organized='true';
 const children=[...root.children],visible=[],groups=new Map();
 children.forEach(node=>{if(node.classList.contains('canvas-modes')||node.classList.contains('primary')||node.matches('[data-feature="walk"],[data-feature="project-walk"],[data-prototype="launch"],[data-action="task-back"],[data-action="prev-slide"],[data-action="next-slide"]'))return visible.push(node);const key=node.dataset.action||node.dataset.prototype;const name=node.dataset.prototype==='screens'?'Создать':toolbarGroups[key];if(!name)return visible.push(node);if(!groups.has(name))groups.set(name,[]);groups.get(name).push(node);});
 root.replaceChildren();if(visible.length){const quick=document.createElement('div');quick.className='tool-quick';visible.forEach(node=>quick.append(node));root.append(quick);}
 for(const [name,nodes] of groups){const details=document.createElement('details');details.className='tool-menu';details.innerHTML=`<summary>${name}<span>⌄</span></summary><div class="tool-menu-panel"></div>`;nodes.forEach(node=>details.lastElementChild.append(node));root.append(details);}
}
document.addEventListener('click',event=>{
 document.querySelectorAll('.tool-menu[open],.top-project-menu[open],.page-more-menu[open]').forEach(menu=>{if(!menu.contains(event.target)||event.target.closest('button'))menu.open=false;});
});
function actions(html,hint){const root=$('#view-actions');root.innerHTML=html;delete root.dataset.organized;$('#view-hint').textContent=hint;applyAccess();queueMicrotask(organizeActionToolbar);}
function empty(title,text,buttons=''){return `<div class="empty-state"><span class="empty-icon">◇</span><h3>${title}</h3><p>${text}</p><div>${buttons}</div></div>`;}
function renderView(){
 if(typeof stopWalk==='function'&&!walk?.project)stopWalk();
 updateCanvasMode();
 const b=block();const collapsed=S.view!=='bpmn';$('#issues-panel').classList.toggle('collapsed',collapsed);$('#toggle-issues').textContent=collapsed?'+':'−';$('.canvas-controls').style.bottom=S.view==='slides'?'18px':collapsed&&!document.fullscreenElement?'62px':'';$('#workspace').classList.toggle('presentation',S.view==='slides');$('#canvas-controls').style.display=['overview','bpmn','uml','slides'].includes(S.view)?'flex':'none';$('#zoom-in').disabled=$('#zoom-out').disabled=$('#fit').disabled=S.view==='slides';document.querySelectorAll('#zoom-in,#zoom-out,#zoom-label,#fit,.control-divider').forEach(el=>el.style.display=S.view==='slides'?'none':'');
 if(S.view==='overview'){actions('<button type="button" class="primary" data-feature="project-walk">▶ Проиграть проект</button>'+button('Связать блоки','link-block'), 'Весь проект по связям блоков и внутренним BPMN');renderCanvas();return;}
 if(S.view==='glossary'){actions(`<button type="button" class="primary" data-feature="new-term" ${canEdit()?'':'disabled'}>+ Термин</button>`,'Понятия, сущности и статусы вашего проекта');renderGlossary();return;}
 if(!b){actions('','Добавьте блок, чтобы начать работу');$('#content').innerHTML=empty('Пока нет блоков','Создайте первый блок проекта.',button('+ Добавить блок','add-block','primary'));return;}
 if(S.view==='bpmn'){
  actions('<button type="button" data-feature="walk" class="soft">▶ Пройти сценарий</button>'+button('↑ Импорт','import-bpmn')+button('+ Элемент','add-node')+button('+ Дорожка','add-lane')+button('+ Пул','add-pool')+button(S.connect?'Отмена связи':'↗ Связь','connect-node')+button('↶','undo-bpmn')+button('История','bpmn-history')+button('XML','edit-xml')+button('↓','export-bpmn'),S.connect?'Выберите начальный и конечный элементы':'Перемещение сохраняется · двойной клик по замечанию приближает элемент');
  const bpmnBlocks=S.project.blocks.filter(item=>item.bpmn);
  if(bpmnBlocks.length){
   const current=Math.max(0,bpmnBlocks.findIndex(item=>item.id===S.selected));
   $('#view-hint').innerHTML=`<div class="bpmn-layer-switcher" aria-label="Быстрый переход между BPMN"><button type="button" data-bpmn-jump="${esc(bpmnBlocks[(current-1+bpmnBlocks.length)%bpmnBlocks.length].id)}" aria-label="Предыдущая BPMN" ${bpmnBlocks.length<2?'disabled':''}>‹</button><label><span>BPMN</span><select id="bpmn-layer-select" aria-label="Выбрать BPMN проекта">${bpmnBlocks.map(item=>`<option value="${esc(item.id)}" ${item.id===S.selected?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label><button type="button" data-bpmn-jump="${esc(bpmnBlocks[(current+1)%bpmnBlocks.length].id)}" aria-label="Следующая BPMN" ${bpmnBlocks.length<2?'disabled':''}>›</button></div>`;
   $('#bpmn-layer-select').onchange=event=>selectBlock(event.target.value,'bpmn');
   $('#view-hint').querySelectorAll('[data-bpmn-jump]').forEach(control=>control.onclick=()=>selectBlock(control.dataset.bpmnJump,'bpmn'));
  }
  $('#view-actions').insertAdjacentHTML('afterbegin','<button type="button" class="primary" data-prototype="launch">▶ Запустить прототип</button><button type="button" data-prototype="screens">Экраны задач</button>');
  $('#view-actions').insertAdjacentHTML('afterbegin',`<div class="canvas-modes" role="group" aria-label="Управление схемой"><button type="button" data-canvas-mode="pan" title="Перемещать схему целиком">✋ Рука</button><button type="button" data-canvas-mode="edit" title="Перемещать элементы схемы" ${canEdit()?'':'disabled'}>↖ Редактирование</button></div>`);
  updateCanvasMode();
  if(!b.bpmn){$('#content').innerHTML=empty('Новая BPMN-схема','Создайте простую схему или импортируйте файл .bpmn.',button('Создать схему','new-bpmn','primary')+' '+button('Импортировать','import-bpmn'));return;}
  renderCanvas();return;
 }
 if(S.view==='uml'){actions((S.detailId?button('← К BPMN','task-back'):'')+button('Участники','uml-actors')+button('+ Сообщение','uml-message')+button('Сценарий','uml-messages')+button('↓ SVG','export-svg'),'Диаграмма последовательности · участники и сообщения');if(!activeUml(b).participants.length){$('#content').innerHTML=empty('Первое взаимодействие','Добавьте участников: пользователя, систему или сервис.',button('+ Участники','uml-actors','primary'));return;}renderCanvas();return;}
 if(S.view==='requirements'||S.view==='technical'){
  const technical=S.view==='technical', key=technical?'technical':'requirements';actions(button('↓ Экспорт','export-text'),technical?'Контракт или техническое описание блока':'Бизнес-правила, ограничения и условия приёмки');
  $('#content').innerHTML=`<div class="document-view"><h2>${technical?'API и данные':'Требования к блоку'}</h2><p>${technical?'Свободный текст, JSON, OpenAPI или описание структуры данных.':'Опишите поведение, исключения и ожидаемый результат.'} Сохраняется после паузы во вводе.</p><textarea id="document-text" class="${technical?'code':''}" aria-label="${technical?'API и данные':'Требования'}" placeholder="${technical?'Опишите интерфейс или вставьте контракт…':'Добавьте требования…'}">${esc(b[key])}</textarea></div>`;
  $('#document-text').readOnly=!canEdit();if(!technical)renderRequirements();
  $('#document-text').addEventListener('input',e=>{b[key]=e.target.value;refreshCompleteness();clearTimeout(S.timer);$('#save-state').textContent='Есть правки…';S.timer=setTimeout(save,650);});$('#document-text').addEventListener('change',()=>{clearTimeout(S.timer);save();});return;
 }
 if(S.view==='slides'){
  const slides=presentationBlocks();if(!slides.length){actions('','Презентация проекта');$('#content').innerHTML=empty('Пока нет слайдов','Создайте первый блок проекта — он появится здесь как слайд.',button('+ Новый блок','add-block','primary'));return;}
  S.slide=Math.min(Math.max(S.slide,0),slides.length-1);const slide=slides[S.slide];
  actions(button('←','prev-slide')+`<span class="inspector-note">${S.slide+1} / ${slides.length}</span>`+button('→','next-slide')+(canEdit()?button('↑','slide-up')+button('↓','slide-down')+button('✎ Слайд','edit-slide')+button('+ Слайд','duplicate-slide')+(slide.block_id?button('Удалить слайд','delete-slide'):'')+button('↑ PPTX','import-slides'):'')+button('↓ PPTX','export-pptx')+button('↓ HTML','export-slides')+button('Печать / PDF','print-slides'),'Презентация проекта · ← → для навигации · перетащите слайд для смены порядка');
  $('#content').innerHTML=`<div class="slide-workbench"><nav class="slide-outline" aria-label="Слайды презентации">${slides.map((item,index)=>`<button type="button" data-slide-jump="${index}" draggable="${canEdit()?'true':'false'}" class="${index===S.slide?'active':''}" aria-current="${index===S.slide?'true':'false'}"><span>${item.slide?.layout==='section'?'§':String(index+1).padStart(2,'0')}</span><strong>${esc(item.slide?.title||item.name)}</strong></button>`).join('')}</nav><div class="slide-wrap">${slideHTML(slide,S.slide)}${slide.slide?.notes?`<details class="slide-speaker-notes"><summary>Заметки докладчика</summary><p>${esc(slide.slide.notes)}</p></details>`:''}</div></div>`;
  $('#content').querySelectorAll('[data-slide-jump]').forEach(control=>control.onclick=()=>{S.slide=Number(control.dataset.slideJump);S.selected=slides[S.slide].block_id||slides[S.slide].id;renderInspector();renderView();});
  if(canEdit()){
   const outline=$('#content .slide-outline');let moving=null;
   outline.ondragstart=e=>{const item=e.target.closest('[data-slide-jump]');if(!item)return;moving=Number(item.dataset.slideJump);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(moving));item.classList.add('dragging');};
   outline.ondragover=e=>{const item=e.target.closest('[data-slide-jump]');if(item&&moving!==null){e.preventDefault();e.dataTransfer.dropEffect='move';}};
   outline.ondrop=async e=>{const item=e.target.closest('[data-slide-jump]');if(!item||moving===null)return;e.preventDefault();const target=Number(item.dataset.slideJump),source=moving;moving=null;if(source===target)return;const reordered=[...slides],moved=reordered.splice(source,1)[0];reordered.splice(target,0,moved);S.project.presentation_order=reordered.map(entry=>entry.id);S.slide=target;S.selected=moved.block_id||moved.id;await save();renderInspector();renderView();};
   outline.ondragend=()=>{moving=null;outline.querySelectorAll('.dragging').forEach(item=>item.classList.remove('dragging'));};
  }
 }
}
function presentationBlocks(){const order=S.project.presentation_order||[],positions=new Map(order.map((id,index)=>[id,index]));const extras=(S.project.presentation_extra_slides||[]).map(entry=>{const block=S.project.blocks.find(item=>item.id===entry.block_id);return block?{...block,id:entry.id,block_id:block.id,slide:entry.slide}:null;}).filter(Boolean);return [...S.project.blocks,...extras].sort((a,b)=>(positions.get(a.id)??Infinity)-(positions.get(b.id)??Infinity));}
function suggestSlideMatches(slides,blocks){
 const stop=new Set(['для','это','как','или','что','при','про','без','есть','все','его','еще','эта','этот','the','and','for','with','project','проект','система','данные']);
 const words=value=>new Set(String(value||'').toLocaleLowerCase().match(/[\p{L}\p{N}]{3,}/gu)?.filter(word=>!stop.has(word))||[]);
 const overlap=(a,b)=>a.size?[...a].filter(word=>b.has(word)).length/a.size:0;
 const candidates=[];
 slides.forEach((slide,index)=>{const title=words(slide.title),body=words((slide.lines||[]).slice(0,3).join(' '));
  blocks.forEach(block=>{const name=words(block.name),context=words([block.description,block.requirements].join(' '));
   const exact=slide.title.trim().toLocaleLowerCase()===block.name.trim().toLocaleLowerCase();
   const score=exact?1:0.55*overlap(title,name)+0.35*overlap(title,context)+0.1*overlap(body,new Set([...name,...context]));
   if(score>=0.38)candidates.push({index,id:block.id,score});
  });
 });
 candidates.sort((a,b)=>b.score-a.score);const selected=new Map();
 for(const candidate of candidates)if(!selected.has(candidate.index))selected.set(candidate.index,candidate.id);
 return selected;
}
function prepareSlideImport(project,selected){
 if(!selected.length)throw new Error('Выберите хотя бы один слайд.');
 if(project.blocks.length+selected.filter(item=>item.id==='__new__').length>200)throw new Error('В проекте допускается не более 200 блоков.');
 const blocks=structuredClone(project.blocks),extras=structuredClone(project.presentation_extra_slides||[]),imported=[],used=new Set();
 for(const {source,id,suggestion} of selected){
  let target;
  if(id==='__new__'){
   const index=blocks.length;
   target={id:uid(),name:(source.title.trim()||`Слайд ${source.number}`).slice(0,200),description:(source.lines[0]||'').slice(0,20000),requirements:'',owner:'',status:'draft',x:70+(index%3)*310,y:100+Math.floor(index/3)*240,bpmn:'',uml:{participants:[],messages:[]},technical:''};
   blocks.push(target);
  }else{
   target=blocks.find(item=>item.id===id);
   if(!target)throw new Error('Блок больше не существует.');
  }
  const first=!used.has(target.id);used.add(target.id);
  const aligned=suggestion?.block_id===target.id?suggestion:null;
  const slide={title:aligned?.title||source.title,message:(aligned?.message||source.lines[0]||target.description).slice(0,4000),bullets:(aligned?.bullets||source.lines.slice(1,7)).map(line=>line.slice(0,240)),layout:!aligned&&!source.lines.length&&!source.image?'section':(aligned?.bullets?.length||source.lines.length>1)?'bullets':'summary',...(source.image?{image:source.image}:{})};
  if(first){target.slide=slide;imported.push(target.id);}else{const extra={id:uid(),block_id:target.id,slide};extras.push(extra);imported.push(extra.id);}
 }
 if(blocks.length+extras.length>200)throw new Error('В презентации допускается до 200 слайдов.');
 const imageBytes=[...blocks.map(item=>item.slide),...extras.map(item=>item.slide)].reduce((total,slide)=>{const image=slide?.image;if(!image)return total;const encoded=image.slice(image.indexOf(',')+1);return total+Math.floor(encoded.length*3/4)-(encoded.endsWith('==')?2:encoded.endsWith('=')?1:0);},0);
 if(imageBytes>3_000_000)throw new Error('Изображения презентации превышают 3 МБ. Уберите часть слайдов или изображения.');
 const positions=new Map((project.presentation_order||[]).map((id,index)=>[id,index]));
 const rest=[...blocks,...extras].filter(item=>!imported.includes(item.id)).sort((a,b)=>(positions.get(a.id)??Infinity)-(positions.get(b.id)??Infinity));
 return {blocks,extras,order:[...imported,...rest.map(item=>item.id)]};
}
function slideHTML(b,index){const slide=b.slide||{},layout=slide.layout||'summary',bullets=slide.bullets||[],message=slide.message??b.description;return `<article class="slide slide-${layout}"><div class="eyebrow">${esc(S.project.name)} / ${String(index+1).padStart(2,'0')}</div><h2>${esc(slide.title||b.name)}</h2><div class="slide-description">${esc(message||(layout==='section'?'':'Добавьте главный тезис слайда.'))}</div>${slide.image?`<img class="slide-image" src="${esc(slide.image)}" alt="Иллюстрация слайда">`:""}${layout!=='summary'&&bullets.length?`<ul class="slide-points">${bullets.map(point=>`<li>${esc(point)}</li>`).join('')}</ul>`:''}${layout==='decision'?'<div class="slide-decision-label">Ключевое решение</div>':''}<div class="slide-footer"><span>${esc(b.owner||'Ответственный не назначен')}</span><span class="slide-status">${statusNames[b.status]}</span></div></article>`;}
let pptxLibraryPromise;
async function loadPptxLibrary(){
 if(window.PptxGenJS&&window.FacetPptx)return;
 if(!pptxLibraryPromise)pptxLibraryPromise=(async()=>{
  for(const source of ['/vendor/jszip.min.js','/vendor/pptxgen.min.js','/pptx-export.js']){
   await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=source;script.onload=resolve;script.onerror=()=>reject(new Error('Не удалось загрузить модуль экспорта PPTX.'));document.head.append(script);});
  }
 })().catch(error=>{pptxLibraryPromise=null;throw error;});
 return pptxLibraryPromise;
}
async function pptxImage(image){
 if(!image?.startsWith('data:image/webp;'))return image;
 return new Promise((resolve,reject)=>{const element=new Image();element.onload=()=>{try{const canvas=document.createElement('canvas');canvas.width=element.naturalWidth;canvas.height=element.naturalHeight;canvas.getContext('2d').drawImage(element,0,0);resolve(canvas.toDataURL('image/png'));}catch(error){reject(error);}};element.onerror=()=>reject(new Error('Не удалось подготовить изображение слайда.'));element.src=image;});
}
function overviewSVG(){
 const p=S.project;
 const lines=p.links.map(l=>{const a=p.blocks.find(b=>b.id===l.source),b=p.blocks.find(b=>b.id===l.target);if(!a||!b)return '';const x1=a.x+260,y1=a.y+85,x2=b.x,y2=b.y+85;const d=Math.abs(b.y-a.y)>180?`M ${a.x+130} ${a.y+170} V ${b.y-35} H ${b.x+130} V ${b.y}`:`M ${x1} ${y1} H ${(x1+x2)/2} V ${y2} H ${x2}`;return `<path d="${d}" fill="none" stroke="#b5bfda" stroke-width="1.7" marker-end="url(#arrow)"/>`;}).join('');
 const cards=p.blocks.map((b,i)=>{const selected=b.id===S.selected,count=S.analyses.get(b.id)?.report.issues.length||0;const colors=[['#eff5ff','#739ad7'],['#f4effd','#a288d7'],['#eef6f8','#76a9b4'],['#fff4ed','#cba88c']][i%4];return `<g class="block-card" data-id="${esc(b.id)}" transform="translate(${b.x},${b.y})"><rect class="card-bg" width="260" height="170" rx="13" fill="${selected?'#f5f0ff':'white'}" stroke="${selected?'#ad90e3':'#e2e7f1'}" stroke-width="${selected?1.8:1}"/><rect class="card-shine" x="1" y="1" width="258" height="60" rx="12" fill="none"/><rect class="card-icon" x="15" y="16" width="31" height="31" rx="8" fill="${colors[0]}"/><text class="card-icon-symbol" x="30" y="38" text-anchor="middle" fill="${colors[1]}" font-size="21">▱</text><g class="card-title">${svgText(b.name,57,33,22,15,'#3e4665',600)}</g><g class="card-description">${svgText(b.description||'Добавьте описание блока',16,70,29,12,'#8290a8',400,2)}</g><g class="card-tags" transform="translate(16,111)"><rect width="43" height="20" rx="5" fill="#f1eef8"/><text x="21" y="14" text-anchor="middle" font-size="9" fill="#9a88be">BPMN</text><rect x="50" width="37" height="20" rx="5" fill="#eff3fb"/><text x="68" y="14" text-anchor="middle" font-size="9" fill="#8b9bc0">UML</text>${count?`<rect class="issue-tag" x="97" width="131" height="20" rx="5" fill="#fff1df"/><text class="issue-tag-text" x="107" y="14" font-size="9" fill="#bf914f">!  Замечаний: ${count}</text>`:''}</g><line class="card-divider" x1="16" y1="141" x2="244" y2="141" stroke="#eeedf6"/><circle class="owner-dot" cx="23" cy="155" r="7" fill="${colors[0]}"/><text class="card-owner" x="37" y="159" font-size="9" fill="#97a0b6">${esc((b.owner||'Без ответственного').slice(0,26))}</text><circle class="card-port" cx="259" cy="85" r="4" fill="#c5bbdc" stroke="white" stroke-width="2"/></g>`;}).join('');
 return lines+cards;
}
function svgText(text,x,y,width,size=12,color='#68738f',weight=400,maxLines=1){const words=String(text).split(/\s+/);let lines=[],line='';for(const word of words){if((line+' '+word).trim().length>width&&line){lines.push(line);line='';}line+=(line?' ':'')+word;}if(line)lines.push(line);if(lines.length>maxLines){lines=lines.slice(0,maxLines);lines[maxLines-1]=lines[maxLines-1].slice(0,Math.max(0,width-1))+'…';}return `<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${color}">${lines.map((l,i)=>`<tspan x="${x}" dy="${i?size*1.5:0}">${esc(l)}</tspan>`).join('')}</text>`;}
function bpmnSVG(){
 const result=S.analyses.get(S.selected);if(!result)return '';const d=result.diagram,severity={},markers=new Map(),triggered=new Set(),loops=new Map();result.report.issues.forEach(i=>{if(severity[i.element_id]!=='error')severity[i.element_id]=i.severity;});
 try{const xml=new DOMParser().parseFromString(result.xml,'application/xml');for(const event of xml.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/MODEL','*')){if(event.localName==='subProcess'&&event.getAttribute('triggeredByEvent')==='true')triggered.add(event.getAttribute('id'));const loop=[...event.children].find(child=>child.localName==='multiInstanceLoopCharacteristics'||child.localName==='standardLoopCharacteristics');if(loop)loops.set(event.getAttribute('id'),loop.localName==='standardLoopCharacteristics'?'↻':loop.getAttribute('isSequential')==='true'?'≡':'Ⅲ');if(!event.localName.endsWith('Event'))continue;const definition=[...event.children].find(child=>child.localName.endsWith('EventDefinition'));if(definition)markers.set(event.getAttribute('id'),definition.localName.replace('EventDefinition',''));}}catch{}
 function style(id,container=false){const s=severity[id];return {stroke:s==='error'?'#ce5265':s==='warning'?'#bd8c35':container?'#c5cddd':'#9398b4',fill:s==='error'?'#fff0f3':s==='warning'?'#fff8e9':container?'#fcfcfe':'#f6f4fc'};}
 function shape(s){const st=style(s.element_id,['participant','lane'].includes(s.kind));let body='';const w=s.width,h=s.height;
 if(s.kind.endsWith('Event')){body=`<ellipse class="outline" cx="${w/2}" cy="${h/2}" rx="${w/2}" ry="${h/2}" fill="${st.fill}" stroke="${st.stroke}" stroke-width="${s.kind==='endEvent'?3:1.5}"/>`;if(!['startEvent','endEvent'].includes(s.kind))body+=`<ellipse cx="${w/2}" cy="${h/2}" rx="${w/2-4}" ry="${h/2-4}" fill="none" stroke="${st.stroke}"/>`;const icon={timer:'◷',message:'✉',signal:'△',error:'⚡',escalation:'↑',compensate:'↶',cancel:'×',terminate:'●',conditional:'≡',link:'➜'}[markers.get(s.element_id)];if(icon)body+=`<text x="${w/2}" y="${h/2+6}" text-anchor="middle" font-size="20" fill="${st.stroke}">${icon}</text>`;}
 else if(s.kind.endsWith('Gateway'))body=`<polygon class="outline" points="${w/2},0 ${w},${h/2} ${w/2},${h} 0,${h/2}" fill="${st.fill}" stroke="${st.stroke}" stroke-width="1.5"/><text x="${w/2}" y="${h/2+7}" text-anchor="middle" font-size="24" fill="${st.stroke}">${s.kind==='parallelGateway'?'+':s.kind==='exclusiveGateway'?'×':s.kind==='inclusiveGateway'?'○':s.kind==='complexGateway'?'✳':'◇'}</text>`;
 else if(['dataObject','dataObjectReference'].includes(s.kind)){body=`<path class="outline" d="M 0 0 H ${w-20} L ${w} 20 V ${h} H 0 Z M ${w-20} 0 V 20 H ${w}" fill="${st.fill}" stroke="${st.stroke}" stroke-width="1.5"/>${svgText(s.name||'Данные',10,h/2,Math.max(9,Math.floor((w-18)/6)),11,'#65718f',400,4)}`;}
 else if(s.kind==='textAnnotation'){body=`<path class="outline" d="M 12 0 H 0 V ${h} H 12" fill="none" stroke="${st.stroke}" stroke-width="2"/>${svgText(s.name||'Пояснение',20,24,Math.max(10,Math.floor((w-28)/6)),11,'#65718f',400,5)}`;}
 else if(['participant','lane'].includes(s.kind)){body=`<rect class="outline" width="${w}" height="${h}" fill="${st.fill}" stroke="${st.stroke}"/><line x1="30" y1="0" x2="30" y2="${h}" stroke="${st.stroke}"/><text transform="translate(20,${h/2}) rotate(-90)" text-anchor="middle" font-size="12" fill="#808da8">${esc(s.name||s.kind)}</text>`;}
 else body=`<rect class="outline" width="${w}" height="${h}" rx="10" fill="${st.fill}" stroke="${st.stroke}" stroke-width="${s.kind==='callActivity'?3:1.5}" ${triggered.has(s.element_id)?'stroke-dasharray="5 4"':''}/>${s.kind==='transaction'?`<rect x="4" y="4" width="${w-8}" height="${h-8}" rx="7" fill="none" stroke="${st.stroke}" stroke-width="1.2"/>`:''}${svgText(s.name||'(без названия)',12,h/2-4,Math.max(10,Math.floor((w-24)/6)),12,'#65718f',400,3)}${['subProcess','transaction','adHocSubProcess'].includes(s.kind)?`<text x="${w/2}" y="${h-5}" text-anchor="middle" font-size="15">${s.kind==='transaction'?'▣':s.kind==='adHocSubProcess'?'~':'⊞'}</text>`:''}`;
 if(loops.has(s.element_id))body+=`<text x="${w/2}" y="${h-5}" text-anchor="middle" font-size="15" fill="${st.stroke}">${loops.get(s.element_id)}</text>`;
 if(s.kind.endsWith('Event')||s.kind.endsWith('Gateway'))body+=svgText(s.name,s.label?s.label[0]-s.x:-28,s.label?s.label[1]-s.y+12:h+19,24,11,'#8490a9',400,2);
 const linkedDetail=block().element_details?.find(d=>d.element_id===s.element_id);if(linkedDetail?.uml?.participants.length)body+=`<g><rect x="${w-33}" y="-9" width="37" height="18" rx="5" fill="${umlIsCurrent(linkedDetail)?'#ede4fb':'#fff2dc'}" stroke="${umlIsCurrent(linkedDetail)?'#b79cdd':'#d6a34d'}"/><text x="${w-14}" y="4" text-anchor="middle" font-size="9" fill="#8862bd">${umlIsCurrent(linkedDetail)?'UML':'UML !'}</text></g>`;
 if(linkedDetail?.screen)body+=`<g><rect x="-5" y="-9" width="48" height="18" rx="5" fill="#e4f1ff" stroke="#91b8e3"/><text x="19" y="4" text-anchor="middle" font-size="9" fill="#4d7daf">Экран</text></g>`;
 const visualKind=s.kind.endsWith('Event')?'node-event':s.kind.endsWith('Gateway')?'node-gateway':['subProcess','callActivity','transaction','adHocSubProcess'].includes(s.kind)?'node-subprocess':['participant','lane'].includes(s.kind)?'node-container':'node-task';
 return `<g class="node ${visualKind} ${severity[s.element_id]?`severity-${severity[s.element_id]}`:''} ${S.element===s.element_id?'selected':''}" data-id="${esc(s.element_id)}" data-kind="${esc(s.kind)}" transform="translate(${s.x},${s.y})">${body}<title>${esc(s.name||s.element_id)} · ${esc(s.kind)}</title></g>`;
 }
 const containers=d.shapes.filter(s=>['participant','lane'].includes(s.kind)||s.expanded),nodes=d.shapes.filter(s=>!containers.includes(s));
 const edges=d.edges.map(e=>{const st=style(e.element_id),points=e.points.map(p=>p.join(',')).join(' ');let label='';if(e.name){const p=e.label?[e.label[0],e.label[1]+12]:e.points[Math.floor(e.points.length/2)];label=svgText(e.name,p[0]+5,p[1]-7,24,10,'#8591ad');}return `<g class="bpmn-edge ${severity[e.element_id]?`severity-${severity[e.element_id]}`:''}" data-edge="${esc(e.element_id)}"><polyline class="flow" points="${points}" fill="none" stroke="${S.element===e.element_id?'#986acf':st.stroke}" stroke-width="${S.element===e.element_id?3:1.4}" ${['messageFlow','association'].includes(e.kind)?'stroke-dasharray="6 4"':''} ${e.kind==='association'?'':'marker-end="url(#arrow)"'}/>${label}</g>`;}).join('');
 return containers.map(shape).join('')+edges+nodes.map(shape).join('');
}
function umlSVG(){const uml=activeUml();const pos=Object.fromEntries(uml.participants.map((p,i)=>[p.id,110+i*220]));const height=120+uml.messages.length*78;return uml.participants.map(p=>`<g class="uml-actor"><rect x="${pos[p.id]-75}" y="25" width="150" height="52" rx="12" fill="#f1edfb" stroke="#c9bbdf"/>${svgText(p.name,pos[p.id]-61,56,22,12,'#78679d')}<line class="uml-lifeline" x1="${pos[p.id]}" y1="77" x2="${pos[p.id]}" y2="${height}" stroke="#c6cddd" stroke-dasharray="6 6"/></g>`).join('')+uml.messages.map((m,i)=>{const a=pos[m.from],b=pos[m.to],y=125+i*78;return `<g class="uml-message"><path d="${a===b?`M ${a} ${y} h 65 v 30 h -65`:`M ${a} ${y} H ${b}`}" stroke="#8e8ba9" fill="none" ${m.kind==='return'?'stroke-dasharray="6 4"':''} marker-end="url(#arrow)"/>${svgText((i+1)+'. '+m.text,Math.min(a,b)+12,y-12,32,11,'#768199',400,2)}</g>`;}).join('');}
function renderCanvas(){
 if(S.view==='overview'&&!S.project.blocks.length){$('#content').innerHTML=empty('Ваш проект начинается здесь','Добавляйте блоки, связывайте их и раскрывайте детали.',button('+ Первый блок','add-block','primary'));return;}
 const inner=S.view==='overview'?overviewSVG():S.view==='bpmn'?bpmnSVG():umlSVG();
 $('#content').innerHTML=`<svg class="diagram-svg diagram-${S.view}" role="img" aria-label="${viewNames[S.view]}" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="diagramGlass" x1="0" y1="0" x2="1" y2="1"><stop class="glass-stop-one" offset="0"/><stop class="glass-stop-two" offset=".52"/><stop class="glass-stop-three" offset="1"/></linearGradient><linearGradient id="diagramShine" x1="0" y1="0" x2="0" y2="1"><stop class="shine-stop" offset="0"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4 L 0 8" fill="#a0a9c4"/></marker></defs><g class="drawing">${inner}</g></svg>`;
 if(!S.camera)fit();else applyCamera();
}
function fit(box){const svg=$('.diagram-svg');if(!svg)return;let bounds=box;if(!bounds){try{const r=svg.querySelector('.drawing').getBBox();bounds={x:r.x,y:r.y,w:r.width,h:r.height};}catch{return;}}const pad=box?45:55, width=Math.max(200,svg.clientWidth),height=Math.max(150,svg.clientHeight),ratio=width/height;let w=Math.max(bounds.w+pad*2,box?width/2.2:180),h=Math.max(bounds.h+pad*2,box?height/2.2:130);if(w/h<ratio)w=h*ratio;else h=w/ratio;S.camera={x:bounds.x+bounds.w/2-w/2,y:bounds.y+bounds.h/2-h/2,w,h};applyCamera();}
function applyCamera(){const svg=$('.diagram-svg');if(!svg||!S.camera)return;svg.setAttribute('viewBox',`${S.camera.x} ${S.camera.y} ${S.camera.w} ${S.camera.h}`);$('#zoom-label').textContent=Math.round(svg.clientWidth/S.camera.w*100)+'%';}
function zoom(factor){if(!S.camera)return;const c=S.camera,w=Math.max(70,Math.min(100000,c.w*factor)),h=c.h*w/c.w;S.camera={x:c.x+(c.w-w)/2,y:c.y+(c.h-h)/2,w,h};applyCamera();}
function focusElement(id){S.element=id;const d=S.analyses.get(S.selected)?.diagram;if(!d)return;const s=d.shapes.find(s=>s.element_id===id),e=d.edges.find(e=>e.element_id===id);if(S.view!=='bpmn'){S.view='bpmn';render();}else renderCanvas();if(s)fit({x:s.x,y:s.y,w:s.width,h:s.height});else if(e){const xs=e.points.map(p=>p[0]),ys=e.points.map(p=>p[1]);fit({x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys)});}else toast('У замечания нет видимого элемента на текущей странице BPMN.');}
function renderIssues(){const b=block(),a=S.analyses.get(b?.id),issues=a?.report.issues||[];$('#issue-count').textContent=issues.length;$('#issue-scope').textContent=b?.name||'Выберите блок';$('#issues').innerHTML=issues.length?issues.map((i,n)=>`<button class="issue ${i.severity}" data-issue="${n}" title="Двойной клик — приблизить элемент"><span class="issue-symbol">!</span><span>${esc(i.message)}<small>${esc(i.hint)}</small></span><span class="issue-code">${esc(i.element_name||i.element_id||'XML')}</span></button>`).join(''):`<div class="empty-check">${b?.bpmn?'✓ Структурных замечаний не найдено.':'Импортируйте или создайте BPMN, чтобы проверить процесс.'}</div>`;
 if(a?.diagram.note)$('#issues').insertAdjacentHTML('beforeend',`<div class="empty-check">${esc(a.diagram.note)}</div>`);}
async function replaceBpmn(b,xml,result){const history=S.undo.get(b.id)||[];history.push(b.bpmn);if(history.length>30)history.shift();S.undo.set(b.id,history);b.bpmn=xml;S.analyses.set(b.id,result||await api('/api/bpmn/analyze','POST',{xml}));await save();if(S.selected===b.id){renderIssues();renderInspector();if(S.view==='bpmn')renderCanvas();}}
async function editBpmn(action){if(!canEdit())return; if(S.busy)return;const b=block();if(!b)return;S.busy=true;try{const result=await api('/api/bpmn/edit','POST',{xml:b.bpmn,action,project_id:S.project.id});await replaceBpmn(b,result.xml,result);if(action.op==='move'&&walk&&!walk.project&&walk.blockId===b.id)walk.xml=b.bpmn;if(action.op==='move'&&typeof refreshWalkHighlight==='function')refreshWalkHighlight();}catch(e){toast(e.message,true);if(S.view==='bpmn')renderCanvas();}finally{S.busy=false;}}
function versionDate(value){const date=new Date(typeof value==='number'?value*1000:value);return Number.isNaN(date.getTime())?'—':date.toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'});}
async function openBpmnHistory(){
 const b=block();if(!b?.bpmn)return toast('В блоке пока нет BPMN.');
 const history=await api(`/api/projects/${S.project.id}/bpmn-history?block=${encodeURIComponent(b.id)}`),current=history.current;
 modal('История BPMN',`<div class="bpmn-history-current"><span class="eyebrow">ТЕКУЩАЯ ВЕРСИЯ</span><strong>Версия проекта ${current.revision}</strong><small>${versionDate(current.created)} · ${current.elements} элементов · ${current.flows} связей</small></div><div class="bpmn-history-list">${history.versions.map(item=>`<button type="button" data-bpmn-version="${esc(item.id)}"><span><strong>Версия проекта ${item.revision}</strong><small>${versionDate(item.created)} · ${esc(item.author)}</small></span><span>${item.elements} элементов<br>${item.flows} связей</span></button>`).join('')||'<p class="modal-note">Предыдущих версий пока нет. Они появятся после следующего изменения этой BPMN.</p>'}</div><section id="bpmn-history-detail"><p class="modal-note">Выберите версию, чтобы увидеть отличие от текущей схемы.</p></section>`,()=>false);
 $('#submit-modal').hidden=true;
 $('#modal-body').querySelectorAll('[data-bpmn-version]').forEach(item=>item.onclick=()=>showBpmnVersion(item.dataset.bpmnVersion,history.access));
}
async function showBpmnVersion(versionId,access){
 const b=block(),target=$('#bpmn-history-detail');if(!target||!b)return;
 target.innerHTML='<p class="modal-note">Сравниваю версии…</p>';
 try{
  const version=await api(`/api/projects/${S.project.id}/bpmn-history?block=${encodeURIComponent(b.id)}&version=${encodeURIComponent(versionId)}`),diff=version.diff;
  const changes=[diff.added.length?`<div><strong>Добавлено</strong><p>${diff.added.map(esc).join(', ')}</p></div>`:'',diff.removed.length?`<div><strong>Удалено</strong><p>${diff.removed.map(esc).join(', ')}</p></div>`:'',diff.renamed.length?`<div><strong>Изменено</strong><p>${diff.renamed.map(item=>`${esc(item.from)} → ${esc(item.to)}`).join('<br>')}</p></div>`:'',diff.flow_changes?`<div><strong>Связи процесса</strong><p>Добавлено, удалено или изменено связей: ${diff.flow_changes}</p></div>`:''].join('');
  target.innerHTML=`<div class="bpmn-version-summary"><span class="eyebrow">СРАВНЕНИЕ С ТЕКУЩЕЙ</span><h3>Версия проекта ${version.revision}</h3><div class="bpmn-version-deltas"><span class="${diff.elements_delta<0?'negative':''}">${diff.elements_delta>0?'+':''}${diff.elements_delta} элементов</span><span class="${diff.flows_delta<0?'negative':''}">${diff.flows_delta>0?'+':''}${diff.flows_delta} связей</span></div>${diff.layout_only?'<p>Логика не изменилась — отличается только расположение элементов и стрелок.</p>':changes||'<p>Структурных отличий не найдено.</p>'}${access==='viewer'||access==='commenter'?'':`<div class="bpmn-history-restore"><button type="button" data-restore-version="${esc(version.id)}" class="primary">Восстановить эту версию</button><span hidden>Текущая BPMN сохранится в истории. <button type="button" data-restore-confirm class="primary">Да, восстановить</button> <button type="button" data-restore-cancel>Отмена</button></span></div>`}</div>`;
  const restore=target.querySelector('[data-restore-version]');if(restore)restore.onclick=()=>{restore.hidden=true;restore.nextElementSibling.hidden=false;};
  target.querySelector('[data-restore-cancel]')?.addEventListener('click',()=>{restore.hidden=false;restore.nextElementSibling.hidden=true;});
  target.querySelector('[data-restore-confirm]')?.addEventListener('click',()=>restoreBpmnVersion(version.id));
 }catch(error){target.innerHTML=`<p class="text-danger">${esc(error.message)}</p>`;}
}
async function restoreBpmnVersion(versionId){
 if(S.timer)await save();if(S.pending)await S.queue;
 const selected=S.selected,result=await api(`/api/projects/${S.project.id}/bpmn-restore`,'POST',{block_id:selected,version_id:versionId,revision:S.project.revision});
 S.project=result;S.selected=selected;S.analyses.clear();S.camera=null;S.element=null;await analyzeAll();$('#modal').close();render();refreshProjects();toast('Версия BPMN восстановлена.');
}
function chooseFile(accept,handler){const el=$('#file-input');el.value='';el.accept=accept;el.onchange=async()=>{if(!el.files[0])return;try{if(el.files[0].size>12*1024*1024)throw new Error('Файл больше 12 МБ.');await handler(await el.files[0].text(),el.files[0]);}catch(e){toast(e.message,true);}};el.click();}
async function action(name){
 const b=block();
 if(name==='confirm-uml'){if(!canEdit()||!S.detailId)return;const detail=taskDetail();if(!detail?.uml.participants.length)return toast('Сначала добавьте участников UML.');detail.uml_review=reviewBasis(detail);if(await save()){refreshReview();toast('Актуальность UML подтверждена.');}return;}
 if(name==='task-back'){const id=S.detailId;if(S.timer)save();S.detailId=null;S.view='bpmn';S.camera=null;render();focusElement(id);return;}
 if(name==='add-block')return addBlock();
 if(name==='link-block'){
  if(!b||S.project.blocks.length<2)return toast('Добавьте хотя бы два блока.');
  const targets=S.project.blocks.filter(x=>x.id!==b.id&&!S.project.links.some(l=>l.source===b.id&&l.target===x.id));
  if(!targets.length)return toast('Все остальные блоки уже связаны с этим блоком.');
  return modal('Связать блоки',`<p class="modal-note">После «${esc(b.name)}» следует:</p><label class="field">Следующий блок<select name="target">${targets.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('')}</select></label>`,async d=>{S.project.links.push({id:uid(),source:b.id,target:d.get('target')});render();await save();},'Добавить связь');
 }
 if(name==='delete-block')return modal('Удалить блок?',`<p class="modal-note">Будет удалён блок «${esc(b.name)}», его представления и связи. Можно предварительно экспортировать проект через меню ⋯.</p>`,async()=>{S.project.blocks=S.project.blocks.filter(x=>x.id!==b.id);const removedSlides=new Set((S.project.presentation_extra_slides||[]).filter(item=>item.block_id===b.id).map(item=>item.id));removedSlides.add(b.id);S.project.presentation_extra_slides=(S.project.presentation_extra_slides||[]).filter(item=>item.block_id!==b.id);S.project.presentation_order=(S.project.presentation_order||[]).filter(id=>!removedSlides.has(id));S.project.links=S.project.links.filter(l=>l.source!==b.id&&l.target!==b.id);S.analyses.delete(b.id);S.selected=S.project.blocks[0]?.id;S.camera=null;render();await save();},'Удалить');
 if(name==='import-bpmn'){if(!b)return toast('Сначала создайте блок.');return chooseFile('.bpmn,.xml',async(xml,file)=>{if(file.size>5*1024*1024)throw new Error('BPMN должен быть меньше 5 МБ.');const result=await api('/api/bpmn/analyze','POST',{xml});const apply=async()=>{await replaceBpmn(b,xml,result);S.view='bpmn';S.camera=null;render();};if(b.bpmn)modal('Заменить BPMN?',`<p class="modal-note">Файл «${esc(file.name)}» заменит схему блока. Предыдущую схему можно вернуть кнопкой ↶ до закрытия проекта.</p>`,apply,'Импортировать');else await apply();});}
 if(name==='new-bpmn'){if(!b)return;const xml='<?xml version="1.0" encoding="UTF-8"?><definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1" targetNamespace="urn:workspace"><process id="Process_1" isExecutable="false"><startEvent id="start" name="Начало"/><task id="task" name="Проверить заявку"/><endEvent id="end" name="Конец"/><sequenceFlow id="flow1" sourceRef="start" targetRef="task"/><sequenceFlow id="flow2" sourceRef="task" targetRef="end"/></process></definitions>';await replaceBpmn(b,xml);S.camera=null;renderView();return;}
 if(name==='bpmn-history')return openBpmnHistory();
 if(name==='export-bpmn'){if(!b?.bpmn)return toast('В блоке пока нет BPMN.');return download(b.name+'.bpmn',b.bpmn,'application/xml');}
 if(name==='edit-xml'){if(!b)return;return modal('Исходный BPMN XML',`<p class="modal-note">Изменения сохранятся в проекте. Некорректный XML будет показан в проверке.</p>${field('BPMN 2.0','xml',b.bpmn,'textarea')}`,async d=>{await replaceBpmn(b,d.get('xml'));S.camera=null;renderView();});}
 if(name==='add-lane'){
  if(!b?.bpmn)return toast('Сначала создайте BPMN-схему.');
  const xmlDoc=new DOMParser().parseFromString(b.bpmn,'application/xml'),ns='http://www.omg.org/spec/BPMN/20100524/MODEL';
  const processes=[...xmlDoc.getElementsByTagNameNS(ns,'process')],participants=[...xmlDoc.getElementsByTagNameNS(ns,'participant')];
  const selected=[...xmlDoc.getElementsByTagNameNS(ns,'*')].find(node=>node.getAttribute('id')===S.element);
  const selectedId=selected?.localName==='participant'?selected.getAttribute('processRef'):selected?.parentElement?.localName==='process'?selected.parentElement.getAttribute('id'):'';
  const processField=processes.length>1?`<label class="field">Пул<select name="process_id">${processes.map(process=>{const id=process.getAttribute('id'),participant=participants.find(item=>item.getAttribute('processRef')===id);return `<option value="${esc(id)}" ${id===selectedId?'selected':''}>${esc(participant?.getAttribute('name')||process.getAttribute('name')||id)}</option>`;}).join('')}</select></label>`:'';
  return modal('Новая дорожка',processField+field('Роль или участник процесса','name','Новая дорожка')+'<p class="modal-note">Дорожка появится внутри выбранного пула. Назначайте ей действия в окне элемента BPMN.</p>',async data=>{await editBpmn({op:'add_lane',name:data.get('name'),process_id:data.get('process_id')||''});S.camera=null;renderView();},'Добавить');
 }
 if(name==='add-pool'){
  if(!b?.bpmn)return toast('Сначала создайте BPMN-схему.');
  return modal('Новый участник процесса',field('Название пула','name','Новый участник')+'<p class="modal-note">Для участника будет создан отдельный процесс. Связь между пулами станет сообщением, а не потоком последовательности.</p>',async data=>{await editBpmn({op:'add_pool',name:data.get('name')});S.camera=null;renderView();},'Добавить');
 }
 if(name==='add-node'){
  if(!b)return;
  const shapes=S.analyses.get(b.id)?.diagram.shapes||[];
  const activities=shapes.filter(shape=>shape.kind==='task'||shape.kind.endsWith('Task')||['subProcess','transaction','callActivity','adHocSubProcess'].includes(shape.kind));
  const xmlDoc=new DOMParser().parseFromString(b.bpmn||'','application/xml'),bpmnNamespace='http://www.omg.org/spec/BPMN/20100524/MODEL';
  const processes=[...xmlDoc.getElementsByTagNameNS(bpmnNamespace,'process')],localProcesses=processes.slice(1);
  const parentById=new Map([...xmlDoc.getElementsByTagNameNS(bpmnNamespace,'*')].filter(node=>node.getAttribute('id')).map(node=>[node.getAttribute('id'),node.parentElement?.getAttribute('id')||'']));
  const containers=shapes.filter(shape=>['subProcess','transaction','adHocSubProcess'].includes(shape.kind)&&shape.expanded);
  const selectedContainer=containers.find(shape=>shape.element_id===S.element||shape.element_id===parentById.get(S.element))?.element_id||'';
  const participants=[...xmlDoc.getElementsByTagNameNS(bpmnNamespace,'participant')];
  const poolName=process=>participants.find(item=>item.getAttribute('processRef')===process.getAttribute('id'))?.getAttribute('name')||process.getAttribute('name')||process.getAttribute('id');
  const selectedProcess=processes.find(process=>process.getAttribute('id')===S.element||process.getAttribute('id')===parentById.get(S.element))?.getAttribute('id')||'';
  const containerField=`<label class="field">Где добавить элемент<select name="container_id"><option value="">${esc(poolName(processes[0]))}</option>${processes.slice(1).map(process=>`<option value="${esc(process.getAttribute('id'))}" ${selectedProcess===process.getAttribute('id')?'selected':''}>Пул: ${esc(poolName(process))}</option>`).join('')}${containers.map(shape=>`<option value="${esc(shape.element_id)}" ${selectedContainer===shape.element_id?'selected':''}>Внутри: ${esc(shape.name||shape.kind)}</option>`).join('')}</select><small>Связи внутри процесса задают порядок. Между пулами связь показывает сообщение.</small></label>`;
  modal('Добавить элемент BPMN',containerField+`<label class="field">Тип элемента<select name="kind"><optgroup label="Задачи"><option value="task">Задача</option><option value="userTask">Пользовательская</option><option value="serviceTask">Сервисная</option><option value="manualTask">Ручная</option><option value="scriptTask">Скрипт</option><option value="businessRuleTask">Бизнес-правило</option><option value="sendTask">Отправка сообщения</option><option value="receiveTask">Получение сообщения</option><option value="subProcess">Подпроцесс с внутренним потоком</option><option value="adHocSubProcess">Свободный подпроцесс</option><option value="eventSubProcess">Событийный подпроцесс</option><option value="transaction">Транзакция (откат вручную)</option><option value="callActivity">Вызов другого процесса</option></optgroup><optgroup label="Данные и пояснения"><option value="dataObject">Объект данных</option><option value="textAnnotation">Текстовая аннотация</option></optgroup><optgroup label="События"><option value="startEvent">Начальное</option><option value="intermediateCatchEvent">Промежуточное ожидающее</option><option value="intermediateThrowEvent">Промежуточное отправляющее</option><option value="boundaryEvent">Граничное событие на действии</option><option value="endEvent">Конечное</option></optgroup><optgroup label="Шлюзы"><option value="exclusiveGateway">Исключающий (XOR)</option><option value="inclusiveGateway">Включающий (OR)</option><option value="parallelGateway">Параллельный (AND)</option><option value="eventBasedGateway">По событию</option><option value="complexGateway">Сложный (ручное условие)</option></optgroup></select></label><label class="field" id="bpmn-event-field">Маркер события<select name="event"><option value="">Без маркера</option><option value="message">Сообщение</option><option value="signal">Сигнал</option><option value="timer">Таймер</option><option value="conditional">Условие</option><option value="link">Ссылка внутри процесса</option><option value="error">Ошибка</option><option value="cancel">Отмена транзакции</option><option value="escalation">Эскалация</option><option value="compensate">Компенсация (вручную)</option><option value="terminate">Завершить все ветки</option></select></label><label class="field" id="bpmn-duration-field">Длительность таймера (ISO 8601)<input name="duration" placeholder="PT15M — 15 минут" value="PT15M"><small>Например: PT30S, PT2H или P1D. В сценарии срабатывание подтверждается вручную.</small></label><label class="field" id="bpmn-condition-field">Условие события<input name="condition" maxlength="1000" placeholder="Например: сумма заказа больше 100 000"><small>Условие подтверждается вручную при проигрывании сценария.</small></label><label class="field" id="bpmn-link-field">Название связи<input name="link_name" maxlength="100" placeholder="Например: Возврат к проверке"><small>Создайте принимающее и отправляющее события с одинаковым названием.</small></label><label class="field" id="bpmn-cancel-scope-field">Транзакция для ветки отмены<select name="scope">${activities.filter(shape=>shape.kind==='transaction').map(shape=>`<option value="${esc(shape.element_id)}">${esc(shape.name||'Транзакция')}</option>`).join('')}</select><small>Facet добавит выбор между обычным завершением и отменой внутрь новой транзакции.</small></label><label class="field" id="bpmn-call-field">Вызываемый процесс<select name="called_element"><option value="">Внешний процесс — подтвердить вручную</option>${localProcesses.map(process=>`<option value="${esc(process.getAttribute('id'))}">${esc(process.getAttribute('name')||process.getAttribute('id'))}</option>`).join('')}</select><small>Выберите процесс из этой BPMN-схемы или подтвердите внешний вызов вручную в сценарии.</small></label><div id="bpmn-boundary-fields"><label class="field">Действие, на котором произошло событие<select name="attached_to">${activities.map(shape=>`<option value="${esc(shape.element_id)}" data-parent="${esc(parentById.get(shape.element_id)||'')}">${esc(shape.name||shape.kind)}</option>`).join('')}</select></label><label class="field"><input type="checkbox" name="interrupting" checked> Прервать действие</label></div><label class="field" id="bpmn-trigger-field">Режим событийного подпроцесса<label><input type="checkbox" name="trigger_interrupting" checked> Прервать основной процесс</label></label>`+field('Название','name','Новая задача'),async d=>{const requestedKind=d.get('kind'),triggered=requestedKind==='eventSubProcess',kind=triggered?'subProcess':requestedKind,event=d.get('event');if(kind==='boundaryEvent'&&(!activities.length||!event))throw new Error('Выберите действие и тип граничного события.');if(triggered&&!['message','signal','timer','conditional','error','escalation'].includes(event))throw new Error('Выберите событие запуска подпроцесса.');const x=shapes.length?Math.max(...shapes.map(s=>s.x+s.width))+70:100;await editBpmn({op:'add',kind,event:triggered?'':event,triggered_by_event:triggered,instantiate:kind==='eventBasedGateway'&&d.has('instantiate'),receive_instantiate:kind==='receiveTask'&&d.has('receive_instantiate'),event_gateway_type:d.get('event_gateway_type')||'Exclusive',multi_instance_count:d.get('loop_mode')==='multi'&&d.get('multi_instance_count')?Number(d.get('multi_instance_count')):null,multi_instance_sequential:d.get('loop_mode')==='multi'&&d.has('multi_instance_sequential'),multi_instance_completion:d.get('loop_mode')==='multi'?d.get('multi_instance_completion')||'':'',standard_loop:d.get('loop_mode')==='standard',standard_loop_condition:d.get('loop_mode')==='standard'?d.get('standard_loop_condition')||'':'',standard_loop_maximum:d.get('loop_mode')==='standard'&&d.get('standard_loop_maximum')?Number(d.get('standard_loop_maximum')):null,standard_loop_test_before:d.get('loop_mode')==='standard'&&d.has('standard_loop_test_before'),trigger_event:triggered?event:'',name:d.get('name'),attached_to:d.get('attached_to'),interrupting:triggered?event==='error'||d.has('trigger_interrupting'):['error','cancel'].includes(event)||d.has('interrupting'),duration:d.get('duration'),condition:d.get('condition'),link_name:d.get('link_name'),scope:d.get('scope'),container_id:d.get('container_id'),called_element:d.get('called_element'),ad_hoc_ordering:d.get('ad_hoc_ordering')||'Parallel',ad_hoc_completion:d.get('ad_hoc_completion')||'',x,y:100});S.camera=null;renderView();},'Добавить');
  const gatewayField=document.createElement('div');gatewayField.id='bpmn-gateway-field';gatewayField.innerHTML='<label class="field">Режим событийного шлюза<select name="event_gateway_type"><option value="Exclusive">Первое событие выбирает путь</option><option value="Parallel">Дождаться всех событий</option></select></label><label class="field"><input type="checkbox" name="instantiate"> Запускать процесс этим шлюзом</label><small>После создания соедините шлюз минимум с двумя ожидающими событиями или задачами получения.</small>';
  $('#bpmn-trigger-field').insertAdjacentElement('afterend',gatewayField);
  const receiveField=document.createElement('label');receiveField.className='field';receiveField.id='bpmn-receive-field';receiveField.innerHTML='<input type="checkbox" name="receive_instantiate"> Получение сообщения запускает процесс<small>Такая задача не имеет входящего потока. В сценарии получение подтверждается вручную.</small>';
  gatewayField.insertAdjacentElement('afterend',receiveField);
  const adHocField=document.createElement('div');adHocField.id='bpmn-ad-hoc-field';adHocField.innerHTML='<label class="field">Порядок действий<select name="ad_hoc_ordering"><option value="Parallel">Параллельно</option><option value="Sequential">По очереди</option></select></label><label class="field">Условие завершения<input name="ad_hoc_completion" maxlength="1000" placeholder="Например: все документы согласованы"></label><small>В сценарии внутренние действия выбираются вручную и могут повторяться. Завершение подтверждается вручную.</small>';
  receiveField.insertAdjacentElement('afterend',adHocField);
  const multiField=document.createElement('div');multiField.id='bpmn-multi-field';multiField.innerHTML='<label class="field">Экземпляров действия<input type="number" name="multi_instance_count" min="1" max="20" placeholder="Один обычный шаг"></label><label class="field"><input type="checkbox" name="multi_instance_sequential"> Выполнять по очереди</label><label class="field">Условие досрочного завершения<input name="multi_instance_completion" maxlength="1000" placeholder="Например: получено одно согласование"></label><small>Условие проверяется после завершения каждого экземпляра. В сценарии подтвердите его вручную.</small>';
  gatewayField.insertAdjacentElement('afterend',multiField);
  const loopField=document.createElement('label');loopField.className='field';loopField.id='bpmn-loop-field';loopField.innerHTML='Повторение<select name="loop_mode"><option value="">Без повторения</option><option value="multi">Несколько экземпляров</option><option value="standard">Обычный цикл</option></select>';
  multiField.insertAdjacentElement('beforebegin',loopField);
  const standardField=document.createElement('div');standardField.id='bpmn-standard-field';standardField.innerHTML='<label class="field">Условие продолжения цикла<input name="standard_loop_condition" maxlength="1000" placeholder="Например: есть ещё заявки"></label><label class="field">Максимум повторов<input type="number" name="standard_loop_maximum" min="1" max="20" placeholder="Необязательно"></label><label class="field"><input type="checkbox" name="standard_loop_test_before"> Проверять условие до первого повтора</label><small>В сценарии результат условия подтверждается вручную после каждой итерации.</small>';
  multiField.insertAdjacentElement('afterend',standardField);
  const kind=$('#modal-body [name="kind"]'),containerSelect=$('#modal-body [name="container_id"]'),marker=$('#bpmn-event-field'),boundary=$('#bpmn-boundary-fields'),event=$('#modal-body [name="event"]'),duration=$('#bpmn-duration-field'),condition=$('#bpmn-condition-field'),link=$('#bpmn-link-field'),cancelScope=$('#bpmn-cancel-scope-field'),callField=$('#bpmn-call-field'),triggerField=$('#bpmn-trigger-field');
  const gatewayMode=gatewayField.querySelector('[name="event_gateway_type"]'),gatewayInstantiate=gatewayField.querySelector('[name="instantiate"]');
  gatewayMode.onchange=()=>{if(gatewayMode.value==='Parallel')gatewayInstantiate.checked=true;};
  gatewayInstantiate.onchange=()=>{if(!gatewayInstantiate.checked)gatewayMode.value='Exclusive';};
  event.onchange=()=>{duration.style.display=event.value==='timer'?'':'none';condition.style.display=event.value==='conditional'?'':'none';link.style.display=event.value==='link'?'':'none';cancelScope.style.display=event.value==='cancel'&&kind.value==='endEvent'?'':'none';const triggerInterrupt=triggerField.querySelector('[name="trigger_interrupting"]');triggerInterrupt.disabled=kind.value==='eventSubProcess'&&event.value==='error';if(triggerInterrupt.disabled)triggerInterrupt.checked=true;const interrupt=boundary.querySelector('[name="interrupting"]');interrupt.disabled=['error','cancel'].includes(event.value);if(interrupt.disabled)interrupt.checked=true;const host=boundary.querySelector('[name="attached_to"]');for(const option of host.options)option.disabled=option.dataset.parent!==(containerSelect.value||processes[0]?.getAttribute('id'))||(event.value==='cancel'&&!activities.some(shape=>shape.element_id===option.value&&shape.kind==='transaction'));if(host.selectedOptions[0]?.disabled)host.value=[...host.options].find(option=>!option.disabled)?.value||'';};
  containerSelect.onchange=event.onchange;
  kind.addEventListener('change',()=>{gatewayField.hidden=kind.value!=='eventBasedGateway';receiveField.hidden=kind.value!=='receiveTask';adHocField.hidden=kind.value!=='adHocSubProcess';const nameInput=$('#modal-body [name="name"]');nameInput.parentElement.firstChild.textContent=kind.value==='textAnnotation'?'Текст':kind.value==='dataObject'?'Название данных':'Название';if(['Новая задача','Данные','Пояснение'].includes(nameInput.value))nameInput.value=kind.value==='textAnnotation'?'Пояснение':kind.value==='dataObject'?'Данные':'Новая задача';});
  const loopMode=loopField.querySelector('[name="loop_mode"]');
  function updateLoopFields(){const task=kind.value==='task'||kind.value.endsWith('Task'),activity=task||['subProcess','transaction','callActivity'].includes(kind.value);loopField.hidden=!activity;multiField.hidden=!activity||loopMode.value!=='multi';standardField.hidden=!activity||loopMode.value!=='standard';if(!activity)loopMode.value='';}
  kind.addEventListener('change',updateLoopFields);loopMode.addEventListener('change',updateLoopFields);updateLoopFields();
  gatewayField.hidden=true;receiveField.hidden=true;adHocField.hidden=true;
  kind.onchange=()=>{callField.style.display=kind.value==='callActivity'?'':'none';marker.style.display=kind.value.endsWith('Event')||kind.value==='eventSubProcess'?'':'none';triggerField.style.display=kind.value==='eventSubProcess'?'':'none';boundary.style.display=kind.value==='boundaryEvent'?'':'none';const allowed={link:['intermediateCatchEvent','intermediateThrowEvent'],conditional:['startEvent','intermediateCatchEvent','boundaryEvent'],timer:['startEvent','intermediateCatchEvent','boundaryEvent'],error:['boundaryEvent','endEvent'],cancel:activities.some(shape=>shape.kind==='transaction')?['boundaryEvent','endEvent']:[],escalation:['boundaryEvent','intermediateThrowEvent','endEvent'],compensate:['intermediateThrowEvent'],terminate:['endEvent']};for(const type of ['link','cancel','compensate','terminate'])if(kind.value==='eventSubProcess')allowed[type]=[];for(const type of ['timer','conditional','error','escalation'])if(kind.value==='eventSubProcess')allowed[type]=['eventSubProcess'];for(const [type,kinds] of Object.entries(allowed))event.querySelector('option[value="'+type+'"]').disabled=!kinds.includes(kind.value);if(kind.value==='eventSubProcess'){event.querySelector('option[value=""]').disabled=true;event.value='message';}else{event.querySelector('option[value=""]').disabled=false;if(kind.value!=='boundaryEvent'||event.selectedOptions[0]?.disabled)event.value='';}event.onchange();};kind.onchange();
  return;
 }
 if(name==='connect-node'){S.connect=S.connect?null:{source:null};if(S.connect)canvasMode='edit';renderView();return;}
 if(name==='undo-bpmn'){const history=S.undo.get(b?.id);if(!history?.length)return toast('Нет действий для отмены.');const xml=history.pop();b.bpmn=xml;await analyzeBlock(b);await save();S.element=null;S.camera=null;renderView();renderIssues();return;}
 if(name==='uml-actors'){
  if(!b)return;const actors=structuredClone(activeUml(b).participants);
  function rows(){return actors.map((a,i)=>`<div class="actor-row"><input data-actor-index="${i}" value="${esc(a.name)}" aria-label="Имя участника"><button type="button" data-remove-actor="${i}" aria-label="Удалить участника">×</button></div>`).join('');}
  modal('Участники UML',`<p class="modal-note">Слева направо: пользователь, приложение, внешние сервисы. При удалении участника удаляются его сообщения.</p><div id="actor-rows">${rows()}</div><button type="button" id="append-actor">+ Участник</button>`,async()=>{if(actors.some(a=>!a.name.trim()))throw new Error('Заполните имена участников.');activeUml(b).participants=actors;activeUml(b).messages=activeUml(b).messages.filter(m=>actors.some(a=>a.id===m.from)&&actors.some(a=>a.id===m.to));S.camera=null;renderInspector();renderView();await save();});
  $('#append-actor').onclick=()=>{actors.push({id:uid(),name:'Новый участник'});$('#actor-rows').innerHTML=rows();};
  $('#actor-rows').oninput=e=>{if(e.target.dataset.actorIndex!==undefined)actors[Number(e.target.dataset.actorIndex)].name=e.target.value;};
  $('#actor-rows').onclick=e=>{if(e.target.dataset.removeActor!==undefined){actors.splice(Number(e.target.dataset.removeActor),1);$('#actor-rows').innerHTML=rows();}};return;
 }
 if(name==='uml-message'){if(!b||!activeUml(b).participants.length)return action('uml-actors');const options=activeUml(b).participants.map(a=>`<option value="${esc(a.id)}">${esc(a.name)}</option>`).join('');return modal('Новое сообщение',`<div class="row"><label class="field">От кого<select name="from">${options}</select></label><label class="field">Кому<select name="to">${options}</select></label></div>`+field('Сообщение','text')+`<label class="field">Тип<select name="kind"><option value="call">Вызов</option><option value="return">Ответ</option></select></label>`,async d=>{if(!d.get('text').trim())throw new Error('Укажите сообщение.');activeUml(b).messages.push({id:uid(),from:d.get('from'),to:d.get('to'),text:d.get('text'),kind:d.get('kind')});S.camera=null;renderInspector();renderView();await save();},'Добавить');}
 if(name==='uml-messages'){
  const messages=structuredClone(activeUml(b).messages);function rows(){return messages.map((m,i)=>`<div class="message-row"><span>${i+1}. ${esc(m.text)}</span><button type="button" data-msg-up="${i}" ${i===0?'disabled':''}>↑</button><button type="button" data-msg-remove="${i}">×</button></div>`).join('')||'<p class="modal-note">Сообщений пока нет.</p>';}
  modal('Порядок сообщений',`<p class="modal-note">Переставляйте или удаляйте сообщения. Для нового сообщения используйте кнопку «+ Сообщение».</p><div id="message-rows">${rows()}</div>`,async()=>{activeUml(b).messages=messages;S.camera=null;renderInspector();renderView();await save();});
  $('#message-rows').onclick=e=>{if(e.target.dataset.msgUp!==undefined){const i=Number(e.target.dataset.msgUp);if(i>0)[messages[i-1],messages[i]]=[messages[i],messages[i-1]];}else if(e.target.dataset.msgRemove!==undefined)messages.splice(Number(e.target.dataset.msgRemove),1);$('#message-rows').innerHTML=rows();};return;
 }
 if(name==='export-svg'){const svg=$('.diagram-svg');if(svg)download(b.name+'.svg',new XMLSerializer().serializeToString(svg),'image/svg+xml');return;}
 if(name==='export-text')return download(b.name+(S.view==='technical'?'-api.txt':'-requirements.txt'),b[S.view==='technical'?'technical':'requirements'],'text/plain');
 if(name==='import-slides'){
  if(!canEdit())return toast('У вас нет права редактировать проект.',true);
  const picker=$('#file-input');picker.value='';picker.accept='.pptx';
  picker.onchange=async()=>{const file=picker.files[0];if(!file)return;try{
   if(!/\.pptx$/i.test(file.name)||file.size>7*1024*1024)throw new Error('Выберите PPTX размером до 7 МБ.');
   const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Не удалось прочитать файл.'));reader.readAsDataURL(file);});
   const result=await api('/api/presentation/extract','POST',{project_id:S.project.id,content});
   const proposed=suggestSlideMatches(result.slides,S.project.blocks);let agentMatches=new Map();const projectId=S.project.id;
   const rows=result.slides.map((source,index)=>{const match=proposed.get(index);return `<label class="pptx-match"><span><strong>${source.number}. ${esc(source.title)}</strong><small>${esc(source.lines.slice(0,2).join(' · ').slice(0,130)||'Без текста')}${match?' · предложена связь':''}${source.image?' · изображение': ''}</small>${source.image_note?`<small>${esc(source.image_note)}</small>`:''}<small class="pptx-ai-note"></small></span><select name="slide_${index}" aria-label="Блок для слайда ${source.number}"><option value="">Пропустить</option><option value="__new__" ${match?'':'selected'}>+ Создать блок из слайда</option>${S.project.blocks.map(item=>`<option value="${esc(item.id)}" ${item.id===match?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label>`;}).join('');
   modal('Сопоставить PPTX с проектом',`<p class="modal-note">Facet предложил связи по заголовкам и содержимому. Проверьте их перед импортом: несколько слайдов можно привязать к одному блоку без создания лишних блоков. Первый обновит основной слайд блока, остальные добавятся в презентацию. Слайды с выбором «Пропустить» не импортируются.</p><button type="button" id="pptx-ai-suggest" class="soft">✦ Уточнить сопоставление с агентом</button><p id="pptx-ai-status" class="modal-note" role="status">Агент предложит связи по содержимому блоков и шагам BPMN. Подтвердите импорт сами.</p><div class="pptx-match-list">${rows}</div>`,async data=>{if(S.project?.id!==projectId)throw new Error('Проект изменился. Откройте импорт заново.');const selected=result.slides.map((source,index)=>({source,id:data.get('slide_'+index),suggestion:agentMatches.get(source.number)})).filter(item=>item.id);const prepared=prepareSlideImport(S.project,selected);S.project.blocks=prepared.blocks;S.project.presentation_extra_slides=prepared.extras;S.project.presentation_order=prepared.order;S.slide=0;S.selected=prepared.blocks.find(item=>item.id===prepared.order[0])?.id||prepared.extras.find(item=>item.id===prepared.order[0])?.block_id;if(!await save())throw new Error('Сохранение не удалось. Экспортируйте проект перед обновлением страницы.');renderInspector();renderView();toast('Слайды импортированы в проект.');},'Импортировать выбранные');
   $('#pptx-ai-suggest').onclick=async event=>{const button=event.currentTarget;button.disabled=true;const status=$('#pptx-ai-status');status.textContent='Агент анализирует слайды и BPMN…';try{const suggested=await api('/api/presentation/suggest','POST',{project_id:projectId,slides:result.slides});if(!$('#modal').open||$('#modal-title').textContent!=='Сопоставить PPTX с проектом'||S.project?.id!==projectId)return;agentMatches=new Map(suggested.matches.map(item=>[item.slide_number,item]));result.slides.forEach((slide,index)=>{const match=agentMatches.get(slide.number),row=$('#modal-body [name="slide_'+index+'"]')?.closest('.pptx-match');if(!row)return;row.querySelector('select').value=match?.block_id||'__new__';row.querySelector('.pptx-ai-note').textContent=match?'✦ '+match.reason+' · '+match.title:'Агент не нашёл надёжную связь';});status.textContent='Предложения агента готовы. Проверьте связи и импортируйте выбранные слайды.';}catch(error){status.textContent=error.message+' Можно продолжить с предложениями по заголовкам.';}finally{button.disabled=false;}};
  }catch(error){toast(error.message,true);}};picker.click();return;
 }
 if(name==='edit-slide'){
  if(!canEdit())return toast('У вас нет права редактировать проект.',true);
  const slide=presentationBlocks()[S.slide],extra=S.project.presentation_extra_slides?.find(item=>item.id===slide.id),current=slide.slide||{};
  modal('Содержание слайда',`<p class="modal-note">Слайд связан с блоком «${esc(slide.name)}». Заголовок, тезис и пункты можно настроить отдельно от описания процесса.</p>${field('Заголовок','title',current.title??slide.name)}${field('Главный тезис','message',current.message??slide.description,'textarea')}<label class="field">Структура<select name="layout"><option value="summary" ${current.layout==='summary'||!current.layout?'selected':''}>Один тезис</option><option value="bullets" ${current.layout==='bullets'?'selected':''}>Тезис и пункты</option><option value="decision" ${current.layout==='decision'?'selected':''}>Решение и аргументы</option><option value="section" ${current.layout==='section'?'selected':''}>Раздел презентации</option></select></label>${field('Пункты — по одному на строке, максимум 6','bullets',(current.bullets||[]).join('\n'),'textarea')}${field('Заметки докладчика — не показываются на слайде','notes',current.notes||'','textarea')}<label class="field">Изображение (PNG, JPEG или WebP до 300 КБ)<input id="slide-image-file" name="image_file" type="file" accept="image/png,image/jpeg,image/webp"></label>${current.image?`<label class="field"><input name="remove_image" type="checkbox"> Удалить текущее изображение</label>`:''}<button type="button" id="slide-reset" class="soft">Вернуть данные блока</button>`,async data=>{const title=String(data.get('title')||'').trim(),message=String(data.get('message')||'').trim(),bullets=String(data.get('bullets')||'').split(/\r?\n/).map(item=>item.trim()).filter(Boolean),notes=String(data.get('notes')||'').trim();if(!title)throw new Error('Укажите заголовок слайда.');if(title.length>200||message.length>4000||notes.length>5000||bullets.length>6||bullets.some(item=>item.length>240))throw new Error('Слишком длинный слайд: до 6 пунктов по 240 символов.');let image=current.image;if(data.get('remove_image'))image=undefined;const file=data.get('image_file');if(file&&file.size){if(file.size>300_000||!['image/png','image/jpeg','image/webp'].includes(file.type))throw new Error('Выберите PNG, JPEG или WebP до 300 КБ.');image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error('Не удалось прочитать изображение.'));reader.readAsDataURL(file);});}if(extra)extra.slide={title,message,layout:data.get('layout'),bullets,notes,...(image?{image}:{})};else slide.slide={title,message,layout:data.get('layout'),bullets,notes,...(image?{image}:{})};await save();renderView();});
  $('#slide-reset').onclick=async()=>{if(extra)extra.slide={title:slide.name,message:slide.description,layout:'summary',bullets:[]};else delete slide.slide;$('#modal').close();await save();renderView();};return;
 }
 if(name==='duplicate-slide'){
  if(!canEdit())return;const slides=presentationBlocks();if(slides.length>=200)return toast('В презентации допускается до 200 слайдов.',true);
  const source=slides[S.slide],entry={id:uid(),block_id:source.block_id||source.id,slide:structuredClone(source.slide||{title:source.name,message:source.description,layout:'summary',bullets:[]})};
  (S.project.presentation_extra_slides??=[]).push(entry);slides.splice(S.slide+1,0,entry);S.project.presentation_order=slides.map(item=>item.id);S.slide++;await save();renderView();return;
 }
 if(name==='delete-slide'){
  if(!canEdit())return;const slides=presentationBlocks(),source=slides[S.slide];if(!source.block_id)return;
  modal('Удалить слайд?',`<p class="modal-note">Дополнительный слайд «${esc(source.slide?.title||source.name)}» будет удалён. Блок проекта и его BPMN сохранятся.</p>`,async()=>{S.project.presentation_extra_slides=S.project.presentation_extra_slides.filter(item=>item.id!==source.id);S.project.presentation_order=(S.project.presentation_order||[]).filter(id=>id!==source.id);S.slide=Math.min(S.slide,presentationBlocks().length-1);S.selected=presentationBlocks()[S.slide]?.block_id||presentationBlocks()[S.slide]?.id;await save();renderInspector();renderView();},'Удалить');return;
 }
 if(name==='slide-up'||name==='slide-down'){if(!canEdit())return;const slides=presentationBlocks(),next=S.slide+(name==='slide-up'?-1:1);if(next<0||next>=slides.length)return;[slides[S.slide],slides[next]]=[slides[next],slides[S.slide]];S.project.presentation_order=slides.map(item=>item.id);S.slide=next;await save();renderView();return;}
 if(name==='prev-slide'||name==='next-slide'){const slides=presentationBlocks();S.slide=Math.max(0,Math.min(slides.length-1,S.slide+(name==='prev-slide'?-1:1)));S.selected=slides[S.slide]?.block_id||slides[S.slide]?.id;renderInspector();renderView();return;}
 if(name==='export-pptx'){
  const slides=presentationBlocks();if(!slides.length)return toast('Сначала создайте блоки для презентации.',true);
  await loadPptxLibrary();
  const prepared=await Promise.all(slides.map(async item=>({...item,slide:{...item.slide,...(item.slide?.image?{image:await pptxImage(item.slide.image)}:{})}})));
  const pptx=window.FacetPptx.build(new window.PptxGenJS(),prepared,S.project.name,statusNames);
  await pptx.writeFile({fileName:(S.project.name.replace(/[\\/:*?"<>|]/g,'_').trim()||'Facet')+'.pptx',compression:true});
  return toast('Презентация PPTX сохранена.');
 }
 if(name==='export-slides'||name==='print-slides'){
  if(!presentationBlocks().length)return toast('Сначала создайте блоки для презентации.',true);
  const style='body{margin:0;background:#f2eff8;font-family:system-ui;color:#302b49}.slide{box-sizing:border-box;background:white;min-height:70vh;max-width:1000px;margin:40px auto;padding:70px;border-radius:20px;page-break-after:always;display:flex;flex-direction:column}.eyebrow{color:#9a80c7;font-size:13px}h2{font-size:46px;margin:24px 0}.slide-description{font-size:24px;line-height:1.6;white-space:pre-wrap}.slide-points{font-size:21px;line-height:1.55;margin:24px 0}.slide-points li{margin:9px 0}.slide-image{max-width:100%;max-height:34vh;object-fit:contain;align-self:center;margin:18px 0}.slide-decision-label{order:-1;color:#7958d6;font-weight:700;text-transform:uppercase;letter-spacing:.1em}.slide-footer{margin-top:auto;padding-top:70px;display:flex;justify-content:space-between;color:#9a92ac}.slide-section{justify-content:center;background:linear-gradient(135deg,#e9edff,#f8eafb)}.slide-section h2{font-size:64px}.slide-section .slide-description{font-size:28px}.slide-section .slide-footer{display:none}@page{size:landscape;margin:0}@media print{body{background:white}.slide{margin:0;padding:35px;border-radius:0;min-height:100vh}}';
  const html=`<!doctype html><html lang="ru"><meta charset="utf-8"><title>${esc(S.project.name)} · слайды</title><style>${style}</style><body>${presentationBlocks().map(slideHTML).join('')}</body></html>`;
  if(name==='export-slides')return download(S.project.name+'-slides.html',html,'text/html');
  const preview=window.open('','_blank');if(!preview)return toast('Разрешите всплывающее окно, чтобы открыть печатный просмотр.',true);
  preview.document.open();preview.document.write(html);preview.document.close();preview.focus();preview.print();return;
 }
}
document.addEventListener('click',async e=>{try{
 const view=e.target.closest('[data-view]');if(view)return setView(view.dataset.view);
 const blockEl=e.target.closest('[data-block]');if(blockEl)return selectBlock(blockEl.dataset.block);
 const act=e.target.closest('[data-action]');if(act)return await action(act.dataset.action);
 const unlink=e.target.closest('[data-unlink]');if(unlink){S.project.links=S.project.links.filter(l=>l.id!==unlink.dataset.unlink);render();await save();return;}
 const issue=e.target.closest('[data-issue]');if(issue){const i=S.analyses.get(S.selected)?.report.issues[Number(issue.dataset.issue)];if(i){S.element=i.element_id;if(S.view==='bpmn')renderCanvas();}return;}
}catch(err){toast(err.message,true);}});
$('#issues').addEventListener('dblclick',e=>{const row=e.target.closest('[data-issue]');if(!row)return;const i=S.analyses.get(S.selected)?.report.issues[Number(row.dataset.issue)];if(i)focusElement(i.element_id);});
$('#issues').addEventListener('keydown',e=>{if(e.key==='Enter'){const row=e.target.closest('[data-issue]');const i=S.analyses.get(S.selected)?.report.issues[Number(row?.dataset.issue)];if(i)focusElement(i.element_id);}});
$('#add-block').onclick=$('#add-sidebar').onclick=addBlock;
$('#project-select').onchange=async e=>{try{if(e.target.value==='__new'){e.target.value=S.project?.id||'';newProjectDialog();}else await openProject(e.target.value);}catch(err){toast(err.message,true);}};
$('#project-menu').onclick=()=>{if(!S.project)return newProjectDialog();
 modal('Настройки проекта',field('Название проекта','name',S.project.name)+field('Цель проекта','goal',S.project.goal,'textarea')+'<div class="modal-actions"><button type="button" id="export-project">↓ Экспорт проекта</button><button type="button" id="import-project">↑ Импорт проекта</button><button type="button" id="create-project">+ Новый проект</button></div><p class="modal-note">JSON-экспорт включает блоки, связи и все представления. Импорт создаёт отдельный проект.</p>',async d=>{if(!d.get('name').trim())throw new Error('Укажите название.');S.project.name=d.get('name');S.project.goal=d.get('goal');render();await save();await refreshProjects();});
 $('#modal-form [name="name"]').disabled=!canEdit();$('#modal-form [name="goal"]').disabled=!canEdit();$('#submit-modal').hidden=!canEdit();
 $('#export-project').onclick=()=>download(S.project.name+'.project.json',JSON.stringify(S.project,null,2));
 $('#create-project').onclick=newProjectDialog;
 $('#import-project').onclick=()=>chooseFile('.json',async text=>{if(S.pending)await S.queue;if(S.failed)throw new Error('Экспортируйте свои правки перед импортом.');const p=await api('/api/projects','POST',{project:JSON.parse(text),space_id:A.space});$('#modal').close();await refreshProjects();await openProject(p.id);toast('Проект импортирован.');});
};
$('#zoom-in').onclick=()=>zoom(.8);$('#zoom-out').onclick=()=>zoom(1.25);$('#fit').onclick=()=>fit();
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await $('#workspace').requestFullscreen();}catch{toast('Браузер не разрешил полноэкранный режим.',true);}}
$('#fullscreen').onclick=fullscreen;
$('#present').onclick=()=>{if(!S.project?.blocks.length)return toast('Создайте блоки для презентации.');setView('slides');fullscreen();};
$('#toggle-issues').onclick=()=>{const collapsed=$('#issues-panel').classList.toggle('collapsed');$('#toggle-issues').textContent=collapsed?'+':'−';$('.canvas-controls').style.bottom=collapsed&&!document.fullscreenElement?'62px':'';};
document.addEventListener('fullscreenchange',()=>{(document.fullscreenElement||document.body).append($('#toast'));requestAnimationFrame(()=>{S.camera=null;if($('.diagram-svg'))fit();});$('#fullscreen').title=document.fullscreenElement?'Выйти из полного экрана':'На весь экран';const exit=$('[data-walk-fullscreen]');if(exit)exit.textContent=document.fullscreenElement?'Уменьшить окно':'На весь экран';});
let drag=null;
let lastBpmnTap={id:null,at:0};
$('#content').tabIndex=0;
$('#view-actions').addEventListener('click',e=>{
 const mode=e.target.closest('[data-canvas-mode]');if(!mode||mode.disabled)return;
 canvasMode=mode.dataset.canvasMode;S.connect=null;updateCanvasMode();
 $('#view-hint').textContent='Два пальца — прокрутка · щипок или Ctrl + колесо — масштаб · пробел + перетаскивание — рука';
 const connect=$('[data-action="connect-node"]');if(connect)connect.textContent='↗ Связь';
});
function point(event){const svg=$('.diagram-svg');if(!svg)return{x:0,y:0};const pt=new DOMPoint(event.clientX,event.clientY);const matrix=svg.getScreenCTM();return matrix?pt.matrixTransform(matrix.inverse()):{x:0,y:0};}
$('#content').addEventListener('pointerdown',async e=>{
 if(![0,1].includes(e.button)||S.busy||!e.target.closest('svg'))return;
 $('#content').focus({preventScroll:true});
 const hitItem=e.target.closest('[data-id]'),hitEdge=e.target.closest('[data-edge]');
 const hitId=hitItem?.dataset.id||hitEdge?.dataset.edge;
 if(S.view==='bpmn'&&hitId){const now=Date.now();if((e.detail>1||(lastBpmnTap.id===hitId&&now-lastBpmnTap.at<430))){lastBpmnTap={id:null,at:0};drag=null;e.preventDefault();openBpmnElement(hitId);return;}lastBpmnTap={id:hitId,at:now};}
 const pan=spacePan||e.button===1||(S.view==='bpmn'&&canvasMode==='pan');
 const item=pan?null:hitItem,edge=pan?null:hitEdge;
 if(S.connect&&S.view==='bpmn'&&item){const id=item.dataset.id;if(!S.connect.source){S.connect.source=id;S.element=id;renderCanvas();toast('Теперь выберите конечный элемент.');}else{const source=S.connect.source;S.connect=null;await editBpmn({op:'connect',source,target:id});renderView();}return;}
 if(edge&&S.view==='bpmn'){S.element=edge.dataset.edge;renderCanvas();return;}
 const p=point(e);drag={id:item?.dataset.id,view:S.view,start:p,client:{x:e.clientX,y:e.clientY},camera:{...S.camera},moved:false,dx:0,dy:0};
 if(item&&S.view==='overview'){S.selected=item.dataset.id;renderInspector();$('#block-list').querySelectorAll('[data-block]').forEach(el=>el.classList.toggle('active',el.dataset.block===S.selected));renderIssues();drag.original=structuredClone(block());document.querySelectorAll('.block-card .card-bg').forEach(r=>{const active=r.parentElement.dataset.id===S.selected;r.setAttribute('stroke',active?'#ad90e3':'#e2e7f1');r.setAttribute('fill',active?'#f5f0ff':'white');});}
 if(item&&S.view==='bpmn'){S.element=item.dataset.id;drag.original=structuredClone(S.analyses.get(S.selected).diagram);document.querySelectorAll('.node').forEach(n=>n.classList.toggle('selected',n.dataset.id===S.element));}
 if(!canEdit()&&drag)drag.id=null;
 $('#content').setPointerCapture(e.pointerId);
 applyAccess();if(!item||pan||e.button===1)e.preventDefault();
});
window.addEventListener('pointermove',e=>{
 if(!drag)return;const dist=Math.hypot(e.clientX-drag.client.x,e.clientY-drag.client.y);if(dist<4&&!drag.moved)return;drag.moved=true;
 const p=point(e);drag.dx=p.x-drag.start.x;drag.dy=p.y-drag.start.y;
 if(!drag.id){const svg=$('.diagram-svg');if(!svg)return;const ratio=drag.camera.w/svg.clientWidth;S.camera={...drag.camera,x:drag.camera.x-(e.clientX-drag.client.x)*ratio,y:drag.camera.y-(e.clientY-drag.client.y)*ratio};applyCamera();return;}
 if(drag.view==='overview'){const b=block();b.x=drag.original.x+drag.dx;b.y=drag.original.y+drag.dy;renderCanvas();}
 else if(drag.view==='bpmn'){const d=structuredClone(drag.original),s=d.shapes.find(x=>x.element_id===drag.id);if(!s||s.attached_to)return;const group=new Set([s.element_id]);if(['lane','participant'].includes(s.kind)||s.expanded)d.shapes.forEach(n=>{if(n.x>=s.x&&n.y>=s.y&&n.x+n.width<=s.x+s.width&&n.y+n.height<=s.y+s.height)group.add(n.element_id);});d.shapes.forEach(n=>{if(group.has(n.attached_to))group.add(n.element_id);});d.shapes.forEach(n=>{if(group.has(n.element_id)){n.x+=drag.dx;n.y+=drag.dy;if(n.label){n.label[0]+=drag.dx;n.label[1]+=drag.dy;}}});d.edges.forEach(edge=>{const a=group.has(edge.source_id),b=group.has(edge.target_id);if(a&&b)edge.points=edge.points.map(([x,y])=>[x+drag.dx,y+drag.dy]);else if(a||b){const first=a?0:edge.points.length-1;edge.points[first][0]+=drag.dx;edge.points[first][1]+=drag.dy;}});S.analyses.get(S.selected).diagram=d;renderCanvas();}
});
window.addEventListener('pointerup',async()=>{if(!drag)return;const d=drag;drag=null;if(!d.moved)return;if(d.view==='overview'&&d.id){save();}else if(d.view==='bpmn'&&d.id){S.analyses.get(S.selected).diagram=d.original;await editBpmn({op:'move',id:d.id,dx:d.dx,dy:d.dy});}});
window.addEventListener('pointercancel',()=>{if(drag?.id){if(drag.view==='overview')Object.assign(block(),drag.original);if(drag.view==='bpmn')S.analyses.get(S.selected).diagram=drag.original;renderCanvas();}drag=null;});
function openBpmnElement(id){
 if(S.view!=='bpmn'||!id)return;
 const d=S.analyses.get(S.selected)?.diagram;
 const n=d?.shapes.find(x=>x.element_id===id)||d?.edges.find(x=>x.element_id===id);if(!n)return;
 const isTask=n.kind==='task'||n.kind.endsWith('Task')||['subProcess','callActivity','transaction','adHocSubProcess'].includes(n.kind);
 const existing=block().element_details?.find(x=>x.element_id===id);
 const namespace='http://www.omg.org/spec/BPMN/20100524/MODEL',xmlDoc=new DOMParser().parseFromString(S.analyses.get(S.selected).xml,'application/xml');
 const semanticNode=[...xmlDoc.getElementsByTagNameNS(namespace,'*')].find(node=>node.getAttribute('id')===id);
 const adHocNode=n.kind==='adHocSubProcess'?semanticNode:null;
 const adHocCondition=[...(adHocNode?.children||[])].find(node=>node.localName==='completionCondition')?.textContent||'';
 const adHocForm=adHocNode?`<label class="field">Порядок действий<select name="ad_hoc_ordering"><option value="Parallel" ${adHocNode.getAttribute('ordering')!=='Sequential'?'selected':''}>Параллельно</option><option value="Sequential" ${adHocNode.getAttribute('ordering')==='Sequential'?'selected':''}>По очереди</option></select></label><label class="field">Условие завершения<input name="ad_hoc_completion" maxlength="1000" value="${esc(adHocCondition)}"></label><label class="field"><input type="checkbox" name="ad_hoc_cancel_remaining" ${adHocNode.getAttribute('cancelRemainingInstances')!=='false'?'checked':''}> Прервать незавершённые действия при завершении</label>`:'';
 const laneable=semanticNode?.parentNode?.localName==='process'&&(n.kind==='task'||n.kind.endsWith('Task')||n.kind.endsWith('Gateway')||(n.kind.endsWith('Event')&&n.kind!=='boundaryEvent')||['subProcess','transaction','adHocSubProcess','callActivity'].includes(n.kind));
 const laneSet=laneable?[...semanticNode.parentNode.childNodes].find(node=>node.nodeType===1&&node.namespaceURI===namespace&&node.localName==='laneSet'):null;
 const lanes=laneSet?[...laneSet.childNodes].filter(node=>node.nodeType===1&&node.namespaceURI===namespace&&node.localName==='lane'):[];
 const laneForm=lanes.length?`<label class="field">Дорожка<select name="lane_id"><option value="">Без дорожки</option>${lanes.map(lane=>`<option value="${esc(lane.getAttribute('id'))}" ${n.lane_id===lane.getAttribute('id')?'selected':''}>${esc(lane.getAttribute('name')||'Дорожка')}</option>`).join('')}</select></label>`:'';
 async function saveBpmnNode(data){await editBpmn(n.kind==='adHocSubProcess'?{op:'configure_ad_hoc',id,name:data.get('name'),ad_hoc_ordering:data.get('ad_hoc_ordering'),ad_hoc_completion:data.get('ad_hoc_completion'),ad_hoc_cancel_remaining:data.has('ad_hoc_cancel_remaining')}:laneForm&&data.get('lane_id')!==(n.lane_id||'')?{op:'assign_lane',id,name:data.get('name'),lane_id:data.get('lane_id')}:{op:'rename',id,name:data.get('name')});}
 modal('Элемент BPMN',`<p class="modal-note">${esc(n.kind)} · ${esc(id)}</p>`+field(n.kind==='textAnnotation'?'Текст':'Название','name',n.name)+laneForm+adHocForm+(isTask?linkedRequirementPanel(id)+(existing?reviewPanel(existing):'')+taskFields(existing)+`<button type="button" id="open-task-uml" class="soft">${existing?'Открыть UML':'Создать UML'}</button>`:'')+(canEdit()&&['subProcess','transaction','adHocSubProcess'].includes(n.kind)&&!n.expanded?'<button type="button" id="expand-bpmn-node" class="soft">Раскрыть внутренний поток</button>':'')+(canEdit()?button(n.kind==='participant'?'Удалить пул':'Удалить элемент','delete-node','danger'):''),async data=>{
  if(!canEdit())return;
  await saveBpmnNode(data);
  if(isTask){const b=block();let detail=b.element_details?.find(x=>x.element_id===id);if(detail||Object.values(readTaskFields(data)).some(value=>value.trim())){if(!detail){detail={element_id:id,description:'',uml:{participants:[],messages:[]}};(b.element_details??=[]).push(detail);}Object.assign(detail,readTaskFields(data));await save();renderCanvas();}}
 });
 $('#modal-body').querySelectorAll('input,textarea').forEach(el=>{el.readOnly=!canEdit();if(el.tagName==='TEXTAREA')el.maxLength=20000;});$('#submit-modal').hidden=!canEdit();
 if($('#expand-bpmn-node'))$('#expand-bpmn-node').onclick=async()=>{$('#modal').close();await editBpmn({op:'expand',id});S.camera=null;renderView();};
 if(isTask)$('#open-task-uml').onclick=async()=>{try{
  if(canEdit()){
   const data=new FormData($('#modal-form'));if(data.get('name')!==n.name||adHocNode||(laneForm&&data.get('lane_id')!==(n.lane_id||'')))await saveBpmnNode(data);
   S.detailId=id;Object.assign(taskDetail(block(),true),readTaskFields(data));if(!await save())return;
  }
  $('#modal').close();await openTaskUml(id);
 }catch(error){toast(error.message,true);}};
 if(isTask)addScreenTaskButton(id,n);
 const del=$('#modal-body [data-action="delete-node"]');if(del)del.onclick=e=>{e.stopPropagation();modal(n.kind==='participant'?'Удалить пул?':'Удалить элемент?',`<p class="modal-note">${n.kind==='participant'?'Пул, его процесс, действия и связи сообщений будут удалены.':'Элемент и его связи будут удалены.'} Детализация останется в проекте для восстановления через отмену.</p>`,async()=>{await editBpmn({op:'delete',id});S.element=null;},'Удалить');};
}
$('#content').addEventListener('dblclick',e=>{
 const item=e.target.closest('[data-id]'),edge=e.target.closest('[data-edge]');
 if(item&&S.view==='overview'){selectBlock(item.dataset.id,'bpmn');return;}
 if(S.view==='bpmn')openBpmnElement(item?.dataset.id||edge?.dataset.edge);
});
$('#content').addEventListener('wheel',e=>{
 const svg=$('.diagram-svg');if(!svg||!S.camera)return;
 e.preventDefault();if(drag)return;
 const unit=e.deltaMode===1?16:e.deltaMode===2?svg.clientHeight:1;
 if(e.ctrlKey||e.metaKey){
  const anchor=point(e),c=S.camera;
  const w=Math.max(70,Math.min(100000,c.w*Math.exp(Math.max(-1,Math.min(1,e.deltaY*unit*.01))))),scale=w/c.w;
  S.camera={x:anchor.x-(anchor.x-c.x)*scale,y:anchor.y-(anchor.y-c.y)*scale,w,h:c.h*scale};
 }else{
  const matrix=svg.getScreenCTM();if(!matrix)return;
  const inverse=matrix.inverse(),origin=new DOMPoint(0,0).matrixTransform(inverse);
  const delta=new DOMPoint((e.shiftKey&&!e.deltaX?e.deltaY:e.deltaX)*unit,(e.shiftKey&&!e.deltaX?0:e.deltaY)*unit).matrixTransform(inverse);
  S.camera={...S.camera,x:S.camera.x+delta.x-origin.x,y:S.camera.y+delta.y-origin.y};
 }
 applyCamera();
},{passive:false});
document.addEventListener('keydown',e=>{
 if(e.code!=='Space'||e.repeat||$('#modal').open||e.target.closest('input,textarea,select,button,[contenteditable="true"]')||!$('.diagram-svg'))return;
 e.preventDefault();spacePan=true;updateCanvasMode();
});
document.addEventListener('keyup',e=>{if(e.code==='Space'){spacePan=false;updateCanvasMode();}});
window.addEventListener('blur',()=>{spacePan=false;updateCanvasMode();});
document.addEventListener('keydown',e=>{if($('#modal').open||['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;if(S.view==='slides'&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();action(e.key==='ArrowLeft'?'prev-slide':'next-slide');}if(S.view==='bpmn'&&(e.metaKey||e.ctrlKey)&&e.key==='z'){e.preventDefault();action('undo-bpmn');}if(e.key==='Escape'){S.connect=null;if(drag){if(drag.id&&drag.view==='overview')Object.assign(block(),drag.original);if(drag.id&&drag.view==='bpmn')S.analyses.get(S.selected).diagram=drag.original;drag=null;renderCanvas();}}});
window.addEventListener('beforeunload',e=>{if(S.pending||S.failed||$('#save-state').textContent==='Есть правки…'){e.preventDefault();e.returnValue='';}});
new ResizeObserver(()=>{if($('.diagram-svg')&&S.camera)applyCamera();}).observe($('#content'));
