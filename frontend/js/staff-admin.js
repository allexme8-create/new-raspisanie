"use strict";
let staffClassCatalog=[];
function classOptions(selected=""){
  let html='<option value="">Без класса</option>'+staffClassCatalog.map(name=>`<option value="${esc(name)}"${name===selected?' selected':''}>${esc(name)}</option>`).join("");
  if(selected&&!staffClassCatalog.includes(selected))html+=`<option value="${esc(selected)}" selected disabled>${esc(selected)} (нет в конструкторе)</option>`;
  return html;
}
function updateCreateClassVisibility(){$("staffHomeroomField").classList.toggle("hidden",$("staffRole").value!=="teacher");}
$("staffRole").onchange=updateCreateClassVisibility;
async function loadStaffUsers(){
  const currentToken=token;
  try{
    const [data,planner]=await Promise.all([api("/api/admin/users"),api("/api/admin/planner")]);
    if(!currentToken||token!==currentToken)return;
    staffClassCatalog=planner.project.classes.map(c=>c.name);
    const selected=$("staffHomeroom").value;$("staffHomeroom").innerHTML=classOptions(selected);if(staffClassCatalog.includes(selected))$("staffHomeroom").value=selected;
    updateCreateClassVisibility();
    const list=$("staffUsersList");
    list.innerHTML=data.users.length?`<ul class="staff-user-list">${data.users.map((u,i)=>`<li><div class="staff-user-details"><span>${u.full_name ? `${esc(u.full_name)} · ` : ""}${esc(u.email)} · ${esc(u.position || (u.role==="director"?"директор":u.role==="teacher"?"учитель":"заместитель директора"))}</span>${u.role==="teacher"?`<div class="staff-homeroom"><label for="staffUserClass${i}">Классное руководство</label><select id="staffUserClass${i}">${classOptions(u.homeroom_class||"")}</select> <button type="button" class="btn secondary" data-homeroom-user="${i}">Сохранить класс</button></div>`:""}<div id="staffPassword${i}" class="staff-password" aria-live="polite"></div></div><div class="staff-user-actions"><button type="button" class="btn secondary" data-show-user="${i}">Показать пароль</button><button type="button" class="btn secondary" data-reset-user="${i}">Обновить пароль</button><button type="button" class="btn danger" data-delete-user="${i}">Удалить</button></div></li>`).join("")}</ul>`:'<p class="muted">Пользователей пока нет.</p>';
    list.querySelectorAll("[data-homeroom-user]").forEach(button=>button.onclick=async()=>{
      const i=Number(button.dataset.homeroomUser),user=data.users[i];button.disabled=true;
      try{await api(`/api/admin/users/${encodeURIComponent(user.id)}/homeroom`,{method:"PUT",body:{homeroom_class:$(`staffUserClass${i}`).value}});
        if(token!==currentToken)return;$("staffAdminResult").innerHTML='<div class="alert ok">Классное руководство сохранено.</div>';await loadStaffUsers();
      }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}finally{button.disabled=false;}
    });
    list.querySelectorAll("[data-show-user]").forEach(button=>button.onclick=async()=>{
      const i=Number(button.dataset.showUser),user=data.users[i],out=$(`staffPassword${i}`);
      if(out.textContent){out.textContent="";button.textContent="Показать пароль";return;}
      button.disabled=true;
      try{const result=await api(`/api/admin/users/${encodeURIComponent(user.id)}/password`,{method:"POST"});
        if(token!==currentToken)return;
        out.textContent=`Пароль: ${result.password}`;button.textContent="Скрыть пароль";
      }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
      finally{button.disabled=false;}
    });
    list.querySelectorAll("[data-reset-user]").forEach(button=>button.onclick=async()=>{
      const i=Number(button.dataset.resetUser),user=data.users[i];
      if(!confirm(`Создать новый пароль для ${user.email}? Старый пароль и активные сеансы перестанут действовать.`))return;
      button.disabled=true;
      try{const result=await api(`/api/admin/users/${encodeURIComponent(user.id)}/password/reset`,{method:"POST"});
        if(token!==currentToken)return;
        $(`staffPassword${i}`).textContent=`Новый пароль: ${result.password}`;
        const showButton=list.querySelector(`[data-show-user="${i}"]`);if(showButton)showButton.textContent="Скрыть пароль";
        $("staffAdminResult").innerHTML='<div class="alert ok">Новый пароль создан. Передайте его пользователю безопасным способом.</div>';
      }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
      finally{button.disabled=false;}
    });
    list.querySelectorAll("[data-delete-user]").forEach(button=>button.onclick=async()=>{
      const user=data.users[Number(button.dataset.deleteUser)];
      if(!confirm(`Удалить пользователя ${user.email}? Доступ прекратится, история задач сохранится.`))return;
      button.disabled=true;
      try{await api(`/api/admin/users/${encodeURIComponent(user.id)}`,{method:"DELETE"});
        if(token!==currentToken)return;
        $("staffAdminResult").innerHTML=`<div class="alert ok">Пользователь ${esc(user.email)} удалён.</div>`;
        await loadStaffUsers();
      }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;button.disabled=false;}
    });
  }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
}
$("staffUsersRefresh").onclick=loadStaffUsers;
$("staffCreateForm").onsubmit=async e=>{
  e.preventDefault();const currentToken=token,button=e.currentTarget.querySelector("button");button.disabled=true;
  $("staffAdminResult").innerHTML="";
  try{
    const data=await api("/api/admin/users",{method:"POST",body:{full_name:$("staffFullName").value.trim(),email:$("staffEmail").value.trim(),role:$("staffRole").value,homeroom_class:$("staffRole").value==="teacher"?$("staffHomeroom").value:"",position:$("staffPosition").value.trim()}});
    if(!currentToken||token!==currentToken)return;
    $("staffFullName").value="";$("staffHomeroom").value="";$("staffEmail").value="";$("staffPosition").value="";
    $("staffAdminResult").innerHTML=`<div class="alert ok">Пользователь ${esc(data.user.email)} создан. Пароль: <b>${esc(data.password)}</b><br>Передайте его пользователю безопасным способом.</div>`;
    await loadStaffUsers();
  }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
  finally{button.disabled=false;}
};
document.addEventListener("planner-catalog-changed",()=>{if(token)loadStaffUsers();});
document.addEventListener("admin-panel-open",loadStaffUsers);
document.addEventListener("admin-panel-close",()=>{$("staffUsersList").innerHTML="";$("staffAdminResult").innerHTML="";});
if(!$("adminPanel").classList.contains("hidden"))loadStaffUsers();
