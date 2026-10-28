import {node,put,date,empty} from './dashboard-core.js';
const verdicts={SUPPORTED:'Поддержана',PARTIALLY_SUPPORTED:'Частично поддержана',NOT_SUPPORTED:'Не поддержана',INCONCLUSIVE:'Недостаточно данных'};
const confidence={LOW:'низкая',MEDIUM:'средняя',HIGH:'высокая'};
function paragraph(label,value){const p=node('p');p.append(node('strong',label+' '),node('span',value??'—'));return p;}
export function renderGrowth(rows){
  if(!rows.length){put('detail-growth',empty('Анализ пока не добавлен','Growth Analyst сохранит здесь вывод, доказательства и следующий тест. Отсутствие анализа не означает плохой результат.'));return;}
  const fragments=rows.map((r,index)=>{
    const box=node('details',null,'history-box');box.open=index===0;
    const p=r.provenance;
    box.append(node('summary',`${date(r.analysis_snapshot_at)} · ${verdicts[r.hypothesis_status]||r.hypothesis_status} · уверенность ${confidence[r.confidence]||r.confidence}`));
    const hypotheses=(p.experiments||[]).map(e=>`${e.experiment.hypothesis||e.experiment.name} · метрика: ${e.experiment.metric||'—'} · вариант: ${e.variant||'—'}`).join('; ');
    box.append(paragraph('Гипотеза:',hypotheses||'Не зафиксирована'),paragraph('Вывод:',r.diagnosis),paragraph('Качество данных:',r.data_quality),paragraph('Что узнали:',r.learning));
    const next=r.next_experiment;
    box.append(paragraph('Сохраняем:',next.keep),paragraph('Меняем:',next.change),paragraph('Основная метрика:',next.primary_metric),paragraph('Признак успеха:',next.success_signal));
    const evidence=node('details');evidence.append(node('summary','Доказательства и план проверки'));
    for(const [label,values] of [['Поддерживают',r.supporting_evidence],['Противоречат',r.contrary_evidence],['Не хватает',r.missing_data],['Другие объяснения',r.competing_explanations]])evidence.append(paragraph(label+':',values.join('; ')||'Не указано'));
    evidence.append(paragraph('Почему:',next.why),paragraph('Как измеряем:',next.measurement_plan),paragraph('После теста:',next.decision_after_test),paragraph('Сценаристу:',r.scenarist_learning_brief),paragraph('Визуальному режиссёру:',r.visual_learning_brief));
    evidence.append(paragraph('Источники:',p.sources.join(', ')),paragraph('Последнее измерение:',date(p.last_observed_at)),paragraph('Данные до:',date(r.data_cutoff_at)),paragraph('Версия агента:',r.agent_version),paragraph('Сохранено:',date(r.created_at)));
    const ages=p.snapshots.map(s=>s.publication_age_hours).filter(a=>a!=null);
    if(ages.length)evidence.append(paragraph('Фактический возраст наблюдений:',ages.map(a=>`${Number(a).toFixed(1)} ч.`).join(', ')));
    evidence.append(paragraph('ID наблюдений:',[...p.snapshots,...p.retention].map(s=>s.id).join(', ')));
    box.append(evidence);return box;
  });
  put('detail-growth',...fragments);
}
