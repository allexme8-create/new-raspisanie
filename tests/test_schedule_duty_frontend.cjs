const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{add(){},remove(){},toggle(){},contains(){return false}},querySelectorAll(){return []}});return elements.get(id)}
class FixedDate extends Date{constructor(...args){super(...(args.length?args:['2026-11-09T01:30:00Z']))}static now(){return new FixedDate().getTime()}}
const ctx={Date:FixedDate,Intl,console,localStorage:{getItem:()=>null,setItem(){}},document:{hidden:false,body:{classList:{toggle(){}}},getElementById:el,querySelectorAll:()=>[],addEventListener(){}},matchMedia:()=>({matches:false,addEventListener(){},addListener(){}}),setInterval(){},clearTimeout(){},fetch:async()=>({ok:true,json:async()=>({})})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/js/app.js','utf8'),ctx);
vm.runInContext(`state.bellSchedule={shifts:{'1':{'Пн':{'1':{start:'08:00',end:'09:00'},'2':{start:'09:20',end:'10:00'}}},'2':{'Пн':{'1':{start:'13:00',end:'14:00'}}}}};publicDuty={today:'2026-11-09',timezone:'Asia/Krasnoyarsk',entries:[{slot:0,full_name:'Админ',role:'associate',position:'Завуч'},{slot:1,full_name:'<Учитель>',role:'teacher',position:'Учитель',class_name:'5А'},{slot:2,full_name:'Другой',role:'teacher',position:'Учитель',class_name:'6Б'}]};renderDutyBanner();`,ctx);
const html=el('classDuty').innerHTML;assert.equal(el('teacherDuty').innerHTML,html);assert.match(html,/9 ноября 2026 года/);assert.doesNotMatch(html,/Asia\/Krasnoyarsk/);assert.match(html,/Дежурный администратор: <strong><span class="person-associate">Админ<\/span> · Завуч<\/strong>/);assert.match(html,/1-я смена · дежурный учитель: <strong><span class="person-teacher">&lt;Учитель&gt;<\/span> · Учитель · 5А<\/strong>/);assert.match(html,/<p class="">2-я смена · дежурный учитель: <strong><span class="person-teacher">Другой<\/span> · Учитель · 6Б<\/strong><\/p>/);
vm.runInContext('state.bellSchedule=null;renderDutyBanner()',ctx);assert.match(el('classDuty').innerHTML,/текущая смена не определяется/);assert.match(el('classDuty').innerHTML,/<strong><span class="person-teacher">Другой/);
vm.runInContext("publicDuty.entries=[];renderDutyBanner()",ctx);assert.match(el('classDuty').innerHTML,/Не назначен/);assert.doesNotMatch(el('classDuty').innerHTML,/<strong>/);
const page=fs.readFileSync('frontend/index.html','utf8');assert.doesNotMatch(page,/Дежурство сегодня|scheduleDuty/);
vm.runInContext(`state.classes=['5А'];state.teachers={grid:{}};state.subjects=null;state.teacherNames=['Иванова'];state.curClass=null;state.curTeacher=null;renderClassArea();renderTeacherArea()`,ctx);
assert.doesNotMatch(el('classArea').innerHTML,/classDuty/);assert.doesNotMatch(el('teacherArea').innerHTML,/teacherDuty/);
vm.runInContext(`state.curClass='5А';renderClassArea();state.curTeacher='Иванова';renderTeacherArea()`,ctx);
assert.match(el('classArea').innerHTML,/classDuty/);assert.match(el('teacherArea').innerHTML,/teacherDuty/);
vm.runInContext(`state.curClass=null;renderClassArea();state.curTeacher=null;renderTeacherArea()`,ctx);
assert.doesNotMatch(el('classArea').innerHTML,/classDuty/);assert.doesNotMatch(el('teacherArea').innerHTML,/teacherDuty/);
console.log('Schedule duty banner OK');
