'use strict';
/* Переход Claude, адаптированный к реальному результату входа Facet. */
window.FacetAuthTransition=(()=>{
 let overlay=null,scene=null,label=null,started=0,timer=null;
 const reduce=()=>matchMedia('(prefers-reduced-motion: reduce)').matches||document.body.classList.contains('reduce-motion');
 function build(){
  if(overlay)return;
  overlay=document.createElement('div');overlay.id='login-transition';overlay.setAttribute('aria-hidden','true');
  overlay.innerHTML=`<div class="lt-scene"><svg class="lt-svg" viewBox="0 0 400 260" aria-hidden="true"><path class="lt-edge" data-d="1" d="M76 130 L166 72"/><path class="lt-edge" data-d="2" d="M76 130 L166 188"/><path class="lt-edge" data-d="3" d="M166 72 L262 130"/><path class="lt-edge" data-d="4" d="M166 188 L262 130"/><path class="lt-edge" data-d="5" d="M262 130 L334 130"/><rect class="lt-node" data-n="1" x="40" y="108" width="72" height="44" rx="12"/><rect class="lt-node" data-n="2" x="134" y="50" width="64" height="44" rx="12"/><rect class="lt-node" data-n="3" x="134" y="166" width="64" height="44" rx="12"/><circle class="lt-node lt-node-final" data-n="4" cx="300" cy="130" r="36"/></svg><div class="lt-label">Собираем схему проекта…</div></div>`;
  document.body.append(overlay);scene=overlay.querySelector('.lt-scene');label=overlay.querySelector('.lt-label');
  overlay.querySelectorAll('.lt-edge').forEach(edge=>{const length=edge.getTotalLength();edge.style.strokeDasharray=length;edge.style.strokeDashoffset=length;});
 }
 function start(){
  if(overlay)return;build();started=performance.now();
  requestAnimationFrame(()=>{overlay?.classList.add('lt-show');requestAnimationFrame(()=>scene?.classList.add('lt-build'));});
 }
 function close(){
  clearTimeout(timer);const old=overlay;if(!old)return;
  old.classList.remove('lt-show','lt-fade');scene?.classList.remove('lt-build','lt-zoom');
  overlay=scene=label=null;timer=setTimeout(()=>old.remove(),reduce()?50:400);
 }
 function fail(){close();}
 function success(){
  if(!overlay)return Promise.resolve();
  if(reduce()){close();return Promise.resolve();}
  const remaining=Math.max(0,1400-(performance.now()-started));
  return new Promise(resolve=>{timer=setTimeout(()=>{
   if(label)label.textContent='Открываем рабочее пространство…';
   requestAnimationFrame(()=>requestAnimationFrame(()=>{scene?.classList.add('lt-zoom');overlay?.classList.add('lt-fade');}));
   timer=setTimeout(()=>{close();resolve();},1350);
  },remaining);});
 }
 return {start,success,fail};
})();
