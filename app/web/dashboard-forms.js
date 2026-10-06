import { metricAvailability } from "./dashboard-presentation.js";
import {
  $,
  state,
  sources,
  labels,
  node,
  put,
  empty,
  fmt,
  date,
  message,
  api,
  button,
  table,
  title,
  platformMark,
  collectionMode,
  collectionMark,
  period,
  setViewNotes,
  localInput,
  utc,
  submit,
} from "./dashboard-core.js";
const contentMetrics = [
  "views",
  "unique_viewers",
  "likes",
  "comments",
  "shares",
  "saves",
  "profile_visits",
  "followers_gained",
  "watch_time_avg_seconds",
  "watch_time_total_seconds",
  "completion_rate",
  "traffic_for_you_pct",
  "traffic_profile_pct",
  "traffic_search_pct",
  "traffic_following_pct",
  "traffic_other_pct",
  "new_viewers_pct",
  "returning_viewers_pct",
  "female_pct",
  "male_pct",
  "other_gender_pct",
  "age_18_24_pct",
  "age_25_34_pct",
  "age_35_44_pct",
  "age_45_54_pct",
  "age_55_plus_pct",
];
const accountMetrics = [
  "followers",
  "views",
  "unique_viewers",
  "profile_views",
  "likes",
  "comments",
  "shares",
  "saves",
  "new_viewers",
];
const extraLabels = {
  traffic_for_you_pct: "Рекомендации, %",
  traffic_profile_pct: "Профиль, %",
  traffic_search_pct: "Поиск, %",
  traffic_following_pct: "Подписки, %",
  traffic_other_pct: "Другой трафик, %",
  new_viewers_pct: "Новые зрители, %",
  returning_viewers_pct: "Вернувшиеся, %",
  female_pct: "Женщины, %",
  male_pct: "Мужчины, %",
  other_gender_pct: "Другой пол, %",
  age_18_24_pct: "18–24, %",
  age_25_34_pct: "25–34, %",
  age_35_44_pct: "35–44, %",
  age_45_54_pct: "45–54, %",
  age_55_plus_pct: "55+, %",
};
let parsedFile = null;
export function prepareObservation() {
  const kind = $("observation-kind").value,
    selected = $("observation-target").value,
    items = kind === "content" ? state.content : state.accounts;
  $("observation-target").replaceChildren(
    ...items.map(
      (c) =>
        new Option(
          kind === "content"
            ? `${c.platform} · ${title(c)}`
            : `${c.platform} · @${c.username}`,
          c.id,
        ),
    ),
  );
  if (items.some((c) => c.id === selected))
    $("observation-target").value = selected;
  $("observation-scope").replaceChildren(
    new Option("Не указан", ""),
    new Option(
      kind === "content" ? "С момента публикации" : "Текущие счётчики",
      kind === "content" ? "lifetime" : "current",
    ),
    new Option("Диапазон дат", "range"),
  );
  scopeChanged();
  $("retention-inputs").hidden = kind !== "content";
  $("geo-inputs").hidden = kind !== "content";
  const metrics = kind === "content" ? contentMetrics : accountMetrics;
  const fields = metrics.map((key) => {
      const l = node("label", labels[key] || extraLabels[key]),
        input = node("input");
      input.type = "number";
      input.name = key;
      input.min = "0";
      input.step =
        key.includes("seconds") ||
        key.endsWith("_pct") ||
        key === "completion_rate"
          ? "0.000001"
          : "1";
      if (key.endsWith("_pct") || key === "completion_rate") input.max = "100";
      l.append(input);
      return l;
    });
  const groups = new Map();
  metrics.forEach((key,i) => {
    const name = key.startsWith("watch_time") || key === "completion_rate" ? "Время просмотра и досмотр"
      : key.startsWith("traffic_") || ["profile_visits", "followers_gained"].includes(key) ? "Трафик и действия"
      : key.endsWith("_pct") || ["unique_viewers", "new_viewers"].includes(key) ? "Аудитория" : "Основные показатели";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(fields[i]);
  });
  const containers = [];
  for (const [name, inputs] of groups) {
    if (name === "Основные показатели") containers.push(...inputs);
    else {
      const group = node("details", null, "wide metric-group"), grid = node("div", null, "form-grid");
      grid.append(...inputs); group.append(node("summary", name), grid); containers.push(group);
    }
  }
  put("observation-metrics", ...containers);
  if (!$("observation-time").value) $("observation-time").value = localInput();
  targetChanged();
}
function targetChanged() {
  const selected = (
    $("observation-kind").value === "content" ? state.content : state.accounts
  ).find((c) => c.id === $("observation-target").value);
  const old = $("observation-source").value;
  $("observation-source").replaceChildren(
    ...(selected
      ? [
          selected.platform === "instagram" ? "instagram_ui" : "tiktok_studio",
          "manual",
        ]
      : []
    ).map((s) => new Option(sources[s], s)),
  );
  if ([...$("observation-source").options].some((o) => o.value === old))
    $("observation-source").value = old;
}
function scopeChanged() {
  $("observation-period").hidden = $("observation-scope").value !== "range";
  ["period-start", "period-end"].forEach(
    (id) => ($(id).required = !$("observation-period").hidden),
  );
}
function number(input) {
  if (input.value === "") return null;
  const n = Number(input.value);
  if (
    !Number.isFinite(n) ||
    n < 0 ||
    (input.max && n > Number(input.max)) ||
    (input.step === "1" && !Number.isSafeInteger(n))
  )
    throw Error("Метрики должны быть допустимыми неотрицательными числами.");
  return input.step === "1" ? n : input.value;
}
export function renderExperiments() {
  put(
    "experiment-list",
    ...(state.experiments.length
      ? state.experiments.map((e) => {
          const c = node("article", null, "experiment-card");
          c.append(
            node("h3", e.name),
            node("p", e.hypothesis || "Гипотеза не описана"),
            node(
              "p",
              `Метрика: ${labels[e.metric] || "Не выбран"} · ${date(e.started_at)} → ${date(e.ended_at)}`,
              "muted",
            ),
          );
          const actions = node("div", null, "experiment-actions"),
            select = node("select");
          select.setAttribute("aria-label", "Статус гипотезы " + e.name);
          ["draft", "running", "completed", "stopped"].forEach((s) =>
            select.append(new Option(({draft:"Черновик",running:"Проверяется",completed:"Завершена",stopped:"Остановлена"})[s], s)),
          );
          select.value = e.status;
          actions.append(
            select,
            button("Сохранить статус", async () => {
              await api(`/experiments/${e.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: select.value }),
              });
              e.status = select.value;
              message("global-message", "Статус гипотезы сохранён.");
            }),
          );
          c.append(actions);
          return c;
        })
      : [
          empty(
            "Гипотез пока нет",
            "Опишите предположение и ключевую метрику, затем свяжите публикации с вариантами.",
          ),
        ]),
  );
}
export function updateMetricAvailability() {
  const key = $("experiment-metric").value, source = $("experiment-source").value;
  const { available, total } = metricAvailability(state.comparison?.rows || [], source, key);
  $("experiment-availability").textContent = !key ? "Выберите показатель для проверки гипотезы."
    : total ? `Показатель доступен в ${available} из ${total} наблюдений.`
    : "Для этого источника нет наблюдений.";
}
export function setupForms(refresh) {
  const metrics = [...new Set([...contentMetrics.filter(k => labels[k]), "average_watch_pct", "like_rate", "comment_rate", "share_rate", "save_rate", "profile_visit_rate", "follow_conversion", "returning_viewer_rate"])];
  $("experiment-metric").replaceChildren(new Option("Выберите показатель", ""), ...metrics.map(k => new Option(labels[k], k)));
  $("experiment-metric").addEventListener("change", updateMetricAvailability);
  $("experiment-source").addEventListener("change", updateMetricAvailability);
  $("observation-kind").addEventListener("change", prepareObservation);
  $("observation-target").addEventListener("change", targetChanged);
  $("observation-scope").addEventListener("change", scopeChanged);
  submit($("observation-form"), "observation-message", async () => {
    const kind = $("observation-kind").value,
      parent = (kind === "content" ? state.content : state.accounts).find(
        (c) => c.id === $("observation-target").value,
      );
    if (!parent)
      throw Error(
        "Сначала добавьте публикацию или аккаунт с точным идентификатором платформы.",
      );
    const record = {
      platform: parent.platform,
      source: $("observation-source").value,
      snapshot_at: utc($("observation-time").value),
      snapshot_status: $("observation-status").value,
      metric_scope: $("observation-scope").value || null,
      notes: $("observation-notes").value || null,
      raw_payload: { entry_method: "dashboard", collection_method: "manual" },
    };
    record[kind === "content" ? "platform_content_id" : "platform_account_id"] =
      kind === "content"
        ? parent.platform_content_id
        : parent.platform_account_id;
    if (record.metric_scope === "range") {
      record.source_period_start = utc($("period-start").value);
      record.source_period_end = utc($("period-end").value);
    }
    for (const input of $("observation-metrics").querySelectorAll("input"))
      record[input.name] = number(input);
    const batch = { version: 1, [kind + "_snapshots"]: [record] };
    if (kind === "content") {
      record.geography = $("observation-geo").value.trim()
        ? $("observation-geo")
            .value.trim()
            .split("\n")
            .map((line) => {
              const pieces = line.split(";");
              if (
                pieces.length !== 3 ||
                !/^[A-Z]{2}$/.test(pieces[0].trim().toUpperCase())
              )
                throw Error(
                  "География: код;название;процент, одна страна на строку.",
                );
              const value = pieces[2].trim();
              if (
                value &&
                (!Number.isFinite(Number(value)) ||
                  Number(value) < 0 ||
                  Number(value) > 100)
              )
                throw Error("Процент страны должен быть от 0 до 100.");
              return {
                country_code: pieces[0].trim().toUpperCase(),
                country_name: pieces[1].trim() || null,
                percentage: value || null,
              };
            })
        : [];
      const ret = {
        platform: parent.platform,
        platform_content_id: parent.platform_content_id,
        source: record.source,
        snapshot_at: record.snapshot_at,
        snapshot_status: record.snapshot_status,
        source_period_start: record.source_period_start || null,
        source_period_end: record.source_period_end || null,
        notes: record.notes,
        drop_off_second: number($("retention-drop")),
        average_watch_seconds: number($("retention-average")),
        completion_rate: number($("retention-completion")),
      };
      if (
        [
          ret.drop_off_second,
          ret.average_watch_seconds,
          ret.completion_rate,
        ].some((v) => v !== null)
      )
        batch.retention_snapshots = [ret];
    }
    await api("/manual-snapshots/import", {
      method: "POST",
      body: JSON.stringify(batch),
    });
    await refresh();
    message(
      "observation-message",
      "Наблюдение добавлено.",
    );
  });
  submit($("tags-form"), "tags-message", async () => {
    const data = Object.fromEntries(
      [...$("tag-fields").querySelectorAll("[name]")].map((i) => [
        i.name,
        i.value || null,
      ]),
    );
    await api(`/content/${state.detail.id}/tags`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    await refresh();
    message("tags-message", "Теги сохранены.");
  });
  submit($("experiment-form"), "experiment-message", async () => {
    await api("/experiments", {
      method: "POST",
      body: JSON.stringify({
        name: $("experiment-name").value,
        hypothesis: $("experiment-hypothesis").value || null,
        metric: $("experiment-metric").value || null,
        notes: $("experiment-notes").value || null,
      }),
    });
    $("experiment-form").reset();
    await refresh();
    message("experiment-message", "Гипотеза создана.");
  });
  submit($("link-experiment-form"), "global-message", async () => {
    await api("/content-experiments", {
      method: "POST",
      body: JSON.stringify({
        content_id: state.detail.id,
        experiment_id: $("link-experiment").value,
        variant: $("link-variant").value || null,
      }),
    });
    await refresh();
    message("global-message", "Гипотеза связана с публикацией.");
  });
  $("import-file").addEventListener("change", async () => {
    parsedFile = null;
    $("import-submit").disabled = true;
    $("import-submit").dataset.locked = "true";
    try {
      const file = $("import-file").files[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024)
        throw Error("Размер отчёта не должен превышать 5 МБ.");
      const data = JSON.parse(await file.text());
      if (
        data.version !== 1 ||
        !["content_snapshots", "account_snapshots", "retention_snapshots"].some(
          (k) => Array.isArray(data[k]) && data[k].length,
        )
      )
        throw Error("Отчёт должен иметь версию 1 и поддерживаемые разделы наблюдений.");
      parsedFile = data;
      message(
        "import-preview",
        `Публикации: ${data.content_snapshots?.length || 0}; аккаунты: ${data.account_snapshots?.length || 0}; удержание: ${data.retention_snapshots?.length || 0}. Полная проверка выполняется сервером до записи.`,
      );
      $("import-submit").disabled = false;
      $("import-submit").dataset.locked = "false";
    } catch (e) {
      message(
        "import-preview",
        e instanceof SyntaxError
          ? "Файл не содержит допустимый JSON."
          : e.message,
        true,
      );
    }
  });
  submit($("json-import-form"), "import-message", async () => {
    if (!parsedFile) throw Error("Выберите допустимый JSON-файл.");
    await api("/manual-snapshots/import", {
      method: "POST",
      body: JSON.stringify(parsedFile),
    });
    parsedFile = null;
    $("json-import-form").reset();
    await refresh();
    message("import-preview", "");
    message(
      "import-message",
      "Весь batch добавлен. Повторный импорт создаст новые наблюдения.",
    );
    $("import-submit").dataset.locked = "true";
  });
}


// This list uses all accounts/publications, independently of hidden comparison filters.
export function renderManualMeasurements(data, accountRows, openContent) {
  const manualSources = new Set(["instagram_ui", "tiktok_studio", "manual"]);
  const rows = data.rows.filter(r => manualSources.has(r.snapshot.source));
  setViewNotes("import", [...rows.map(r=>({name:title(r.content),snapshot:r.snapshot})),...accountRows.map(r=>({name:(r.account.platform==="tiktok"?"TikTok":"Instagram")+" @"+r.account.username,snapshot:r.snapshot}))], rows.length ? [...(rows.every(r=>r.snapshot.metric_scope==="lifetime") && !rows.some(r=>r.snapshot.notes?.includes("с момента публикации")) ? ["Показатели публикаций — с момента публикации."] : []), "Прочерк означает отсутствие данных; 0 — измеренное нулевое значение."] : []);
  const methods = new Set([...rows, ...accountRows].map(r => collectionMode(r.snapshot)));
  $("observation-collection-mode").replaceChildren(collectionMark(methods.size === 1 ? [...methods][0] : methods.size ? "mixed" : "agent"));
  const box = $("manual-measurements");
  box.replaceChildren();
  if (!rows.length && !accountRows.length) {
    box.append(empty("Наблюдений пока нет", "Поручите AI-агенту прочитать Insights и Studio или добавьте показатели самостоятельно."));
    return;
  }
  const wrap = (headers, values, label) => {
    const region = node("div", null, "table-wrap");
    region.tabIndex = 0;
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", label);
    const grid = table(headers, values);
    grid.querySelectorAll("th").forEach(th => th.scope = "col");
    region.append(grid);
    return region;
  };
  const context = (s, name) => {
    const cell = node("div");
    cell.append(name);
    if (s.snapshot_status === "anomalous") cell.append(node("p", "Аномалия", "data-warning"));
    return cell;
  };
  for (const source of manualSources) {
    const selected = rows.filter(r => r.snapshot.source === source);
    const accounts = accountRows.filter(r => r.snapshot.source === source);
    if (!selected.length && !accounts.length) continue;
    const section = node("section", null, "edit-box");
    const heading = node("h3");
    const platform = selected[0]?.content.platform || accounts[0]?.account.platform;
    if (source !== "manual") heading.append(platformMark(platform));
    heading.append(document.createTextNode(sources[source]));
    section.append(heading);
    if (selected.length) {
      const mixedPeriods = selected.some(r=>r.snapshot.metric_scope!=="lifetime");
      section.append(node("h4", "Публикации"), wrap(
        ["Публикация", ...(mixedPeriods ? ["Период"] : []), "Просмотры", "Среднее, сек.", "Досмотр, %"],
        selected.map(({content: c, snapshot: s}) => [
          context(s, button(title(c), () => openContent(c, s.source), "title-link")),
          ...(mixedPeriods ? [period(s)] : []), fmt(s.views), fmt(s.watch_time_avg_seconds), fmt(s.completion_rate),
        ]), sources[source] + ": публикации"));
    }
    if (accounts.length) {
      section.append(node("h4", "Аккаунты"), wrap(
        ["Аккаунт", "Период", "Подписчики", "Просмотры", "Зрители", "Посещения профиля"],
        accounts.map(({account: a, snapshot: s}) => [
          context(s, node("strong", "@" + a.username)),
          s.raw_payload?.displayed_period || period(s),
          fmt(s.followers), fmt(s.views), fmt(s.unique_viewers), fmt(s.profile_views),
        ]), sources[source] + ": аккаунты"));
    }
    box.append(section);
  }
  if (data.truncated) box.append(node("p", "Показана часть последних измерений; полная история доступна в публикациях.", "data-warning"));
}
