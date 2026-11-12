const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('frontend/staff.html','utf8');
for(const text of ['Мой профиль','Поставить задачу или создать проект','Состояние текущих задач','Состояние проектов','Статистика сроков','Дежурство','В меню кабинета'])assert.ok(html.includes(text));
const code=fs.readFileSync('frontend/js/staff.js','utf8');
async function run(path,role){
  const elements=new Map(),buttons=['staffProfileView','staffDutyView','staffCreateView','staffStatsView','staffTasksView','staffProjectsView'].map(view=>({dataset:{staffView:view}}));
  function el(id){if(!elements.has(id)){const classes=new Set();elements.set(id,{textContent:'',innerHTML:'',value:'',classList:{toggle(name,on){on?classes.add(name):classes.delete(name)},contains(name){return classes.has(name)}},querySelectorAll(){return []}})}return elements.get(id)}
  const context={document:{getElementById:el,querySelectorAll:s=>s==='[data-staff-view]'?buttons:[],hidden:false},location:{pathname:path},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},fetch:async path=>({ok:true,json:async()=>path.endsWith('/assignees')?{users:[]}:path.endsWith('/projects')?{projects:[]}:{tasks:[]}}),console};
  vm.createContext(context);vm.runInContext(code,context);
  await vm.runInContext(`staffToken='token';showSession({user:{id:'u',role:'${role}',full_name:'Тест'},must_change:false})`,context);
  const hidden=id=>el(id).classList.contains('hidden');
  assert.equal(hidden('staffHome'),false);assert.equal(hidden('staffBack'),true);
  assert.equal(hidden('staffDutyChoice'),role==='director');assert.equal(hidden('staffCreateChoice'),role==='teacher');assert.equal(hidden('staffStatsChoice'),role==='teacher');
  for(const button of buttons){
    if((['staffCreateView','staffStatsView'].includes(button.dataset.staffView)&&role==='teacher')||(button.dataset.staffView==='staffDutyView'&&role==='director')){button.onclick();assert.equal(hidden('staffHome'),false);continue;}
    button.onclick();assert.equal(hidden('staffHome'),true);assert.equal(hidden('staffBack'),false);
    for(const view of buttons)assert.equal(hidden(view.dataset.staffView),view!==button);
    el('staffBack').onclick();assert.equal(hidden('staffHome'),false);assert.equal(hidden('staffBack'),true);
  }
  assert.equal(typeof el('projectRefresh').onclick,'function');
}
(async()=>{await run('/Director','director');await run('/associate','associate');await run('/teacher','teacher');console.log('Staff navigation OK')})().catch(e=>{console.error(e);process.exitCode=1});
