"use strict";
(async()=>{
  const params=new URLSearchParams(location.search),code=params.get("code"),state=params.get("state"),error=params.get("error");
  history.replaceState(null,"",location.pathname);
  const result=document.getElementById("oauthResult");
  if(error){result.textContent="Провайдер отклонил подключение. Вернитесь в админку и попробуйте снова.";return;}
  const token=localStorage.getItem("schedule_admin_token")||"";
  if(!code||!state||!token){result.textContent="Не удалось завершить подключение. Войдите в админку и начните заново в этом же браузере.";return;}
  try{
    const response=await fetch("/api/admin/mail-oauth/complete",{method:"POST",headers:{"Content-Type":"application/json",Authorization:`Bearer ${token}`,"X-Admin-Token":token},body:JSON.stringify({code,state}),cache:"no-store"});
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Не удалось подключить почту");
    result.textContent=`Почта ${data.sender} подключена. Вернитесь в админку.`;
  }catch(e){result.textContent=e.message;}
})();
