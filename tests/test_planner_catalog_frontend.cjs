const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),buttons=[];let confirmation=false;
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{contains:()=>false,add(){},remove(){}},querySelectorAll:s=>s==='[data-kind]'?buttons:[]});return elements.get(id)}
const ctx={document:{dispatchEvent(){}},$:el,esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),api:async()=>({}),confirm:()=>confirmation,toast(){},Event:class{},crypto:{randomUUID:()=>"x"},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/planner.js','utf8'),ctx);
vm.runInContext(`plannerProject={revision:0,classes:[{name:'5А',shift:1,max_daily:7}],teachers:[{name:'Иванов ИИ',unavailable:[]}],subjects:[],rooms:[],loads:[],placements:[]};plannerIssues=[];plannerRender()`,ctx);
assert.match(el('plannerRoot').innerHTML,/Список классов \(1\)/);assert.match(el('plannerRoot').innerHTML,/Список учителей \(1\)/);assert.match(el('plannerRoot').innerHTML,/plannerImportTeachers/);assert.match(el('plannerRoot').innerHTML,/data-form="classes"/);assert.match(el('plannerRoot').innerHTML,/data-form="teachers"/);
const b={dataset:{kind:'teachers',index:'0'}};buttons.push(b);vm.runInContext('plannerRender()',ctx);let deleted=false;vm.runInContext('plannerChange=async fn=>{fn(plannerProject);globalThis.changed=true}',ctx);b.onclick();assert.equal(ctx.changed,undefined);confirmation=true;b.onclick();assert.equal(ctx.changed,true);assert.equal(vm.runInContext('plannerProject.teachers.length',ctx),0);
console.log('Planner catalog UI OK');
