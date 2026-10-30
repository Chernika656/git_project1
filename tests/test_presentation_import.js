const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const context = {structuredClone, serial:0};
vm.createContext(context);
vm.runInContext('function uid(){return "new-"+(++serial)}\n' +
  source.slice(source.indexOf('function prepareSlideImport('), source.indexOf('function slideHTML(')), context);

const image = 'data:image/png;base64,iVBORw0KGgo=';
const project = {
  blocks:[
    {id:'existing', name:'Оплата', slide:{image:'data:image/png;base64,iVBORw0KGgo='}},
    {id:'other', name:'Доставка'},
  ],
  presentation_order:['other','existing'],
};
const chosen = [
  {source:{number:1,title:'Проверка',lines:['Подтвердить заказ'],image},id:'__new__'},
  {source:{number:2,title:'Оплата',lines:['Принять платёж']},id:'existing'},
];
const result = context.prepareSlideImport(project,chosen);
assert.deepEqual(Array.from(result.order),['new-1','existing','other']);
assert.equal(result.blocks[0].slide.image, project.blocks[0].slide.image);
assert.equal(result.blocks[2].description,'Подтвердить заказ');
assert.equal(result.blocks[2].slide.image,image);
assert.equal(project.blocks.length,2);
assert.throws(()=>context.prepareSlideImport(project,[chosen[1],chosen[1]]),/одним слайдом/);
const titleOnly=context.prepareSlideImport(project,[{source:{number:1,title:'Раздел',lines:[]},id:'__new__'}]);
assert.equal(titleOnly.blocks[2].slide.layout,'section');
