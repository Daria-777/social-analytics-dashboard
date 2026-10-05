import {
  $,
  dataContext,
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
  period,
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
import { publicationBars } from "./dashboard-charts.js";
import { sortObservations, updateTimes } from "./dashboard-presentation.js";
import { updateMetricAvailability } from "./dashboard-forms.js";
import { preview, setupPreview } from "./dashboard-preview.js";
import { openDetail } from "./dashboard-detail.js";
import {
  setupForms,
  prepareObservation,
  renderExperiments,
} from "./dashboard-forms.js";
const headings = {
  overview: "Аналитика аккаунтов",
  content: "Публикации и их история",
  comparison: "Сравнение публикаций",
  import: "Наблюдения",
  experiments: "Гипотезы",
  detail: "История публикации",
};
export function view(name) {
  state.view = name;
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
  $("filter-disclosure").hidden = ["detail", "import", "experiments"].includes(name);
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
  const selected = state.accounts.filter(
    (a) =>
      !$("filter-platform").value || a.platform === $("filter-platform").value,
  );
  const histories = await Promise.all(
    selected.map(async (a) => [a, await all(`/accounts/${a.id}/history`)]),
  );
  const cards = [];
  state.accountMeasurements = [];
  for (const [a, history] of histories) {
    const latest = new Map();
    history
      .filter(
        (s) =>
          !$("filter-source").value || s.source === $("filter-source").value,
      )
      .forEach((s) =>
        latest.set(
          JSON.stringify([
            s.source,
            s.metric_scope,
            s.source_period_start,
            s.source_period_end,
          ]),
          s,
        ),
      );
    for (const s of latest.values()) {
      state.accountMeasurements.push({platform:a.platform,at:s.snapshot_at});
      cards.push(
        card(platformContext(a.platform, `@${a.username}`), s, [
          ["Подписчики", fmt(s.followers)],
          ["Аккаунт подписан на", fmt(s.following)],
          ["Просмотры", fmt(s.views)],
          ["Уникальные зрители", fmt(s.unique_viewers)],
          ["Просмотры профиля", fmt(s.profile_views)],
          ["Новые зрители", fmt(s.new_viewers)],
        ], true, latest.size > 1),
      );
    }
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
  return sortObservations(rows, $("content-sort").value);
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
  box.append(values, dataContext(s, state.comparison.rows.filter(row=>row.content.id===c.id).length > 1));
  if (!keys.length) box.append(node("p", "Показатели в этом наблюдении недоступны", "muted"));
  return box;
}
function renderContent() {
  const rows = entries();
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
  $("content-count").textContent = `${new Set(rows.map(r=>r.content.id)).size} публикаций · ${state.comparison.rows.length} последних наблюдений${state.comparison.truncated ? " · выборка ограничена 1000; сузьте фильтры" : ""}`;
  const ids = new Set([...new Set(sortObservations(rows, "date").map(r=>r.content.id))].slice(0,6));
  put("recent-content", ...(rows.length ? sortObservations(rows,"date").filter(r=>ids.has(r.content.id)).map(r=>publicationCard(r,true)) : [selectionEmpty()]));
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
  const warnings = Object.entries(state.collectionHealth || {}).filter(([p])=>!$("filter-platform").value || p===$("filter-platform").value).flatMap(([p,s]) => s.last_status === "failed" || s.last_status === "partial" ? [platformContext(p,s.last_status === "failed" ? "Последний сбор завершился с ошибкой; показаны сохранённые данные" : "Последний сбор неполный; часть показателей могла не обновиться")] : []);
  put("last-update", node("p", times.latest ? `Последнее обновление данных: ${date(times.latest)}` : "Время обновления пока неизвестно", "muted"), ...warnings, ...(platforms.length ? [info] : []));
}
function renderComparison() {
  if (!state.comparison?.groups?.length) {
    const e = state.appliedFilters?.length ? selectionEmpty() : empty("Для сравнения пока нет наблюдений", "Сравнение появится после сохранения показателей публикаций и их разметки.");
    put("comparison-table", e);
    put("comparison-cards", state.appliedFilters?.length ? selectionEmpty() : empty("Для сравнения пока нет наблюдений","Сохраните показатели публикаций и заполните разметку."));
    return;
  }
  const key = $("comparison-metric").value;
  const guards = {
    insufficient_sample: "Недостаточно данных",
    directional_only: "Только направление",
    observational_signal: "Наблюдаемая связь",
  };
  const groupCards = state.comparison.groups.map(g => {
    const m = g.metrics[key], card = node("article",null,"comparison-group-card");
    card.append(g.group ? node("h3",g.group) : button("Без тега — разметить публикации",()=>{view("content");message("global-message","Откройте историю публикации и раздел «Разметка публикации».");}),platformMark(g.platform));
    card.append(node("p",labels[key],"muted"),node("strong",metric(m.mean,key),"metric-value"),node("p",`Среднее · медиана ${metric(m.median,key)}`,"muted"),node("p",`Доступно ${m.n} из ${g.sample_size} наблюдений`),node("p",g.comparable_period ? guards[m.guardrail] : "Неизвестный период — без агрегирования","data-warning"),dataContext(g,true));
    return card;
  });
  put("comparison-cards",...groupCards);
  put(
    "comparison-table",
    table(
      [
        "Группа",
        "Платформа / источник",
        "Период / статус",
        "Публикаций",
        "Доступных значений",
        "Среднее",
        "Медиана",
        "Уверенность",
      ],
      (state.comparison?.groups || []).map((g) => {
        const m = g.metrics[key];
        return [
          g.group || button("Без тега — разметить публикации", () => {
            view("content");
            message("global-message", "Откройте историю публикации и заполните разметку в разделе «Разметка публикации».");
          }),
          g.platform + " / " + sources[g.source],
          period(g) +
            " / " +
            (statuses[g.snapshot_status] || g.snapshot_status),
          g.sample_size,
          m.n,
          metric(m.mean, key),
          metric(m.median, key),
          g.comparable_period
            ? guards[m.guardrail]
            : "Неизвестный период — без агрегирования",
        ];
      }),
    ),
  );
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
    await Promise.all([overview(), contentAndComparison()]);
    renderUpdateInfo();
    renderExperiments();
    prepareObservation();
    if (state.view === "detail" && state.detail)
      await openDetail(state.detail.id);
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
$("filter-disclosure").open = !mobileFilters.matches;
mobileFilters.addEventListener("change", e => { $("filter-disclosure").open = !e.matches; });
$("comparison-group").addEventListener("change", () =>
  contentAndComparison().catch((e) =>
    message("global-message", e.message, true),
  ),
);
$("comparison-metric").addEventListener("change", renderComparison);
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
setupForms(refresh);
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
