import {node,put,fmt,metric,labels,provenance,platformMark,dataContext,empty} from './dashboard-core.js';
import {preview} from './dashboard-preview.js';
import {chartGroups,historyPoints} from './dashboard-presentation.js';
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
