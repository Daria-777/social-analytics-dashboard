import {node,put,fmt,metric,date,labels,provenance,platformMark,dataContext,empty,state,table} from './dashboard-core.js';
import {preview} from './dashboard-preview.js';
import {chartGroups,historyPoints,accountTrend,accountWeeks,accountDailyChanges,accountMetrics} from './dashboard-presentation.js';
const ns='http://www.w3.org/2000/svg';
const colors=['#067462','#a34f21','#365e83','#715b7f','#646a24'];
const shapes=['circle','square','triangle','diamond'];
function svgNode(tag,attrs,text) {
  const el=document.createElementNS(ns,tag);
  Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));
  if(text!=null) el.textContent=text;
  return el;
}
function marker(index,x,y,size=5) {
  const fill=colors[index%colors.length];
  switch(shapes[index%shapes.length]) {
    case 'square':return svgNode('rect',{x:x-size,y:y-size,width:size*2,height:size*2,fill});
    case 'triangle':return svgNode('polygon',{points:`${x},${y-size} ${x+size},${y+size} ${x-size},${y+size}`,fill});
    case 'diamond':return svgNode('polygon',{points:`${x},${y-size} ${x+size},${y} ${x},${y+size} ${x-size},${y}`,fill});
    default:return svgNode('circle',{cx:x,cy:y,r:size,fill});
  }
}
export function renderHistoryChart(c,history) {
  const points=historyPoints(c,history);
  if(!points.length){put('growth-chart',empty('Нет измеренных точек','Нужны просмотры и время публикации.'));return;}
  const groups=chartGroups(points.map(s=>({content:c,snapshot:s}))), svg=svgNode('svg',{viewBox:'0 0 340 240',role:'img','aria-label':'Реальные просмотры: X — часы после публикации, Y — просмотры. Числовые значения доступны ниже.',class:'history-plot'});
  const maxAge=Math.max(1,...points.map(s=>s.age)),maxViews=Math.max(1,...points.map(s=>Number(s.views)));
  [0,1].forEach(t=>{
    const y=195-t*155,x=52+t*264;
    svg.append(svgNode('line',{x1:52,x2:316,y1:y,y2:y,stroke:'#dce2d8'}),svgNode('text',{x:4,y:y+5},fmt(maxViews*t,0)),svgNode('text',{x,y:218,'text-anchor':t?'end':'start'},fmt(maxAge*t)+' ч.'));
  });
  svg.append(svgNode('text',{x:52,y:20},'Просмотры'));
  const legend=node('ul',null,'plot-legend'),numbers=node('details',null,'chart-values');
  const list=node('ul',null,'measured-points');
  numbers.append(node('summary',`Измерения числами (${points.length})`),list);
  groups.forEach(([,rows],index)=>{
    const li=node('li'),symbol=svgNode('svg',{viewBox:'0 0 20 20','aria-hidden':'true',class:'series-marker'});
    symbol.append(marker(index,10,10,5));
    li.append(symbol,node('span',`Серия ${index+1}`),dataContext({...rows[0].snapshot,snapshot_at:null},true));legend.append(li);
    rows.forEach(({snapshot:s})=>{
      svg.append(marker(index,52+s.age/maxAge*264,195-Number(s.views)/maxViews*155));
      const value=node('li');
      value.append(node('strong',`Серия ${index+1} · через ${fmt(s.age)} ч. · ${fmt(s.views)} просмотров`),node('p',provenance(s),'muted'));
      list.append(value);
    });
  });
  put('growth-chart',...(points.length===1?[node('p','Одно измерение — тренд пока не виден.','muted')]:[]),svg,legend,numbers);
}
export function publicationBars(rows,key,contentLink) {
  if(!rows.length) return empty('Нет публикаций для графика','Измените фильтры или откройте список.');
  const displayValue = value => metric(value,key) + (["completion_rate","average_watch_pct"].includes(key)?"%":key==="watch_time_avg_seconds"?" сек.":"");
  const panels=chartGroups(rows),root=node('div',null,'publication-panels');
  panels.forEach(([,group])=>{
    const first=group[0],s=first.snapshot;
    const panel=node('section',null,'publication-panel'),heading=node('h3');
    heading.append(platformMark(first.content.platform),node('span',labels[key]));
    panel.append(heading);
    if(s) panel.append(dataContext({...s,snapshot_at:null},true));
    const values=group.map(r=>r.derived?.[key]??r.snapshot?.[key]);
    const max=Math.max(["completion_rate","average_watch_pct"].includes(key)?100:1,...values.filter(v=>v!=null).map(Number));
    panel.append(node("p",`Шкала: 0–${displayValue(max)}`,"muted"));
    group.forEach((r,i)=>{
      const row=node('article',null,'publication-bar'),name=node('div',null,'bar-name');
      name.append(preview(r.content),contentLink(r.content),platformMark(r.content.platform));
      row.append(name);
      const value=values[i];
      if(value==null) row.append(node('p','Нет данных','muted'));
      else {
        const meter=node('meter');meter.min=0;meter.max=max;meter.value=Number(value);
        meter.setAttribute('aria-label',`${labels[key]}: ${displayValue(value)}`);
        row.append(node('strong',displayValue(value),'bar-value'),meter);
      }
      const age=(Date.parse(r.snapshot?.snapshot_at)-Date.parse(r.content.published_at))/3600000;
      row.append(node('p',Number.isFinite(age)&&age>=0?`Возраст при измерении: ${fmt(age)} ч.`:'Возраст при измерении неизвестен','muted'));
      if(r.snapshot) row.append(dataContext(r.snapshot));
      panel.append(row);
    });
    root.append(panel);
  });
  return root;
}

