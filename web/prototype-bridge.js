'use strict';
// Только этот доверенный код исполняется в изолированном окне прототипа.
let prototype=null,pageId=null,values=Object.create(null),history=[];
const root=document.getElementById('prototype-root');
const style=document.createElement('style');document.head.append(style);
const baseCSS='*{box-sizing:border-box}body{margin:0;padding:24px;font:15px/1.5 system-ui;color:#2b304a;background:#f7f6fc}input,select,textarea,button{font:inherit}input,select,textarea{padding:10px;border:1px solid #ddd8ea;border-radius:8px;max-width:100%}button{cursor:pointer;padding:10px 18px;border:0;border-radius:9px;background:#7658c9;color:white}label{display:grid;gap:6px;margin:16px 0}table{border-collapse:collapse;width:100%}th,td{padding:12px;text-align:left;border-bottom:1px solid #e8e3ef}article,form{max-width:880px;margin:auto}h1{line-height:1.2}';
const tags=new Set('MAIN SECTION ARTICLE HEADER FOOTER NAV ASIDE DIV SPAN P H1 H2 H3 H4 UL OL LI STRONG EM SMALL BR HR FORM LABEL INPUT TEXTAREA SELECT OPTION BUTTON TABLE THEAD TBODY TR TH TD FIELDSET LEGEND PROGRESS DETAILS SUMMARY'.split(' '));
const attrs=new Set('class id title name value type placeholder required disabled checked selected min max step minlength maxlength rows cols for multiple data-go data-value aria-label role'.split(' '));
function cleanHTML(markup){
 const template=document.createElement('template');template.innerHTML=markup;
 for(const el of [...template.content.querySelectorAll('*')]){
  if(!tags.has(el.tagName)){el.remove();continue;}
  for(const attribute of [...el.attributes])if(!attrs.has(attribute.name))el.removeAttribute(attribute.name);
 }
 return template.content;
}
function remember(){
 for(const el of root.querySelectorAll('input[name],textarea[name],select[name]')){
  if(el.type==='radio'){if(el.checked)values[el.name]=el.value;}
  else values[el.name]=el.type==='checkbox'?el.checked:el.value;
 }
}
function show(id){
 const page=prototype.pages.find(p=>p.id===id);if(!page)return;
 pageId=id;root.replaceChildren(cleanHTML(page.html));
 for(const el of root.querySelectorAll('input[name],textarea[name],select[name]'))if(Object.hasOwn(values,el.name)){
  if(el.type==='checkbox')el.checked=!!values[el.name];
  else if(el.type==='radio')el.checked=values[el.name]===el.value;
  else el.value=values[el.name];
 }
 for(const el of root.querySelectorAll('[data-value]'))if(Object.hasOwn(values,el.dataset.value))el.textContent=String(values[el.dataset.value]);
 window.scrollTo(0,0);parent.postMessage({type:'facet-prototype-page',title:page.title,canBack:history.length>0},'*');
}
function go(id){if(!prototype.pages.some(p=>p.id===id))return;remember();if(history.length<100)history.push(pageId);show(id);}
root.addEventListener('submit',e=>{e.preventDefault();const form=e.target;if(!form.reportValidity())return;go(e.submitter?.dataset.go||form.dataset.go);});
root.addEventListener('click',e=>{
 const button=e.target.closest('button[data-go]');if(!button)return;
 if(button.closest('form')&&button.type==='submit')return;
 e.preventDefault();go(button.dataset.go);
});
window.addEventListener('message',e=>{
 if(e.source!==parent)return;
 if(e.data?.type==='facet-prototype-init'){
  prototype=e.data.prototype;values=Object.create(null);history=[];
  style.textContent=baseCSS+'\n'+prototype.css;show(prototype.pages[0].id);
 }else if(e.data?.type==='facet-prototype-back'&&history.length){remember();show(history.pop());}
 else if(e.data?.type==='facet-prototype-reset'&&prototype){values=Object.create(null);history=[];show(prototype.pages[0].id);}
});
parent.postMessage({type:'facet-prototype-ready'},'*');
