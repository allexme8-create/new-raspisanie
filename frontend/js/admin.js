"use strict";
/* Логика админ-панели: загрузки расписания/звонков и выбор классов смены. */
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),2800); }

const TOKEN_KEY="schedule_admin_token";
let token=localStorage.getItem(TOKEN_KEY)||"";
const KIND_LABEL={teachers:"Учителя",subjects:"Предметы"};

async function api(path,{method="GET",body,form}={}){
  const requestToken=token;
  const opts={method,headers:{},credentials:"same-origin"};
  if(requestToken){
    opts.headers.Authorization=`Bearer ${requestToken}`;
    opts.headers["X-Admin-Token"]=requestToken;
  }
  if(form){ opts.body=form; }
  else if(body!==undefined){ opts.headers["Content-Type"]="application/json"; opts.body=JSON.stringify(body); }
  const resp=await fetch(path,opts);
  if(resp.status===401){
    if(requestToken&&requestToken===token) logout(false);
    throw new Error("Сессия истекла — войдите заново");
  }
  let data=null;
  try{ data=await resp.json(); }catch(e){}
  if(!resp.ok) throw new Error(typeof data?.detail==="string"?data.detail:Array.isArray(data?.detail)?data.detail.map(x=>x.msg).join("; "):`Ошибка ${resp.status}`);
  return data;
}

function showPanel(on){
  $("loginCard").classList.toggle("hidden",on);
  $("adminPanel").classList.toggle("hidden",!on);
  document.dispatchEvent(new Event(on?"admin-panel-open":"admin-panel-close"));
}
function logout(callApi=true){
  const oldToken=token;
  token=""; localStorage.removeItem(TOKEN_KEY);
  showPanel(false);
  if(callApi===true){
    if(oldToken)fetch("/api/admin/logout",{method:"POST",credentials:"same-origin",headers:{Authorization:`Bearer ${oldToken}`,"X-Admin-Token":oldToken}}).catch(()=>{});
    toast("Вы вышли из админ-панели");
  }
}
function fmtDate(iso){
  try{ return new Date(iso).toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}); }
  catch(e){ return "—"; }
}

function renderShiftClasses(st){
  const list=$("shiftClassList"),save=$("saveShiftBtn");
  const classes=Array.isArray(st.classes)?st.classes:[];
  const selected=new Set(st.second_shift_classes||[]);
  if(!classes.length){
    list.innerHTML='<p class="muted">Сначала загрузите расписание уроков.</p>';
    save.disabled=true;
    return;
  }
  list.innerHTML=classes.map((name,index)=>{
    const id=`second-shift-${index}`;
    return `<label class="shift-class-option" for="${id}">
      <input id="${id}" type="checkbox" value="${esc(name)}" ${selected.has(name)?"checked":""}>
      <span>${esc(name)}</span>
    </label>`;
  }).join("");
  if(!st.bell_schedule)list.insertAdjacentHTML("beforeend",'<p class="muted">Сначала загрузите расписание звонков, чтобы применить смену.</p>');
  save.disabled=!st.bell_schedule;
}

