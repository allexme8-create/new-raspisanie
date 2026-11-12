"use strict";
async function loadStaffUsers(){
  const currentToken=token;
  try{
    const data=await api("/api/admin/users");
    if(!currentToken||token!==currentToken)return;
    const list=$("staffUsersList");
    list.innerHTML=data.users.length?`<ul class="staff-user-list">${data.users.map((u,i)=>`<li><div class="staff-user-details"><span>${u.full_name ? `${esc(u.full_name)} · ` : ""}${esc(u.email)} · ${esc(u.position || (u.role==="director"?"директор":u.role==="teacher"?"учитель":"заместитель директора"))}</span><div id="staffPassword${i}" class="staff-password" aria-live="polite"></div></div><div class="staff-user-actions"><button type="button" class="btn secondary" data-show-user="${i}">Показать пароль</button><button type="button" class="btn secondary" data-reset-user="${i}">Обновить пароль</button><button type="button" class="btn danger" data-delete-user="${i}">Удалить</button></div></li>`).join("")}</ul>`:'<p class="muted">Пользователей пока нет.</p>';
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
    const data=await api("/api/admin/users",{method:"POST",body:{full_name:$("staffFullName").value.trim(),email:$("staffEmail").value.trim(),role:$("staffRole").value,position:$("staffPosition").value.trim()}});
    if(!currentToken||token!==currentToken)return;
    $("staffFullName").value="";$("staffEmail").value="";$("staffPosition").value="";
    $("staffAdminResult").innerHTML=`<div class="alert ok">Пользователь ${esc(data.user.email)} создан. Пароль: <b>${esc(data.password)}</b><br>Передайте его пользователю безопасным способом.</div>`;
    await loadStaffUsers();
  }catch(error){if(token===currentToken)$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
  finally{button.disabled=false;}
};
document.addEventListener("admin-panel-open",loadStaffUsers);
document.addEventListener("admin-panel-close",()=>{$("staffUsersList").innerHTML="";$("staffAdminResult").innerHTML="";});
if(!$("adminPanel").classList.contains("hidden"))loadStaffUsers();
