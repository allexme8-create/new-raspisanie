"use strict";
async function loadStaffUsers(){
  try{
    const data=await api("/api/admin/users");
    $("staffUsersList").innerHTML=data.users.length?`<ul class="staff-user-list">${data.users.map((u,i)=>`<li><span>${esc(u.email)} · ${u.role==="director"?"директор":"заместитель директора"}</span><button type="button" class="btn danger" data-user-index="${i}">Удалить</button></li>`).join("")}</ul>`:'<p class="muted">Пользователей пока нет.</p>';
    $("staffUsersList").querySelectorAll("[data-user-index]").forEach(button=>button.onclick=async()=>{
      const user=data.users[Number(button.dataset.userIndex)];
      if(!user||!confirm(`Удалить пользователя ${user.email}? Доступ прекратится, а история задач сохранится. На почту будет отправлено уведомление.`))return;
      button.disabled=true;
      $("staffAdminResult").innerHTML="";
      try{
        await api(`/api/admin/users/${encodeURIComponent(user.id)}`,{method:"DELETE"});
        $("staffAdminResult").innerHTML=`<div class="alert ok">Пользователь ${esc(user.email)} удалён, уведомление принято почтовым сервером.</div>`;
        await loadStaffUsers();
      }catch(error){$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;button.disabled=false;}
    });
  }catch(e){$("staffAdminResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;}
}
$("staffUsersRefresh").onclick=loadStaffUsers;
$("staffCreateForm").onsubmit=async e=>{
  e.preventDefault();
  const button=e.currentTarget.querySelector("button");
  button.disabled=true;
  $("staffAdminResult").innerHTML="";
  try{
    const data=await api("/api/admin/users",{method:"POST",body:{email:$("staffEmail").value.trim(),role:$("staffRole").value}});
    $("staffEmail").value="";
    $("staffAdminResult").innerHTML=`<div class="alert ok">Пользователь ${esc(data.user.email)} создан, письмо отправлено.</div>`;
    await loadStaffUsers();
  }catch(error){$("staffAdminResult").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
  finally{button.disabled=false;}
};
