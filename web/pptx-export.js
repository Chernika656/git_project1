/* Editable PowerPoint export for Facet project slides. */
(function(root){
 'use strict';
 const W=13.333,H=7.5;
 function value(text){return String(text??'').trim();}
 function addText(slide,text,options){if(value(text))slide.addText(value(text),{fontFace:'Aptos',margin:0,breakLine:false,...options});}
 function build(pptx,blocks,projectName,statusNames={}){
  pptx.layout='LAYOUT_WIDE';
  pptx.author='Facet';
  pptx.subject='Презентация проекта '+value(projectName);
  pptx.title=value(projectName)||'Facet';
  pptx.lang='ru-RU';
  blocks.forEach((block,index)=>{
   const source=block.slide||{},layout=source.layout||'summary',section=layout==='section';
   const title=value(source.title||block.name),message=value(source.message??block.description);
   const bullets=Array.isArray(source.bullets)?source.bullets.map(value).filter(Boolean).slice(0,6):[];
   const slide=pptx.addSlide();
   slide.background={color:section?'E9EDFF':'FFFFFF'};
   slide.addShape(pptx.ShapeType.rect,{x:0,y:0,w:W,h:.12,line:{color:section?'8466C7':'7355B8'},fill:{color:section?'8466C7':'7355B8'}});
   addText(slide,`${value(projectName)} / ${String(index+1).padStart(2,'0')}`,{x:.72,y:.43,w:11.85,h:.25,fontSize:10,bold:true,color:'8B77B5',charSpacing:1.5});
   if(layout==='decision')addText(slide,'КЛЮЧЕВОЕ РЕШЕНИЕ',{x:.72,y:.93,w:8,h:.28,fontSize:11,bold:true,color:'7355B8',charSpacing:1.3});
   const titleY=section?2.2:layout==='decision'?1.37:1.14;
   addText(slide,title,{x:.72,y:titleY,w:11.85,h:section?1.45:1.12,fontSize:section?36:30,bold:true,color:'302B49',breakLine:false,fit:'shrink',valign:'mid'});
   const bodyY=section?3.83:2.5;
   const image=source.image;
   const hasImage=typeof image==='string'&&/^data:image\/(png|jpeg);base64,/.test(image);
   const textWidth=hasImage&&!section?6.2:11.85;
   addText(slide,message,{x:.76,y:bodyY,w:textWidth,h:section?1.0:1.08,fontSize:section?23:20,color:'4B4565',breakLine:false,fit:'shrink',valign:'top'});
   if(hasImage)slide.addImage({data:image,x:section?8.6:7.35,y:section?3.5:2.48,w:section?3.7:5.25,h:section?2.5:3.5,sizing:{type:'contain',w:section?3.7:5.25,h:section?2.5:3.5},altText:'Иллюстрация слайда'});
   if(!section&&layout!=='summary'&&bullets.length){
    const y=3.78,available=2.35,row=Math.min(.58,available/bullets.length),font=bullets.length>4?15:17;
    bullets.forEach((point,n)=>{
     slide.addShape(pptx.ShapeType.ellipse,{x:.8,y:y+n*row+.15,w:.11,h:.11,line:{color:'8466C7'},fill:{color:'8466C7'}});
     addText(slide,point,{x:1.08,y:y+n*row,w:hasImage?5.85:11.1,h:row-.04,fontSize:font,color:'4B4565',fit:'shrink',valign:'mid'});
    });
   }
   if(!section){
    slide.addShape(pptx.ShapeType.line,{x:.72,y:6.84,w:11.88,h:0,line:{color:'E4DDED',width:1}});
    addText(slide,value(block.owner)||'Ответственный не назначен',{x:.76,y:6.93,w:8,h:.24,fontSize:10,color:'9189A4'});
    addText(slide,value(statusNames[block.status]||block.status),{x:9.3,y:6.93,w:3.2,h:.24,fontSize:10,color:'9189A4',align:'right'});
   }
   if(value(source.notes))slide.addNotes(value(source.notes));
  });
  return pptx;
 }
 const api={build};
 if(typeof module==='object'&&module.exports)module.exports=api;
 root.FacetPptx=api;
})(typeof window==='undefined'?globalThis:window);
