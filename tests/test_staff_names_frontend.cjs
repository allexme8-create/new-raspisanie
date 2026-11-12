const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function el(id){if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(){return []}});return elements.get(id);}
const users=[{id:'11111111abcdef',full_name:'Иванов Иван',email:'private@example.com'},{id:'22222222abcdef',full_name:'Иванов Иван',email:'other@example.com'},{id:'333',full_name:'',email:'missing@example.com'}];
const task={id:'t',status:'pending',description:'Тест',deadline:'2030-01-01T00:00:00Z',assignee_name:'Иванов Иван',assignee_email:'private@example.com'};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/Director'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},fetch:async path=>({ok:true,json:async()=>path.endsWith('/associates')?{users}:{tasks:[task]}}),console};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 await vm.runInContext('staffToken="token"; showSession({user:{role:"director",full_name:"Петров Пётр",email:"director@example.com"},must_change:false})',context);
 assert.equal(el('staffIdentity').textContent,'Петров Пётр');
 assert.match(el('taskAssignee').innerHTML,/Иванов Иван \(11111111\)/);
 assert.match(el('taskAssignee').innerHTML,/Иванов Иван \(22222222\)/);
 assert.match(el('taskAssignee').innerHTML,/>ФИО не указано \(333\)/);
 assert.doesNotMatch(el('taskAssignee').innerHTML,/@example.com/);
 assert.match(el('taskList').innerHTML,/Исполнитель: Иванов Иван/);
 assert.doesNotMatch(el('taskList').innerHTML,/@example.com/);
 task.assignee_name='';await vm.runInContext('loadTasks()',context);
 assert.match(el('taskList').innerHTML,/Исполнитель: ФИО не указано/);
 task.assignee_name='Удалённый пользователь';await vm.runInContext('loadTasks()',context);
 assert.match(el('taskList').innerHTML,/Исполнитель: Удалённый пользователь/);
 console.log('Staff name display OK');
})().catch(e=>{console.error(e);process.exitCode=1});