async function loadStatus(){
  try{
    const st=await api("/api/admin/status");
    $("bellDownloadBtn").disabled=!st.bell_schedule;
    const list=[];
    for(const kind of ["teachers","subjects"]){
      const f=st[kind];
      if(f){
        list.push(`<div class="frow">
          <span class="tag-ok">✔</span>
          <span class="fkind">${KIND_LABEL[kind]}</span>
          <div><div class="fname">${esc(f.filename||"Загружено")}</div>
          <div class="fmeta">классов: ${f.classes} · строк расписания: ${f.lesson_rows}</div></div>
          <div class="spacer"></div>
          <button class="btn danger" data-del="${kind}">Удалить</button>
        </div>`);
      }else{
        list.push(`<div class="frow"><span style="color:var(--busy)">✖</span>
          <span class="fkind" style="background:#fdeeee;color:var(--busy)">${KIND_LABEL[kind]}</span>
          <span class="fmeta">Файл не загружен</span>
        </div>`);
      }
    }
    if(st.bell_schedule){
      const bell=st.bell_schedule;
      list.push(`<div class="frow">
        <span class="tag-ok">✔</span>
        <span class="fkind">Звонки</span>
        <div><div class="fname">${esc(bell.filename||"Расписание звонков")}</div>
        <div class="fmeta">уроков с временем: ${bell.lesson_rows} · смены: ${bell.shifts.join(", ")}</div></div>
        <div class="spacer"></div>
        <button class="btn danger" data-del="bell_schedule">Удалить</button>
      </div>`);
    }else{
      list.push(`<div class="frow"><span style="color:var(--busy)">✖</span>
        <span class="fkind" style="background:#fdeeee;color:var(--busy)">Звонки</span>
        <span class="fmeta">Файл не загружен</span>
      </div>`);
    }
    const b=st.backup||{};
    const backupMarkup=b.enabled
      ? `☁️ <b>Автобэкап включён</b>: после обновления расписание сохраняется в GitHub (<span class="mono">${esc(b.repo)}</span>, ветка <span class="mono">${esc(b.branch)}</span>).`
      : `☁️ Автобэкап в GitHub не настроен — после перезапуска хостинга файлы нужно будет загрузить заново. Настройка описана в DEPLOY.md.`;
    list.push(`<div class="alert" style="margin:4px 0 0;background:${b.enabled?"#eef0ff":"#f4f5fa"};border-color:${b.enabled?"#c7cde2":"var(--line)"}">${backupMarkup}</div>`);
    $("filesList").innerHTML=list.join("");
    $("updatedLabel").textContent=st.updated_at?`Последнее обновление: ${fmtDate(st.updated_at)}`:"";
    renderShiftClasses(st);
    $("filesList").querySelectorAll("[data-del]").forEach(button=>button.onclick=async()=>{
      const kind=button.dataset.del;
      const label=kind==="bell_schedule"?"расписание звонков":KIND_LABEL[kind];
      if(!confirm(`Удалить файл «${label}»?`)) return;
      try{ await api(`/api/admin/file/${kind}`,{method:"DELETE"}); toast("Файл удалён"); }
      catch(e){ toast(`⚠️ ${e.message}`); }
      await loadStatus();
    });
    return true;
  }catch(e){
    $("bellDownloadBtn").disabled=true;
    $("filesList").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;
    return false;
  }
}

function alertBox(elId,items){
  if(!items.length){ $(elId).innerHTML=""; return; }
  const ok=items.every(i=>i.ok);
  $(elId).innerHTML=`<div class="alert ${ok?"ok":"err"}">`+
    items.map(i=>i.ok
      ? `✔ <b>${esc(i.file)}</b> → файл «${KIND_LABEL[i.kind]||"расписания"}»${i.classes!=null?` (${i.classes} классов)`:""}`
      : `⚠️ <b>${esc(i.file)}</b>: ${esc(i.error)}`
    ).join("<br>")+`</div>`;
}

/* ── вход ── */
$("loginForm").onsubmit=async e=>{
  e.preventDefault();
  const btn=$("loginBtn"); btn.disabled=true;
  $("loginAlert").innerHTML="";
  try{
    const data=await api("/api/admin/login",{method:"POST",body:{password:$("password").value}});
    token=data.token; localStorage.setItem(TOKEN_KEY,token);
    $("password").value="";
    showPanel(true); await loadStatus();
    toast("✔ Добро пожаловать!");
  }catch(err){
    $("loginAlert").innerHTML=`<div class="alert err">${esc(err.message)}</div>`;
  }finally{ btn.disabled=false; }
};

$("logoutBtn").onclick=()=>logout();
$("refreshBtn").onclick=()=>loadStatus();

/* ── загрузка файлов расписания ── */
const dz=$("dropzone"), fi=$("fileInput");
dz.onclick=()=>fi.click();
fi.onchange=()=>{ uploadFiles([...fi.files]); fi.value=""; };
dz.ondragover=e=>{e.preventDefault();dz.classList.add("drag");};
dz.ondragleave=()=>dz.classList.remove("drag");
dz.ondrop=e=>{e.preventDefault();dz.classList.remove("drag");uploadFiles([...e.dataTransfer.files]);};

