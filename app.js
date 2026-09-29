const regionEl=document.querySelector('#region'),dateEl=document.querySelector('#date'),childrenEl=document.querySelector('#children'),yearEl=document.querySelector('#year'),resultEl=document.querySelector('#result'),archiveEl=document.querySelector('#archive');
let db;
dateEl.value=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Krasnoyarsk',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const rub=v=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB'}).format(v);
const share=n=>n===1?1/4:n===2?1/3:1/2;
function render(){
  if(!db)return;
  const region=regionEl.value,years=Object.keys(db.years).map(Number).sort((a,b)=>b-a),requested=new Date(`${dateEl.value}T12:00:00`).getFullYear()-1;
  if(!region||!dateEl.value){resultEl.textContent='Выберите регион и дату.';archiveEl.textContent='';return}
  if(dateEl.value<'2026-03-01'){resultEl.textContent='Это правило применяется с 1 марта 2026 года. Для более ранней даты расчёт здесь не показывается.';return}
  const active=years.find(y=>y<=requested&&db.years[y][region]?.effective_from&&db.years[y][region].effective_from<=dateEl.value&&(!db.years[y][region].valid_until||db.years[y][region].valid_until>=dateEl.value));
  const entry=active?db.years[active][region]:null;
  if(entry){const value=Math.round(entry.salary*share(+childrenEl.value)*100)/100;resultEl.innerHTML=`<div>Ориентир в месяц</div><div class="amount">${rub(value)}</div><div class="meta">Средняя зарплата за ${active} год: ${rub(entry.salary)}. Применяется с ${new Date(entry.effective_from+'T12:00:00').toLocaleDateString('ru-RU')}. <a href="${entry.source}" target="_blank" rel="noopener">Источник</a>.</div>`}
  else resultEl.textContent='Нет проверенных данных о показателе, применимом на эту дату. Сумму пока не показываем.';
  const selected=db.years[yearEl.value]?.[region];archiveEl.innerHTML=selected?`Средняя зарплата за ${yearEl.value} год: <strong>${rub(selected.salary)}</strong><p class="meta">Проверено ${selected.checked_at}. <a href="${selected.source}" target="_blank" rel="noopener">Источник</a></p>`:'Для этого региона за выбранный год нет проверенных данных.';
}
fetch('data/salaries.json').then(r=>{if(!r.ok)throw Error('Данные недоступны');return r.json()}).then(data=>{db=data;const regions=[...new Set(Object.values(db.years).flatMap(y=>Object.keys(y)))].sort((a,b)=>a.localeCompare(b,'ru'));regionEl.innerHTML='<option value="">Выберите регион</option>'+regions.map(r=>`<option>${r}</option>`).join('');yearEl.innerHTML=Object.keys(db.years).sort((a,b)=>b-a).map(y=>`<option>${y}</option>`).join('');render()}).catch(()=>{regionEl.innerHTML='<option>Данные пока недоступны</option>';resultEl.textContent='Не удалось загрузить проверенные показатели. Попробуйте позже.'});
[regionEl,dateEl,childrenEl,yearEl].forEach(el=>el.addEventListener('change',render));
