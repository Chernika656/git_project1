'use strict';
const screenFieldTypes={text:'Текст',email:'Электронная почта',number:'Число',textarea:'Многострочный текст'};
function screenFor(id,b=block()){return b?.element_details?.find(d=>d.element_id===id)?.screen;}
function screenMarkup(screen,values={},preview=false){
 return `<div class="prototype-brand"><span>◈</span> ${esc(S.project.name)}</div><h2>${esc(screen.title)}</h2><p class="prototype-copy">${esc(screen.text)}</p>${screen.fields.map(f=>`<label class="field">${esc(f.label)}${f.required?' <span class="required-star">*</span>':''}${f.type==='textarea'?`<textarea name="${esc(f.id)}" maxlength="2000" ${f.required?'required':''} ${preview?'disabled':''}>${esc(values[f.id]||'')}</textarea>`:`<input name="${esc(f.id)}" type="${esc(f.type)}" maxlength="2000" ${f.type==='number'?'step="any"':''} value="${esc(values[f.id]||'')}" ${f.required?'required':''} ${preview?'disabled':''}>`}</label>`).join('')}<button type="${preview?'button':'submit'}" class="primary prototype-submit" ${preview?'disabled':''}>${esc(screen.button)} →</button>`;
}
async function openScreenEditor(id){
 if(!canEdit())return;
 const project=S.project,b=block(),node=taskShapes().find(n=>n.element_id===id);if(!node)return toast('Экран можно привязать к задаче BPMN.');
 const draft=structuredClone(screenFor(id)||{title:node.name||'Новый экран',text:'',button:'Продолжить',fields:[]});
 modal('Экран задачи',`<div id="screen-builder"><div class="screen-settings"><p class="modal-note">${esc(node.name||id)} · экран откроется на этом шаге прототипа.</p>${field('Заголовок','screen-title',draft.title)}${field('Текст на экране','screen-text',draft.text,'textarea')}${field('Название кнопки','screen-button',draft.button)}<div class="section-card-heading"><h3>Поля</h3><button type="button" id="screen-add">+ Поле</button></div><div id="screen-fields"></div><p class="inspector-note">Кнопка ведёт по исходящей связи BPMN. Ветки выбираются отдельно на развилке.</p></div><div class="screen-preview-wrap"><span class="eyebrow">ПРЕДПРОСМОТР</span><div id="screen-preview" class="prototype-screen"></div></div></div>`,async()=>{
  if(!canEdit()||S.project!==project||block()!==b)throw Error('Откройте экран заново в выбранном блоке.');
  if(!draft.title.trim()||!draft.button.trim())throw Error('Укажите заголовок и название кнопки.');
  if(draft.fields.some(f=>!f.label.trim()))throw Error('Добавьте подписи ко всем полям.');
  let detail=b.element_details?.find(d=>d.element_id===id);
  if(!detail){detail={element_id:id,description:'',uml:{participants:[],messages:[]}};(b.element_details??=[]).push(detail);}
  detail.screen=structuredClone(draft);
  if(!await save())throw Error('Экран не сохранён на сервере. Экспортируйте проект перед перезагрузкой.');
  render();toast('Экран сохранён. Нажмите «Запустить прототип».');
 },'Сохранить экран');
 const preview=()=>{$('#screen-preview').innerHTML=screenMarkup(draft,{},true);};
 for(const [name,key,max] of [['screen-title','title',200],['screen-text','text',10000],['screen-button','button',100]]){
  const el=$(`[name="${name}"]`);el.maxLength=max;el.oninput=()=>{draft[key]=el.value;preview();};
 }
 function rows(){
  $('#screen-fields').innerHTML=draft.fields.map((f,i)=>`<div class="screen-field-row" data-field-index="${i}"><label class="field">Подпись<input data-setting="label" value="${esc(f.label)}" maxlength="200"></label><label class="field">Тип<select data-setting="type">${optionList(screenFieldTypes,f.type)}</select></label><label class="screen-required"><input type="checkbox" data-setting="required" ${f.required?'checked':''}>Обязательное</label><button type="button" data-remove-field="${i}" aria-label="Удалить поле ${i+1}">×</button></div>`).join('')||'<p class="inspector-note">Можно оставить только текст и кнопку или добавить до 12 полей.</p>';
  $('#screen-add').disabled=draft.fields.length>=12;
 }
 $('#screen-fields').oninput=e=>{const row=e.target.closest('[data-field-index]');if(!row)return;const f=draft.fields[Number(row.dataset.fieldIndex)],key=e.target.dataset.setting;if(key){f[key]=key==='required'?e.target.checked:e.target.value;preview();}};
 $('#screen-fields').onclick=e=>{const remove=e.target.closest('[data-remove-field]');if(remove){draft.fields.splice(Number(remove.dataset.removeField),1);rows();preview();}};
 $('#screen-add').onclick=()=>{if(draft.fields.length>=12)return;draft.fields.push({id:uid(),label:'Новое поле',type:'text',required:false});rows();preview();};rows();preview();
}
function addScreenTaskButton(id,node){
 if(!taskShapes().some(n=>n.element_id===id)||!canEdit())return;
 $('#open-task-uml').insertAdjacentHTML('afterend',` <button type="button" class="primary" id="edit-task-screen">${screenFor(id)?'Изменить экран':'＋ Экран прототипа'}</button>`);
 $('#edit-task-screen').onclick=async()=>{try{
  const data=new FormData($('#modal-form'));
  if(data.get('name')!==node.name)await editBpmn({op:'rename',id,name:data.get('name')});
  const b=block();let detail=b.element_details?.find(d=>d.element_id===id);
  const fields=readTaskFields(data);
  if(detail||Object.values(fields).some(v=>v.trim())){if(!detail){detail={element_id:id,description:'',uml:{participants:[],messages:[]}};(b.element_details??=[]).push(detail);}Object.assign(detail,fields);if(!await save())return;}
  await openScreenEditor(id);
 }catch(err){toast(err.message,true);}};
}
function screenList(){
 const tasks=taskShapes();
 modal('Экраны прототипа',`<p class="modal-note">Добавьте экраны к задачам, которые пользователь должен пройти. Шаги без экранов останутся видны как этапы процесса.</p><div class="screen-task-list">${tasks.map(n=>`<div><span><strong>${esc(n.name||n.element_id)}</strong><small>${screenFor(n.element_id)?'Экран настроен':'Без экрана'}</small></span>${canEdit()?`<button type="button" data-edit-screen="${esc(n.element_id)}">${screenFor(n.element_id)?'Изменить':'Добавить'}</button>`:''}</div>`).join('')||'<p>Сначала добавьте задачи в BPMN.</p>'}</div>`,()=>{});$('#submit-modal').hidden=true;
 $('#modal-body').onclick=e=>{const button=e.target.closest('[data-edit-screen]');if(button)openScreenEditor(button.dataset.editScreen).catch(err=>toast(err.message,true));};
}
function launchPrototype(){
 if(!block())return toast('Выберите блок проекта.');
 S.connect=null;
 openHtmlPrototype(block().html_prototype||starterPrototype(block()));
}
function showPrototypeScreen(panel,id,options){
 if(!walk?.prototype)return;
 panel.classList.add('prototype-panel');$('#workspace').classList.add('prototyping');
 panel.querySelector('.walk-heading span').textContent='◈ ПРОТОТИП · '+(walk.path.length?'ШАГ '+walk.path.length:'СТАРТ');
 const screen=walk.screens.get(id);if(!screen)return;
 if(options.next.length!==1)return; // Неверные или неподдерживаемые переходы остаются видимыми.
 panel.querySelectorAll('[data-feature="walk-next"]').forEach(el=>el.remove());
 const form=document.createElement('form');form.id='prototype-form';form.className='prototype-screen';
 form.innerHTML=screenMarkup(screen,walk.values.get(id)||{});
 panel.querySelector('.walk-buttons').before(form);
 const persist=()=>walk.values.set(id,Object.fromEntries(new FormData(form)));
 form.oninput=persist;
 form.onsubmit=e=>{
  e.preventDefault();if(!walk||!form.reportValidity())return;
  for(const input of form.querySelectorAll('[required]'))if(!input.value.trim()){input.setCustomValidity('Заполните поле.');input.reportValidity();input.oninput=()=>input.setCustomValidity('');return;}
  persist();walk.path.push(options.next[0].target);showWalk();
 };
 const note=document.createElement('p');note.className='prototype-session-note';note.textContent='Тестовый запуск · значения полей хранятся только до завершения прототипа.';form.append(note);
}
document.addEventListener('click',e=>{const el=e.target.closest('[data-prototype]');if(!el)return;try{if(el.dataset.prototype==='screens')screenList();else if(el.dataset.prototype==='launch')launchPrototype();}catch(err){toast(err.message,true);}});
