"use strict";
/* Одинаковый предмет получает один цвет независимо от класса и режима карты. */
function lessonColorClass(subjects, raw=""){
  const name=String((Array.isArray(subjects)&&subjects.find(x=>String(x||"").trim()))||raw||"").normalize("NFKC").trim().replace(/\s+/g," ").toLocaleLowerCase("ru-RU");
  if(!name)return "";
  let hash=2166136261;
  for(const char of name){hash^=char.codePointAt(0);hash=Math.imul(hash,16777619);}
  return `lesson-color-${(hash>>>0)%14}`;
}
