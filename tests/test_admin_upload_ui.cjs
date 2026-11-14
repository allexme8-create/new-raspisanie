const assert=require('node:assert/strict'),fs=require('node:fs');
const html=fs.readFileSync('frontend/admin.html','utf8'),js=fs.readFileSync('frontend/js/admin.js','utf8');
assert.doesNotMatch(html,/Яндекс\.Диска|yandexBtn|yandexUrl|yandexResult/);
assert.doesNotMatch(js,/yandexBtn|yandexUrl|yandexResult|fetch-yandex/);
assert.match(html,/id="fileInput"/);assert.match(html,/id="saveShiftBtn"/);
console.log('Admin file upload without Yandex block OK');
