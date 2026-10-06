import {
  $,
  dataContext,
  setViewNotes,
  renderViewNotes,
  collectionMark,
  platformMark,
  state,
  sources,
  labels,
  statuses,
  node,
  put,
  empty,
  fmt,
  metric,
  date,
  utc,
  period,
  briefPeriod,
  status,
  provenance,
  message,
  showLogin,
  api,
  button,
  table,
  card,
  title,
  query,
  filterMap,
  all,
  activeContent,
  submit,
} from "./dashboard-core.js";
import { accountTimeline, accountDailyTable, publicationBars } from "./dashboard-charts.js";
import { sortObservations, publicationSelection, updateTimes, accountOverview, accountPeriodInsights, accountMetrics, comparisonFormat, comparisonSelection } from "./dashboard-presentation.js";
import { updateMetricAvailability } from "./dashboard-forms.js";
import { setupReports } from "./dashboard-reports.js";
import { preview, setupPreview } from "./dashboard-preview.js";
import { openDetail } from "./dashboard-detail.js";
import {
  setupForms,
  prepareObservation,
  renderExperiments,
  renderManualMeasurements,
} from "./dashboard-forms.js";
const headings = {
  overview: "Обзор аккаунтов",
  content: "Аналитика публикаций",
  comparison: "Сравнение публикаций",
  import: "Наблюдения",
  experiments: "Гипотезы",
  detail: "История публикации",
};
export function view(name) {
  state.view = name;
  renderViewNotes();
  document
    .querySelectorAll(".view")
    .forEach((el) => (el.hidden = el.id !== "view-" + name));
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => {
      b.classList.toggle("active", b.dataset.view === (name === "detail" ? "content" : name));
      if (b.dataset.view === (name === "detail" ? "content" : name)) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
  $("page-title").textContent = headings[name];
  $("filter-disclosure").hidden = ["overview", "detail", "import", "experiments", "comparison"].includes(name);
  $("active-filters").hidden = name !== "content";
  if (state.comparison) renderUpdateInfo();
  $("main-content").focus();
}
document.querySelectorAll("[data-entry-mode]").forEach((el) => {
  el.replaceChildren(collectionMark(el.dataset.entryMode));
});
document
  .querySelectorAll("[data-view]")
  .forEach((b) => b.addEventListener("click", () => view(b.dataset.view)));
$("detail-back").addEventListener("click", () => view("content"));
function contentLink(c) {
  const b = button(
    title(c),
    async () => {
      await openDetail(c.id);
      view("detail");
      $("detail-title").focus();
    },
    "title-link",
  );
  b.title = title(c);
  return b;
}
async function overview() {
  const selected = state.accounts;
  const histories = await Promise.all(
    selected.map(async (a) => [a, await all(`/accounts/${a.id}/history`)]),
  );
  state.manualAccountRows = histories.flatMap(([account, rows]) => rows.filter(s => ["instagram_ui", "tiktok_studio", "manual"].includes(s.source)).map(snapshot => ({account, snapshot})));
  const cards = [], changes = [];
  state.accountMeasurements = [];
  for (const [a, history] of histories) {
    const {primary:s}=accountOverview(history,a.platform);
    for (const snapshot of [s,...accountPeriodInsights(history,a.platform+'_api')].filter(Boolean)) state.accountMeasurements.push({platform:a.platform,at:snapshot.snapshot_at});
    const accountCard = s ? card(platformContext(a.platform, `@${a.username}`), s,
      accountMetrics.filter(key=>key==='followers'||s[key]!=null).map(key=>[labels[key],fmt(s[key])]),
      true) : node('article',null,'observation-card');
    if(s) {
      const header=node('div',null,'account-summary');
      header.append(accountCard.querySelector('.card-heading'),accountCard.querySelector('.metric-strip'));
      accountCard.prepend(header);
      accountCard.append(accountTimeline(history,s));
    }
    else accountCard.append(platformContext(a.platform,`@${a.username}`),empty('Нет текущих показателей аккаунта'));
    const accountChanges=accountDailyTable(history,s,a.platform+'_api',platformContext(a.platform,`@${a.username}`));
    if(accountChanges) changes.push(accountChanges);
    cards.push(accountCard);
  }
  put(
    "account-cards",
    ...(cards.length
      ? cards
      : [
          empty(
            "Аккаунт пока не измерен",
            "Запустите сбор или добавьте наблюдение.",
          ),
        ]),
  );
  setViewNotes("overview", histories.flatMap(([a,history])=>{
    const primary=accountOverview(history,a.platform).primary;
    return [primary,...accountPeriodInsights(history,a.platform+'_api')].filter(Boolean).map(snapshot=>({name:(a.platform==="tiktok"?"TikTok":"Instagram")+" @"+a.username,snapshot}));
  }), ["На недельном графике — последний сохранённый замер каждой недели. Прочерк означает отсутствие данных; 0 — измеренное нулевое значение."]);
  put("account-changes",...changes);
  $("account-changes-section").hidden = !changes.length;
  const [health, runs] = await Promise.all([
    api("/collectors/status"),
    api("/collectors/runs?limit=100"),
  ]);
  const collectors = ["instagram", "tiktok"].map((p) => {
    const c = node("article", null, "collector-card"),
      h = node("div", null, "card-heading"),
      ready = state.config[p + "_ready"],
      s = health[p];
    h.append(
      platformMark(p),
      status(s.last_status),
    );
    c.append(
      h,
      node(
        "p",
        ready
          ? "Авторизация настроена."
          : "Не подключён: требуется авторизация аккаунта.",
        "collector-meta",
      ),
      node(
        "p",
        `Последний успешный сбор: ${date(s.last_success_at)}`,
        "card-provenance",
      ),
    );
    if (s.last_error_type)
      c.append(
        node(
          "p",
          "Тип последней ошибки: " + s.last_error_type,
          "card-provenance",
        ),
      );
    const actions = node("div", null, "collector-actions");
    for (const dry of [true, false]) {
      const b = button(
        dry ? "Проверить доступ без сохранения" : "Собрать наблюдения",
        async () => {
          const result = await api(`/collectors/${p}/run`, {
            method: "POST",
            body: JSON.stringify({ run_id: crypto.randomUUID(), dry_run: dry }),
          });
          message(
            "global-message",
            `${p}: ${statusesText(result.status)}; новых наблюдений: ${fmt(result.content_snapshots)}.`,
          );
          await refresh();
          message(
            "global-message",
            `${p}: ${statusesText(result.status)}; наблюдений: ${fmt(result.content_snapshots)}.`,
          );
        },
      );
      b.disabled = !ready;
      actions.append(b);
    }
    c.append(actions);
    return c;
  });
  put("collector-cards", ...collectors);
  $("schedule-status").textContent = state.config.scheduler_configured
    ? "Расписание настроено. История показывает завершённые запуски; активность процесса здесь не проверяется."
    : "Автоматическое расписание выключено.";
  const runRows = runs.map((r) => {
    const tr = node("tr");
    [
      platformContext(r.platform, r.id),
      date(r.started_at),
      status(r.status),
      fmt(r.summary.content_snapshots),
      fmt(r.summary.schedule?.attempts),
    ].forEach((v) => {
      const td = node("td");
      td.append(v instanceof Node ? v : document.createTextNode(v));
      tr.append(td);
    });
    return tr;
  });
  if (!runRows.length) {
    const tr = node("tr"),
      td = node("td", "Запусков пока нет");
    td.colSpan = 5;
    tr.append(td);
    runRows.push(tr);
  }
  put("run-rows", ...runRows);
  state.collectionHealth = health;
}
const statusesText = (s) =>
  ({
    success: "успешно",
    partial: "частично",
    failed: "ошибка",
    dry_run: "проверка без сохранения",
  })[s] ||
  s ||
  "завершено";
async function contentAndComparison() {
  const data = await api("/analytics/content-comparison?" + query());
  state.comparison = data;
  state.selection = activeContent();
  state.appliedFilters = [...query()].filter(([k]) => !["limit", "group_by"].includes(k));
  renderContent();
  updateMetricAvailability();
  renderComparison();
}
const contentKeys = ["views", "unique_viewers", "watch_time_avg_seconds", "average_watch_pct", "completion_rate", "likes", "shares", "saves", "comments", "profile_visits", "followers_gained"];
function selectionEmpty() {
  if (state.appliedFilters?.length) {
    const names = {platform:"Платформа",source:"Источник",date_from:"С",date_to:"По",series:"Серия",topic:"Тема",hook_type:"Тип хука",format:"Формат",cta_type:"CTA",content_pillar:"Контент-пиллар"};
    const e = empty("По этим фильтрам публикаций не найдено", state.appliedFilters.map(([k,v]) => `${names[k] || k}: ${sources[v] || v}`).join(" · "));
    e.append(button("Сбросить фильтры", resetFilters));
    return e;
  }
  const connected = state.accounts.length || state.config.instagram_ready || state.config.tiktok_ready;
  return connected
    ? empty("Публикаций пока нет", "Запустите сбор данных.")
    : empty("Аккаунт ещё не подключён", "Подключите аккаунт для сбора данных.");
}
function entries() {
  const rows = [...(state.comparison?.rows || [])];
  if (!state.appliedFilters?.some(([k]) => k === "source")) {
    const seen = new Set(rows.map(r => r.content.id));
    for (const c of state.selection || []) if (!seen.has(c.id)) rows.push({content:c,snapshot:null,derived:{}});
  }
  const source = state.appliedFilters?.find(([k]) => k === "source")?.[1] || "";
  const key = $("content-display").value === "chart" ? $("content-chart-metric").value : "views";
  return sortObservations(publicationSelection(rows, {source, key}), $("content-sort").value);
}
function platformContext(platform, text) {
  const context = node("span", null, "platform-context");
  context.append(platformMark(platform), node("span", text));
  return context;
}
function publicationCard(r, availableOnly = false) {
  const c = r.content, s = r.snapshot;
  const box = node("article", null, "publication-card"), head = node("div", null, "publication-heading"), text = node("div");
  text.append(contentLink(c), platformContext(c.platform, date(c.published_at)));
  head.append(preview(c), text);
  box.append(head);
  if (!s) { box.append(node("p", "Наблюдений пока нет в этой выборке", "muted")); return box; }
  const keys = ["views", "likes", "shares"].filter(k => !availableOnly || s[k] != null);
  const values = node("div", null, "metric-strip");
  for (const k of keys) { const m = node("div"); m.append(node("strong", fmt(s[k]), "metric-value"), node("span", labels[k], "metric-label")); values.append(m); }
  box.append(values, dataContext(s, true));
  if (!keys.length) box.append(node("p", "Показатели в этом наблюдении недоступны", "muted"));
  return box;
}
function renderContent() {
  const rows = entries();
  setViewNotes("content", rows.filter(r=>r.snapshot).map(r=>({name:title(r.content),snapshot:r.snapshot})), ["Прочерк означает отсутствие данных; 0 — измеренное нулевое значение."]);
  $("sort-help").hidden = $("content-sort").value !== "views";
  const chart = $("content-display").value === "chart";
  $("chart-metric-control").hidden = !chart;
  $("publication-chart").hidden = !chart;
  $("content-cards").hidden = chart;
  $("content-table").hidden = chart;
  if (chart) put("publication-chart", publicationBars(rows, $("content-chart-metric").value, contentLink));
  const constraints = state.appliedFilters || [];
  $("filter-summary").textContent = constraints.length ? `Фильтры: ${constraints.length} ограничений` : "Фильтры: все платформы · любые даты";
  $("active-filters").replaceChildren(...(constraints.length ? [node("span", constraints.map(([k,v])=>`${({platform:"Платформа",source:"Источник",date_from:"С",date_to:"По",series:"Серия",topic:"Тема",hook_type:"Хук"})[k]||k}: ${sources[v]||v}`).join(" · ")),button("Сбросить",resetFilters)] : []));
  put("content-cards", ...(rows.length ? rows.map(r => publicationCard(r)) : [selectionEmpty()]));
  function contentTable(keys, compact = false) {
    if (compact && rows.length) {
      const grid=table(["Фото", "Публикация", "Источник", ...keys.map(k=>labels[k])], rows.map(r=>{
        const cell=node("div",null,"title-cell"), context=node("div",null,"publication-source"), s=r.snapshot;
        cell.append(contentLink(r.content),platformContext(r.content.platform,date(r.content.published_at)));
        if(s) {
          context.append(node("span",sources[s.source] || s.source));
          if(s.metric_scope!=="lifetime") context.append(node("span",briefPeriod(s),"cell-note"));
          context.append(dataContext(s));
        } else context.append(node("span","Нет наблюдений","muted"));
        return [preview(r.content),cell,context,...keys.map(k=>metric(r.derived?.[k] ?? s?.[k],k))];
      }));
      return grid;
    }
    return rows.length ? table(["Фото", compact ? "Публикация" : "Публикация / источник", ...keys.map(k => labels[k])], rows.map(r => {
      const cell = node("div", null, "title-cell"), s = r.snapshot;
      cell.append(contentLink(r.content), platformContext(r.content.platform, date(r.content.published_at)));
      if (s) {
        if (compact) cell.append(dataContext(s, state.comparison.rows.filter(row=>row.content.id===r.content.id).length > 1));
        else cell.append(node("span", provenance(s), "cell-note"), status(s.snapshot_status));
      }
      else cell.append(node("span", "Наблюдений пока нет", "cell-note"));
      return [preview(r.content), cell, ...keys.map(k => metric(r.derived?.[k] ?? s?.[k], k))];
    })) : selectionEmpty();
  }
  put("content-table", contentTable(["views", "likes", "shares"], true));
  put("content-full-table", contentTable(contentKeys));
  $("content-count").textContent = `${rows.length} публикаций${state.comparison.truncated ? " · выборка ограничена 1000; сузьте фильтры" : ""}`;

}
function renderUpdateInfo() {
  const rows = [...(state.accountMeasurements || []), ...state.comparison.rows.map(r=>({platform:r.content.platform,at:r.snapshot.snapshot_at}))];
  const times = updateTimes(rows), info = node("details", null, "update-details");
  info.append(node("summary", "Обновление по платформам"),node("p",`Часовой пояс: ${state.config.display_timezone}`,"muted"));
  if (times.unknown) info.append(node("p", "Для части данных время обновления неизвестно.", "muted"));
  const platforms = [...new Set(rows.map(r=>r.platform))];
  for (const p of platforms) {
    const measured = updateTimes(rows.filter(r=>r.platform===p));
    const health = state.collectionHealth?.[p];
    info.append(platformContext(p, `Измерение: ${date(measured.latest)} · Успешный сбор: ${date(health?.last_success_at)}`));
  }
  const warnings = Object.entries(state.collectionHealth || {}).filter(([p])=>state.view === "overview" || !$("filter-platform").value || p===$("filter-platform").value).flatMap(([p,s]) => s.last_status === "failed" || s.last_status === "partial" ? [platformContext(p,s.last_status === "failed" ? "Последний сбор завершился с ошибкой; показаны сохранённые данные" : "Последний сбор неполный; часть показателей могла не обновиться")] : []);
  put("last-update", node("p", times.latest ? `Последнее обновление данных: ${date(times.latest)}` : "Время обновления пока неизвестно", "muted"), ...warnings, ...(platforms.length ? [info] : []));
}
function renderComparison() {
  const data=state.allComparisonData;
  if(!data) return;
  const rows=data.rows, platforms=[...new Set(rows.map(r=>r.content.platform))];
  if(!platforms.includes(state.comparisonPlatform)) state.comparisonPlatform=platforms.includes("tiktok") ? "tiktok" : platforms[0];
  const platform=state.comparisonPlatform;
  put("comparison-platforms",...platforms.map(p=>{
    const b=button("",()=>{state.comparisonPlatform=p;renderComparison();},"comparison-platform");
    const mark=platformMark(p);mark.tabIndex=-1;b.append(mark);
    b.setAttribute("aria-label",{instagram:"Instagram",tiktok:"TikTok"}[p] || p);
    b.setAttribute("aria-pressed",String(p===platform));
    return b;
  }));
  const selectOptions=(id,values, preferred)=>{
    const control=$(id), before=control.value;
    control.replaceChildren(...values.map(value=>{const option=node("option",sources[value] || value);option.value=value;return option;}));
    control.value=values.includes(before) ? before : preferred || values[0] || "";
    control.disabled=!values.length;
  };
  const platformRows=rows.filter(r=>r.content.platform===platform), availableSources=[...new Set(platformRows.map(r=>r.snapshot.source))];
  const usableCount=source=>comparisonSelection(platformRows,{platform,source,format:$("comparison-format").value || "Короткое видео",key:$("comparison-metric").value}).available;
  const latest=source=>Math.max(0,...platformRows.filter(r=>r.snapshot.source===source).map(r=>Date.parse(r.snapshot.snapshot_at)||0));
  availableSources.sort((a,b)=>usableCount(b)-usableCount(a) || latest(b)-latest(a));
  selectOptions("comparison-source",availableSources);
  const source=$("comparison-source").value;
  const formats=[...new Set(platformRows.filter(r=>r.snapshot.source===source).map(r=>comparisonFormat(r.content)))];
  selectOptions("comparison-format",formats,formats.includes("Короткое видео") ? "Короткое видео" : formats[0]);
  const format=$("comparison-format").value, key=$("comparison-metric").value, groupBy=$("comparison-group").value;
  let from=null,to=null;
  try {
    if($("comparison-from").value) from=Date.parse(utc($("comparison-from").value+"T00:00"));
    if($("comparison-to").value) to=Date.parse(utc($("comparison-to").value+"T23:59"))+59999;
  } catch(e) {put("comparison-cards",empty("Проверьте даты",e.message));return;}
  setViewNotes("comparison");
  put("comparison-context");put("comparison-insight");put("comparison-exclusions");
  if(from!=null && to!=null && from>to) {put("comparison-cards",empty("Начало периода позже окончания", "Измените даты публикаций."));return;}
  const result=comparisonSelection(rows,{platform,source,format,key,groupBy,from,to});
  const measured=result.groups.flatMap(g=>g.rows);
  const measuredTimes=measured.map(r=>Date.parse(r.snapshot.snapshot_at)).filter(Number.isFinite);
  const dates=[...new Set(measuredTimes.length ? [date(Math.min(...measuredTimes)).split(",")[0],date(Math.max(...measuredTimes)).split(",")[0]] : [])];
  const publicationDates=[$("comparison-from").value,$("comparison-to").value];
  document.querySelector(".comparison-dates > summary").textContent=publicationDates.some(Boolean) ? "Публикации: "+(publicationDates[0] || "начало истории")+" — "+(publicationDates[1] || "без верхней границы") : "Период публикаций: все даты";
  $("comparison-context").textContent=`С момента публикации · публикаций: ${measured.length}${dates.length ? " · измерения "+dates.join(" — ") : ""}${result.quality==="estimated" ? " · оценочные значения" : ""}`;
  const skipped=[result.anomalies ? `${result.anomalies} с аномалией` : "",result.periods ? `${result.periods} с другим или неизвестным периодом` : "",result.otherQuality ? `${result.otherQuality} с другим состоянием данных` : ""].filter(Boolean);
  $("comparison-exclusions").textContent=skipped.length ? "Не включены измерения: "+skipped.join("; ") : "";
  if(!result.groups.length) {put("comparison-cards",empty("Нет сопоставимых публикаций", "Выберите другой источник, формат или период."));return;}
  const valued=result.groups.filter(g=>g.n), name=g=>groupBy==="publication" ? title(g.rows[0].content) : g.group || "Без тега";
  if(!valued.length) {put("comparison-cards",empty("По этому показателю нет данных", "Выберите другой показатель или источник."));return;}
  const best=valued[0], tied=valued.filter(g=>g.mean===best.mean);
  const insight=node("section",null,"comparison-insight");
  if(data.truncated) insight.append(node("p","Выборка ограничена 1000 измерениями. Результат по всей истории не определён.","data-warning"));
  else if(valued.length===1) insight.append(node("p","Есть данные только для одной "+(groupBy==="publication" ? "публикации" : "группы")+" — сравнить пока не с чем."));
  else if(tied.length===valued.length) insight.append(node("p",`Значения одинаковые: ${metric(best.mean,key)}. Различий по этому показателю пока нет.`));
  else {
    const lead={views:"Больше просмотров",average_watch_pct:"Выше среднее время просмотра",completion_rate:"Выше досмотр",share_rate:"Выше доля репостов",save_rate:"Выше доля сохранений",profile_visit_rate:"Выше доля переходов в профиль",follow_conversion:"Выше конверсия в подписку"}[key];
    insight.append(node("p",`${lead}${groupBy!=="publication" ? " в среднем" : ""}: «${name(best)}» — ${metric(best.mean,key)}${["completion_rate","average_watch_pct"].includes(key) ? "%" : ""}${tied.length>1 ? "; есть равные результаты" : ""}.`));
  }
  if(key==="views" && groupBy==="publication" && !data.truncated) {
    const retention=comparisonSelection(rows,{platform,source,format,key:"completion_rate",groupBy,from,to}).groups.filter(g=>g.n);
    if(retention.length>1 && retention[0].mean>retention.at(-1).mean) {
      const top=retention[0], leader=retention.find(g=>g.group===best.group);
      const equal=retention.filter(g=>g.mean===top.mean).length;
      insight.append(node("p",`Досмотр выше у «${name(top)}» — ${metric(top.mean,"completion_rate")}%${equal>1 ? " (есть равные результаты)" : ""}.${leader && top.group!==best.group ? " У лидера по просмотрам — "+metric(leader.mean,"completion_rate")+"%." : ""}`));
    }
  }
  const small=groupBy!=="publication" && valued.some(g=>g.n<5);
  setViewNotes("comparison", measured.map(r=>({name:title(r.content),snapshot:r.snapshot})), [small ? "В группах меньше 5 публикаций. Эффективность типа хука или темы ещё не подтверждена." : "Публикации разного возраста. Накопленные результаты не показывают, что именно вызвало разницу."]);

  put("comparison-insight",insight);
  const list=node("ol",null,"comparison-ranking"), maximum=Math.max(...valued.map(g=>g.mean));
  list.setAttribute("aria-label",groupBy==="publication" ? "Результаты публикаций" : "Средние результаты групп");
  for(const g of result.groups) {
    const row=node("li",null,"comparison-row"), head=node("div",null,"comparison-row-heading");
    const label=groupBy==="publication" ? button(name(g),async()=>{await openDetail(g.rows[0].content.id,source);view("detail");$("detail-title").focus();},"comparison-name") : node("strong",name(g));
    head.append(label,node("strong",metric(g.mean,key),"comparison-value"));row.append(head);
    if(groupBy!=="publication") row.append(node("p",`Среднее · ${g.n} из ${g.rows.length} публикаций с данными`,"muted"));
    const track=node("div",null,"comparison-bar-track"), bar=node("div",null,"comparison-bar");
    track.setAttribute("aria-hidden","true");bar.style.width=(g.mean!=null && maximum>0 ? 100*g.mean/maximum : 0)+"%";track.append(bar);row.append(track);
    if(groupBy!=="publication") {
      const details=node("details"), members=node("ul",null,"comparison-members");
      details.append(node("summary",`Публикации (${g.rows.length})`));
      for(const r of g.rows) {const member=node("li");member.append(button(title(r.content),async()=>{await openDetail(r.content.id,source);view("detail");$("detail-title").focus();},"comparison-name"),node("span",metric(r.derived?.[key] ?? r.snapshot[key],key)));if(r.content.hook_text) member.append(node("p",r.content.hook_text,"muted"));members.append(member);}
      details.append(members);row.append(details);
      if(!g.group) row.append(button("Разметить публикации",()=>view("content")));
    }
    list.append(row);
  }
  put("comparison-cards",list);
}
async function refresh() {
  const b = $("refresh");
  b.disabled = true;
  message("global-message", "Загружаю наблюдения…");
  try {
    state.config = { ...(await api("/dashboard/config")), display_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" };
    $("test-banner").hidden = !state.config.test_database;
    [state.accounts, state.content, state.experiments] = await Promise.all([
      all("/accounts"),
      all("/content"),
      all("/experiments"),
    ]);
    const [, , manualData] = await Promise.all([overview(), contentAndComparison(), api("/analytics/content-comparison?limit=1000")]);
    state.allComparisonData=manualData;
    renderComparison();
    renderManualMeasurements(manualData, state.manualAccountRows, async (c, source) => { await openDetail(c.id, source); view("detail"); $("detail-title").focus(); });
    renderUpdateInfo();
    renderExperiments();
    prepareObservation();
    if (state.view === "detail" && state.detail)
      await openDetail(state.detail.id, state.detailSource);
    message(
      "global-message",
      state.comparison.truncated
        ? "Выборка ограничена 1000 наблюдений. Сузьте фильтры перед выводами."
        : "",
    );
  } catch (e) {
    message(
      "global-message",
      "Обновление не завершено. Прежняя выборка может не соответствовать фильтрам. " +
        e.message,
      true,
    );
  } finally {
    b.disabled = false;
  }
}
$("refresh").addEventListener("click", refresh);
$("filters").addEventListener("submit", async (e) => {
  e.preventDefault();
  const params = new URLSearchParams();
  Object.keys(filterMap)
    .concat(["from", "to"])
    .forEach((id) => {
      const v = $("filter-" + id).value;
      if (v) params.set(id, v);
    });
  history.replaceState(
    null,
    "",
    "/dashboard" + (params.size ? "?" + params : ""),
  );
  await refresh();
});
async function resetFilters() {
  $("filters").reset();
  history.replaceState(null, "", "/dashboard");
  await refresh();
}
$("reset-filters").addEventListener("click", resetFilters);
$("content-sort").addEventListener("change", renderContent);
$("content-display").addEventListener("change", renderContent);
$("content-chart-metric").addEventListener("change", renderContent);
const mobileFilters = window.matchMedia("(max-width: 700px)");
$("filter-disclosure").open = false;
mobileFilters.addEventListener("change", e => { if(e.matches) $("filter-disclosure").open = false; });
for(const id of ["comparison-group","comparison-metric","comparison-source","comparison-format","comparison-from","comparison-to"]) $(id).addEventListener("change",renderComparison);
const params = new URLSearchParams(location.search);
Object.keys(filterMap)
  .concat(["from", "to"])
  .forEach((id) => {
    if (params.has(id)) $("filter-" + id).value = params.get(id);
  });
submit($("login-form"), "login-error", async () => {
  const key = $("access-key").value;
  $("access-key").value = "";
  await api("/dashboard/session", {
    method: "POST",
    body: JSON.stringify({
      api_key: key,
      remember_browser: $("remember-browser").checked,
    }),
  });
  $("login").hidden = true;
  $("workspace").hidden = false;
  await refresh();
});
$("logout").addEventListener("click", async () => {
  try {
    await api("/dashboard/logout", { method: "POST" });
    showLogin();
    state.accounts = [];
    state.content = [];
    state.experiments = [];
    state.comparison = null;
    document.querySelectorAll(".view").forEach((el) =>
      el
        .querySelectorAll("table,.observation-card,.experiment-card")
        .forEach((n) => {
          // Keep the static run-history tbody for a subsequent login.
          if (n.querySelector("#run-rows")) $("run-rows").replaceChildren();
          else n.remove();
        }),
    );
  } catch (e) {
    message("global-message", e.message, true);
  }
});
setupPreview();
setupReports();
setupForms(refresh);
view("overview");
(async () => {
  try {
    state.config = { ...(await api("/dashboard/config")), display_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" };
    $("login").hidden = true;
    $("workspace").hidden = false;
    await refresh();
  } catch (e) {
    showLogin();
    if (!e.message.includes("сессия")) message("login-error", e.message, true);
  }
})();
