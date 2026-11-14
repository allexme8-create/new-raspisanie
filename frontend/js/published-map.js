"use strict";
/* Карта опубликованной сетки хранит правки отдельно, не изменяя черновик конструктора. */
let publishedMapData=null,publishedMapClass="",publishedMapSelected=null,publishedMapBusy=false;
const publishedMapDays=["Пн","Вт","Ср","Чт","Пт","Сб"];
async function loadPublishedMap(){
  try{
    let data=await api(`/api/admin/schedule-map${publishedMapClass?'?class_name='+encodeURIComponent(publishedMapClass):''}`);
    if(!publishedMapClass&&data.classes.length){publishedMapClass=data.classes[0];data=await api(`/api/admin/schedule-map?class_name=${encodeURIComponent(publishedMapClass)}`);}
    publishedMapData=data;publishedMapSelected=null;
    $("publishedMapClass").innerHTML=data.classes.map(c=>`<option value="${esc(c)}"${c===publishedMapClass?' selected':''}>${esc(c)}</option>`).join("");
    $("publishedMapEdit").classList.add("hidden");renderPublishedMap();
  }catch(e){$("publishedMapStatus").textContent=e.message;}
}
function renderPublishedMap(){
  const map=$("publishedMap"),status=$("publishedMapStatus"),data=publishedMapData;
  if(!data||!publishedMapClass){map.innerHTML='<p class="muted">Расписание не загружено.</p>';status.textContent="";return;}
  if(data.stale)status.textContent="Опубликованное расписание изменилось. Отмените старые изменения карты и загрузите актуальные данные.";
  else if(publishedMapSelected)status.textContent="Урок выбран. Нажмите «+» в нужной ячейке или исправьте данные выше.";
  else status.textContent=data.has_changes?"Есть неопубликованные изменения.":"Показано текущее опубликованное расписание.";
  $("publishedMapPublish").disabled=data.stale||!data.has_changes;
  let html='<div class="planner-map-scroll"><div class="planner-map-grid"><div class="planner-map-head">Урок</div>'+publishedMapDays.map(d=>`<div class="planner-map-head">${esc(d)}</div>`).join("");
  for(let lesson=1;lesson<=12;lesson++){
    html+=`<div class="planner-map-number">${lesson}</div>`;
    for(const day of publishedMapDays){
      const cells=data.entries.filter(e=>e.day===day&&e.lesson===lesson);
      html+=`<div class="planner-map-cell" data-pub-day="${day}" data-pub-lesson="${lesson}"><button type="button" class="planner-map-drop" data-pub-target aria-label="Перенести в ${esc(day)}, урок ${lesson}">+</button>${cells.map(e=>`<button type="button" class="planner-map-lesson ${publishedMapSelected?.day===e.day&&publishedMapSelected?.raw===e.raw?'selected':''}" data-pub-source="${esc(e.raw)}" data-pub-source-day="${esc(e.day)}"><strong>${esc((e.subjects.names||[]).join(', ')||e.subjects.raw||'Без предмета')}</strong><span>${esc((e.teachers.names||[]).join(', ')||e.teachers.raw||'')}</span><span>${esc([...new Set([...(e.subjects.rooms||[]),...(e.teachers.rooms||[])])].join(', '))}</span>${e.before_shift?'<span>До начала смены</span>':''}</button>`).join("")}</div>`;
    }
  }
  map.innerHTML=html+'</div></div>';
  map.querySelectorAll("[data-pub-target]").forEach(button=>button.onclick=()=>{const cell=button.closest('[data-pub-day]');if(publishedMapSelected&&cell)movePublishedMap(publishedMapSelected,cell.dataset.pubDay,Number(cell.dataset.pubLesson));});
  map.querySelectorAll("[data-pub-source]").forEach(chip=>{
    let pointer=null,suppress=false;
    const selected=()=>({day:chip.dataset.pubSourceDay,raw:chip.dataset.pubSource});
    chip.onclick=()=>{if(suppress){suppress=false;return;}if(publishedMapBusy||data.stale)return;publishedMapSelected=selected();openPublishedMapEdit();renderPublishedMap();};
    chip.onpointerdown=e=>{if(e.button!==0||publishedMapBusy||data.stale)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY,drag:false};chip.setPointerCapture(e.pointerId);};
    chip.onpointermove=e=>{if(pointer&&pointer.id===e.pointerId&&Math.hypot(e.clientX-pointer.x,e.clientY-pointer.y)>8){pointer.drag=true;chip.classList.add('dragging');}};
    chip.onpointercancel=()=>{pointer=null;chip.classList.remove('dragging');};
    chip.onpointerup=e=>{if(!pointer||pointer.id!==e.pointerId)return;const drag=pointer.drag;pointer=null;chip.classList.remove('dragging');if(!drag)return;suppress=true;const cell=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-pub-day]');if(cell&&map.contains(cell))movePublishedMap(selected(),cell.dataset.pubDay,Number(cell.dataset.pubLesson));else {status.textContent='Перенос отменён.';setTimeout(()=>{suppress=false},0);}};
  });
}
function openPublishedMapEdit(){
  const e=publishedMapData.entries.find(x=>x.day===publishedMapSelected.day&&x.raw===publishedMapSelected.raw);
  if(!e)return;
  $("publishedMapEditTitle").textContent=`${publishedMapClass} · ${e.day} · урок ${e.before_shift?'до смены':e.lesson}`;
  $("publishedMapSubjects").value=(e.subjects.names||[]).join(', ');
  $("publishedMapTeachers").value=(e.teachers.names||[]).join(', ');
  $("publishedMapRooms").value=[...new Set([...(e.subjects.rooms||[]),...(e.teachers.rooms||[])])].join(', ');
  $("publishedMapEdit").classList.remove("hidden");
}
$("publishedMapEditClose").onclick=()=>{$("publishedMapEdit").classList.add("hidden");publishedMapSelected=null;renderPublishedMap();};
$("publishedMapEdit").onsubmit=async e=>{
  e.preventDefault();if(!publishedMapSelected||publishedMapBusy||publishedMapData.stale)return;
  const split=id=>$(id).value.split(',').map(x=>x.trim()).filter(Boolean);
  publishedMapBusy=true;
  try{await api('/api/admin/schedule-map/edit',{method:'POST',body:{revision:publishedMapData.revision,class_name:publishedMapClass,day:publishedMapSelected.day,raw:publishedMapSelected.raw,subjects:split('publishedMapSubjects'),teachers:split('publishedMapTeachers'),rooms:split('publishedMapRooms')}});await loadPublishedMap();$("publishedMapStatus").textContent='Данные урока сохранены. Изменения ещё не опубликованы.';}
  catch(error){$("publishedMapStatus").textContent=error.message;}finally{publishedMapBusy=false;}
};
async function movePublishedMap(source,targetDay,targetLesson){
  if(publishedMapBusy||publishedMapData.stale)return;publishedMapBusy=true;$("publishedMapStatus").textContent='Проверяем и сохраняем перенос…';
  try{await api('/api/admin/schedule-map/move',{method:'POST',body:{revision:publishedMapData.revision,class_name:publishedMapClass,day:source.day,raw:source.raw,target_day:targetDay,target_lesson:targetLesson}});await loadPublishedMap();$("publishedMapStatus").textContent='Урок перенесён. Изменения ещё не опубликованы.';}
  catch(e){$("publishedMapStatus").textContent=e.message;}finally{publishedMapBusy=false;}
}
$("publishedMapSection").ontoggle=()=>{if($("publishedMapSection").open&&!publishedMapData)loadPublishedMap();};
$("publishedMapClass").onchange=()=>{publishedMapClass=$("publishedMapClass").value;loadPublishedMap();};
$("publishedMapRefresh").onclick=()=>loadPublishedMap();
$("publishedMapReset").onclick=async()=>{if(!confirm('Отменить все неопубликованные изменения карты?'))return;try{await api('/api/admin/schedule-map/reset',{method:'POST',body:{revision:publishedMapData.revision}});await loadPublishedMap();}catch(e){$("publishedMapStatus").textContent=e.message;}};
$("publishedMapPublish").onclick=async()=>{if(!publishedMapData||!confirm('Опубликовать изменения карты вместо текущего расписания?'))return;try{await api('/api/admin/schedule-map/publish',{method:'POST',body:{revision:publishedMapData.revision}});await loadPublishedMap();await loadStatus();$("publishedMapStatus").textContent='Расписание опубликовано.';}catch(e){$("publishedMapStatus").textContent=e.message;}};
