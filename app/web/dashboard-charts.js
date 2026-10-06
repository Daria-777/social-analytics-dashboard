import {node,put,fmt,metric,date,labels,provenance,platformMark,dataContext,empty,state,table} from './dashboard-core.js';
import {preview} from './dashboard-preview.js';
import {chartGroups,historyPoints,accountTrend,accountWeeks,accountMetrics,accountPeriodMetrics,accountDailyMetrics} from './dashboard-presentation.js';
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
  const keys=accountMetrics.filter(key=>key==='followers'||accountTrend(history,latest,key).points.length);
  const select=node('select'),label=node('label',null,'account-metric-select');
  label.append(node('span','Показатель','sr-only'),select);
  const displayLabels={...labels,profile_views:'Просмотры профиля',new_viewers:'Новые зрители'};
  for (const key of keys) {
    const option=node('option',displayLabels[key]); option.value=key;
    option.disabled=key!=='followers'&&!accountTrend(history,latest,key).points.length;
    select.append(option);
  }
  const chart=node('div',null,'account-week-chart');root.append(label,chart);
  let pageSize=4,renderPage=()=>{};
  const calendarDate=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC',dateStyle:'short'}).format(new Date(value+'T12:00:00Z'));
  function render() {
    const key=select.value,{points}=accountTrend(history,latest,key);
    chart.replaceChildren();
    if (!points.length) {chart.append(node('p','Нет сохранённых замеров','muted'));renderPage=()=>{};return;}
    const weeks=accountWeeks(points,state.config.display_timezone,new Date(),key);
    let end=weeks.length;
    const scroll=node('div',null,'account-week-scroll');scroll.tabIndex=0;
    scroll.setAttribute('role','region');scroll.setAttribute('aria-label',`${displayLabels[key]} по неделям`);
    const list=node('ol',null,'account-weeks');
    const max=Math.max(1,...weeks.map(w=>w.value??0));
    const nav=node('div',null,'account-week-navigation');
    const previous=node('button',null,'outlined week-page-button'),next=node('button',null,'outlined week-page-button');
    previous.type=next.type='button';
    previous.setAttribute('aria-label','Предыдущие недели');next.setAttribute('aria-label','Следующие недели');
    for (const [button,path] of [[previous,'M12 5 7 10l5 5'],[next,'m8 5 5 5-5 5']]) {
      const icon=svgNode('svg',{viewBox:'0 0 20 20','aria-hidden':'true',fill:'none',stroke:'currentColor','stroke-width':1.6,'stroke-linecap':'round','stroke-linejoin':'round'});
      icon.append(svgNode('path',{d:path}));button.append(icon);
    }
    const range=node('span',null,'week-page-range');range.setAttribute('aria-live','polite');
    nav.append(previous,range,next);scroll.append(list);chart.append(scroll,nav);
    renderPage=()=>{
      const start=Math.max(0,end-pageSize),visible=weeks.slice(start,end);
      list.replaceChildren();list.style.setProperty('--visible-weeks',visible.length);
      for (const week of visible) {
        const column=node('li',null,'account-week');
        column.append(node('strong',week.value==null?'—':fmt(week.value,0),'account-week-value'));
        const svg=svgNode('svg',{viewBox:'0 0 64 144','aria-hidden':'true',class:'account-week-bar'});
        svg.append(svgNode('line',{x1:0,x2:64,y1:140,y2:140,stroke:'#dce2d8'}));
        if (week.value!=null) {
          const height=week.value/max*132;
          svg.append(svgNode('rect',{x:10,y:140-height,width:44,height,rx:3,fill:colors[0]}));
        }
        column.append(svg,node('span',calendarDate(week.start)+' –','week-date'),node('span',calendarDate(week.end),'week-date'));
        column.append(node('span',week.value==null?'Нет данных':week.current?'Эта неделя':'','week-note'));
        list.append(column);
      }
      nav.hidden=weeks.length<=pageSize;
      previous.disabled=start===0;next.disabled=end===weeks.length;
      range.textContent=`Недели ${start+1}–${end} из ${weeks.length}`;
    };
    const move=direction=>{
      if(direction<0&&end>pageSize) end=Math.max(1,end-pageSize);
      else if(direction>0&&end<weeks.length) end=Math.min(weeks.length,end+pageSize);
      renderPage();
    };
    previous.addEventListener('click',()=>move(-1));next.addEventListener('click',()=>move(1));
    scroll.addEventListener('keydown',e=>{
      if(e.key==='ArrowLeft'||e.key==='ArrowRight') {e.preventDefault();move(e.key==='ArrowLeft'?-1:1);}
    });
    renderPage();
    if (weeks.length===1) chart.append(node('p','Пока данные только за одну неделю','muted'));
  }
  select.addEventListener('change',render);render();
  // Fit readable date columns rather than growing the card with every new week.
  const observer=new ResizeObserver(([entry])=>{
    if(!root.isConnected) {observer.disconnect();return;}
    const size=Math.max(2,Math.min(4,Math.floor((entry.contentRect.width+8)/96)));
    if(size!==pageSize) {pageSize=size;renderPage();}
  });
  observer.observe(root);
  return root;
}


export function accountDailyTable(history,latest,source,accountTitle) {
  const rows=accountDailyMetrics(history,latest,source);
  if(!rows.length) return null;
  const root=node('section',null,'account-daily-metrics');
  const heading=node('h3');heading.append(accountTitle);root.append(heading);
  const keys=accountPeriodMetrics.filter(key=>rows.some(row=>row.activity?.[key]!=null));
  const daily=rows.every(row=>!row.activity||row.daily);
  const dateOnly=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC',dateStyle:'short'}).format(new Date(value+'T12:00:00Z'));
  const values=rows.map(row=>{
    const delta=row.values.followers;
    const change=node('span',delta==null?'Нет сравнения':`${delta>0?'+':''}${fmt(delta,0)}`,delta==null?'muted':null);
    let dates=row.start===row.end?dateOnly(row.end):dateOnly(row.start)+' → '+dateOnly(row.end);
    if(!row.daily) dates='Период: '+dates;
    return [dates,change,...keys.map(key=>row.activity?.[key]==null?node('span','Нет данных','muted'):fmt(row.activity[key],0))];
  });
  const wrap=node('div',null,'table-wrap daily-metrics-table');wrap.tabIndex=0;
  wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Динамика показателей по дням');
  const grid=table(['Дата','Изменение подписчиков',...keys.map(key=>labels[key]+(daily?' за день':' за период'))],values);
  const columns=node('colgroup');
  for(let i=0;i<2+keys.length;i++) columns.append(node('col'));
  grid.prepend(columns);
  grid.style.setProperty('--daily-metric-count',String(keys.length));
  grid.prepend(node('caption','Изменение подписчиков между замерами и просмотры/реакции за указанные сутки UTC. Интервалы пропусков не разделяются на дни.','sr-only'));
  wrap.append(grid);root.append(wrap);
  if(source==='tiktok_api'&&!keys.length) root.append(node('p','Дневные просмотры и реакции TikTok не поступают. Статистика видео — в «Публикациях».','muted'));
  return root;
}
