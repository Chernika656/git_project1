'use strict';
async function logoutAccount(){try{if(S.timer)save();if(S.pending)await S.queue;if(S.failed){toast('Перед выходом экспортируйте несохранённые правки.',true);return;}await api('/api/auth/logout','POST',{});clearInterval(notificationTimer);A.user=null;A.csrf=null;S.project=null;S.analyses.clear();S.undo.clear();$('#content').innerHTML='';$('#inspector').innerHTML='';$('#block-list').innerHTML='';$('#section-main').innerHTML='';showAuth('login','Вы вышли из аккаунта.');}catch(e){toast(e.message,true);}}
const A={user:null,csrf:null,space:null,spaces:[],delivery:'local',migration:false,pendingInvite:null,telegram:null,securityEvents:[],notificationCount:0};
function currentSpecialty(){return A.spaces.find(space=>space.id===A.space)?.team_specialty||A.user?.specialty||'business';}
const specialties={leader:'Руководитель',product:'Product Manager',business:'Бизнес-аналитик',system:'Системный аналитик',developer:'Разработчик',qa:'Тестировщик',designer:'Продуктовый дизайнер',manager:'Менеджер проекта'};
const seniorities={junior:'Junior',middle:'Middle',senior:'Senior',lead:'Lead',head:'Head'};
const teamRoles={owner:'Владелец',admin:'Администратор',member:'Участник'};
const accessRoles={none:'Нет доступа',viewer:'Просмотр',commenter:'Комментирование',editor:'Редактирование',manager:'Управление'};
const editActions=new Set(['confirm-uml','link-block','delete-block','import-bpmn','new-bpmn','edit-xml','add-node','connect-node','undo-bpmn','uml-actors','uml-message','uml-messages','delete-node','add-block']);
function canEdit(){return !!A.user&&!!S.project&&['editor','manager'].includes(S.project.access);}
function applyAccess(){const allowed=canEdit();$('#workspace').classList.toggle('empty-workspace',!S.project);document.querySelectorAll('[data-view]').forEach(el=>el.disabled=!S.project);$('#present').disabled=!S.project;document.body.classList.toggle('readonly',!allowed);['#add-block','#add-sidebar'].forEach(s=>$(s).disabled=!allowed);document.querySelectorAll('[data-action]').forEach(b=>{if(editActions.has(b.dataset.action))b.disabled=!allowed;});document.querySelectorAll('[data-unlink]').forEach(b=>b.disabled=!allowed);$('#project-access').hidden=S.project?.access!=='manager';if(!allowed&&S.project)$('#save-state').textContent=accessRoles[S.project.access]||'Просмотр';}
document.addEventListener('click',e=>{const button=e.target.closest('[data-action]');if((button&&editActions.has(button.dataset.action)||e.target.closest('[data-unlink]'))&&!canEdit()){e.preventDefault();e.stopImmediatePropagation();toast('Для этого действия нужно право редактирования.',true);}},true);
function optionList(map,value){return Object.entries(map).map(([v,n])=>`<option value="${v}" ${value===v?'selected':''}>${n}</option>`).join('');}
function authField(label,name,type='text',autocomplete='',value=''){return `<label class="field">${label}<input name="${name}" type="${type}" autocomplete="${autocomplete}" value="${esc(value)}" ${type==='password'?'minlength="15" maxlength="128"':name==='name'?'maxlength="100"':'maxlength="254"'} required></label>`;}
function deliveryHint(){return A.delivery==='local'?'<div class="auth-notice">Локальный режим: письма сохраняются в <strong>data/mailbox</strong> в папке приложения. Откройте последнее письмо .eml и перейдите по ссылке. Отправка на почту появится после настройки SMTP.</div>':'<p class="auth-hint">Проверьте входящие письма и папку «Спам».</p>';}
let telegramPoll;
async function telegramLogin(){
 clearInterval(telegramPoll);const button=$('#telegram-login');button.disabled=true;$('#auth-error').hidden=true;
 // Open the window directly from the click. Safari and mobile browsers often block
 // windows created only after the asynchronous request has finished.
 const insideTelegram=/Telegram/i.test(navigator.userAgent);
 const botWindow=insideTelegram?null:window.open('about:blank','facet-telegram');
 if(botWindow)botWindow.opener=null;
 try{const link=await api('/api/auth/telegram/start','POST',{});
  if(botWindow)botWindow.location.replace(link.url);
  const status=$('#telegram-status');status.textContent=insideTelegram?'Откройте бота и нажмите Start. Затем вернитесь на эту страницу — вход завершится автоматически. ':'В Telegram нажмите «Запустить» или Start. После подтверждения вернитесь сюда — вход завершится автоматически. ';
  const reopen=document.createElement('a');reopen.href=link.url;reopen.target='_blank';reopen.rel='noopener';reopen.textContent=botWindow?'Открыть бота ещё раз':'Открыть Telegram-бота';status.append(reopen);
  const deadline=Date.now()+link.expires_in*1000;
  telegramPoll=setInterval(async()=>{if(Date.now()>deadline){clearInterval(telegramPoll);button.disabled=false;$('#telegram-status').textContent='Ссылка истекла. Запустите вход ещё раз.';return;}
   try{const result=await api('/api/auth/telegram/complete','POST',{token:link.token});if(result.state!=='confirmed')return;clearInterval(telegramPoll);A.user=result.user;A.csrf=result.csrf;await bootAccounts();}
   catch(error){clearInterval(telegramPoll);button.disabled=false;$('#auth-error').textContent=error.message;$('#auth-error').hidden=false;}
  },1500);
 }catch(error){if(botWindow)botWindow.close();button.disabled=false;$('#auth-error').textContent=error.message;$('#auth-error').hidden=false;}
}
async function linkTelegramProfile(){
 clearInterval(telegramPoll);const button=$('#profile-link-telegram'),status=$('#profile-telegram-status');button.disabled=true;status.textContent='Создаём безопасную ссылку…';
 const botWindow=window.open('about:blank','facet-telegram-link');if(botWindow)botWindow.opener=null;
 try{const link=await api('/api/auth/telegram/start','POST',{});if(botWindow)botWindow.location.replace(link.url);
  status.innerHTML=`Подтвердите привязку в боте. <a href="${esc(link.url)}" target="_blank" rel="noopener">Открыть Telegram</a>`;
  const deadline=Date.now()+link.expires_in*1000;
  telegramPoll=setInterval(async()=>{if(Date.now()>deadline){clearInterval(telegramPoll);button.disabled=false;status.textContent='Ссылка истекла. Попробуйте ещё раз.';return;}
   try{const result=await api('/api/auth/telegram/complete','POST',{token:link.token});if(result.state!=='confirmed')return;clearInterval(telegramPoll);A.user=result.user;A.csrf=result.csrf;await refreshIdentity();accountChrome();if($('#modal').open)$('#modal').close();if(typeof showSection==='function'&&typeof activeSection!=='undefined'&&activeSection==='account')await showSection('account');toast('Telegram привязан к аккаунту.');}
   catch(error){clearInterval(telegramPoll);button.disabled=false;status.textContent=error.message;}
  },1500);
 }catch(error){if(botWindow)botWindow.close();button.disabled=false;status.textContent=error.message;}
}
function addEmailDialog(){
 modal('Добавить почту',`<p class="modal-note">После подтверждения вы сможете входить как через Telegram, так и по почте с этим паролем.</p>${authField('Почта','email','email','email')}${authField('Пароль','password','password','new-password')}${authField('Повторите пароль','password_confirm','password','new-password')}<p class="auth-hint">Пароль должен содержать от 15 до 128 символов.</p>`,async data=>{
  if(data.get('password')!==data.get('password_confirm'))throw new Error('Пароли не совпадают.');
  const result=await api('/api/auth/email/start','POST',{email:data.get('email'),password:data.get('password')});
  toast(result.delivery==='local'?'Письмо сохранено локально.':'Письмо отправлено. Откройте ссылку подтверждения.');
 },'Отправить письмо');
}
function unlinkLoginMethod(method){
 const label=method==='email'?'почту':'Telegram';
 modal(`Отключить ${label}?`,`<p class="modal-note">После отключения вход этим способом станет недоступен. Проекты и данные аккаунта сохранятся.</p>${authField('Текущий пароль','password','password','current-password')}`,async data=>{
  await api('/api/auth/methods/unlink','POST',{method,password:data.get('password')});
  await refreshIdentity();accountChrome();toast(`${method==='email'?'Почта':'Telegram'} отключён.`);
  if(typeof activeSection!=='undefined'&&activeSection==='account')await showSection('account');
 },'Отключить');
}
function showAuth(mode='login',message='',token=''){
 clearInterval(telegramPoll);
 if(typeof clearAgentSession==='function')clearAgentSession();
 if(typeof stopWalk==='function')stopWalk();
 document.body.classList.add('auth-locked');$('#auth-screen').hidden=false;if($('#modal').open)$('#modal').close();
 const titles={login:'С возвращением',register:'Создайте аккаунт',forgot:'Восстановить пароль',resend:'Подтвердить почту',verify:'Подтверждение почты',reset:'Новый пароль',email:'Добавление почты'};
 const subtitles={login:'Войдите, чтобы продолжить работу над проектами.',register:'Начните в личном пространстве. Команду можно создать позже.',forgot:'Отправим ссылку для установки нового пароля.',resend:'Запросите новую ссылку подтверждения.',verify:'Подтвердите адрес и вернитесь ко входу.',reset:'После смены пароля все прошлые сессии завершатся.',email:'Подтвердите адрес, чтобы входить по почте и через Telegram.'};
 let fields='';if(mode==='register')fields+=authField('Ваше имя','name','text','name');
 if(['login','register','forgot','resend'].includes(mode))fields+=authField('Почта','email','email','email');
 if(['login','register','reset'].includes(mode))fields+=authField(mode==='reset'?'Новый пароль':'Пароль','password','password',mode==='login'?'current-password':'new-password');
 if(mode==='register')fields+=`<label class="field">Специализация<select name="specialty">${optionList(specialties,'business')}</select></label><p class="auth-hint">Пароль: 15–128 символов. Можно использовать длинную фразу.</p>`;
 const labels={login:'Войти',register:'Создать аккаунт',forgot:'Отправить ссылку',resend:'Отправить письмо',verify:'Подтвердить почту',reset:'Сохранить пароль',email:'Подтвердить и подключить'};
 $('#auth-card').innerHTML=`<div class="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</div><h2>${titles[mode]}</h2><p>${subtitles[mode]}</p>${message?`<div class="auth-notice">${esc(message)}</div>`:''}<form id="auth-form">${fields}<div id="auth-error" class="auth-error" hidden></div><button type="submit" class="primary">${labels[mode]}</button></form>`+
 (['login','register'].includes(mode)&&A.telegram?.enabled?`<div class="auth-divider"><span>или</span></div><button type="button" id="telegram-login" class="telegram-login"><span>➤</span> Продолжить через Telegram</button><p id="telegram-status" class="auth-hint"></p>`:'')+
 (mode==='login'?'<div class="auth-switch"><span>Нет аккаунта?</span><button class="text-button" data-auth="register">Зарегистрироваться</button></div><div class="auth-switch"><button class="text-button" data-auth="forgot">Забыли пароль?</button><button class="text-button" data-auth="resend">Подтвердить почту</button></div>':'<div class="auth-switch"><button class="text-button" data-auth="login">← Вернуться ко входу</button></div>')+
 (A.pendingInvite?'<div class="auth-notice">У вас есть приглашение. Войдите с той почтой, на которую его отправили.</div>':'');
 if($('#telegram-login'))$('#telegram-login').onclick=telegramLogin;
 $('#auth-form').onsubmit=async e=>{e.preventDefault();const submit=e.target.querySelector('[type=submit]');submit.disabled=true;$('#auth-error').hidden=true;const data=Object.fromEntries(new FormData(e.target));if(mode==='login')window.FacetAuthTransition?.start();try{
  const endpoint={forgot:'forgot',resend:'resend',verify:'verify',reset:'reset',login:'login',register:'register',email:'email/confirm'}[mode];if(token)data.token=token;
  const result=await api('/api/auth/'+endpoint,'POST',data);
  if(mode==='login'){A.user=result.user;A.csrf=result.csrf;const ready=await bootAccounts();if(ready)await window.FacetAuthTransition?.success();else window.FacetAuthTransition?.fail();return;}
  if(mode==='email'){history.replaceState(null,'',location.pathname);if(A.user){await bootAccounts();toast(result.message);}else showAuth('login',result.message);return;}
  if(mode==='verify'||mode==='reset'){
   history.replaceState(null,'',location.pathname);
   if(mode==='verify'&&A.user){await bootAccounts();toast(result.message);}
   else showAuth('login',result.message);
   return;
  }
  showAuth('login','Если адрес подходит для этого действия, письмо подготовлено.');$('#auth-card').insertAdjacentHTML('beforeend',deliveryHint());
 }catch(err){if(mode==='login')window.FacetAuthTransition?.fail();$('#auth-error').textContent=err.message;$('#auth-error').hidden=false;}finally{submit.disabled=false;}};
}
document.addEventListener('click',e=>{const el=e.target.closest('[data-auth]');if(el)showAuth(el.dataset.auth);});
async function refreshIdentity(){const me=await api('/api/auth/me');A.user=me.user;A.csrf=me.csrf;A.spaces=me.spaces;A.delivery=me.delivery;A.migration=me.migration_available;A.telegram=me.telegram;A.securityEvents=me.security_events||[];A.notificationCount=me.notification_count||0;return me;}
function renderNotificationCount(){const badge=$('#notification-count');if(!badge)return;badge.textContent=A.notificationCount>99?'99+':String(A.notificationCount);badge.hidden=!A.notificationCount;}
let notificationTimer=0,notificationSyncing=false;
async function syncNotificationCount(notify=true){
 if(!A.user||document.hidden||notificationSyncing)return;
 notificationSyncing=true;try{const previous=A.notificationCount,result=await api('/api/notifications/count');A.notificationCount=result.unread||0;renderNotificationCount();if(notify&&A.notificationCount>previous)toast(A.notificationCount-previous===1?'Новое уведомление.':`Новых уведомлений: ${A.notificationCount-previous}`);}catch(error){if(error.status===401)clearInterval(notificationTimer);}finally{notificationSyncing=false;}
}
function startNotificationSync(){clearInterval(notificationTimer);notificationTimer=setInterval(()=>syncNotificationCount(true),30000);}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncNotificationCount(true);});
window.addEventListener('online',()=>syncNotificationCount(false));
async function openNotificationCenter(){
 try{const [result,tasks]=await Promise.all([api('/api/notifications'),api('/api/mobile/tasks?paged=1&filter=active&page=1')]);A.notificationCount=result.unread;renderNotificationCount();const icons={task:'✓',deadline:'⏰',approval:'✦',team:'♧'};
  const digest=`<section class="task-digest"><div class="task-digest-head"><strong>Текущие задачи</strong><button type="button" id="digest-open-tasks" class="text-button">Открыть задачи →</button></div><div class="task-digest-counts"><span><strong>${tasks.counts.todo}</strong> новых</span><span><strong>${tasks.counts.in_progress}</strong> в работе</span><span><strong>${tasks.counts.done}</strong> завершено</span></div>${tasks.items.length?`<div class="task-digest-list">${tasks.items.slice(0,3).map(item=>`<div><strong>${esc(item.title)}</strong><small>${item.project_name?esc(item.project_name)+' · ':''}${item.status==='in_progress'?'В работе':'Новая'}${item.due?' · до '+new Date(item.due*1000).toLocaleDateString('ru'):''}</small></div>`).join('')}</div>`:'<p>Активных задач нет.</p>'}</section>`;
  modal('Уведомления и задачи',digest+`<div class="notification-toolbar"><span>${result.unread?`Непрочитанных: ${result.unread}`:'Новых уведомлений нет'}</span>${result.unread?'<button type="button" id="notifications-read-all" class="text-button">Прочитать все</button>':''}</div><div class="notification-list">${result.items.map(item=>`<button type="button" class="notification-item ${item.unread?'unread':''}" data-notification="${esc(item.key)}" data-target="${esc(item.target)}"><span class="notification-icon">${icons[item.kind]||'•'}</span><span><strong>${esc(item.title)}</strong><small>${esc(item.body)}</small><small>${new Date(item.created*1000).toLocaleString('ru')}</small></span></button>`).join('')||'<div class="projects-empty"><p>Новых событий пока нет.</p></div>'}</div>`,()=>{},'Закрыть');
  $('#digest-open-tasks').onclick=()=>{$('#modal').close();showSection('tasks');};
  $('#notifications-read-all')?.addEventListener('click',async()=>{await api('/api/notifications/read','POST',{});A.notificationCount=0;renderNotificationCount();document.querySelectorAll('.notification-item').forEach(item=>item.classList.remove('unread'));$('#notifications-read-all').remove();});
  document.querySelectorAll('[data-notification]').forEach(item=>item.onclick=async()=>{await api('/api/notifications/read','POST',{keys:[item.dataset.notification]});A.notificationCount=Math.max(0,A.notificationCount-(item.classList.contains('unread')?1:0));renderNotificationCount();$('#modal').close();await showSection(item.dataset.target);});
 }catch(error){toast(error.message,true);}
}
async function openGlobalSearch(){
 const commands=[{icon:'▱',title:'Открыть проекты',action:'projects'},{icon:'◫',title:'Открыть аналитику',action:'analytics'},{icon:'✓',title:'Открыть задачи',action:'tasks'},{icon:'♧',title:'Открыть команду',action:'team'},{icon:'✦',title:'Открыть агента',action:'agent'}];
 modal('Поиск и команды',`<label class="field command-search-field">Поиск по Facet<input id="global-search-input" autocomplete="off" placeholder="Проект, блок, BPMN, задача или участник…"></label><div id="global-search-results" class="command-results"></div><p class="auth-hint">Enter — открыть первый результат · Esc — закрыть</p>`,async()=>{document.querySelector('#global-search-results [data-search-result]')?.click();},'Открыть');
 const input=$('#global-search-input'),list=$('#global-search-results'),icons={project:'▱',block:'▦',bpmn:'◇',requirements:'≡',technical:'⌘',glossary:'Aa',task:'✓',member:'♧'};
 const drawCommands=()=>{list.innerHTML=commands.map((item,index)=>`<button type="button" data-search-result data-command="${item.action}" class="command-result ${index===0?'selected':''}"><span>${item.icon}</span><span><strong>${item.title}</strong><small>Быстрая команда</small></span></button>`).join('');bind();};
 const bind=()=>list.querySelectorAll('[data-search-result]').forEach(button=>button.onclick=async()=>{const command=button.dataset.command;if(command){$('#modal').close();return showSection(command);}const item=button._searchItem;if(!item)return;$('#modal').close();if(item.target_section)return showSection(item.target_section);if(item.space_id&&item.space_id!==A.space)await openSpace(item.space_id);if(item.project_id!==S.project?.id)await openProject(item.project_id);if(item.block_id)selectBlock(item.block_id,item.view||'overview');else if(item.view)setView(item.view);if(item.element_id){await analyzeBlock(block());focusElement(item.element_id);}if(item.term_id)focusTerm(item.term_id);});
 let timer=0,request=0;input.oninput=()=>{clearTimeout(timer);const value=input.value.trim(),current=++request;if(value.length<2)return drawCommands();list.innerHTML='<div class="command-loading">Поиск…</div>';timer=setTimeout(async()=>{try{const result=await api('/api/search?q='+encodeURIComponent(value));if(current!==request)return;list.innerHTML=result.items.map((item,index)=>`<button type="button" data-search-result class="command-result ${index===0?'selected':''}"><span>${icons[item.kind]||'•'}</span><span><strong>${esc(item.title)}</strong><small>${esc(item.subtitle||'')}</small></span><span class="command-kind">${esc(item.kind)}</span></button>`).join('')||'<div class="projects-empty"><p>Ничего не найдено.</p></div>';list.querySelectorAll('[data-search-result]').forEach((button,index)=>button._searchItem=result.items[index]);bind();}catch(error){list.innerHTML=`<div class="auth-error">${esc(error.message)}</div>`;}},220);};
 drawCommands();setTimeout(()=>input.focus(),0);
}
function accountChrome(){
 $('#account-menu').textContent=A.user.name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();$('#account-menu').className='avatar '+A.user.color;$('#account-menu').title=A.user.name;
 $('#space-select').innerHTML=A.spaces.map(s=>`<option value="${esc(s.id)}">${s.kind==='personal'?'⌂':'♧'} ${esc(s.name)}</option>`).join('')+'<option value="__new">＋ Создать команду</option>';$('#space-select').value=A.space;
 const space=A.spaces.find(s=>s.id===A.space);$('#team-settings').innerHTML=space?.kind==='team'?'<span>♧</span>Участники и команда':'<span>＋</span>Создать команду';
 $('.sidebar-bottom').innerHTML=`<span class="local-dot"></span><div><strong>${esc(A.user.name)}</strong><small>${space?.kind==='team'?esc(teamRoles[space.role])+' · ':''}${esc(specialties[currentSpecialty()])}</small></div>`;
 renderNotificationCount();
}
$('#notification-center').onclick=openNotificationCenter;
$('#global-search').onclick=openGlobalSearch;
document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(A.user)openGlobalSearch();}});
function emptyProjects(){S.project=null;S.selected=null;S.analyses.clear();S.undo.clear();S.failed=false;$('#page-title').textContent=A.spaces.find(s=>s.id===A.space)?.name||'Проекты';$('#page-subtitle').textContent='Ваше пространство для совместной работы';$('#block-list').innerHTML='';$('#inspector').innerHTML='<p class="inspector-note">Выберите или создайте проект.</p>';$('#view-actions').innerHTML='';$('#view-hint').textContent='';$('#issue-count').textContent='0';$('#issue-scope').textContent='';$('#issues').innerHTML='';$('#canvas-controls').style.display='none';$('#content').innerHTML=`<div class="welcome-card"><span class="block-icon" style="margin:0 auto 20px">▦</span><h2>Место для нового проекта</h2><p>Создайте проект с нуля или откройте демонстрационный пример. Участникам команды доступны только назначенные им проекты.</p><div class="modal-actions"><button class="primary" id="welcome-new">+ Новый проект</button><button id="welcome-demo">Демо-проект</button></div>${A.migration?'<button class="text-button" id="welcome-migrate">Перенести локальные проекты</button>':''}</div>`;$('#save-state').textContent='';applyAccess();$('#welcome-new').onclick=newProjectDialog;$('#welcome-demo').onclick=async()=>{try{const p=await api('/api/projects','POST',{name:'Интернет-магазин',space_id:A.space,demo:true});await refreshProjects();await openProject(p.id);}catch(e){toast(e.message,true);}};if($('#welcome-migrate'))$('#welcome-migrate').onclick=claimDialog;}
async function openSpace(id){if(S.timer)save();if(S.pending)await S.queue;if(S.failed){$('#space-select').value=A.space;return toast('Сначала экспортируйте несохранённые правки.',true);}A.space=id;localStorage.setItem('workspace.space.'+A.user.id,id);accountChrome();const projects=await refreshProjects();if(projects.length){const last=localStorage.getItem('workspace.lastProject');await openProject(projects.some(p=>p.id===last)?last:projects[0].id);}else emptyProjects();}
async function bootAccounts(){
 try{await refreshIdentity();const hash=new URLSearchParams(location.hash.slice(1));
 if(hash.has('invite')){A.pendingInvite=hash.get('invite');sessionStorage.setItem('workspace.invite',A.pendingInvite);history.replaceState(null,'',location.pathname);}
 A.pendingInvite=A.pendingInvite||sessionStorage.getItem('workspace.invite');
 if(hash.has('verify')||hash.has('reset')||hash.has('email')){const mode=hash.has('verify')?'verify':hash.has('reset')?'reset':'email';const token=hash.get(mode);history.replaceState(null,'',location.pathname);showAuth(mode,'',token);return;}
 if(!A.user){showAuth();return;}
 document.body.classList.remove('auth-locked');$('#auth-screen').hidden=true;$('#auth-card').innerHTML='';
 const link=new URL(location.href),projectId=link.searchParams.get('project'),blockId=link.searchParams.get('block');
 let linkedProject=null;
 if(projectId){try{linkedProject=await api('/api/projects/'+encodeURIComponent(projectId));}catch(error){toast('Не удалось открыть проект из ссылки: '+error.message,true);}}
 const last=localStorage.getItem('workspace.space.'+A.user.id);
 const linkedSpace=linkedProject&&A.spaces.some(space=>space.id===linkedProject.space_id)?linkedProject.space_id:null;
 await openSpace(linkedSpace||(A.spaces.some(s=>s.id===last)?last:A.spaces[0].id));
 if(linkedProject){
  if(S.project?.id!==linkedProject.id)await openProject(linkedProject.id);
  if(blockId){if(S.project.blocks.some(item=>item.id===blockId))selectBlock(blockId,'overview');else toast('Блок из ссылки больше не существует.',true);}
  link.searchParams.delete('project');link.searchParams.delete('block');history.replaceState(null,'',link.pathname+link.search+link.hash);
 }
 window.dispatchEvent(new CustomEvent('workspace-ready',{detail:{linkedProject:!!linkedProject}}));
 startNotificationSync();
 if(A.pendingInvite)inviteDialog();
 return true;
 }catch(e){
  if(e.status===401){showAuth('login','Сессия завершена. Войдите заново.');return false;}
  document.body.classList.add('auth-locked');$('#auth-screen').hidden=false;
  $('#auth-card').innerHTML=`<div class="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</div><h2>Не удалось загрузить Facet</h2><p>${esc(e.message||'Проверьте подключение к сети.')}</p><button type="button" class="primary" id="auth-retry">Повторить подключение</button>`;
  $('#auth-retry').onclick=bootAccounts;
  return false;
 }
}
async function createTeamDialog(){try{const status=await api('/api/agent/status');if(status.plan!=='team'){await showSection('settings');$('#plan-settings')?.scrollIntoView({behavior:'smooth'});return toast('Для создания команды включите тариф Team.',true);}}catch(error){return toast(error.message,true);}modal('Создать команду',field('Название команды','name','Новая команда'),async d=>{const result=await api('/api/spaces','POST',{name:d.get('name')});await refreshIdentity();await openSpace(result.id);},'Создать');}
$('#space-select').onchange=async e=>{try{if(e.target.value==='__new'){e.target.value=A.space;createTeamDialog();}else await openSpace(e.target.value);}catch(err){toast(err.message,true);}};
$('#team-settings').onclick=()=>{const space=A.spaces.find(s=>s.id===A.space);if(space.kind==='personal')createTeamDialog();else teamDialog();};
function inviteDialog(){modal('Присоединиться к команде',`<p class="modal-note">Приглашение будет принято для аккаунта <strong>${esc(A.user.email)}</strong>. Почта должна совпадать с адресом приглашения.</p>`,async()=>{const r=await api('/api/invitations/accept','POST',{token:A.pendingInvite});A.pendingInvite=null;sessionStorage.removeItem('workspace.invite');await refreshIdentity();await openSpace(r.space_id);toast('Вы присоединились к команде.');},'Принять приглашение');}
function claimDialog(){modal('Перенести локальные проекты',`<p class="modal-note">Проекты прежней версии будут перенесены в ваше личное пространство. Самостоятельная регистрация доступа к ним не даёт.</p><p class="copy-hint">Ключ находится в файле data/local-transfer.key в папке приложения. Перенос можно выполнить один раз.</p>${field('Ключ переноса','key')}`,async d=>{const r=await api('/api/legacy/claim','POST',{key:d.get('key').trim()});await refreshIdentity();await openSpace(A.spaces.find(s=>s.kind==='personal').id);toast('Перенесено проектов: '+r.count);},'Перенести проекты');}
$('#account-menu').onclick=()=>{
 const telegramLabel=A.telegram?.linked?(A.telegram.linked.username?'@'+A.telegram.linked.username:'Telegram привязан'):'Telegram не привязан';
 const security=`<div class="section-note">Вход и безопасность</div><div class="identity-method"><div><strong>Почта</strong><small>${A.user.telegram_only?'Не подключена':esc(A.user.email)+' · подтверждена'}</small></div>${A.user.telegram_only?'<button type="button" id="profile-add-email">Добавить почту</button>':A.telegram?.linked?'<button type="button" id="profile-unlink-email">Отключить</button>':'<span class="role-pill">Основной вход</span>'}</div><div class="identity-method"><div><strong>Telegram</strong><small>${esc(telegramLabel)}</small></div>${A.telegram?.linked?(A.user.telegram_only?'<span class="role-pill">Основной вход</span>':'<button type="button" id="profile-unlink-telegram">Отключить</button>'):'<button type="button" id="profile-link-telegram">Привязать Telegram</button>'}</div><p id="profile-telegram-status" class="auth-hint"></p>`;
 modal('Ваш профиль',`<div class="profile-preview"><span class="avatar ${A.user.color}">${esc(A.user.name[0])}</span><div><strong>${esc(A.user.name)}</strong><div class="modal-note">${A.user.telegram_only?'Вход через Telegram':esc(A.user.email)+' · почта подтверждена'}</div></div></div>${field('Ваше имя','name',A.user.name)}<input type="hidden" name="specialty" value="${esc(A.user.specialty)}"><label class="field">Цвет аватара<select name="color">${optionList({purple:'Лавандовый',blue:'Голубой',peach:'Персиковый',teal:'Бирюзовый',rose:'Розовый'},A.user.color)}</select></label>${security}<div class="modal-actions">${A.user.telegram_only?'':'<button type="button" id="profile-reset">Изменить пароль</button>'}${A.migration?'<button type="button" id="profile-claim">Перенести старые проекты</button>':''}<button type="button" id="logout" class="danger">Выйти</button></div>`,async d=>{await api('/api/auth/profile','PUT',Object.fromEntries(d));await refreshIdentity();accountChrome();});
 $('#logout').onclick=logoutAccount;
 if($('#profile-link-telegram'))$('#profile-link-telegram').onclick=linkTelegramProfile;
 if($('#profile-add-email'))$('#profile-add-email').onclick=addEmailDialog;
 if($('#profile-unlink-email'))$('#profile-unlink-email').onclick=()=>unlinkLoginMethod('email');
 if($('#profile-unlink-telegram'))$('#profile-unlink-telegram').onclick=()=>unlinkLoginMethod('telegram');
 if($('#profile-reset'))$('#profile-reset').onclick=async()=>{try{await api('/api/auth/forgot','POST',{email:A.user.email});toast(A.delivery==='local'?'Письмо сохранено в data/mailbox.':'Ссылка отправлена на вашу почту.');}catch(e){toast(e.message,true);}};
 if($('#profile-claim'))$('#profile-claim').onclick=claimDialog;
};
function editMemberOrganization(info,member){
 const byId=new Map(info.members.map(m=>[m.id,m])),below=m=>{const seen=new Set();while(m?.manager_id&&!seen.has(m.id)){if(m.manager_id===member.id)return true;seen.add(m.id);m=byId.get(m.manager_id);}return false;};
 const managers=info.members.filter(m=>m.id!==member.id&&!below(m)).map(m=>`<option value="${esc(m.id)}" ${m.id===member.manager_id?'selected':''}>${esc(m.name)} · ${esc(specialties[m.specialty]||'Участник')}</option>`).join('');
 modal('Место в структуре',`<p class="modal-note"><strong>${esc(member.name)}</strong> · специализация, уровень и руководитель описывают место человека в команде. Права доступа задаются отдельно.</p><label class="field">Специализация в команде<select name="specialty">${optionList(specialties,member.specialty)}</select></label><label class="field">Уровень<select name="seniority">${optionList(seniorities,member.seniority||'middle')}</select></label>${field('Подразделение','department',member.department||'')}<label class="field">Непосредственный руководитель<select name="manager_id"><option value="">Нет руководителя</option>${managers}</select></label>`,async d=>{await api('/api/spaces/'+A.space+'/organization','POST',{user_id:member.id,...Object.fromEntries(d)});await showSection('team');toast('Структура команды обновлена.');},'Сохранить');
}
function telegramTeamInviteDialog(info,owner){
 const managers=info.members.map(m=>`<option value="${esc(m.id)}" ${m.id===A.user.id?'selected':''}>${esc(m.name)} · ${esc(specialties[m.specialty]||'Участник')}</option>`).join('');
 modal('Telegram-приглашение',`<label class="field">Роль в команде<select name="role">${optionList(owner?{member:'Участник',admin:'Администратор'}:{member:'Участник'},'member')}</select></label><label class="field">Специализация в команде<select name="specialty">${optionList(specialties,'business')}</select></label><label class="field">Непосредственный руководитель<select name="manager_id"><option value="">Без руководителя</option>${managers}</select></label><p class="modal-note">Роль, специализация и руководитель фиксируются в одноразовой ссылке. Приглашение действует 7 дней. Новый пользователь зарегистрируется через бота, существующий Telegram-пользователь вступит в команду.</p>`,async d=>{
  const result=await api('/api/spaces/'+A.space+'/telegram-invite','POST',{role:d.get('role'),specialty:d.get('specialty'),manager_id:d.get('manager_id')||null});
  const manager=info.members.find(m=>m.id===result.manager_id);
  setTimeout(()=>{modal('Ссылка готова',`<p class="modal-note">Перешлите ссылку приглашённому. Бот добавит его в команду с правами «<strong>${esc(teamRoles[result.role])}</strong>», специализацией «<strong>${esc(specialties[result.specialty]||'Не указана')}</strong>»${manager?` и руководителем «<strong>${esc(manager.name)}</strong>»`:''}. Если человек уже состоит в команде, его текущие права и место в структуре сохранятся.</p><label class="field">Одноразовая ссылка<input id="telegram-team-link" value="${esc(result.url)}" readonly></label><button type="button" id="copy-telegram-team-link">Копировать ссылку</button>`,()=>{},'Закрыть');$('#copy-telegram-team-link').onclick=async()=>{await navigator.clipboard.writeText(result.url);toast('Ссылка скопирована.');};},0);
 },'Создать ссылку');
}
async function teamDialog(){try{
 const info=await api('/api/spaces/'+A.space);const admin=['owner','admin'].includes(info.role),owner=info.role==='owner';
 let html=`<p class="modal-note">${esc(info.name)} · ${teamRoles[info.role]}. Владелец может менять роли, администратор — управлять участниками.</p><div class="section-note">Участники</div>`;
 html+=info.members.map(m=>`<div class="member-card"><span class="avatar ${esc(m.color)}">${esc(m.name[0])}</span><div class="member-info"><strong>${esc(m.name)}</strong><small>${esc(m.email||'Только Telegram')}</small><small>${seniorities[m.seniority]||'Middle'} · ${specialties[m.specialty]}${m.department?' · '+esc(m.department):''}</small></div>${admin?`<button type="button" class="soft member-org-button" data-member-org="${esc(m.id)}">Структура</button>`:''}<span class="role-pill">${teamRoles[m.role]}</span>${owner&&m.id!==A.user.id&&m.role!=='owner'?`<button type="button" class="soft" data-change-role="${esc(m.id)}" data-next-role="${m.role==='admin'?'member':'admin'}">${m.role==='admin'?'Сделать участником':'Сделать администратором'}</button>`:''}${admin&&m.id!==A.user.id&&m.role!=='owner'&&(owner||m.role==='member')?`<button type="button" class="icon text-danger" data-remove-member="${esc(m.id)}" aria-label="Удалить ${esc(m.name)}">×</button>`:''}</div>`).join('');
 if(admin){const pending=[...info.invitations.map(i=>({...i,label:i.email})),...(info.telegram_invitations||[]).map(i=>({...i,label:'Telegram-ссылка'}))];html+=`<div class="section-note">Приглашения</div>`+pending.map(i=>`<div class="member-card"><div class="member-info"><strong>${esc(i.label)}</strong><small>${teamRoles[i.role]}${i.team_specialty?' · '+specialties[i.team_specialty]:''}${i.manager_id?' · Руководитель: '+esc(info.members.find(m=>m.id===i.manager_id)?.name||'выбыл из команды'):''} · до ${new Date(i.expires*1000).toLocaleDateString('ru')}</small></div><button type="button" data-revoke="${esc(i.id)}" class="text-button">Отозвать</button></div>`).join('')+`<div class="modal-actions"><button type="button" id="invite-member" class="primary">+ Telegram-ссылка</button>${owner?'<button type="button" id="transfer-team">Передать владение</button>':''}</div>`;}
 if(info.history?.length){const labels={team_created:'Команда создана',invite_created:'Создано приглашение',invite_revoked:'Приглашение отозвано',member_joined:'Участник вступил',member_removed:'Участник удалён',role_changed:'Роль изменена',profile_changed:'Структура обновлена',ownership_transferred:'Владение передано'};html+=`<div class="section-note">История</div>`+info.history.slice(0,12).map(e=>`<div class="member-card"><div class="member-info"><strong>${esc(labels[e.kind]||e.kind)}</strong><small>${esc(e.actor_name)}${e.target_name?' · '+esc(e.target_name):''} · ${new Date(e.created*1000).toLocaleString('ru')}</small></div></div>`).join('');}
 modal('Участники команды',html,()=>{},'Готово');$('#cancel-modal').hidden=true;
 $('#modal').addEventListener('close',()=>{$('#cancel-modal').hidden=false;},{once:true});
 document.querySelectorAll('[data-member-org]').forEach(el=>el.onclick=()=>{const member=info.members.find(m=>m.id===el.dataset.memberOrg);if(member)editMemberOrganization(info,member);});
 document.querySelectorAll('[data-remove-member]').forEach(el=>el.onclick=()=>modal('Удалить участника?', '<p class="modal-note">Участник потеряет доступ ко всем проектам команды. Для возвращения потребуется новое приглашение.</p>',async()=>{await api('/api/spaces/'+A.space+'/member','POST',{user_id:el.dataset.removeMember,role:'remove'});toast('Участник удалён из команды.');},'Удалить'));
 document.querySelectorAll('[data-change-role]').forEach(el=>el.onclick=()=>modal('Изменить роль?',`<p class="modal-note">Новая роль: <strong>${teamRoles[el.dataset.nextRole]}</strong>.</p>`,async()=>{await api('/api/spaces/'+A.space+'/member','POST',{user_id:el.dataset.changeRole,role:el.dataset.nextRole});toast('Роль участника изменена.');},'Изменить'));
 document.querySelectorAll('[data-revoke]').forEach(el=>el.onclick=async()=>{try{await api('/api/spaces/'+A.space+'/revoke','POST',{id:el.dataset.revoke});el.closest('.member-card').remove();}catch(e){toast(e.message,true);}});
 if($('#invite-member'))$('#invite-member').onclick=()=>telegramTeamInviteDialog(info,owner);
 if($('#transfer-team'))$('#transfer-team').onclick=()=>{const candidates=info.members.filter(m=>m.id!==A.user.id);if(!candidates.length)return toast('Сначала пригласите другого участника.');modal('Передать владение',`<p class="modal-note">Вы станете администратором. Новый владелец сможет управлять вашими правами в команде.</p><label class="field">Новый владелец<select name="user_id">${candidates.map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${esc(m.email||'Только Telegram')}</option>`).join('')}</select></label>`+authField('Ваш пароль','password','password','current-password'),async d=>{await api('/api/spaces/'+A.space+'/transfer','POST',Object.fromEntries(d));await refreshIdentity();accountChrome();toast('Владение передано.');},'Передать владение');};
 }catch(e){toast(e.message,true);}}
$('#project-access').onclick=async()=>{try{
 const members=await api('/api/projects/'+S.project.id+'/access');
 modal('Доступ к проекту',`<p class="access-note">Владелец и администраторы команды имеют полный доступ. Остальным участникам права назначаются отдельно. Комментарии появятся на следующем этапе; сейчас эта роль даёт просмотр.</p>`+members.map(m=>`<div class="member-card"><div class="member-info"><strong>${esc(m.name)}</strong><small>${esc(m.email||'Только Telegram')}</small></div>${['owner','admin'].includes(m.team_role)?'<small>Полный доступ</small>':`<select name="${esc(m.id)}" aria-label="Доступ ${esc(m.name)}">${optionList(accessRoles,m.project_role||'none')}</select>`}</div>`).join(''),async d=>{for(const [user_id,role] of d){const before=members.find(m=>m.id===user_id)?.project_role||'none';if(before!==role)await api('/api/projects/'+S.project.id+'/access','PUT',{user_id,role});}const id=S.project.id;await refreshProjects();try{await openProject(id);}catch{await openSpace(A.space);}toast('Права сохранены.');});
 }catch(e){toast(e.message,true);}};
window.addEventListener('hashchange',()=>bootAccounts());
bootAccounts();
