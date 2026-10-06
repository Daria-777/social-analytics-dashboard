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

// Prefer an API current summary; keep distinct contexts separate.
export function accountOverview(history, platform) {
  const latest=new Map();
  const context=s=>JSON.stringify([s.source,s.metric_scope,s.source_period_start,s.source_period_end,s.snapshot_status]);
  for (const snapshot of [...history].filter(s=>Number.isFinite(Date.parse(s.snapshot_at))).sort((a,b)=>Date.parse(a.snapshot_at)-Date.parse(b.snapshot_at))) latest.set(context(snapshot),snapshot);
  const rows=[...latest.values()].sort((a,b)=>Date.parse(b.snapshot_at)-Date.parse(a.snapshot_at));
  const current=rows.filter(s=>s.metric_scope==='current');
  const primary=current.find(s=>s.source===platform+'_api')??current[0]??null;
  return {primary,additional:rows.filter(s=>s!==primary)};
}

export const accountMetrics=['followers','views','unique_viewers','profile_views','new_viewers'];

// Day-end observations, never gross follows/unfollows or interpolated daily events.
export function accountDailyChanges(history, latest, timeZone) {
  if(latest.metric_scope!=='current') return [];
  const context=s=>JSON.stringify([s.source,s.metric_scope,s.source_period_start,s.source_period_end,s.snapshot_status]);
  const calendar=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'});
  const localDay=value=>{
    const parts=Object.fromEntries(calendar.formatToParts(new Date(value)).map(p=>[p.type,p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const valid=value=>value!=null&&['number','string'].includes(typeof value)&&String(value).trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;
  const moments=new Map();
  for(const s of history) {
    const at=Date.parse(s.snapshot_at);
    if(context(s)!==context(latest)||!Number.isFinite(at)) continue;
    if(!moments.has(at)) moments.set(at,{at,values:Object.fromEntries(accountMetrics.map(key=>[key,valid(s[key])]))});
    else for(const key of accountMetrics) if(moments.get(at).values[key]!==valid(s[key])) moments.get(at).values[key]=null;
  }
  const days=new Map();
  for(const point of [...moments.values()].sort((a,b)=>a.at-b.at)) days.set(localDay(point.at),point);
  const rows=new Map(),previous=new Map();
  const nextDay=value=>new Date(Date.parse(value+'T12:00:00Z')+86400000).toISOString().slice(0,10);
  for(const [day,point] of days) {
    let changed=false;
    for(const key of accountMetrics) {
      const value=point.values[key],before=previous.get(key);
      if(value!=null&&before) {
        const start=nextDay(before.day)===day?day:before.day,end=day,id=start+'/'+end;
        if(!rows.has(id)) rows.set(id,{start,end,values:{},observations:{}});
        rows.get(id).values[key]=value-before.value;
        rows.get(id).observations[key]={from:before.at,to:point.at};
        changed=true;
      }
      if(value!=null) previous.set(key,{day,value,at:point.at});
    }
    if(!changed) rows.set(day+'/'+day,{start:day,end:day,values:{},observations:{}});
  }
  return [...rows.values()].sort((a,b)=>b.end.localeCompare(a.end)||b.start.localeCompare(a.start));
}

// Actual period totals, never differences of cumulative counters or cross-source sums.
export const accountPeriodMetrics=['views','likes','comments','shares','saves','unique_viewers','profile_views','new_viewers'];
export function accountPeriodInsights(history, source) {
  const latest=new Map();
  for(const row of history) {
    const start=Date.parse(row.source_period_start),end=Date.parse(row.source_period_end),at=Date.parse(row.snapshot_at);
    if(row.source!==source||row.metric_scope!=='range'||![start,end,at].every(Number.isFinite)||end<=start) continue;
    if(!accountPeriodMetrics.some(key=>row[key]!=null&&String(row[key]).trim()!==''&&Number.isFinite(Number(row[key]))&&Number(row[key])>=0)) continue;
    const context=JSON.stringify([start,end,row.snapshot_status]);
    if(!latest.has(context)||at>Date.parse(latest.get(context).snapshot_at)) latest.set(context,row);
  }
  return [...latest.values()].sort((a,b)=>Date.parse(b.source_period_end)-Date.parse(a.source_period_end)||Date.parse(b.snapshot_at)-Date.parse(a.snapshot_at));
}

// Label one requested UTC reporting day, including exclusive and inclusive end bounds.
export function accountPeriodDay(row) {
  const start=Date.parse(row.source_period_start),end=Date.parse(row.source_period_end);
  if(!Number.isFinite(start)||!Number.isFinite(end)||start%86400000!==0||![86399000,86400000].includes(end-start)) return null;
  return new Date(start).toISOString().slice(0,10);
}

// Align account observations and provider day totals on the same UTC calendar.
// Multi-day differences and non-daily reporting periods remain separate interval rows.
export function accountDailyMetrics(history, latest, source) {
  const rows=latest?accountDailyChanges(history,latest,'UTC')
    .filter(row=>row.values.followers!=null||!Object.keys(row.values).length)
    .map(row=>({...row,activity:null,daily:true})):[];
  for(const activity of accountPeriodInsights(history,source)) {
    const day=accountPeriodDay(activity);
    const existing=day&&rows.find(row=>row.daily&&row.start===day&&row.end===day&&!row.activity);
    if(existing) existing.activity=activity;
    else rows.push({start:day??new Date(activity.source_period_start).toISOString().slice(0,10),end:day??new Date(activity.source_period_end).toISOString().slice(0,10),values:{},observations:{},activity,daily:day!=null});
  }
  return rows.sort((a,b)=>b.end.localeCompare(a.end)||b.start.localeCompare(a.start));
}


// Pick a whole observation per publication; never combine metrics from different sources.
export function publicationSelection(rows, {source="", key="views"} = {}) {
  const selected = new Map();
  const rank = r => {
    const s = r.snapshot;
    if (!s) return [1, 1, 1, 1, 3, 0];
    const value = r.derived?.[key] ?? s[key];
    const known = value != null && ["number", "string"].includes(typeof value) && String(value).trim() && Number.isFinite(Number(value));
    return [
      ["confirmed", "manual", "estimated"].includes(s.snapshot_status) ? 0 : 1,
      s.metric_scope === "lifetime" && !s.source_period_start && !s.source_period_end ? 0 : 1,
      known ? 0 : 1,
      ["instagram_api", "tiktok_api"].includes(s.source) ? 0 : 1,
      ({confirmed:0, manual:1, estimated:2})[s.snapshot_status] ?? 3,
      -(Date.parse(s.snapshot_at) || 0),
    ];
  };
  const compare = (a, b) => {
    const left = rank(a), right = rank(b);
    for (let i = 0; i < left.length; i++) if (left[i] !== right[i]) return left[i] - right[i];
    return 0;
  };
  for (const row of rows) {
    if (source && row.snapshot?.source !== source) continue;
    const previous = selected.get(row.content.id);
    if (!previous || compare(row, previous) < 0) selected.set(row.content.id, row);
  }
  return [...selected.values()];
}

// A comparison is one platform/source/format and one quality level, never a union of sources.
export function comparisonFormat(content) {
  return content.format || ({reel:"Короткое видео",video:"Короткое видео",carousel:"Карусель",photo:"Фото",story:"История"})[content.content_type] || "Не указан";
}
export function comparisonSelection(rows, {platform, source, format, key, groupBy="publication", from=null, to=null}) {
  const selected=rows.filter(r=>r.content.platform===platform && r.snapshot.source===source && comparisonFormat(r.content)===format &&
    (from==null || Date.parse(r.content.published_at)>=from) && (to==null || Date.parse(r.content.published_at)<=to));
  const latest=new Map();
  let periods=0;
  for(const r of selected) {
    const s=r.snapshot;
    if(s.metric_scope!=="lifetime" || s.source_period_start || s.source_period_end) {periods++; continue;}
    if(!latest.has(r.content.id) || Date.parse(s.snapshot_at)>Date.parse(latest.get(r.content.id).snapshot.snapshot_at)) latest.set(r.content.id,r);
  }
  const candidates=[...latest.values()];
  const quality=["confirmed","manual","estimated"].find(status=>candidates.some(r=>r.snapshot.snapshot_status===status));
  const excluded=candidates.filter(r=>r.snapshot.snapshot_status!==quality);
  const groups=new Map();
  for(const r of candidates.filter(r=>r.snapshot.snapshot_status===quality)) {
    const group=groupBy==="publication" ? r.content.id : r.content[groupBy] || null;
    if(!groups.has(group)) groups.set(group,{group,rows:[],values:[]});
    const g=groups.get(group), value=r.derived?.[key] ?? r.snapshot[key];
    g.rows.push(r);
    if(value!=null && ["number","string"].includes(typeof value) && String(value).trim() && Number.isFinite(Number(value))) g.values.push(Number(value));
  }
  const results=[...groups.values()].map(g=>({...g,n:g.values.length,mean:g.values.length ? g.values.reduce((a,b)=>a+b,0)/g.values.length : null}));
  results.sort((a,b)=>a.mean==null ? b.mean==null ? 0 : 1 : b.mean==null ? -1 : b.mean-a.mean);
  return {groups:results,quality,periods,anomalies:excluded.filter(r=>r.snapshot.snapshot_status==="anomalous").length,otherQuality:excluded.filter(r=>r.snapshot.snapshot_status!=="anomalous").length,total:candidates.length,available:results.reduce((n,g)=>n+g.n,0)};
}
