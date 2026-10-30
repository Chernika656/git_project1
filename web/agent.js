'use strict';
const AI={draft:null,previous:null,report:null,busy:false,messages:[],changeDraft:null,chatProject:null,scope:'block',blockId:null,layer:null,mode:'auto'};
const LAYER_AGENT_ACTIONS={
 overview:{title:'Помощник по блоку',note:'Описание, структура и согласованность представлений',actions:[
  {id:'overview-review',icon:'⌁',title:'Проверить блок',text:'Найти пробелы и противоречия',prompt:'Проанализируй выбранный блок. Кратко найди пробелы, противоречия и предложи точечные исправления.'},
  {id:'overview-improve',icon:'✎',title:'Улучшить описание',text:'Сделать цель и результат яснее',prompt:'Улучши обзор выбранного блока: название не меняй без необходимости, уточни описание, результат и ответственного. Подготовь черновик.'},
  {id:'overview-layers',icon:'◫',title:'Дополнить слои',text:'Связать требования, BPMN и UML',layer:'all',prompt:'Дополни недостающие слои выбранного блока и согласуй между собой обзор, требования, BPMN, UML и API. Не заменяй уже хорошие данные.'}]},
 requirements:{title:'Помощник по требованиям',note:'Полнота, однозначность и связь с процессом',actions:[
  {id:'requirements-review',icon:'⌕',title:'Проверить требования',text:'Найти неоднозначности и пропуски',prompt:'Проверь требования выбранного блока на полноту, однозначность, проверяемость и противоречия. Предложи исправления черновиком.'},
  {id:'requirements-structure',icon:'≡',title:'Структурировать',text:'Собрать реестр требований',prompt:'Преобразуй требования выбранного блока в компактный структурированный реестр с понятными названиями и статусом draft. Сохрани исходный смысл.'},
  {id:'requirements-trace',icon:'↗',title:'Связать с BPMN',text:'Сопоставить требования задачам',layer:'bpmn',prompt:'Сверь требования выбранного блока с BPMN и привяжи требования к подходящим элементам через детализацию. Не меняй логику процесса без необходимости.'}]},
 bpmn:{title:'Помощник BPMN',note:'Логика процесса, расположение и прототип интерфейса',actions:[
  {id:'bpmn-layout',icon:'◇',title:'Улучшить схему',text:'Выровнять блоки и связи · 0 токенов',prompt:'Проанализируй и визуально выровняй BPMN, сделай расположение блоков и связей аккуратнее, не изменяя логику.'},
  {id:'bpmn-review',icon:'⌕',title:'Анализ логики',text:'Проверить ветки и завершения',kind:'analysis'},
  {id:'bpmn-prototype',icon:'▣',title:'HTML-прототип',text:'Создать интерфейс по процессу',kind:'prototype'},
  {id:'bpmn-project',icon:'◫',title:'Разбить BPMN на проект',text:'Точно перенести элементы и создать слои',kind:'project',layer:'all',prompt:'Разбей исходную BPMN выбранного блока на 2–4 крупных логических блока проекта без изменения логики. Первой и единственной операцией создания блоков используй split_bpmn: source_block_id — ID выбранного блока, а element_ids всех групп должны ровно один раз покрыть полный список bpmn_split_candidates. Не используй create_block и set_bpmn для новых блоков: сервер сам перенесёт исходные XML-элементы, ID, типы, условия, подпроцессы, специальные события, циклы и связи. После split_bpmn наполни алиасы новых блоков требованиями, UML sequence, API и данными, слайдами. Исходный блок сохрани как общую карту. Используй не более 50 операций и пиши дополнительные слои компактно.'}]},
 uml:{title:'Помощник UML',note:'Участники, сообщения и соответствие BPMN',actions:[
  {id:'uml-improve',icon:'⇄',title:'Улучшить UML',text:'Уточнить участников и сообщения',prompt:'Проанализируй UML sequence выбранного блока и улучши участников, порядок сообщений и названия вызовов. Подготовь черновик без лишних взаимодействий.'},
  {id:'uml-from-bpmn',icon:'◇',title:'Собрать из BPMN',text:'Построить взаимодействия по процессу',prompt:'На основе BPMN выбранного блока создай или обнови UML sequence: выдели участников и основные вызовы с ответами.'},
  {id:'uml-check',icon:'⌕',title:'Проверить связь',text:'Сверить UML с требованиями',prompt:'Сверь UML sequence выбранного блока с BPMN и требованиями. Исправь только явные несоответствия и подготовь черновик.'}]},
 technical:{title:'Помощник API и данных',note:'Контракты, структуры и технические ошибки',actions:[
  {id:'technical-draft',icon:'⌘',title:'Создать контракт',text:'Подготовить API и структуры данных',prompt:'По BPMN, UML и требованиям выбранного блока подготовь компактный технический контракт: методы, пути, запросы, ответы, статусы и основные структуры данных.'},
  {id:'technical-review',icon:'⌕',title:'Проверить API',text:'Найти пропущенные ответы и поля',prompt:'Проверь API и данные выбранного блока. Найди отсутствующие статусы, ошибки, поля и несоответствия требованиям; подготовь исправленный черновик.'},
  {id:'technical-sync',icon:'⇄',title:'Сверить с UML',text:'Согласовать вызовы и контракт',layer:'uml',prompt:'Сверь API выбранного блока с UML sequence и BPMN. Обнови UML только при явном расхождении с техническим контрактом.'}]},
 slides:{title:'Помощник презентации',note:'Краткое объяснение блока для руководителя',actions:[
  {id:'slides-improve',icon:'▣',title:'Улучшить слайд',text:'Сделать формулировки короче',prompt:'Улучши слайд выбранного блока для руководителя: кратко сформулируй цель, результат, статус и ответственного без технического жаргона.'},
  {id:'slides-story',icon:'▷',title:'Подготовить рассказ',text:'Выделить ценность и риски',prompt:'Подготовь содержание слайда выбранного блока: бизнес-ценность, текущий статус, главный риск и следующий шаг. Используй существующие данные.'},
  {id:'slides-check',icon:'⌕',title:'Проверить актуальность',text:'Сверить с остальными слоями',layer:'all',prompt:'Сверь слайд выбранного блока с требованиями, BPMN, UML и API. Исправь устаревшие формулировки и подготовь черновик.'}]},
 glossary:{title:'Помощник словаря',note:'Единые термины для всего проекта',actions:[
  {id:'glossary-extract',icon:'Aa',title:'Собрать термины',text:'Извлечь понятия из проекта',layer:'requirements',prompt:'Собери компактный словарь ключевых терминов проекта из требований и описаний блоков. Удали повторы и свяжи термины с блоками.'},
  {id:'glossary-review',icon:'⌕',title:'Проверить определения',text:'Найти дубли и противоречия',layer:'requirements',prompt:'Проверь словарь проекта: найди дубли, неоднозначные и противоречивые определения. Подготовь исправленный словарь.'}]}
};
const TASK_UML_AGENT_ACTIONS={title:'Помощник UML задачи',note:'Отдельное взаимодействие для выбранного элемента BPMN',actions:[
 {id:'task-uml-create',icon:'⇄',title:'Создать UML задачи',text:'Участники и сообщения шага',prompt:'Создай отдельную UML sequence для выбранной задачи BPMN. Покажи только участников и сообщения, необходимые для выполнения этого шага.'},
 {id:'task-uml-improve',icon:'✎',title:'Улучшить UML',text:'Уточнить вызовы и ответы',prompt:'Улучши отдельную UML sequence выбранной задачи BPMN: уточни участников, порядок вызовов и ответы, не добавляя лишних систем.'},
 {id:'task-uml-check',icon:'⌕',title:'Сверить с задачей',text:'Проверить требования и критерии',prompt:'Сверь отдельную UML sequence выбранной задачи с её описанием, требованиями и критериями приёмки. Подготовь точечные исправления.'}
]};
function agentContext(){return {user:A.user?.id,project:S.project?.id,block:S.selected};}
function sameAgentContext(ctx){return ctx?.user===A.user?.id&&ctx?.project===S.project?.id&&ctx?.block===S.selected;}
function agentButton(){
 const button=document.createElement('button');button.id='open-agent';button.className='soft';button.textContent='✦ Агент';
 button.onclick=()=>openAgent('floating');$('#project-menu').before(button);
 if(!document.querySelector('[data-section="agent"]')){
  const nav=document.createElement('button');nav.className='nav section-link';nav.dataset.section='agent';nav.innerHTML='<span>✦</span>Агент';nav.onclick=()=>showSection('agent');
  document.querySelector('.app-navigation')?.insertBefore(nav,document.querySelector('[data-section="account"]'));
 }
}
agentButton();
function layerAgentHost(){
 let host=$('#layer-agent-actions');
 if(!host){host=document.createElement('section');host.id='layer-agent-actions';host.setAttribute('aria-label','Быстрые действия Facet Agent');$('.view-tabs')?.after(host);}
 return host;
}
function renderLayerAgentActions(){
 const host=layerAgentHost(),b=block(),taskMode=S.view==='uml'&&!!S.detailId,config=taskMode?TASK_UML_AGENT_ACTIONS:LAYER_AGENT_ACTIONS[S.view];
 if(!host)return;
 if(!b||!config){host.hidden=true;host.innerHTML='';return;}
 host.hidden=false;host.className='layer-agent-actions layer-agent-'+S.view;
 host.innerHTML=`<div class="layer-agent-heading"><span class="layer-agent-mark">✦</span><div><small>FACET AGENT · ${esc(taskMode?b.name+' → '+taskName():b.name)}</small><strong>${config.title}</strong><span>${config.note}</span></div></div><div class="layer-agent-buttons">${config.actions.map(action=>`<button type="button" data-layer-agent="${action.id}" ${!canEdit()&&action.kind!=='analysis'?'disabled':''}><span>${action.icon}</span><span><strong>${action.title}</strong><small>${action.text}</small></span></button>`).join('')}</div><div class="layer-agent-confirm" hidden role="alert"><span></span><div><button type="button" data-layer-agent-confirm="yes" class="primary">Да</button><button type="button" data-layer-agent-confirm="no">Нет</button></div></div><div class="layer-agent-result" hidden aria-live="polite"></div>`;
 host.querySelectorAll('[data-layer-agent]').forEach(button=>button.onclick=()=>confirmLayerAgentAction(button.dataset.layerAgent));
}
function findLayerAgentAction(id){return [...Object.values(LAYER_AGENT_ACTIONS).flatMap(item=>item.actions),...TASK_UML_AGENT_ACTIONS.actions].find(action=>action.id===id);}
function confirmLayerAgentAction(id){
 const action=findLayerAgentAction(id),host=$('#layer-agent-actions'),confirm=host?.querySelector('.layer-agent-confirm');if(!action||!confirm)return;
 confirm.dataset.action=id;confirm.hidden=false;confirm.querySelector('span').textContent=action.kind==='project'?`Создать связанные блоки и все слои на основе BPMN «${block()?.name||''}»? Сначала появится черновик.`:`Запустить «${action.title}» для ${S.detailId?'задачи «'+taskName()+'»':'блока «'+(block()?.name||'')+'»'}?`;
 confirm.querySelector('[data-layer-agent-confirm="no"]').onclick=()=>{confirm.hidden=true;delete confirm.dataset.action;};
 confirm.querySelector('[data-layer-agent-confirm="yes"]').onclick=async()=>{confirm.hidden=true;await runLayerAgentAction(action);};
}
async function runLayerAgentAction(action){
 if(!S.project||!block()||AI.busy)return;
 const ctx=agentContext(),layer=action.layer||S.view,resultBox=$('#layer-agent-actions .layer-agent-result');
 AI.scope='block';AI.blockId=S.selected;AI.layer=layer;AI.mode='auto';AI.busy=true;
 updateAgentBusy();
 resultBox.hidden=false;resultBox.className='layer-agent-result loading';resultBox.textContent='Выполняю «'+action.title+'»…';
 $('#layer-agent-actions').querySelectorAll('button').forEach(button=>button.disabled=true);
 try{
  if(canEdit()){clearTimeout(S.timer);if(!await save())throw Error('Не удалось сохранить актуальное состояние проекта.');}
  if(!sameAgentContext(ctx))throw Error('Выбранный блок изменился. Повторите действие.');
  if(action.kind==='analysis'){
   const response=await api('/api/agent/analyze','POST',{project_id:ctx.project,block_id:ctx.block,scope:'bpmn',prompt:''});
   AI.report={...ctx,...response};const report=response.analysis,counts=report.findings.reduce((out,item)=>(out[item.severity]=(out[item.severity]||0)+1,out),{});
   showLayerAgentResult(`<strong>Анализ завершён</strong><p>${esc(report.summary)}</p><small>Ошибок: ${counts.error||0} · проверить: ${counts.warning||0} · предложений: ${counts.suggestion||0}</small>`);
   return;
  }
  if(action.kind==='prototype'){
   const prompt='Создай понятный интерактивный HTML-прототип пользовательского сценария этого блока на основе BPMN и требований. Покажи основной путь, проверки и результат.';
   const response=await api('/api/agent/generate','POST',{project_id:ctx.project,block_id:ctx.block,prompt});
   if(!sameAgentContext(ctx))throw Error('Выбранный блок изменился. Повторите действие.');
   AI.draft={...ctx,prototype:response.prototype};
   showLayerAgentResult(`<strong>HTML-прототип готов</strong><p>${esc(response.prototype.title)} · экранов: ${response.prototype.pages.length}</p><div><button type="button" data-layer-preview>Предпросмотр</button><button type="button" data-layer-prototype-apply class="primary">Применить</button><button type="button" data-layer-result-close>Отклонить</button></div>`);
   $('#layer-agent-actions [data-layer-preview]').onclick=()=>openHtmlPrototype(response.prototype,true);
   $('#layer-agent-actions [data-layer-prototype-apply]').onclick=()=>applyLayerPrototype(ctx,response.prototype);
   $('#layer-agent-actions [data-layer-result-close]').onclick=()=>{AI.draft=null;renderLayerAgentActions();};
   return;
  }
  const focusedPrompt=action.prompt+(S.detailId?` Работай только с BPMN-элементом ID «${S.detailId}» и используй операцию set_task_uml, сохраняя общую UML блока.`:'');
  const response=await api('/api/agent/chat','POST',{project_id:ctx.project,block_id:ctx.block,layer,mode:'auto',prompt:focusedPrompt});
  if(!sameAgentContext(ctx))throw Error('Выбранный блок изменился. Повторите действие.');
  AI.changeDraft=response.draft;
  const usage=response.usage||{},cost=response.estimated_cost==null?'':` · ≈ $${Number(response.estimated_cost).toFixed(4)}`;
  showLayerAgentResult(`<strong>${esc(response.draft?.summary||action.title)}</strong><p>${esc(response.message)}</p><small>${esc(response.model||'Facet')} · ${Number(usage.input_tokens||0).toLocaleString('ru')} вход / ${Number(usage.output_tokens||0).toLocaleString('ru')} выход${cost}</small>${response.draft?'<div><button type="button" data-layer-draft-apply class="primary">Применить</button><button type="button" data-layer-result-close>Отклонить</button></div>':''}`);
  if(response.draft)$('#layer-agent-actions [data-layer-draft-apply]').onclick=applyAgentChanges;
  $('#layer-agent-actions [data-layer-result-close]')?.addEventListener('click',()=>{AI.changeDraft=null;renderLayerAgentActions();});
 }catch(error){showLayerAgentResult(`<strong>Действие не выполнено</strong><p>${esc(error.message)}</p><div><button type="button" data-layer-result-close>Закрыть</button></div>`);$('#layer-agent-actions [data-layer-result-close]').onclick=renderLayerAgentActions;}
 finally{AI.busy=false;updateAgentBusy();$('#layer-agent-actions')?.querySelectorAll('[data-layer-agent]').forEach(button=>button.disabled=!canEdit()&&findLayerAgentAction(button.dataset.layerAgent)?.kind!=='analysis');}
}
function showLayerAgentResult(html){const box=$('#layer-agent-actions .layer-agent-result');if(!box)return;box.hidden=false;box.className='layer-agent-result';box.innerHTML=html;}
async function applyLayerPrototype(ctx,prototype){
 if(!sameAgentContext(ctx)||!canEdit())return toast('Выбранный блок изменился.');
 const b=block(),previous=structuredClone(b.html_prototype??null);b.html_prototype=structuredClone(prototype);
 if(await save()){AI.previous={...ctx,value:previous,applied:JSON.stringify(b.html_prototype)};AI.draft=null;renderLayerAgentActions();toast('HTML-прототип применён к блоку.');}
 else b.html_prototype=previous;
}
async function agentStatus(target){
 try{const s=await api('/api/agent/status');if(!target.isConnected)return;
  target.textContent=(s.configured?'Ключ настроен':'Ключ не настроен')+' · '+s.model+' / '+s.fast_model+' · лично '+s.used_today+' / '+s.daily_limit+' · сервер '+s.global_used_today+' / '+s.global_daily_limit+' · токены за месяц: '+Number(s.input_tokens_month||0).toLocaleString('ru')+' вход / '+Number(s.output_tokens_month||0).toLocaleString('ru')+' выход';
  const card=target.closest('.agent-settings'),usage=card?.querySelector('#settings-agent-usage');
  const plans=document.querySelector('#plan-settings');if(plans){plans.querySelector('#current-plan').textContent='Текущий тариф: '+(s.plan||'free').toUpperCase()+(s.plan_expires?' · до '+new Date(s.plan_expires*1000).toLocaleDateString('ru'):'');plans.querySelectorAll('[data-demo-plan]').forEach(button=>{button.disabled=s.plan===button.dataset.demoPlan;button.textContent=s.plan===button.dataset.demoPlan?'Текущий тариф':`Купить ${button.dataset.demoPlan.toUpperCase()} (демо)`;});}
  if(usage){const limit=Math.max(0,Number(s.daily_limit)||0),used=Math.max(0,Number(s.used_today)||0),reset=s.resets_at?new Date(s.resets_at*1000).toLocaleString('ru',{hour:'2-digit',minute:'2-digit',day:'numeric',month:'long'}):'в полночь UTC';usage.innerHTML=`<strong>Тариф ${esc((s.plan||"free").toUpperCase())}${s.plan_expires?" · до "+esc(new Date(s.plan_expires*1000).toLocaleDateString("ru")):""}</strong><strong>${used} из ${limit} запросов сегодня</strong><meter min="0" max="${Math.max(1,limit)}" value="${Math.min(used,limit)}"></meter><small>Лично осталось ${Math.max(0,limit-used)} · обновление ${esc(reset)}</small><small>Общий бюджет сервера: ${Number(s.global_used_today||0)} из ${Number(s.global_daily_limit||0)} запросов сегодня. Если он закончится раньше личного лимита, агент временно остановится для всех.</small><strong>${Number(s.tokens_used_month||0).toLocaleString('ru')} из ${Number(s.monthly_token_limit||0).toLocaleString('ru')} токенов за месяц · ${Number(s.token_percent_month||0)}%</strong><meter min="0" max="${Math.max(1,Number(s.monthly_token_limit)||0)}" value="${Math.min(Number(s.tokens_used_month)||0,Math.max(1,Number(s.monthly_token_limit)||0))}"></meter><small>Вход ${Number(s.input_tokens_month||0).toLocaleString('ru')}, выход ${Number(s.output_tokens_month||0).toLocaleString('ru')} · обновление 1-го числа UTC.</small>`;}
 }catch(err){if(target.isConnected)target.textContent=err.message;}
}
function openAgent(mode='floating',host=null){
 if(!S.project)return toast('Откройте проект для агента.');
 if(!S.project.blocks.some(item=>item.id===AI.blockId))AI.blockId=S.selected||S.project.blocks[0]?.id||null;
 if(!AI.layer)AI.layer=['overview','requirements','bpmn','uml','technical','slides'].includes(S.view)?S.view:'overview';
 AI.panelContext=agentContext();
 $('#agent-panel')?.remove();
 const floating=mode!=='page';
 const panel=document.createElement('aside');panel.id='agent-panel';panel.className=floating?'agent-floating':'agent-page';panel.setAttribute('aria-label','Агент Facet');
 panel.innerHTML=`<header><div><span class="eyebrow">FACET AI</span><h2>Агент проекта</h2></div><div class="agent-window-actions">${floating?'<button type="button" data-ai-page title="Открыть вкладкой" aria-label="Открыть агента вкладкой">▣</button>':'<button type="button" data-ai-float title="Открыть поверх проекта" aria-label="Открыть агента плавающим окном">↗</button>'}<button type="button" data-ai-close aria-label="Закрыть агента">×</button></div></header><div class="agent-context"><div class="agent-scope"><button type="button" data-ai-scope="project" class="${AI.scope==='project'?'active':''}">Весь проект</button><button type="button" data-ai-scope="block" class="${AI.scope==='block'?'active':''}" ${S.project.blocks.length?'':'disabled'}>Конкретный блок</button></div><div class="agent-context-fields"><label data-agent-block-field>Блок<select id="agent-block-select">${S.project.blocks.map(item=>`<option value="${esc(item.id)}" ${item.id===AI.blockId?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label><label>Слой<select id="agent-layer-select"><option value="all">Все слои</option><option value="overview">Обзор</option><option value="requirements">Требования</option><option value="bpmn">BPMN</option><option value="uml">UML sequence</option><option value="technical">API и данные</option><option value="slides">Слайды</option></select></label><label>Режим<select id="agent-mode-select"><option value="economy">Экономный · Luna</option><option value="auto">Авто</option><option value="quality">Качество · Terra</option></select></label></div><p id="agent-context-note"></p></div><p class="agent-status" role="status">Проверка настройки…</p><div id="agent-chat" class="agent-chat" aria-live="polite"><p class="agent-note">Загрузка диалога…</p></div><label class="field">Сообщение агенту<textarea id="agent-prompt" maxlength="6000" placeholder="Опишите, что нужно сделать с выбранным контекстом…"></textarea></label><button type="button" id="agent-send" class="primary">Отправить</button><p class="agent-note">Агент работает только с указанным контекстом и наследует ваши права. Изменения сначала появляются как один черновик.</p><details class="agent-tools"><summary>Анализ и прототип выбранного блока</summary><p>Выбран блок: <strong>${esc(block()?.name||'Не выбран')}</strong></p><div class="agent-quick"><button type="button" data-ai-analyze="bpmn">Проверить BPMN блока</button><button type="button" data-ai-analyze="project">Проанализировать проект</button></div><div id="agent-analysis" aria-live="polite"></div><div class="agent-prototype"><button type="button" id="agent-generate" class="primary" ${!canEdit()||AI.busy?'disabled':''}>${AI.busy?'Генерация…':'Сгенерировать HTML-прототип'}</button><button type="button" id="agent-starter">Попробовать шаблон без ИИ</button><div id="agent-result" aria-live="polite"></div></div></details><footer><button type="button" id="agent-tasks">Сводка задач</button><button type="button" id="agent-check">Проверить подключение</button><button type="button" id="agent-settings">Настройки</button></footer>`;
 (floating?(document.fullscreenElement||document.body):(host||$('#agent-page-host'))).append(panel);
 if(floating){restoreAgentWindow(panel);enableAgentDrag(panel);enableAgentResize(panel);}
 panel.querySelector('[data-ai-close]').onclick=()=>floating?panel.remove():showSection('workspace');
 panel.querySelector('[data-ai-page]')?.addEventListener('click',()=>showSection('agent'));
 panel.querySelector('[data-ai-float]')?.addEventListener('click',()=>{showSection('workspace');requestAnimationFrame(()=>openAgent('floating'));});
 $('#agent-settings').onclick=async()=>{if(document.fullscreenElement)await document.exitFullscreen();panel.remove();showSection('settings');};
 $('#agent-tasks').onclick=()=>openNotificationCenter();
 $('#agent-check').onclick=async e=>{const button=e.currentTarget;button.disabled=true;try{await api('/api/agent/check','POST',{project_id:S.project.id});toast('OpenAI доступен. Подключение работает.');}catch(err){toast(err.message,true);}finally{button.disabled=false;}};
 $('#agent-starter').disabled=!block();
 $('#agent-starter').onclick=()=>{if(!block())return;if(!sameAgentContext(AI.panelContext))return openAgent(mode,host);AI.draft={...agentContext(),prototype:starterPrototype(block())};renderAgentResult();};
 $('#agent-generate').onclick=generatePrototype;
 $('#agent-send').onclick=()=>sendAgentMessage();
 $('#agent-prompt').onkeydown=e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();sendAgentMessage();}};
 const syncContext=()=>{panel.querySelectorAll('[data-ai-scope]').forEach(item=>item.classList.toggle('active',item.dataset.aiScope===AI.scope));panel.querySelector('[data-agent-block-field]').hidden=AI.scope!=='block';const chosen=S.project.blocks.find(item=>item.id===AI.blockId);const layer={all:'все слои',overview:'обзор',requirements:'требования',bpmn:'BPMN',uml:'UML sequence',technical:'API и данные',slides:'слайды'}[AI.layer],mode={economy:'экономный',auto:'автоматический',quality:'максимальное качество'}[AI.mode];$('#agent-context-note').textContent=(AI.scope==='block'?`Работаем с блоком «${chosen?.name||'не выбран'}»`:'Работаем со всем проектом')+`, слой «${layer}», режим «${mode}».`;};
 panel.querySelectorAll('[data-ai-scope]').forEach(button=>button.onclick=()=>{AI.scope=button.dataset.aiScope;syncContext();});
 $('#agent-block-select').onchange=e=>{AI.blockId=e.target.value;syncContext();};
 $('#agent-layer-select').value=AI.layer;$('#agent-layer-select').onchange=e=>{AI.layer=e.target.value;syncContext();};syncContext();
 $('#agent-mode-select').value=AI.mode;$('#agent-mode-select').onchange=e=>{AI.mode=e.target.value;syncContext();};
 panel.querySelectorAll('[data-ai-analyze]').forEach(button=>button.onclick=()=>analyzeWithAgent(button.dataset.aiAnalyze));
 updateAgentBusy();renderAgentAnalysis();
 agentStatus(panel.querySelector('.agent-status'));renderAgentResult();loadAgentChat();
}
function agentWindowState(){try{return JSON.parse(localStorage.getItem('facet.agent.window')||'{}');}catch{return {};}}
function saveAgentWindow(panel){
 if(!panel?.isConnected||!panel.classList.contains('agent-floating'))return;
 const box=panel.getBoundingClientRect();localStorage.setItem('facet.agent.window',JSON.stringify({left:Math.round(box.left),top:Math.round(box.top),width:Math.round(box.width),height:Math.round(box.height)}));
}
function restoreAgentWindow(panel){
 const saved=agentWindowState(),width=Math.min(Math.max(saved.width||390,280),window.innerWidth-20),height=Math.min(Math.max(saved.height||Math.min(720,window.innerHeight-100),260),window.innerHeight-20);
 panel.style.width=width+'px';panel.style.height=height+'px';panel.style.right='auto';panel.style.bottom='auto';
 panel.style.left=Math.min(Math.max(saved.left??window.innerWidth-width-18,10),window.innerWidth-width-10)+'px';panel.style.top=Math.min(Math.max(saved.top??82,10),window.innerHeight-height-10)+'px';
 if(window.ResizeObserver){const observer=new ResizeObserver(()=>saveAgentWindow(panel));observer.observe(panel);panel._agentObserver=observer;}
}
function enableAgentDrag(panel){
 const header=panel.querySelector('header');
 header.addEventListener('pointerdown',event=>{
  if(event.button!==0||event.target.closest('button'))return;
  const box=panel.getBoundingClientRect(),dx=event.clientX-box.left,dy=event.clientY-box.top;header.setPointerCapture(event.pointerId);panel.classList.add('dragging');
  const move=e=>{panel.style.left=Math.min(Math.max(e.clientX-dx,8),window.innerWidth-panel.offsetWidth-8)+'px';panel.style.top=Math.min(Math.max(e.clientY-dy,8),window.innerHeight-panel.offsetHeight-8)+'px';};
  const stop=()=>{panel.classList.remove('dragging');saveAgentWindow(panel);header.removeEventListener('pointermove',move);header.removeEventListener('pointerup',stop);header.removeEventListener('pointercancel',stop);};
  header.addEventListener('pointermove',move);header.addEventListener('pointerup',stop);header.addEventListener('pointercancel',stop);
 });
}
function enableAgentResize(panel){
 for(const direction of ['n','ne','e','se','s','sw','w','nw'])panel.insertAdjacentHTML('beforeend',`<span class="agent-resize-handle agent-resize-${direction}" data-agent-resize="${direction}" aria-hidden="true"></span>`);
 panel.querySelectorAll('[data-agent-resize]').forEach(handle=>handle.addEventListener('pointerdown',event=>{
  if(event.button!==0)return;event.preventDefault();event.stopPropagation();
  const box=panel.getBoundingClientRect(),startX=event.clientX,startY=event.clientY,direction=handle.dataset.agentResize;
  handle.setPointerCapture(event.pointerId);panel.classList.add('resizing');
  const move=e=>{
   const dx=e.clientX-startX,dy=e.clientY-startY;let left=box.left,top=box.top,width=box.width,height=box.height;
   if(direction.includes('e'))width+=dx;if(direction.includes('s'))height+=dy;
   if(direction.includes('w')){left+=dx;width-=dx;}if(direction.includes('n')){top+=dy;height-=dy;}
   width=Math.min(Math.max(width,280),window.innerWidth-16);height=Math.min(Math.max(height,260),window.innerHeight-16);
   if(direction.includes('w'))left=box.right-width;if(direction.includes('n'))top=box.bottom-height;
   left=Math.min(Math.max(left,8),window.innerWidth-width-8);top=Math.min(Math.max(top,8),window.innerHeight-height-8);
   Object.assign(panel.style,{left:left+'px',top:top+'px',right:'auto',bottom:'auto',width:width+'px',height:height+'px'});
  };
  const stop=()=>{panel.classList.remove('resizing');saveAgentWindow(panel);handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',stop);handle.removeEventListener('pointercancel',stop);handle.removeEventListener('lostpointercapture',stop);};
  handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',stop);handle.addEventListener('pointercancel',stop);handle.addEventListener('lostpointercapture',stop);
 }));
}
async function loadAgentChat(){
 const ctx=agentContext(),changed=AI.chatProject!==ctx.project;AI.chatProject=ctx.project;
 if(changed){AI.messages=[];AI.changeDraft=null;}renderAgentChat();
 try{const result=await api('/api/agent/chat?project_id='+encodeURIComponent(ctx.project));if(AI.chatProject!==ctx.project)return;AI.messages=result.messages||[];renderAgentChat();}
 catch(err){const target=$('#agent-chat');if(target)target.innerHTML=`<p class="agent-note">${esc(err.message)}</p>`;}
}
function operationName(type){return ({set_project:'Обновить проект',split_bpmn:'Точно разбить BPMN',create_block:'Создать блок',update_block:'Обновить блок',set_requirements:'Требования',set_requirement_items:'Структурированные требования',set_bpmn:'BPMN',relayout_bpmn:'Выровнять BPMN',set_element_details:'Детализация BPMN',set_uml:'UML',set_task_uml:'UML задачи',set_api:'API и данные',set_slides:'Слайды',link_blocks:'Связать блоки',unlink_blocks:'Убрать связь',set_glossary:'Словарь'})[type]||type;}
function renderAgentChat(){
 const target=$('#agent-chat');if(!target)return;
 target.innerHTML=(AI.messages.length?AI.messages.map(m=>`<div class="agent-message ${m.role}"><small>${m.role==='user'?'Вы':'Facet Agent'}</small><p>${esc(m.content)}</p>${m.usage?`<span class="agent-usage">${esc(m.model||'')} · ${Number(m.usage.input_tokens||0).toLocaleString('ru')} вход${m.usage.input_tokens_details?.cached_tokens?' ('+Number(m.usage.input_tokens_details.cached_tokens).toLocaleString('ru')+' кеш)':''} · ${Number(m.usage.output_tokens||0).toLocaleString('ru')} выход${m.cost!=null?' · ≈ $'+Number(m.cost).toFixed(4):''}</span>`:''}</div>`).join(''):'<div class="agent-chat-empty"><strong>Чем помочь с проектом?</strong><span>Можно попросить создать сразу несколько связанных представлений.</span></div>')+(AI.changeDraft?`<article class="agent-change-draft"><span class="eyebrow">ЧЕРНОВИК ИЗМЕНЕНИЙ</span><h3>${esc(AI.changeDraft.summary||'Изменения проекта')}</h3><div>${AI.changeDraft.operations.map(op=>`<span>${esc(operationName(op.type))}${op.name?' · '+esc(op.name):''}</span>`).join('')}</div><button type="button" id="agent-apply-changes" class="primary" ${canEdit()?'':'disabled'}>Применить ${AI.changeDraft.operations.length} изменений</button><button type="button" id="agent-discard-changes">Отклонить</button></article>`:'');
 target.scrollTop=target.scrollHeight;
 if($('#agent-apply-changes'))$('#agent-apply-changes').onclick=applyAgentChanges;
 if($('#agent-discard-changes'))$('#agent-discard-changes').onclick=()=>{AI.changeDraft=null;renderAgentChat();};
}
async function sendAgentMessage(quickPrompt=''){
 if(AI.busy||!S.project)return;const prompt=(quickPrompt||$('#agent-prompt').value).trim();if(!prompt)return toast('Напишите сообщение агенту.');
 const ctx=agentContext();AI.busy=true;AI.messages.push({role:'user',content:prompt});$('#agent-prompt').value='';renderAgentChat();updateAgentBusy();
 try{const result=await api('/api/agent/chat','POST',{project_id:ctx.project,block_id:AI.scope==='block'?AI.blockId:null,layer:AI.layer,mode:AI.mode,prompt});if(A.user?.id!==ctx.user||S.project?.id!==ctx.project)return;AI.messages.push({role:'assistant',content:result.message,usage:result.usage,cost:result.estimated_cost,model:result.model});AI.changeDraft=result.draft;renderAgentChat();}
 catch(err){AI.messages.push({role:'assistant',content:'Не удалось выполнить запрос: '+err.message});renderAgentChat();}
 finally{AI.busy=false;updateAgentBusy();const status=$('#agent-panel .agent-status');if(status)agentStatus(status);}
}
async function applyAgentChanges(){
 if(!AI.changeDraft||!canEdit()||AI.busy)return;const draft=AI.changeDraft,button=$('#agent-apply-changes');AI.busy=true;if(button)button.disabled=true;updateAgentBusy();
 try{
  const selectedBefore=S.selected,result=await api('/api/agent/apply','POST',{project_id:S.project.id,draft_id:draft.id});
  S.project=result.project;S.selected=S.project.blocks.some(b=>b.id===selectedBefore)?selectedBefore:S.project.blocks[0]?.id;
  S.analyses.clear();S.camera=null;S.element=null;AI.changeDraft=null;
  await analyzeAll();
  AI.messages.push({role:'assistant',content:'Изменения применены: '+result.summary});render();renderAgentChat();refreshProjects();
  if(S.view==='bpmn')requestAnimationFrame(()=>{S.camera=null;fit();});
  toast('Изменения агента применены.');
 }
 catch(err){toast(err.message,true);}
 finally{AI.busy=false;updateAgentBusy();}
}
function renderAgentResult(){
 const el=$('#agent-result');if(!el)return;
 const draft=AI.draft;
 if(!draft){el.textContent='Здесь появится результат генерации.';return;}
 el.innerHTML=`<h3>${esc(draft.prototype.title)}</h3><p>Экранов: ${draft.prototype.pages.length}${sameAgentContext(draft)?'':' · результат для другого блока'}</p><button type="button" id="agent-preview">Открыть предпросмотр</button><button type="button" id="agent-apply" class="primary" ${!sameAgentContext(draft)||!canEdit()?'disabled':''}>Применить к блоку</button>${sameAgentContext(AI.previous)?'<button type="button" id="agent-undo">Отменить применение</button>':''}`;
 $('#agent-preview').onclick=()=>openHtmlPrototype(draft.prototype,true);
 $('#agent-apply').onclick=async e=>{
  if(!sameAgentContext(draft)||!canEdit())return toast('Вернитесь к исходному блоку.');
  const button=e.currentTarget,b=block(),old=structuredClone(b.html_prototype??null);button.disabled=true;
  b.html_prototype=structuredClone(draft.prototype);
  if(await save()){AI.previous={...agentContext(),value:old,applied:JSON.stringify(b.html_prototype)};toast('HTML-прототип сохранён в блоке.');renderAgentResult();}
  else{b.html_prototype=old;button.disabled=false;}
 };
 if($('#agent-undo'))$('#agent-undo').onclick=async()=>{
  const previous=AI.previous;if(!sameAgentContext(previous)||!canEdit())return;
  const b=block();if(JSON.stringify(b.html_prototype)!==previous.applied)return toast('Прототип уже изменился. Отмена не выполнена.');
  const current=b.html_prototype;b.html_prototype=previous.value;
  if(await save()){AI.previous=null;renderAgentResult();toast('Предыдущий прототип восстановлен.');}else b.html_prototype=current;
 };
}
async function generatePrototype(){
 if(AI.busy||!canEdit()||!block())return;
 if(!sameAgentContext(AI.panelContext))return toast('Блок изменился. Откройте панель агента заново.');
 const prompt=$('#agent-prompt').value.trim();if(!prompt)return toast('Опишите нужный интерфейс.');
 const ctx=agentContext(),target=$('#agent-result'),button=$('#agent-generate');
 AI.busy=true;updateAgentBusy();button.disabled=true;button.textContent='Генерация…';target.textContent='Агент готовит экраны. Это может занять около минуты.';
 try{
  clearTimeout(S.timer);if(!await save())throw Error('Сначала сохраните проект.');
  if(!sameAgentContext(ctx))throw Error('Выбранный блок изменился. Повторите запрос.');
  const result=await api('/api/agent/generate','POST',{project_id:ctx.project,block_id:ctx.block,prompt});
  if(A.user?.id!==ctx.user)return;
  AI.draft={...ctx,prototype:result.prototype};renderAgentResult();toast('Прототип готов к просмотру.');
 }catch(err){if(target.isConnected)target.textContent=err.message;else toast(err.message,true);}
 finally{AI.busy=false;updateAgentBusy();if(button.isConnected){button.disabled=!canEdit();button.textContent='Сгенерировать HTML-прототип';}const status=$('#agent-panel .agent-status');if(status)agentStatus(status);}
}
function renderAgentSettings(root){
 root.insertAdjacentHTML('beforeend',`<section class="section-card agent-settings"><h2>✦ Агент</h2><p>Лимит и использование</p><div id="settings-agent-usage" class="agent-usage-summary" aria-live="polite">Загрузка…</div><p>Дневной лимит запросов обновляется в полночь UTC, месячный лимит токенов — первого числа. Ошибки подключения не расходуют запросы.</p><details><summary>Состояние подключения</summary><p class="agent-status" role="status">Проверка настройки…</p><button type="button" id="settings-agent-check" ${!S.project||!canEdit()?'disabled':''}>Проверить подключение</button><p id="settings-agent-result" role="status"></p></details></section>`);
 root.insertAdjacentHTML('beforeend',`<section class="section-card" id="plan-settings"><h2>Тарифы</h2><p id="current-plan">Загрузка…</p><p>Демонстрационная покупка: деньги не списываются. Тариф включается на 30 дней по клику. После окончания периода его можно включить снова; переключение тарифа во время активного периода не продлевает срок. Персональные лимиты, выданные администратором, сохраняются.</p><div class="plan-grid"><article><h3>Free</h3><p>20 запросов в день · 1 млн токенов в месяц</p><small>Личные проекты и задачи</small></article><article><h3>Pro</h3><p>100 запросов в день · 5 млн токенов в месяц</p><small>Расширенный лимит агента</small><button type="button" data-demo-plan="pro">Купить Pro (демо)</button></article><article><h3>Team</h3><p>200 запросов в день · 20 млн токенов в месяц</p><small>Создание команды и совместная работа</small><button type="button" data-demo-plan="team">Купить Team (демо)</button></article></div><p id="plan-result" role="status"></p></section>`);
 root.querySelectorAll('[data-demo-plan]').forEach(button=>button.onclick=async()=>{button.disabled=true;const status=root.querySelector('#plan-result');try{const result=await api('/api/billing/demo-purchase','POST',{plan:button.dataset.demoPlan});status.textContent=`Тариф ${result.plan.toUpperCase()} действует до ${new Date(result.expires*1000).toLocaleDateString('ru')}. Денег не списано.`;agentStatus(root.querySelector('.agent-settings .agent-status'));}catch(error){status.textContent=error.message;button.disabled=false;}});
 agentStatus(root.querySelector('.agent-settings .agent-status'));
 $('#settings-agent-check').onclick=async e=>{const button=e.currentTarget;button.disabled=true;try{const result=await api('/api/agent/check','POST',{project_id:S.project.id});$('#settings-agent-result').textContent='Подключено · '+result.model;}catch(err){$('#settings-agent-result').textContent=err.message;}finally{button.disabled=false;}};
}
function starterPrototype(b){
 const detail=b.element_details?.find(d=>d.screen),screen=detail?.screen;
 const title=screen?.title||b.name;
 const fields=screen?.fields?.length?screen.fields:[{id:'request',label:'Описание заявки',type:'textarea',required:true}];
 const controls=fields.map(f=>`<label>${esc(f.label)}${f.type==='textarea'?`<textarea name="${esc(f.id)}" ${f.required?'required':''}></textarea>`:`<input name="${esc(f.id)}" type="${esc(f.type)}" ${f.required?'required':''}>`}</label>`).join('');
 return {title,css:'header{display:flex;justify-content:space-between;align-items:center;margin-bottom:32px;color:#786196}article{background:white;padding:32px;border:1px solid #e5deef;border-radius:18px;box-shadow:0 12px 45px #3221540b}input,textarea{width:100%}nav{display:flex;gap:10px;margin-top:24px}small{color:#877c96}.badge{padding:8px 12px;border-radius:18px;background:#e9f4ef;color:#377461}h1{font-size:30px}',pages:[
  {id:'request',title:'Новая заявка',html:`<header><strong>${esc(b.name)}</strong><small>Демонстрационный интерфейс</small></header><article><h1>${esc(title)}</h1><p>${esc(screen?.text||b.description)}</p><form data-go="review">${controls}<button type="submit">Проверить данные →</button></form></article>`},
  {id:'review',title:'Проверка данных',html:`<header><strong>${esc(b.name)}</strong><small>Проверка заявки</small></header><article><h1>Всё верно?</h1>${fields.map(f=>`<p><strong>${esc(f.label)}</strong><br><span data-value="${esc(f.id)}">—</span></p>`).join('')}<nav><button data-go="request">Изменить</button><button data-go="done">Отправить заявку</button></nav></article>`},
  {id:'done',title:'Заявка принята',html:'<article><span class="badge">Принято</span><h1>Заявка создана</h1><p>Результат имитируется. Реальные данные никуда не отправлены.</p><button data-go="request">Вернуться к заявке</button></article>'}
 ]};
}
function openHtmlPrototype(prototype,preview=false){
 stopWalk();$('#agent-panel')?.remove();
 walk={html:true,blockId:S.selected,xml:block()?.bpmn,panelPositions:{}};
 const session=walk,panel=document.createElement('section');panel.id='walk-panel';panel.className='html-prototype-panel';panel.setAttribute('aria-label','HTML-прототип');
panel.innerHTML=`<div class="walk-heading"><span>◈ ${esc(prototype.title)}${preview?' · предпросмотр':''}</span><button type="button" data-html-back disabled>← Назад</button><button type="button" data-html-reset>Сначала</button><button type="button" data-walk-fullscreen>${document.fullscreenElement?'Уменьшить окно':'На весь экран'}</button><button type="button" data-feature="walk-stop">Закрыть</button></div><div class="html-address"><span data-html-title>Загрузка…</span><span>HTML-прототип · тестовые данные</span></div><iframe title="Интерфейс прототипа" sandbox="allow-scripts allow-forms allow-same-origin"></iframe><p class="html-note">Кликабельный интерфейс. Для проверки ветвлений BPMN используйте «Пройти сценарий».</p>`;
 $('#workspace').classList.add('walking','prototyping');$('#workspace').append(panel);
 panel.querySelector('[data-walk-fullscreen]').onclick=fullscreen;
 const frame=panel.querySelector('iframe');
 panel.querySelector('[data-html-back]').onclick=()=>frame.contentWindow.postMessage({type:'facet-prototype-back'},'*');
 panel.querySelector('[data-html-reset]').onclick=()=>frame.contentWindow.postMessage({type:'facet-prototype-reset'},'*');
	 const message=e=>{
  if(walk!==session||e.source!==frame.contentWindow)return;
  if(e.data?.type==='facet-prototype-ready')frame.contentWindow.postMessage({type:'facet-prototype-init',prototype},'*');
	  if(e.data?.type==='facet-prototype-page'){clearTimeout(loadingTimer);panel.querySelector('[data-html-title]').textContent=e.data.title;panel.querySelector('[data-html-back]').disabled=!e.data.canBack;}
	 };
	 window.addEventListener('message',message);
	 frame.addEventListener('load',()=>frame.contentWindow.postMessage({type:'facet-prototype-init',prototype},'*'),{once:true});
	 frame.src='/prototype-frame.html';
	 const loadingTimer=setTimeout(()=>{if(walk===session&&panel.querySelector('[data-html-title]')?.textContent==='Загрузка…')panel.querySelector('[data-html-title]').textContent='Не удалось загрузить прототип';},5000);
	 attachPrototypeDrag(panel);
	 const cleanup=walk.panelCleanup;walk.panelCleanup=()=>{clearTimeout(loadingTimer);cleanup?.();window.removeEventListener('message',message);};
}
document.addEventListener('fullscreenchange',()=>{const panel=$('#agent-panel.agent-floating');if(panel)(document.fullscreenElement||document.body).append(panel);});
function clearAgentSession(){AI.draft=null;AI.previous=null;AI.report=null;AI.messages=[];AI.changeDraft=null;AI.chatProject=null;$('#agent-panel')?.remove();}

function updateAgentBusy(){
 const workspace=$('#workspace');if(workspace){
  const wasWorking=workspace.classList.contains('agent-working');workspace.classList.toggle('agent-working',AI.busy);workspace.setAttribute('aria-busy',String(AI.busy));
  if(AI.busy){clearTimeout(workspace._agentSettleTimer);workspace.classList.remove('agent-settle');}
  else if(wasWorking){workspace.classList.remove('agent-settle');void workspace.offsetWidth;workspace.classList.add('agent-settle');workspace._agentSettleTimer=setTimeout(()=>workspace.classList.remove('agent-settle'),950);}
 }
 const panel=$('#agent-panel');if(!panel)return;
 panel.querySelectorAll('[data-ai-analyze]').forEach(button=>button.disabled=AI.busy||(button.dataset.aiAnalyze==='bpmn'&&!block()));
 if($('#agent-send'))$('#agent-send').disabled=AI.busy;
 if($('#agent-generate'))$('#agent-generate').disabled=AI.busy||!canEdit()||!block();
}
async function analyzeWithAgent(scope,questionRequired=false){
 if(AI.busy||!S.project)return;
 if(AI.panelContext?.project!==S.project?.id||AI.panelContext?.user!==A.user?.id)return openAgent();
 if(scope==='bpmn'&&!sameAgentContext(AI.panelContext))return openAgent();
 const prompt=$('#agent-prompt').value.trim();
 if(questionRequired&&!prompt)return toast('Напишите вопрос по проекту.');
 const ctx=agentContext(),target=$('#agent-analysis');
 AI.busy=true;updateAgentBusy();target.textContent='Агент изучает связи, схемы и требования…';
 try{
  if(canEdit()){clearTimeout(S.timer);if(!await save())throw Error('Не удалось сохранить актуальный контекст проекта.');}
  if(!sameAgentContext(ctx))throw Error('Контекст изменился. Повторите запрос.');
  const result=await api('/api/agent/analyze','POST',{project_id:ctx.project,block_id:ctx.block,scope,prompt});
  if(A.user?.id!==ctx.user)return;
  AI.report={...ctx,...result};renderAgentAnalysis();
 }catch(err){if(target.isConnected)target.textContent=err.message;else toast(err.message,true);}
 finally{AI.busy=false;updateAgentBusy();const status=$('#agent-panel .agent-status');if(status)agentStatus(status);}
}
function renderAgentAnalysis(){
 const target=$('#agent-analysis'),report=AI.report;
 if(!target)return;
 if(!report||report.user!==A.user?.id||report.project!==S.project?.id){target.textContent='';return;}
 const a=report.analysis,stale=report.revision!==S.project.revision;
 const levels={error:'Ошибка',warning:'Проверить',suggestion:'Предложение'};
 target.innerHTML=`<div class="agent-report-heading"><strong>Разбор ${report.scope==='bpmn'?'BPMN':'проекта'}</strong><small>Блоков: ${report.blocks_analyzed} · версия ${report.revision}</small></div>${stale?'<p class="agent-stale">Проект изменился после анализа. Обновите отчёт перед исправлениями.</p>':''}<p class="agent-summary">${esc(a.summary)}</p><div class="agent-findings">${a.findings.map((f,i)=>`<article class="agent-finding ${f.severity}"><small>${levels[f.severity]}</small><h3>${esc(f.title)}</h3><p>${esc(f.explanation)}</p><p><strong>Что сделать:</strong> ${esc(f.recommendation)}</p>${f.block_id?`<button type="button" data-ai-finding="${i}">${f.element_id?'Показать на схеме':'Открыть блок'} →</button>`:''}</article>`).join('')}</div>${a.questions.length?`<h3>Что уточнить</h3><ul>${a.questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul>`:''}${a.next_steps.length?`<h3>Следующие шаги</h3><ol>${a.next_steps.map(q=>`<li>${esc(q)}</li>`).join('')}</ol>`:''}<p class="agent-note">Выводы ИИ требуют оценки аналитика. Это дополнение к обычному BPMN-чекеру.</p><button type="button" data-ai-export>Скачать отчёт</button>`;
 target.querySelectorAll('[data-ai-finding]').forEach(button=>button.onclick=async()=>{
  if(report.project!==S.project?.id||report.user!==A.user?.id)return toast('Откройте исходный проект.');
  const finding=a.findings[Number(button.dataset.aiFinding)];
  const b=S.project.blocks.find(b=>b.id===finding.block_id);if(!b)return toast('Блок уже удалён. Обновите анализ.');
  stopWalk();selectBlock(b.id,finding.element_id?'bpmn':'overview');
  if(finding.element_id){try{await analyzeBlock(b);if(S.selected===b.id)focusElement(finding.element_id);}catch(err){toast(err.message,true);}}
 });
 target.querySelector('[data-ai-export]').onclick=()=>download('facet-analysis.json',JSON.stringify(report,null,2));
}
