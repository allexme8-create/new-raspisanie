"use strict";
const byId=id=>document.getElementById(id);
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const role=location.pathname==="/Director"?"director":"associate";
const key=`schedule_staff_${role}`;
let staffToken=sessionStorage.getItem(key)||"", staffUser=null, refreshing=false;
byId("pageTitle").textContent=role==="director"?"Кабинет директора":"Кабинет заместителя директора";
byId("taskListTitle").textContent=role==="director"?"Контроль задач":"Мои задачи";
const statuses={pending:"В работе",overdue:"Просрочено",completed_on_time:"Выполнено в срок",completed_late:"Выполнено с просрочкой"};
function screen(id){["staffLoginCard","changePasswordCard","staffPanel"].forEach(x=>byId(x).classList.toggle("hidden",x!==id));}
function errorAt(id,error){byId(id).innerHTML=`<div class="alert err">${escapeHTML(error.message)}</div>`;}
async function request(path,{method="GET",body,anonymous=false}={}){
  const headers={};
  if(!anonymous&&staffToken){headers.Authorization=`Bearer ${staffToken}`;headers["X-Staff-Token"]=staffToken;}
  if(body!==undefined)headers["Content-Type"]="application/json";
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"});
  let data={};try{data=await response.json();}catch(e){}
  if(response.status===401&&!anonymous){staffToken="";staffUser=null;sessionStorage.removeItem(key);screen("staffLoginCard");}
  if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:Array.isArray(data.detail)?data.detail.map(x=>x.msg).join("; "):`Ошибка ${response.status}`);
  return data;
}
async function showSession(data){
  staffUser=data.user;
  if(staffUser.role!==role){staffToken="";sessionStorage.removeItem(key);screen("staffLoginCard");return;}
  if(data.must_change){screen("changePasswordCard");return;}
  screen("staffPanel");byId("staffIdentity").textContent=staffUser.full_name ? `${staffUser.full_name} · ${staffUser.email}` : staffUser.email;
  byId("staffFullName").value=staffUser.full_name||""; byId("profileResult").innerHTML="";
  byId("createTaskCard").classList.toggle("hidden",role!=="director");
  if(role==="director")await loadAssignees();
  await loadTasks();
}
async function loadAssignees(){
  try{
    const data=await request("/api/staff/associates"),select=byId("taskAssignee"),previous=select.value;
    select.innerHTML='<option value="">Выберите заместителя</option>'+data.users.map(u=>`<option value="${escapeHTML(u.id)}">${escapeHTML(u.full_name ? `${u.full_name} · ${u.email}` : u.email)}</option>`).join("");
    if(data.users.some(u=>u.id===previous))select.value=previous;
    if(!data.users.length)select.innerHTML='<option value="">Администратор ещё не создал заместителей</option>';
  }catch(e){errorAt("taskCreateError",e);}
}
function fmtDate(iso){return new Date(iso).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});}
async function loadTasks(){
  if(!staffToken||refreshing)return;
  refreshing=true;
  try{
    const data=await request("/api/staff/tasks");
    byId("taskListError").innerHTML="";
    byId("taskList").innerHTML=data.tasks.length?data.tasks.map(t=>`<article class="task-card status-${escapeHTML(t.status)}">
      <div class="task-top"><span class="task-status">${escapeHTML(statuses[t.status]||t.status)}</span><span class="task-deadline">Срок: ${escapeHTML(fmtDate(t.deadline))}</span></div>
      <p class="task-description">${escapeHTML(t.description)}</p>
      <p class="task-meta">${role==="director"?"Исполнитель":"Директор"}: ${escapeHTML(role==="director"?(t.assignee_name || t.assignee_email):(t.director_name || t.director_email))}</p>
      ${t.completed_at?`<p class="task-meta">Отмечено: ${escapeHTML(fmtDate(t.completed_at))}</p>`:""}
      ${role==="associate"?`<label class="task-complete"><input type="checkbox" data-complete="${escapeHTML(t.id)}" ${t.completed_at?"checked disabled":""}> Выполнено</label>`:""}
    </article>`).join(""):'<p class="nodata">Задач пока нет.</p>';
    byId("taskList").querySelectorAll("[data-complete]").forEach(box=>box.onchange=async()=>{
      if(!box.checked)return;
      if(!confirm("Подтвердить выполнение? Отменить отметку будет нельзя.")){box.checked=false;return;}
      box.disabled=true;
      try{await request(`/api/staff/tasks/${encodeURIComponent(box.dataset.complete)}/completion`,{method:"PUT",body:{completed:true}});}
      catch(e){box.checked=false;box.disabled=false;errorAt("taskListError",e);return;}
      await loadTasks();
    });
  }catch(e){errorAt("taskListError",e);}
  finally{refreshing=false;}
}
byId("staffLoginForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("staffLoginError").innerHTML="";
  try{const data=await request("/api/staff/login",{method:"POST",anonymous:true,body:{email:byId("loginEmail").value.trim(),password:byId("loginPassword").value,role}});staffToken=data.token;sessionStorage.setItem(key,staffToken);byId("loginPassword").value="";await showSession(data);}
  catch(error){errorAt("staffLoginError",error);}finally{button.disabled=false;}
};
byId("staffPasswordForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("passwordError").innerHTML="";
  try{await request("/api/staff/password",{method:"POST",body:{password:byId("newPassword").value}});byId("newPassword").value="";await showSession(await request("/api/staff/me"));}
  catch(error){errorAt("passwordError",error);}finally{button.disabled=false;}
};
byId("staffProfileForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("profileResult").innerHTML="";
  try{const data=await request("/api/staff/profile",{method:"PUT",body:{full_name:byId("staffFullName").value}});
    staffUser=data.user;byId("staffFullName").value=staffUser.full_name;
    byId("staffIdentity").textContent=`${staffUser.full_name} · ${staffUser.email}`;
    byId("profileResult").innerHTML='<div class="alert ok">ФИО сохранено.</div>';
  }catch(error){errorAt("profileResult",error);}finally{button.disabled=false;}
};
byId("taskForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("taskCreateError").innerHTML="";
  try{const deadline=new Date(byId("taskDeadline").value);if(Number.isNaN(deadline.getTime()))throw new Error("Укажите срок выполнения");
    await request("/api/staff/tasks",{method:"POST",body:{assignee_id:byId("taskAssignee").value,description:byId("taskDescription").value,deadline:deadline.toISOString()}});
    byId("taskDescription").value="";byId("taskDeadline").value="";await loadTasks();
  }catch(error){errorAt("taskCreateError",error);}finally{button.disabled=false;}
};
document.querySelectorAll("[data-logout]").forEach(button=>button.onclick=async()=>{
  try{await request("/api/staff/logout",{method:"POST"});}catch(e){}
  staffToken="";staffUser=null;sessionStorage.removeItem(key);screen("staffLoginCard");
});
byId("taskRefresh").onclick=()=>{if(role==="director")loadAssignees();loadTasks();};
setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!byId("staffPanel").classList.contains("hidden"))loadTasks();},30000);
if(staffToken)request("/api/staff/me").then(showSession).catch(e=>{if(staffToken)errorAt("staffLoginError",e);screen("staffLoginCard");});