async function uploadFiles(files){
  if(!files.length) return;
  $("uploadResult").innerHTML=`<div class="alert" style="background:#f4f5fa">Загружаю ${files.length} файл(ов)…</div>`;
  const form=new FormData();
  files.forEach(file=>form.append("files",file));
  try{
    const data=await api("/api/admin/upload",{method:"POST",form});
    alertBox("uploadResult",data.results||[]);
    toast("✔ Готово — расписание обновлено для всех посетителей");
  }catch(e){
    $("uploadResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;
  }
  await loadStatus();
}

/* CSV создаётся из текущего расписания и подходит для повторной загрузки. */
$("bellDownloadBtn").onclick=async()=>{
  const button=$("bellDownloadBtn"),requestToken=token;button.disabled=true;
  try{
    const response=await fetch("/api/admin/bell-schedule.csv",{credentials:"same-origin",cache:"no-store",headers:{Authorization:`Bearer ${requestToken}`,"X-Admin-Token":requestToken}});
    if(response.status===401){if(requestToken&&requestToken===token)logout(false);throw new Error("Сессия истекла — войдите заново");}
    if(!response.ok){let data={};try{data=await response.json();}catch(e){}throw new Error(data.detail||`Ошибка ${response.status}`);}
    const url=URL.createObjectURL(await response.blob()),link=document.createElement("a");
    try{link.href=url;link.download="bell-schedule.csv";document.body.appendChild(link);link.click();link.remove();}finally{URL.revokeObjectURL(url);}
  }catch(e){$("bellUploadResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;}
  finally{button.disabled=false;}
};

/* ── отдельная загрузка расписания звонков ── */
$("bellUploadBtn").onclick=async()=>{
  const input=$("bellFileInput"),file=input.files?.[0];
  if(!file){ toast("Выберите файл расписания звонков"); return; }
  const button=$("bellUploadBtn"); button.disabled=true;
  $("bellUploadResult").innerHTML='<div class="alert" style="background:#f4f5fa">Загружаю расписание звонков…</div>';
  const form=new FormData(); form.append("file",file);
  try{
    const data=await api("/api/admin/bell-schedule",{method:"POST",form});
    $("bellUploadResult").innerHTML=`<div class="alert ok">✔ <b>${esc(data.file)}</b> — загружено ${data.lesson_rows} интервалов, смены: ${data.shifts.join(", ")}</div>`;
    input.value="";
    toast("Расписание звонков сохранено");
    await loadStatus();
  }catch(e){
    $("bellUploadResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;
  }finally{ button.disabled=false; }
};

/* ── настройки второй смены ── */
$("saveShiftBtn").onclick=async()=>{
  const selected=[...$("shiftClassList").querySelectorAll("input[type=checkbox]:checked")].map(input=>input.value);
  const button=$("saveShiftBtn"); button.disabled=true;
  try{
    const data=await api("/api/admin/settings",{method:"PUT",body:{second_shift_classes:selected}});
    $("shiftSettingsResult").innerHTML=`<div class="alert ok">✔ Сохранено. Во вторую смену: ${data.second_shift_classes.length?data.second_shift_classes.map(esc).join(", "):"классы не выбраны"}.</div>`;
    await loadStatus();
    toast("Настройки второй смены сохранены");
  }catch(e){
    $("shiftSettingsResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;
  }finally{ button.disabled=false; }
};

/* ── загрузка по ссылке Яндекс.Диска ── */
$("yandexBtn").onclick=async()=>{
  const url=$("yandexUrl").value.trim();
  if(!url){ toast("Вставьте ссылку"); return; }
  const btn=$("yandexBtn"); btn.disabled=true;
  $("yandexResult").innerHTML=`<div class="alert" style="background:#f4f5fa">Скачиваю файл с Яндекс.Диска…</div>`;
  try{
    const data=await api("/api/admin/fetch-yandex",{method:"POST",body:{url}});
    alertBox("yandexResult",[{ok:true,file:data.file,kind:data.kind,classes:null}]);
    $("yandexUrl").value="";
    await loadStatus();
  }catch(e){
    $("yandexResult").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;
  }finally{ btn.disabled=false; }
};

/* ── автостарт: если токен сохранён, проверяем его ── */
(async()=>{
  if(token){
    const valid=await loadStatus();
    if(valid) showPanel(true);
  }
})();
