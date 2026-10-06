// Presentation only: do not aggregate sources, invent values or alter analytics.
export function sortObservations(rows, order) {
  const byDate = (a, b) => (Date.parse(b.content.published_at) || 0) - (Date.parse(a.content.published_at) || 0);
  if (order !== 'views') return [...rows].sort(byDate);
  const groups = new Map();
  for (const r of rows) {
    const s = r.snapshot || {};
    const context = JSON.stringify([r.content.platform, s.source, s.metric_scope, s.source_period_start, s.source_period_end, s.snapshot_status]);
    if (!groups.has(context)) groups.set(context, []);
    groups.get(context).push(r);
  }
  return [...groups.values()].flatMap(group => [...group].sort((a, b) => {
    const av = a.snapshot?.views, bv = b.snapshot?.views;
    if (av == null) return bv == null ? byDate(a, b) : 1;
    if (bv == null) return -1;
    return Number(bv) - Number(av) || byDate(a, b);
  }));
}
export function exactWindow(p) {
  return p.actual_age_hours != null && p.actual_age_hours === p.requested_age_hours;
}
export function metricAvailability(rows, source, key) {
  const selected = rows.filter(r => !source || r.snapshot?.source === source);
  return { total: selected.length, available: selected.filter(r => (r.derived?.[key] ?? r.snapshot?.[key]) != null).length };
}
export function updateTimes(observations) {
  const times = observations.map(r => r.at).filter(at => at && Number.isFinite(Date.parse(at)));
  const unique = new Set(times.map(Date.parse));
  return {latest: times.sort((a,b)=>Date.parse(b)-Date.parse(a))[0] || null, mixed:unique.size>1, unknown:times.length<observations.length};
}
export function chartGroups(rows) {
  const groups = new Map();
  for (const r of rows) {
    const s=r.snapshot || {};
    const key=JSON.stringify([r.content.platform,s.source,s.metric_scope,s.source_period_start,s.source_period_end,s.snapshot_status]);
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(r);
  }
  return [...groups];
}
export function historyPoints(c, history) {
  return history.flatMap(s=>{
    const age=(Date.parse(s.snapshot_at)-Date.parse(c.published_at))/3600000;
    return s.views != null && ['number','string'].includes(typeof s.views) && Number.isFinite(Number(s.views)) && Number(s.views)>=0 && Number.isFinite(age) && age>=0 ? [{...s,age}] : [];
  });
}

// Account counts compare only the same source, scope, period and quality.
export function accountTrend(history, latest, key="followers") {
  const context = s => JSON.stringify([s.source,s.metric_scope,s.source_period_start,s.source_period_end,s.snapshot_status]);
  if (latest.metric_scope !== 'current') return {points:[],delta:null};
  const byTime = new Map();
  for (const s of history) {
    const t = Date.parse(s.snapshot_at), value=s[key];
    if (context(s)!==context(latest) || !Number.isFinite(t) || value==null ||
        !['number','string'].includes(typeof value) || !Number.isFinite(Number(value)) || Number(value)<0) continue;
    if (!byTime.has(t)) byTime.set(t,{...s,[key]:Number(value)});
    else if (byTime.get(t)?.[key]!==Number(value)) byTime.set(t,null);
  }
  const points=[...byTime.values()].filter(Boolean).sort((a,b)=>Date.parse(a.snapshot_at)-Date.parse(b.snapshot_at));
  const last=points.at(-1);
  const delta=points.length>1 && latest[key]!=null && last &&
    Date.parse(last.snapshot_at)===Date.parse(latest.snapshot_at) ? last[key]-points[0][key] : null;
  return {points,delta};
}

// Calendar weeks use the viewer's timezone, including DST and year boundaries.
export function accountWeeks(points, timeZone, now = new Date(), key = "followers") {
  if (!points.length) return [];
  const day = 86400000;
  const calendar = new Intl.DateTimeFormat('en-US', {timeZone, year:'numeric', month:'numeric', day:'numeric'});
  const localDay = value => {
    const parts=Object.fromEntries(calendar.formatToParts(new Date(value)).map(p=>[p.type,p.value]));
    return Date.UTC(Number(parts.year),Number(parts.month)-1,Number(parts.day));
  };
  const monday = date => date - ((new Date(date).getUTCDay()+6)%7)*day;
  const grouped=new Map();
  const ordered=[...points].sort((a,b)=>Date.parse(a.snapshot_at)-Date.parse(b.snapshot_at));
  const previous=new Map(ordered.slice(1).map((point,index)=>[point,ordered[index]]));
  for (const point of ordered) {
    const start=monday(localDay(point.snapshot_at));
    if (!grouped.has(start) || Date.parse(grouped.get(start).snapshot_at)<Date.parse(point.snapshot_at)) grouped.set(start,point);
  }
  const starts=[...grouped.keys()], current=monday(localDay(now));
  const weeks=[];
  for (let start=Math.min(...starts);start<=Math.max(...starts);start+=7*day) {
    const snapshot=grouped.get(start),before=previous.get(snapshot);
    weeks.push({start:new Date(start).toISOString().slice(0,10),end:new Date(start+6*day).toISOString().slice(0,10),value:snapshot?.[key]??null,snapshot:snapshot??null,current:start===current,change:before?{delta:snapshot[key]-before[key],from:before.snapshot_at,to:snapshot.snapshot_at}:null});
  }
  return weeks;
}

// One visible account summary; retain distinct sources and periods in disclosure.
export function accountOverview(history, platform) {
  const latest=new Map();
  const context=s=>JSON.stringify([s.source,s.metric_scope,s.source_period_start,s.source_period_end,s.snapshot_status]);
  for (const snapshot of [...history].filter(s=>Number.isFinite(Date.parse(s.snapshot_at))).sort((a,b)=>Date.parse(a.snapshot_at)-Date.parse(b.snapshot_at))) latest.set(context(snapshot),snapshot);
  const rows=[...latest.values()].sort((a,b)=>Date.parse(b.snapshot_at)-Date.parse(a.snapshot_at));
  const current=rows.filter(s=>s.metric_scope==='current');
  const primary=current.find(s=>s.source===platform+'_api')??current[0]??null;
  return {primary,additional:rows.filter(s=>s!==primary)};
}
