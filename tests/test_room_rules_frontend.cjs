const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();const cell={dataset:{roomRuleDay:'Пн',roomRuleLesson:'1'}};
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{contains:()=>false,add(){},remove(){}},querySelectorAll:s=>id==='roomRulesUI'&&s==='[data-room-rule-day]'?[cell]:[]});return elements.get(id)}
const ctx={$:el,esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),document:{dispatchEvent(){}},api:async()=>({}),confirm:()=>true,toast(){},Event:class{},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/planner.js','utf8'),ctx);
vm.runInContext(`plannerProject={rooms:[{name:'101',unavailable:[]},{name:'102',unavailable:[]}]};plannerChange=fn=>{fn(plannerProject);renderRoomRules()};renderRoomRules()`,ctx);
assert.match(el('roomRulesUI').innerHTML,/101/);assert.match(el('roomRulesUI').innerHTML,/aria-pressed="false"/);
cell.onclick();assert.equal(vm.runInContext('plannerProject.rooms[0].unavailable.length',ctx),1);assert.match(el('roomRulesUI').innerHTML,/room-rule-cell blocked/);assert.match(el('roomRulesUI').innerHTML,/aria-pressed="true"/);
cell.onclick();assert.equal(vm.runInContext('plannerProject.rooms[0].unavailable.length',ctx),0);
el('roomRulesShift').value='2';el('roomRulesShift').onchange();cell.onclick();assert.equal(vm.runInContext('plannerProject.rooms[0].unavailable[0].shift',ctx),2);
el('roomRulesRoom').value='102';el('roomRulesRoom').onchange();cell.onclick();assert.equal(vm.runInContext('plannerProject.rooms[1].unavailable[0].lesson',ctx),1);
console.log('Room rules grid toggle UI OK');
