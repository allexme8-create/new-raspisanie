"use strict";
const byId=id=>document.getElementById(id);
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const role=location.pathname==="/Director"?"director":location.pathname==="/teacher"?"teacher":"associate";
const manager=role!=="teacher", key=`schedule_staff_${role}`;
let staffToken=sessionStorage.getItem(key)||"", staffUser=null, refreshing=false;
byId("pageTitle").textContent=role==="director"?"Кабинет директора":role==="associate"?"Кабинет заместителя директора":"Кабинет учителя";
const roleNames={director:"Директор",associate:"Заместитель директора",teacher:"Учитель"};
function showIdentity(user){byId("staffIdentity").textContent=`${user.full_name||"ФИО не указано — заполните профиль"} · ${user.position||roleNames[user.role]||"Сотрудник"}`;}
const statuses={pending:"В работе",overdue:"Просрочено",completed_on_time:"Выполнено в срок",completed_late:"Выполнено с просрочкой"};
function screen(id){["staffLoginCard","changePasswordCard","staffPanel"].forEach(x=>byId(x).classList.toggle("hidden",x!==id));}
const staffViews=["staffProfileView","staffCreateView","staffTasksView","staffProjectsView"];
function openStaffView(id){
  if(id==="staffCreateView"&&!manager)return;
  if(id!=="staffHome"&&!staffViews.includes(id))return;
  byId("staffHome").classList.toggle("hidden",id!=="staffHome");
  byId("staffBack").classList.toggle("hidden",id==="staffHome");
  staffViews.forEach(view=>byId(view).classList.toggle("hidden",view!==id));
}
document.querySelectorAll("[data-staff-view]").forEach(button=>button.onclick=()=>openStaffView(button.dataset.staffView));
byId("staffBack").onclick=()=>openStaffView("staffHome");
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
  if(staffUser.role!==role){staffToken="";sessionStorage.removeItem(key);screen("staffLoginCard");throw new Error("Откройте кабинет вашей роли");}
  if(data.must_change){screen("changePasswordCard");return;}
  screen("staffPanel");showIdentity(staffUser);
  byId("staffFullName").value=staffUser.full_name||"";byId("staffPosition").value=staffUser.position||"";byId("profileResult").innerHTML="";
  byId("staffCreateChoice").classList.toggle("hidden",!manager);openStaffView("staffHome");
  if(manager)await loadAssignees();
  await loadTasks();
}
async function loadAssignees(){
  try{
    const data=await request("/api/staff/assignees"),select=byId("taskAssignee"),previous=select.value;
    const names=new Map();data.users.forEach(u=>{if(u.full_name)names.set(u.full_name,(names.get(u.full_name)||0)+1);});
    select.innerHTML='<option value="">Выберите исполнителя</option>'+data.users.map(u=>{
      const label=u.full_name?u.full_name+(names.get(u.full_name)>1?` (${u.id.slice(0,8)})`:""):`ФИО не указано (${u.id.slice(0,8)})`;
      const roleName=u.position||roleNames[u.role]||"Сотрудник";
      return `<option value="${escapeHTML(u.id)}">${escapeHTML(label)} · ${escapeHTML(roleName)}</option>`;
    }).join("");
    if(data.users.some(u=>u.id===previous))select.value=previous;
    if(!data.users.length)select.innerHTML='<option value="">Нет доступных исполнителей</option>';
  }catch(e){errorAt("taskCreateError",e);}
}
function fmtDate(iso){return new Date(iso).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"});}
function personName(name,position){return (name||"ФИО не указано")+(position?` · ${position}`:"");}
function taskMarkup(t){
  const mine=t.assignee_id===staffUser.id;
  return `<article class="task-card status-${escapeHTML(t.status)}" data-task-card="${escapeHTML(t.id)}"><div class="task-top"><span class="task-status">${escapeHTML(statuses[t.status]||t.status)}</span><span class="task-deadline">Срок: ${escapeHTML(fmtDate(t.deadline))}</span></div>
    <p class="task-description">${escapeHTML(t.description)}</p>
    <p class="task-meta">Исполнитель: ${escapeHTML(personName(t.assignee_name,t.assignee_position))} · Автор: ${escapeHTML(personName(t.director_name,t.director_position))}</p>
    <p class="task-progress-summary">${t.partial?'Частично выполнено':""}</p>
    <p class="task-reason">${t.failure_reason?`${t.completed_at?'Ранее указанная причина':'Причина невыполнения'}: ${escapeHTML(t.failure_reason)}`:""}</p>
    ${t.completed_at?`<p class="task-meta">Отмечено: ${escapeHTML(fmtDate(t.completed_at))}</p>`:""}
    ${mine?`<label class="task-complete"><input type="checkbox" data-complete="${escapeHTML(t.id)}" ${t.completed_at?"checked disabled":""}> Выполнено</label>`:""}
    <details class="task-discussion" data-discussion="${escapeHTML(t.id)}"><summary>Ход работы и комментарии</summary>
      ${mine&&!t.completed_at?`<form data-progress><label class="task-complete"><input type="checkbox" name="partial" ${t.partial?"checked":""}> Частично выполнено</label><div class="field"><label>Причина невыполнения (необязательно)<textarea name="reason" maxlength="2000" rows="2">${escapeHTML(t.failure_reason||"")}</textarea></label></div><button class="btn secondary" type="submit">Сохранить состояние</button></form>`:""}
      <div class="task-comments" aria-live="polite">Загрузка комментариев…</div>
      <form data-comment><label>Комментарий<textarea name="text" maxlength="2000" rows="2" required></textarea></label><button class="btn secondary" type="submit">Отправить комментарий</button></form>
      <div class="task-action-error" aria-live="polite"></div>
    </details></article>`;
}
function taskDraftsOpen(){
  return ["taskList","projectList"].some(id=>Array.from(byId(id).querySelectorAll("[data-discussion]")).some(detail=>{
    if(detail.open)return true;
    return Array.from(detail.querySelectorAll("textarea,input[type=checkbox]")).some(input=>input.type==="checkbox"?input.checked!==input.defaultChecked:input.value!==input.defaultValue);
  }));
}
async function refreshComments(detail){
  const out=detail.querySelector(".task-comments");
  const data=await request(`/api/staff/tasks/${encodeURIComponent(detail.dataset.discussion)}/comments`);
  out.innerHTML=data.comments.length?data.comments.map(c=>`<div class="task-comment"><b>${escapeHTML(personName(c.author_name,c.author_position))}</b> <span class="task-meta">${escapeHTML(fmtDate(c.created_at))}</span><p>${escapeHTML(c.text)}</p></div>`).join(""):'<p class="hint">Комментариев пока нет.</p>';
}
function bindTaskCards(id){
  byId(id).querySelectorAll("[data-task-card]").forEach(card=>{
    const detail=card.querySelector("[data-discussion]"),error=detail.querySelector(".task-action-error"),tid=detail.dataset.discussion;
    detail.ontoggle=()=>{if(detail.open)refreshComments(detail).catch(e=>errorAtElement(error,e));};
    const comment=detail.querySelector("[data-comment]");
    comment.onsubmit=async e=>{e.preventDefault();const button=comment.querySelector("button"),text=comment.elements.text;button.disabled=true;error.innerHTML="";
      try{await request(`/api/staff/tasks/${encodeURIComponent(tid)}/comments`,{method:"POST",body:{text:text.value}});text.value="";text.defaultValue="";await refreshComments(detail);}
      catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const progress=detail.querySelector("[data-progress]");
    if(progress)progress.onsubmit=async e=>{e.preventDefault();const button=progress.querySelector("button"),partial=progress.elements.partial,reason=progress.elements.reason;button.disabled=true;error.innerHTML="";
      try{const result=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/progress`,{method:"PUT",body:{partial:partial.checked,reason:reason.value}});
        partial.checked=result.task.partial;partial.defaultChecked=partial.checked;reason.value=result.task.failure_reason;reason.defaultValue=reason.value;
        card.querySelector(".task-progress-summary").textContent=partial.checked?"Частично выполнено":"";
        card.querySelector(".task-reason").textContent=reason.value?`Причина невыполнения: ${reason.value}`:"";
      }catch(e){errorAtElement(error,e);}finally{button.disabled=false;}
    };
    const box=card.querySelector("[data-complete]");
    if(box)box.onchange=async()=>{if(!box.checked)return;if(!confirm(progress&&(progress.elements.partial.checked!==progress.elements.partial.defaultChecked||progress.elements.reason.value!==progress.elements.reason.defaultValue)?"Подтвердить выполнение? Несохранённое состояние будет потеряно, отменить выполнение нельзя.":"Подтвердить выполнение? Отменить отметку будет нельзя.")){box.checked=false;return;}
      box.disabled=true;error.innerHTML="";
      try{const result=await request(`/api/staff/tasks/${encodeURIComponent(tid)}/completion`,{method:"PUT",body:{completed:true}});
        card.className=`task-card status-${result.task.status}`;card.querySelector(".task-status").textContent=statuses[result.task.status]||result.task.status;
        card.querySelector(".task-progress-summary").textContent="";
        card.querySelector(".task-reason").textContent=result.task.failure_reason?`Ранее указанная причина: ${result.task.failure_reason}`:"";
        if(progress)progress.remove();if(!taskDraftsOpen())await loadTasks();
      }catch(e){box.checked=false;box.disabled=false;errorAtElement(error,e);detail.open=true;}
    };
  });
}
function errorAtElement(element,error){element.innerHTML=`<div class="alert err">${escapeHTML(error.message)}</div>`;}
async function loadTasks(){
  if(!staffToken||refreshing||taskDraftsOpen())return;refreshing=true;
  try{
    const [data,projectData]=await Promise.all([request("/api/staff/tasks"),request("/api/staff/projects")]);
    if(taskDraftsOpen())return;
    byId("taskListError").innerHTML="";
    const ordinary=data.tasks.filter(t=>!t.project_id);
    byId("taskList").innerHTML=ordinary.length?ordinary.map(taskMarkup).join(""):'<p class="nodata">Задач пока нет.</p>';
    byId("projectList").innerHTML=projectData.projects.length?projectData.projects.map(p=>{
      const tasks=data.tasks.filter(t=>t.project_id===p.id),done=tasks.filter(t=>t.completed_at).length;
      const mine=tasks.filter(t=>t.assignee_id===staffUser.id),mineDone=mine.filter(t=>t.completed_at).length;
      const limited=role!=="director"&&p.owner_id!==staffUser.id;
      const participants=new Map();
      tasks.forEach(t=>{const item=participants.get(t.assignee_id)||{name:personName(t.assignee_name,t.assignee_position),total:0,done:0};item.total++;if(t.completed_at)item.done++;participants.set(t.assignee_id,item);});
      const involvement=!limited&&participants.size?`<p class="hint">Участники: ${Array.from(participants.values()).map(x=>`${escapeHTML(x.name)} — ${x.done}/${x.total}`).join(" · ")}</p>`:"";
      return `<article class="project-card"><h3>${escapeHTML(p.title)}</h3><p class="hint">Автор: ${escapeHTML(personName(p.owner_name,p.owner_position))} · ${limited?"Ваши задачи":"Выполнено"}: ${done} из ${tasks.length}${mine.length?` · Ваше участие: ${mineDone} из ${mine.length}`:""}</p>${involvement}${tasks.length?tasks.map(taskMarkup).join(""):'<p class="nodata">Задач пока нет.</p>'}</article>`;
    }).join(""):'<p class="nodata">Проектов пока нет.</p>';
    if(manager){const select=byId("taskProject"),previous=select.value,editable=projectData.projects.filter(p=>role==="director"||p.owner_id===staffUser.id);
      select.innerHTML='<option value="">Текущие задачи</option>'+editable.map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.title)}</option>`).join("");
      if(editable.some(p=>p.id===previous))select.value=previous;
    }
    bindTaskCards("taskList");bindTaskCards("projectList");
  }catch(e){errorAt("taskListError",e);}finally{refreshing=false;}
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
  try{const data=await request("/api/staff/profile",{method:"PUT",body:{full_name:byId("staffFullName").value,position:byId("staffPosition").value}});staffUser=data.user;byId("staffFullName").value=staffUser.full_name;byId("staffPosition").value=staffUser.position||"";showIdentity(staffUser);byId("profileResult").innerHTML='<div class="alert ok">Профиль сохранён.</div>';}
  catch(error){errorAt("profileResult",error);}finally{button.disabled=false;}
};
byId("projectForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("projectCreateError").innerHTML="";
  try{const data=await request("/api/staff/projects",{method:"POST",body:{title:byId("projectTitle").value}});byId("projectTitle").value="";await loadTasks();byId("taskProject").value=data.id;}
  catch(error){errorAt("projectCreateError",error);}finally{button.disabled=false;}
};
byId("taskForm").onsubmit=async e=>{
  e.preventDefault();const button=e.currentTarget.querySelector("button");button.disabled=true;byId("taskCreateError").innerHTML="";
  try{const deadline=new Date(byId("taskDeadline").value);if(Number.isNaN(deadline.getTime()))throw new Error("Укажите срок выполнения");
    await request("/api/staff/tasks",{method:"POST",body:{assignee_id:byId("taskAssignee").value,project_id:byId("taskProject").value||null,description:byId("taskDescription").value,deadline:deadline.toISOString()}});
    byId("taskDescription").value="";byId("taskDeadline").value="";await loadTasks();
  }catch(error){errorAt("taskCreateError",error);}finally{button.disabled=false;}
};
document.querySelectorAll("[data-logout]").forEach(button=>button.onclick=async()=>{
  try{await request("/api/staff/logout",{method:"POST"});}catch(e){}staffToken="";staffUser=null;sessionStorage.removeItem(key);screen("staffLoginCard");
});
byId("taskRefresh").onclick=byId("projectRefresh").onclick=()=>{if(taskDraftsOpen()){errorAt("taskListError",new Error("Закройте обсуждения и сохраните или очистите черновики перед обновлением."));return;}if(manager)loadAssignees();loadTasks();};
setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!byId("staffPanel").classList.contains("hidden"))loadTasks();},30000);
if(staffToken)request("/api/staff/me").then(showSession).catch(e=>{if(staffToken)errorAt("staffLoginError",e);screen("staffLoginCard");});
