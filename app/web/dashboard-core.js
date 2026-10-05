export const $ = (id) => document.getElementById(id);
export const state = {
  config: { display_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" },
  accounts: [],
  content: [],
  experiments: [],
  view: "overview",
  detail: null,
};
export const sources = {
  instagram_api: "Instagram API",
  instagram_ui: "Instagram Insights",
  tiktok_api: "TikTok API",
  tiktok_studio: "TikTok Studio",
  manual: "Вручную",
};
export const labels = {
  views: "Просмотры",
  unique_viewers: "Уникальные зрители",
  reach: "Охват",
  likes: "Лайки",
  comments: "Комментарии",
  shares: "Репосты",
  saves: "Сохранения",
  profile_visits: "Переходы в профиль",
  followers_gained: "Новые подписчики",
  watch_time_avg_seconds: "Среднее время, сек.",
  watch_time_total_seconds: "Общее время, сек.",
  completion_rate: "Досмотр, %",
  average_watch_pct: "Среднее время, % длины",
  followers: "Подписчики",
  following: "Аккаунт подписан на",
  profile_views: "Просмотры профиля",
  new_viewers: "Новые зрители",
  share_rate: "Доля репостов",
  save_rate: "Доля сохранений",
  follow_conversion: "Конверсия в подписку",
  profile_visit_rate: "Доля переходов",
  returning_viewer_rate: "Доля вернувшихся",
  like_rate: "Доля лайков",
  comment_rate: "Доля комментариев",
};
export const statuses = {
  success: "Успешно",
  partial: "Частично",
  failed: "Ошибка",
  running: "В работе",
  confirmed: "Подтверждено",
  manual: "Вручную",
  unavailable: "Недоступно",
  anomalous: "Аномалия",
  estimated: "Оценка",
  processing: "Обрабатывается",
};
export function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}
export function put(id, ...nodes) {
  $(id).replaceChildren(...nodes);
}
export function empty(
  text = "Наблюдений пока нет",
  hint = "Запустите сбор или добавьте наблюдение.",
) {
  const box = node("div", null, "empty-state");
  box.append(node("strong", text), node("p", hint));
  return box;
}
export function fmt(value, digits = 2) {
  return value == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(
        Number(value),
      );
}
export function metric(value, key) {
  return (key.endsWith("_rate") && key !== "completion_rate") ||
    key === "follow_conversion"
    ? value == null
      ? "—"
      : fmt(Number(value) * 100) + "%"
    : fmt(value);
}
export function date(value) {
  return value
    ? new Intl.DateTimeFormat("ru-RU", {
        dateStyle: "short",
        timeStyle: "short",
        timeZone: state.config.display_timezone,
      }).format(new Date(value))
    : "—";
}
export function period(s) {
  return s.metric_scope === "lifetime"
    ? "С момента публикации"
    : s.metric_scope === "current"
      ? "Текущий счётчик"
      : s.source_period_start && s.source_period_end
        ? `${date(s.source_period_start)} → ${date(s.source_period_end)}`
        : "Период не указан";
}
export function status(value) {
  return node(
    "span",
    statuses[value] || value || "Нет запусков",
    "status-badge " + (value || "unavailable"),
  );
}
export function provenance(s) {
  return `${sources[s.source] || s.source} · ${period(s)} · ${date(s.snapshot_at)}`;
}
export function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}
export function showLogin() {
  const photo = $("photo-dialog");
  if (photo?.open) photo.close();
  $("workspace").hidden = true;
  $("login").hidden = false;
  state.detail = null;
}
export async function api(path, options = {}) {
  let r;
  try {
    r = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw Error(
      "Сервер недоступен. Проверьте локальный запуск и попробуйте снова.",
    );
  }
  if (!r.ok) {
    if (r.status === 401) showLogin();
    throw Error(
      {
        401: "Неверный ключ или сессия завершилась.",
        403: "Запрос отклонён: требуется тот же origin.",
        404: "Объект не найден. Обновите данные.",
        409: "Конфликт или сбор уже выполняется.",
        422: "Проверьте поля, источник, идентификатор и границы периода.",
        429: "Слишком много попыток. Подождите минуту.",
        503: "Конфигурация сервера не готова.",
      }[r.status] ||
        "Не удалось выполнить запрос. Проверьте состояние сервера.",
    );
  }
  return r.json();
}
export function button(text, handler, cls = "quiet") {
  const b = node("button", text, cls);
  b.type = "button";
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await handler();
    } catch (e) {
      message("global-message", e.message, true);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}