export function accountTimeline(history, latest) {
  const root=node('section',null,'account-timeline');
  root.append(node('h3','Динамика по неделям'));
  if (latest.metric_scope !== 'current') {
    root.append(node('p','Недельная история доступна для текущих показателей аккаунта','muted'));
    return root;
  }
  const keys=['followers','following','views','unique_viewers','profile_views','new_viewers'];
  const select=node('select'),label=node('label',null,'account-metric-select');
  label.append(node('span','Показатель'),select);
  const displayLabels={...labels,following:'Аккаунт подписан на',profile_views:'Просмотры профиля',new_viewers:'Новые зрители'};
  for (const key of keys) {
    const option=node('option',displayLabels[key]); option.value=key;
    option.disabled=key!=='followers'&&!accountTrend(history,latest,key).points.length;
    select.append(option);
  }
  const chart=node('div');root.append(label,chart);
  function render() {
    const key=select.value,{points}=accountTrend(history,latest,key);
    chart.replaceChildren();
    if (!points.length) {chart.append(node('p','Нет сохранённых замеров','muted'));return;}
    const weeks=accountWeeks(points,state.config.display_timezone,new Date(),key);
    chart.append(node('p','Последний замер каждой недели','muted'));
    const scroll=node('div',null,'account-week-scroll');scroll.tabIndex=0;
    scroll.setAttribute('role','region');scroll.setAttribute('aria-label',`${displayLabels[key]} по неделям`);
    const list=node('ol',null,'account-weeks');
    const max=Math.max(1,...weeks.map(w=>w.value??0));
    const calendarDate=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC',dateStyle:'short'}).format(new Date(value+'T12:00:00Z'));
    for (const week of weeks) {
      const column=node('li',null,'account-week');
      column.append(node('strong',week.value==null?'—':fmt(week.value,0),'account-week-value'));
      const svg=svgNode('svg',{viewBox:'0 0 64 144','aria-hidden':'true',class:'account-week-bar'});
      svg.append(svgNode('line',{x1:0,x2:64,y1:140,y2:140,stroke:'#dce2d8'}));
      if (week.value!=null) {
        const height=week.value/max*132;
        svg.append(svgNode('rect',{x:10,y:140-height,width:44,height,rx:3,fill:colors[0]}));
      }
      column.append(svg,node('span',calendarDate(week.start)+' –','week-date'),node('span',calendarDate(week.end),'week-date'));
      if (week.current) column.append(node('span','Текущая неделя','week-note'));
      if (week.value==null) column.append(node('span','Нет данных','week-note'));
      list.append(column);
    }
    scroll.append(list);chart.append(scroll);
    if (weeks.length===1) chart.append(node('p','Пока данные только за одну неделю','muted'));

  }
  select.addEventListener('change',render);render();
  return root;
}


export function accountChangesTable(history,latest,accountTitle) {
  const root=node('section',null,'account-daily-changes');
  const heading=node('h3');heading.append(accountTitle);root.append(heading);
  const rows=accountDailyChanges(history,latest,state.config.display_timezone);
  if(!rows.length) {root.append(node('p','Нет данных для сравнения','muted'));return root;}
  root.append(node('p','Между последними замерами дней','muted'));
  const dateOnly=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC',dateStyle:'short'}).format(new Date(value+'T12:00:00Z'));
  const displayLabels={...labels,following:'Подписки',profile_views:'Просмотры профиля',new_viewers:'Новые зрители'};
  const values=rows.map(row=>[
    row.start===row.end?dateOnly(row.end):dateOnly(row.start)+' → '+dateOnly(row.end),
    ...accountMetrics.map(key=>{
      const value=row.values[key],cell=node('span',value==null?'—':`${value>0?'+':''}${fmt(value,0)}`);
      if(value!=null) {
        const measured=row.observations[key];
        cell.title=`Изменение между ${date(new Date(measured.from).toISOString())} и ${date(new Date(measured.to).toISOString())}`;
      } else cell.title='Недостаточно данных для сравнения';
      return cell;
    })
  ]);
  const wrap=node('div',null,'table-wrap daily-growth-table');wrap.tabIndex=0;
  wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Таблица изменений показателей по датам');
  const grid=table(['Дата',...accountMetrics.map(key=>displayLabels[key])],values);
  grid.prepend(node('caption','Чистое изменение показателей между последними замерами дней','sr-only'));
  wrap.append(grid);root.append(wrap);
  return root;
}
