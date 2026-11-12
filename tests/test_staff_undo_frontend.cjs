const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const els=new Map(),calls=[];let cards=[],allow=true,fail=false;
function el(id){if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',value:'',classList:{toggle(){},contains(){return false}},querySelectorAll(s){return s==='[data-task-card]'?cards:s==='[data-discussion]'?cards.map(c=>c.detail):[]}});return els.get(id)}
const error={innerHTML:''},output={innerHTML:''},comment={elements:{text:{value:'',defaultValue:''}},querySelector:()=>({})};
const detail={dataset:{discussion:'t'},open:true,querySelector(s){return ({'.task-action-error':error,'.task-comments':output,'[data-comment]':comment})[s]},querySelectorAll:()=>[]};
const box={checked:true,defaultChecked:true,disabled:false,dataset:{cycle:'0',completedAt:'2029-01-01T00:00:00Z'}},status={textContent:''},summary={textContent:''},reason={textContent:''},rework={textContent:''},completed={remove(){this.removed=true}};
const card={detail,className:'',querySelector(s){return ({'[data-discussion]':detail,'[data-complete]':box,'.task-status':status,'.task-progress-summary':summary,'.task-reason':reason,'.task-rework':rework,'.task-completed-at':completed})[s]}};
const context={document:{getElementById:el,querySelectorAll:()=>[],hidden:false},location:{pathname:'/teacher'},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},setInterval(){},confirm:()=>allow,console,fetch:async(path,opts)=>{calls.push({path,opts});if(path.endsWith('/comments'))return {ok:true,json:async()=>({comments:[],events:[]})};if(fail)return {ok:false,status:409,json:async()=>({detail:'Уже подтверждена'})};const body=JSON.parse(opts.body);return {ok:true,json:async()=>({task:body.completed?{status:'completed_on_time',cycle:1,completed_at:'2030-01-01T00:00:00Z',failure_reason:''}:{status:'pending',cycle:1,completed_at:null,failure_reason:''}})}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/js/staff.js','utf8'),context);
(async()=>{
 vm.runInContext('staffToken="token";staffUser={id:"u"}',context);
 const base='{id:"t",assignee_id:"u",director_id:"a",status:"completed_on_time",completed_at:"2029-01-01T00:00:00Z",deadline:"2030-01-01T00:00:00Z",description:"Тест"}';
 assert.match(vm.runInContext(`taskMarkup(${base})`,context),/checked\s+> Выполнено/);
 assert.match(vm.runInContext(`taskMarkup({...${base},approved_at:"2029-01-02"})`,context),/checked disabled> Выполнено/);
 cards=[card];vm.runInContext('bindTaskCards("taskList")',context);
 allow=false;box.checked=false;await box.onchange();assert.equal(box.checked,true);assert.equal(calls.length,0);
 allow=true;box.checked=false;await box.onchange();assert.equal(status.textContent,'В работе');assert.equal(box.disabled,false);assert.equal(box.dataset.cycle,'1');assert.equal(box.dataset.completedAt,'');assert.ok(completed.removed);
 const body=JSON.parse(calls.find(c=>c.path.endsWith('/completion')).opts.body);assert.equal(body.completed,false);assert.equal(body.expected_completed_at,'2029-01-01T00:00:00Z');
 box.checked=true;await box.onchange();assert.equal(status.textContent,'Выполнено в срок');assert.equal(box.disabled,false);assert.equal(box.dataset.completedAt,'2030-01-01T00:00:00Z');
 fail=true;box.checked=false;await box.onchange();assert.equal(box.checked,true);assert.match(error.innerHTML,/Уже подтверждена/);
 console.log('Staff completion undo UI OK');
})().catch(e=>{console.error(e);process.exitCode=1});
