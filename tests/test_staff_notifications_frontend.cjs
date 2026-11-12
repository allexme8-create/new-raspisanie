const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),calls=[],classes=()=>{const set=new Set();return {toggle:(c,on)=>on?set.add(c):set.delete(c),contains:c=>set.has(c),add:c=>set.add(c)}};
let notices=[{id:7,task_id:'t1',kind:'comment',description:'<важная задача>',actor_name:'<Иван>',actor_position:'Учитель',created_at:'2030-01-01T00:00:00Z',project_id:null}];
const badge={textContent:'',classList:classes()},output={innerHTML:''},error={innerHTML:''};
const detail={open:false,dataset:{discussion:'t1'},querySelector:s=>s==='.task-comments'?output:error,querySelectorAll:()=>[]};
const card={dataset:{taskCard:'t1'},classList:classes(),querySelector:s=>s==='.task-notice'?badge:detail,scrollIntoView(){this.scrolled=true}};
const noticeButton={dataset:{notificationIndex:'0'}};
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:classes(),querySelectorAll(s){if(id==='staffNotificationList'&&s==='[data-notification-index]')return [noticeButton];if(id==='taskList'&&s==='[data-task-card]')return [card];if(id==='taskList'&&s==='[data-discussion]')return [detail];return []}});return elements.get(id)}
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/associate'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},console,fetch:async(path,opts)=>{calls.push({path,opts});let data;if(path.endsWith('/notifications'))data={notifications:notices};else if(path.endsWith('/comments'))data={comments:[{id:'c',created_at:'2030-01-01T00:00:00Z',text:'История',author_name:'Иван'}],events:[],notification_through_id:7};else if(path.endsWith('/notifications/read')){notices=[];data={ok:true}}else data={};return {ok:true,json:async()=>data}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"u"}',context);await vm.runInContext('loadNotifications()',context);
 assert.equal(el('staffNotifications').classList.contains('hidden'),false);assert.match(el('staffNotificationList').innerHTML,/Новый комментарий/);assert.match(el('staffNotificationList').innerHTML,/&lt;важная задача&gt;/);assert.ok(card.classList.contains('task-has-notification'));assert.match(badge.textContent,/1/);
 await noticeButton.onclick();assert.equal(detail.open,true);assert.equal(card.scrolled,true);assert.equal(calls.some(c=>c.path.endsWith('/notifications/read')),false);
 await vm.runInContext('refreshComments',context)(detail);assert.match(output.innerHTML,/История/);assert.equal(el('staffNotifications').classList.contains('hidden'),true);assert.equal(card.classList.contains('task-has-notification'),false);
 const read=calls.find(c=>c.path.endsWith('/notifications/read'));assert.equal(JSON.parse(read.opts.body).through_id,7);
 detail.open=false;notices=[{id:8,task_id:'t1',kind:'completed',description:'Задача',actor_name:'Иван',created_at:'2030-01-01T00:00:00Z'}];await vm.runInContext('loadNotifications()',context);assert.match(el('staffNotificationList').innerHTML,/Задача выполнена/);
 console.log('Staff notifications UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
