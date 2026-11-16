"use strict";
/* Карточка следует за пальцем или мышью; область под ней остаётся доступна для hit-test. */
function moveDragCard(element,dx,dy){
  element.classList.add("dragging");
  element.style.transform=`translate(${dx}px, ${dy}px)`;
  element.style.pointerEvents="none";
}
function finishDragCard(element){
  element.classList.remove("dragging");
  element.style.transform="";
  element.style.pointerEvents="";
}
