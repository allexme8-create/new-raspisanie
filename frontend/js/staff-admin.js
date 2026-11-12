"use strict";
async function loadStaffUsers(){
  try{
    const data=await api("/api/admin/users");
    $("staffUsersList").innerHTML=data.users.length?`<ul class="staff-user-list">${data.users.map(u=>`<li>${esc(u.email)} · ${u.role==="director"?"директор":"заместитель директора"}</li>`).join("")}</ul>`:'<p class="muted">Пользователей пока нет.</p>';
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
