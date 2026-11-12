"use strict";
let dutyCalendar=null, dutySelected=null, dutyVersion=0;
function resetDuty(){
  dutyVersion++;dutyCalendar=null;dutySelected=null;byId("dutyClass").value="";byId("dutyMap").innerHTML="";
  byId("dutyError").innerHTML="";byId("dutySelected").textContent="Выберите свободное место на карте.";byId("dutySubmit").disabled=true;
}
const dutySlotLabel=slot=>slot===0?"Дежурный администратор":`${slot}-я смена · учитель`;
function dutyDateText(value){return new Date(value+"T00:00:00Z").toLocaleDateString("ru-RU",{timeZone:"UTC",day:"numeric",month:"long",weekday:"short"});}
function dutyDays(start,end){
  const result=[];for(let d=new Date(start+"T00:00:00Z"),last=new Date(end+"T00:00:00Z");d<=last;d.setUTCDate(d.getUTCDate()+1))result.push(d.toISOString().slice(0,10));return result;
}
function renderDuty(){
  if(!dutyCalendar)return;
  const data=dutyCalendar,map=new Map(data.entries.map(e=>[`${e.day}:${e.slot}`,e]));
  byId("dutyPeriod").textContent=`${data.quarter}-я четверть: ${dutyDateText(data.start)} — ${dutyDateText(data.end)}. Часовой пояс: ${data.timezone}.`+(data.active?"":" Сейчас каникулы: показана следующая четверть, запись откроется с её начала.");
  byId("dutyClassField").classList.toggle("hidden",role!=="teacher");
  byId("dutyClass").required=role==="teacher";
  const chosen=dutySelected&&map.get(`${dutySelected.day}:${dutySelected.slot}`);
  if(chosen||(dutySelected&&(!data.active||dutySelected.day<data.today||dutySelected.day<data.start||dutySelected.day>data.end)))dutySelected=null;
  byId("dutySelected").textContent=dutySelected?`Выбрано: ${dutyDateText(dutySelected.day)} · ${dutySlotLabel(dutySelected.slot)}`:"Выберите свободное место на карте.";
  byId("dutySubmit").disabled=!dutySelected||!data.active;
  byId("dutyMap").innerHTML=`<div class="duty-grid"><div class="duty-grid-head"><b>Дата</b><b>Дежурный администратор</b><b>1-я смена</b><b>2-я смена</b></div>${dutyDays(data.start,data.end).map(day=>{
    const slots=[0,1,2].map(slot=>{
      const entry=map.get(`${day}:${slot}`),mine=entry?.mine,allowed=(role==="associate"?slot===0:slot!==0),canAct=data.active&&day>=data.today;
      if(entry){const name=entry.full_name||"ФИО не указано",position=entry.position?` · ${entry.position}`:"",cls=entry.class_name?` · ${entry.class_name}`:"";
        return `<div class="duty-slot occupied"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span><strong>${escapeHTML(name)}</strong>${escapeHTML(position+cls)}${mine&&day>=data.today?` <button type="button" class="duty-action" data-duty-cancel="${escapeHTML(day)}" data-slot="${slot}">Отменить запись</button>`:""}</div>`;}
      const selected=dutySelected?.day===day&&dutySelected?.slot===slot;
      return `<div class="duty-slot"><span class="duty-mobile-label">${escapeHTML(dutySlotLabel(slot))}: </span>${allowed&&canAct?`<button type="button" class="duty-action ${selected?'selected':''}" data-duty-select="${escapeHTML(day)}" data-slot="${slot}">${selected?'Выбрано':'Свободно · выбрать'}</button>`:'<span class="muted">Свободно</span>'}</div>`;
    }).join("");
    return `<div class="duty-row ${day===data.today?'duty-today':''}"><strong>${escapeHTML(dutyDateText(day))}${day===data.today?' · сегодня':''}</strong>${slots}</div>`;
  }).join("")}</div>`;
  byId("dutyMap").querySelectorAll("[data-duty-select]").forEach(button=>button.onclick=()=>{dutySelected={day:button.dataset.dutySelect,slot:Number(button.dataset.slot)};renderDuty();byId("dutyForm").scrollIntoView({behavior:"smooth",block:"center"});});
  byId("dutyMap").querySelectorAll("[data-duty-cancel]").forEach(button=>button.onclick=async()=>{
    if(!confirm("Отменить вашу запись на дежурство?"))return;button.disabled=true;byId("dutyError").innerHTML="";
    try{await request(`/api/staff/duty/${encodeURIComponent(button.dataset.dutyCancel)}/${Number(button.dataset.slot)}`,{method:"DELETE"});await loadDutyCalendar();}
    catch(e){errorAt("dutyError",e);button.disabled=false;}
  });
}
async function loadDutyCalendar(){
  if(role==="director"||!staffToken||!staffUser)return;
  const session=staffToken, version=++dutyVersion;
  try{const data=await request("/api/staff/duty");if(staffToken!==session||version!==dutyVersion)return;dutyCalendar=data;renderDuty();}
  catch(e){if(staffToken===session&&version===dutyVersion)errorAt("dutyError",e);}
}
byId("dutyRefresh").onclick=()=>{byId("dutyError").innerHTML="";loadDutyCalendar();};
byId("dutyForm").onsubmit=async e=>{
  e.preventDefault();if(!dutySelected)return;const button=byId("dutySubmit");button.disabled=true;byId("dutyError").innerHTML="";
  const selection=dutySelected;
  try{await request("/api/staff/duty",{method:"POST",body:{day:selection.day,shift:role==="teacher"?selection.slot:null,class_name:role==="teacher"?byId("dutyClass").value.trim():""}});
    dutySelected=null;byId("dutyError").innerHTML='<div class="alert ok">Вы записаны на дежурство.</div>';await loadDutyCalendar();
  }catch(error){errorAt("dutyError",error);await loadDutyCalendar();}finally{if(dutySelected)button.disabled=false;}
};

setInterval(()=>{if(!document.hidden&&staffToken&&staffUser&&!byId("staffDutyView").classList.contains("hidden"))loadDutyCalendar();},60000);