export function table(headers, rows) {
  if (!rows.length) return empty();
  const t = node("table"),
    head = node("thead"),
    tr = node("tr"),
    body = node("tbody");
  headers.forEach((h) => tr.append(node("th", h)));
  head.append(tr);
  rows.forEach((values) => {
    const row = node("tr");
    values.forEach((value) => {
      const td = node("td");
      td.append(
        value instanceof Node
          ? value
          : document.createTextNode(value == null ? "—" : String(value)),
      );
      row.append(td);
    });
    body.append(row);
  });
  t.append(head, body);
  return t;
}
export function card(title, s, fields, compact = false, multiple = false) {
  const c = node("article", null, "observation-card"),
    heading = node("div", null, "card-heading");
  const name = node("strong");
  name.append(title instanceof Node ? title : document.createTextNode(title));
  heading.append(name);
  if (!compact) {
    if (collectionMode(s.source) !== "automatic") heading.append(collectionMark(collectionMode(s.source)));
    if (s.snapshot_status !== "manual" || collectionMode(s.source) !== "manual") heading.append(status(s.snapshot_status));
  }
  c.append(heading);
  if (!compact) c.append(node("p", provenance(s), "card-provenance"));
  const strip = node("div", null, "metric-strip");
  fields.forEach(([label, value]) => {
    const m = node("div");
    m.append(
      node("div", value, "metric-value"),
      node("div", label, "metric-label"),
    );
    strip.append(m);
  });
  c.append(strip);
  if (compact) c.append(dataContext(s, multiple));
  return c;
}
export function title(c) {
  return c.internal_title || c.caption || c.platform_content_id;
}
export function localInput(value = new Date()) {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: state.config.display_timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
export function utc(value) {
  if (!value) return null;
  const input = new Date(value + "Z");
  let result = input;
  for (let i = 0; i < 3; i++) {
    const rendered = new Date(localInput(result) + "Z");
    result = new Date(result.getTime() + input.getTime() - rendered.getTime());
  }
  if (localInput(result) !== value.slice(0, 16))
    throw Error("Локальное время не существует в выбранном часовом поясе.");
  return result.toISOString();
}
export const filterMap = {
  platform: "platform",
  source: "source",
  series: "series",
  topic: "topic",
  hook: "hook_type",
  format: "format",
  cta: "cta_type",
  pillar: "content_pillar",
};
export function query() {
  const q = new URLSearchParams({
    limit: "1000",
    group_by: $("comparison-group").value,
  });
  Object.entries(filterMap).forEach(([id, key]) => {
    if ($("filter-" + id).value) q.set(key, $("filter-" + id).value);
  });
  if ($("filter-from").value)
    q.set("date_from", utc($("filter-from").value + "T00:00"));
  if ($("filter-to").value)
    q.set(
      "date_to",
      new Date(
        new Date(utc($("filter-to").value + "T23:59")).getTime() + 59999,
      ).toISOString(),
    );
  return q;
}
export async function all(path) {
  const rows = [];
  for (let offset = 0; offset < 100000; offset += 1000) {
    const page = await api(
      `${path}${path.includes("?") ? "&" : "?"}limit=1000&offset=${offset}`,
    );
    rows.push(...page);
    if (page.length < 1000) return rows;
  }
  throw Error("Слишком много данных для одного экрана.");
}
export function activeContent() {
  const q = query();
  const from = q.has("date_from") ? Date.parse(q.get("date_from")) : null;
  const to = q.has("date_to") ? Date.parse(q.get("date_to")) : null;
  return state.content.filter((c) => {
    const published = c.published_at ? Date.parse(c.published_at) : NaN;
    // Unknown publication times remain visible until a date filter is applied.
    return (
      Object.values(filterMap)
        .filter((k) => k !== "source")
        .every((k) => !q.has(k) || c[k] === q.get(k)) &&
      (from === null || (Number.isFinite(published) && published >= from)) &&
      (to === null || (Number.isFinite(published) && published <= to))
    );
  });
}
export async function submit(form, id, work) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const b = form.querySelector("button[type=submit]");
    if (b) b.disabled = true;
    message(id, "Сохраняю…");
    try {
      await work();
    } catch (error) {
      message(id, error.message, true);
    } finally {
      if (b) b.disabled = b.dataset.locked === "true";
    }
  });
}

export function platformMark(platform) {
  const name = {instagram:"Instagram",tiktok:"TikTok"}[platform];
  if (!name) return node("span", platform);
  const mark = node("span", null, "platform-mark"), image = node("img");
  mark.setAttribute("role", "img");
  mark.setAttribute("aria-label", name);
  mark.title = name;
  mark.dataset.label = name;
  mark.tabIndex = 0;
  image.src = `/dashboard/assets/platform-${platform}.svg`;
  image.alt = "";
  image.width = image.height = 20;
  mark.append(image);
  return mark;
}

export function briefPeriod(s) {
  return s.metric_scope === "lifetime" ? "Всего" : s.metric_scope === "current" ? "Текущее значение" : period(s);
}
// Entry method follows provenance, independently of quality or collector health.
export function collectionMode(source) {
  if (["instagram_api", "tiktok_api"].includes(source)) return "automatic";
  if (["instagram_ui", "tiktok_studio", "manual"].includes(source)) return "manual";
  return "unknown";
}
export function collectionMark(mode) {
  const names = {automatic:"Автоматически", manual:"Вручную"};
  const mark = node("span", null, "collection-mark");
  mark.dataset.collectionMode = names[mode] ? mode : "unknown";
  if (names[mode]) {
    const image = node("img");
    image.src = `/dashboard/assets/collection-${mode}.svg`;
    image.alt = "";
    image.width = image.height = 16;
    mark.append(image);
  }
  mark.append(node("span", names[mode] || "Способ не указан"));
  return mark;
}
export function dataContext(s) {
  const box = node("div", null, "data-context");
  box.append(node("p", briefPeriod(s), "period-label"));
  if (collectionMode(s.source) !== "automatic") box.append(collectionMark(collectionMode(s.source)));
  const warnings = {estimated:"Значение оценено",anomalous:"Есть сомнения в точности",processing:"Данные ещё обрабатываются",unavailable:"Показатели недоступны"};
  if (warnings[s.snapshot_status]) box.append(node("p", warnings[s.snapshot_status], "data-warning"));
  const details = node("details", null, "data-details");
  details.append(node("summary", "О данных"), node("p", provenance(s), "card-provenance"), status(s.snapshot_status));
  box.append(details);
  return box;
}
