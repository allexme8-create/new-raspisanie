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
    $("bellDownloadBtn").classList.toggle("hidden",!st.bell_schedule);
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
    $("bellDownloadBtn").classList.add("hidden");
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
$("adminExpandAll").onclick=()=>document.querySelectorAll("#adminPanel > .admin-block").forEach(block=>{block.open=true;});
$("adminCollapseAll").onclick=()=>document.querySelectorAll("#adminPanel > .admin-block").forEach(block=>{block.open=false;});

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

const bellEditorDays=["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];
let bellEditorRevision=null;
function bellEditorRow(entry={}){
  const day=entry.day||"Пн",shift=String(entry.shift||1);
  return `<div class="planner-form bell-editor-row"><input type="hidden" data-bell-day value="${esc(day)}"><input type="hidden" data-bell-shift value="${esc(shift)}"><span class="bell-row-context hidden"></span><label>Урок<input data-bell-lesson type="number" min="1" max="99" required value="${esc(entry.lesson||1)}"></label><label>Начало<input data-bell-start type="time" required value="${esc(entry.start||"")}"></label><label>Окончание<input data-bell-end type="time" required value="${esc(entry.end||"")}"></label><button class="btn danger" type="button" data-bell-remove aria-label="Удалить урок" title="Удалить урок">✕</button></div>`;
}
function bellEditorFilter(){
  const day=$("bellEditorDayFilter").value,shift=$("bellEditorShiftFilter").value;
  let visible=0;
  $("bellEditorRows").querySelectorAll(".bell-editor-row").forEach(row=>{
    const matches=(!day||row.querySelector("[data-bell-day]").value===day)&&(!shift||row.querySelector("[data-bell-shift]").value===shift);
    row.classList.toggle("hidden",!matches);
    const context=row.querySelector(".bell-row-context"),details=[];
    if(!day)details.push(row.querySelector("[data-bell-day]").value);
    if(!shift)details.push(`${row.querySelector("[data-bell-shift]").value}-я смена`);
    context.textContent=details.join(" · ");context.classList.toggle("hidden",!details.length);row.classList.toggle("has-context",details.length>0);
    if(matches)visible++;
  });
  $("bellEditorEmpty").classList.toggle("hidden",visible>0);
}
$("bellEditorDayFilter").onchange=bellEditorFilter;
$("bellEditorShiftFilter").onchange=bellEditorFilter;
$("bellEditorLoad").onclick=async()=>{
  if(bellEditorRevision!==null&&!confirm("Загрузить заново? Несохранённые изменения будут потеряны."))return;
  try{
    const result=await api("/api/admin/bell-schedule/editor"),entries=[];
    for(const shift of ["1","2"])for(const day of bellEditorDays){
      const lessons=result.shifts[shift]?.[day]||{};
      for(const lesson of Object.keys(lessons).sort((a,b)=>Number(a)-Number(b)))entries.push({shift,day,lesson,...lessons[lesson]});
    }
    bellEditorRevision=result.revision;$("bellEditorRows").innerHTML=entries.map(bellEditorRow).join("");
    $("bellEditorForm").classList.remove("hidden");bellEditorFilter();$("bellEditorMessage").innerHTML="";
  }catch(e){$("bellEditorMessage").innerHTML=`<div class="alert err">${esc(e.message)}</div>`;}
};
$("bellEditorAdd").onclick=()=>{
  if(!$("bellEditorDayFilter").value)$("bellEditorDayFilter").value="Пн";
  if(!$("bellEditorShiftFilter").value)$("bellEditorShiftFilter").value="1";
  $("bellEditorRows").insertAdjacentHTML("beforeend",bellEditorRow({day:$("bellEditorDayFilter").value,shift:$("bellEditorShiftFilter").value}));
  bellEditorFilter();
};
$("bellEditorRows").onclick=e=>{const button=e.target.closest("[data-bell-remove]");if(button){button.closest(".bell-editor-row").remove();bellEditorFilter();}};
$("bellEditorForm").onsubmit=async e=>{
  e.preventDefault();const button=$("bellEditorSave"),rows=[...$("bellEditorRows").querySelectorAll(".bell-editor-row")];
  for(const row of rows){
    const invalid=[...row.querySelectorAll("input,select")].find(input=>!input.checkValidity());
    if(invalid){$("bellEditorDayFilter").value=row.querySelector("[data-bell-day]").value;$("bellEditorShiftFilter").value=row.querySelector("[data-bell-shift]").value;bellEditorFilter();invalid.reportValidity();return;}
  }
  const entries=rows.map(row=>({day:row.querySelector("[data-bell-day]").value,shift:Number(row.querySelector("[data-bell-shift]").value),lesson:Number(row.querySelector("[data-bell-lesson]").value),start:row.querySelector("[data-bell-start]").value,end:row.querySelector("[data-bell-end]").value}));
  if(!entries.length){$("bellEditorMessage").innerHTML='<div class="alert err">Добавьте хотя бы один урок.</div>';return;}
  button.disabled=true;
  try{const result=await api("/api/admin/bell-schedule/editor",{method:"PUT",body:{revision:bellEditorRevision,entries}});bellEditorRevision=result.revision;$("bellEditorMessage").innerHTML='<div class="alert ok">Расписание звонков сохранено.</div>';await loadStatus();}
  catch(error){$("bellEditorMessage").innerHTML=`<div class="alert err">${esc(error.message)}</div>`;}finally{button.disabled=false;}
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

/* ── автостарт: если токен сохранён, проверяем его ── */
(async()=>{
  if(token){
    const valid=await loadStatus();
    if(valid) showPanel(true);
  }
})();
