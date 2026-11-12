"use strict";
function renderMailSettings(data){
  $("mailSender").value=["automatic","oauth"].includes(data.source)?data.sender:"";
  const mode=data.source==="oauth"?`OAuth · ${data.provider==="yandex"?"Яндекс":"Mail.ru"}`:data.source==="automatic"?"SMTP по паролю приложения":"Настройки сервера";
  const details=data.host&&data.sender?`${esc(data.sender)} · ${esc(data.host)}:${esc(data.port)} · ${esc(data.security.toUpperCase())}`:"Отправитель или сервер не настроен";
  const password=data.source==="oauth"?"OAuth сохранён; SMTP_PASSWORD не требуется. Доступ проверяется при отправке.":data.password_configured?"SMTP_PASSWORD задан (подключение ещё не проверено)":"SMTP_PASSWORD не задан";
  $("mailSettingsStatus").innerHTML=`<div class="alert">${esc(mode)}: ${details}<br>${esc(password)}</div>`;
}
async function loadMailSettings(){
  try{renderMailSettings(await api("/api/admin/mail-settings"));}
  catch(error){$("mailSettingsStatus").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
}
async function saveMailSettings(sender){
  const buttons=$("mailSettingsForm").querySelectorAll("button");buttons.forEach(b=>b.disabled=true);
  try{renderMailSettings(await api("/api/admin/mail-settings",{method:"PUT",body:{sender}}));}
  catch(error){$("mailSettingsStatus").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
  finally{buttons.forEach(b=>b.disabled=false);}
}
$("mailSettingsForm").querySelectorAll("[data-oauth-provider]").forEach(button=>button.onclick=async()=>{
  const input=$("mailSender");
  if(!input.reportValidity())return;
  const popup=window.open("about:blank","_blank");
  if(!popup){$("mailSettingsStatus").innerHTML='<div class="alert err">Разрешите открытие новой вкладки для подключения почты.</div>';return;}
  popup.opener=null;
  button.disabled=true;
  try{
    const data=await api("/api/admin/mail-oauth/start",{method:"POST",body:{provider:button.dataset.oauthProvider,sender:input.value.trim()}});
    popup.location.replace(data.url);
  }catch(error){popup.close();$("mailSettingsStatus").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}
  finally{button.disabled=false;}
});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!$("adminPanel").classList.contains("hidden"))loadMailSettings();});
$("mailSettingsForm").onsubmit=e=>{e.preventDefault();if(confirm("Переключиться на SMTP по паролю приложения? Текущее OAuth-подключение будет удалено."))saveMailSettings($("mailSender").value.trim());};
$("mailUseEnvironment").onclick=()=>{if(confirm("Переключиться на SMTP-настройки сервера? Текущее OAuth-подключение будет удалено."))saveMailSettings(null);};
document.addEventListener("admin-panel-open",loadMailSettings);
if(!$("adminPanel").classList.contains("hidden"))loadMailSettings();
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
