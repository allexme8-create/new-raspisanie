const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),calls=[];let cards=[];
function el(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(s){return s==='[data-task-card]'?cards:[]}});return elements.get(id)}
const button={disabled:false},status={textContent:''},deadline={textContent:''},reworkLabel={textContent:''},summary={textContent:''},reason={textContent:''},completed={remove(){this.removed=true}},error={innerHTML:''};
const form={dataset:{completedAt:'2030-01-01T00:00:00+00:00'},elements:{deadline:{value:'2031-01-01T09:00'},comment:{value:'Добавить раздел'}},querySelector:()=>button,remove(){this.removed=true}};
const comment={elements:{text:{value:'',defaultValue:''}},querySelector:()=>button};
const detail={dataset:{discussion:'t1'},open:false,querySelector(s){return ({'[data-rework]':form,'[data-comment]':comment,'.task-action-error':error})[s]},querySelectorAll(){return []}};
const card={classList:{add(){},remove(){}},querySelector(s){return ({'[data-discussion]':detail,'[data-complete]':null,'.task-status':status,'.task-deadline':deadline,'.task-rework':reworkLabel,'.task-progress-summary':summary,'.task-reason':reason,'.task-completed-at':completed})[s]}};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/users'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},confirm:()=>true,console,fetch:async(path,opts)=>{calls.push({path,opts});return {ok:true,json:async()=>({task:{status:'pending',deadline:'2031-01-01T09:00:00Z'}})}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"author"}',context);
 const raw='{id:"t1",director_id:"author",assignee_id:"teacher",status:"completed_on_time",completed_at:"2030-01-01T00:00:00+00:00",deadline:"2030-01-01T00:00:00Z",description:"Тест",cycle:1}';
 assert.match(vm.runInContext(`taskMarkup(${raw})`,context),/data-rework/);
 assert.doesNotMatch(vm.runInContext(`taskMarkup({...${raw},director_id:"another"})`,context),/data-rework/);
 assert.doesNotMatch(vm.runInContext(`taskMarkup({...${raw},completed_at:null})`,context),/data-rework/);
 assert.match(vm.runInContext(`taskMarkup({...${raw},completed_at:null,rework:true})`,context),/Доделать/);
 cards=[card];vm.runInContext('bindTaskCards("taskList")',context);await form.onsubmit({preventDefault(){}});
 assert.match(reworkLabel.textContent,/Доделать/);assert.equal(status.textContent,'В работе');assert.ok(completed.removed);assert.ok(form.removed);
 const sent=JSON.parse(calls[0].opts.body);assert.equal(sent.comment,'Добавить раздел');assert.equal(sent.expected_completed_at,form.dataset.completedAt);assert.ok(sent.deadline.endsWith('Z'));
 console.log('Staff rework UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
