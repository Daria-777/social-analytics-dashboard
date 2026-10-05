import {
  $,
  platformMark,
  collectionMark,
  collectionMode,
  state,
  sources,
  statuses,
  labels,
  node,
  put,
  empty,
  fmt,
  metric,
  date,
  period,
  provenance,
  message,
  api,
  button,
  table,
  card,
  title,
  all,
} from "./dashboard-core.js";
import { renderHistoryChart } from "./dashboard-charts.js";
import { exactWindow } from "./dashboard-presentation.js";
import { preview } from "./dashboard-preview.js";
function observationSource(s, text) {
  const context = node("div", null, "observation-source");
  if (collectionMode(s.source) !== "automatic") context.append(collectionMark(collectionMode(s.source)));
  context.append(node("div", text));
  return context;
}
const tags = {
  internal_title: "Внутреннее название",
  concept: "Концепт",
  series: "Серия",
  topic: "Тема",
  content_pillar: "Контент-пиллар",
  hook_type: "Тип хука",
  hook_text: "Текст хука",
  story_structure: "Структура истории",
  format: "Формат",
  cta_type: "CTA",
  production_version: "Версия",
  notes: "Заметки",
};
export async function openDetail(id) {
  const source = $("filter-source").value,
    q = source ? "?source=" + source : "";
  const [data, history, retention, experiments] = await Promise.all([
    api(`/analytics/content/${id}${q}`),
    all(`/content/${id}/history${q}`),
    all(`/content/${id}/retention${q}`),
    api(`/content/${id}/experiments`),
  ]);
  state.detail = data.content;
  const c = data.content;
  put("detail-preview", preview(c));
  $("detail-title").textContent = title(c);
  const types = {video:"Видео",photo:"Фото",reel:"Reel",story:"История",carousel:"Карусель",other:"Другая публикация"};
  put("detail-context", platformMark(c.platform), node("span", types[c.content_type] || "Публикация"));
  $("detail-metadata").textContent =
    `${date(c.published_at)} · ${fmt(c.duration_seconds)} сек. · ID ${c.platform_content_id}`;
  const link = $("detail-permalink");
  link.hidden = true;
  link.removeAttribute("href");
  try {
    const url = new URL(c.permalink);
    if (["https:", "http:"].includes(url.protocol)) {
      link.href = url.href;
      link.hidden = false;
    }
  } catch {}
  put(
    "detail-metrics",
    ...(data.latest.length
      ? data.latest.map((r) =>
          card(sources[r.snapshot.source], r.snapshot, [
            ["Просмотры", fmt(r.snapshot.views)],
            ["Уникальные", fmt(r.snapshot.unique_viewers)],
            ["Досмотр, %", fmt(r.snapshot.completion_rate)],
            ["Среднее, сек.", fmt(r.snapshot.watch_time_avg_seconds)],
            ["Среднее, % длины", fmt(r.derived.average_watch_pct)],
            ["Доля репостов", metric(r.derived.share_rate, "share_rate")],
          ]),
        )
      : [empty()]),
  );
  const rateKeys = [
    "like_rate",
    "comment_rate",
    "share_rate",
    "save_rate",
    "profile_visit_rate",
    "follow_conversion",
    "returning_viewer_rate",
  ];
  const derivedTable = table(
      ["Источник / период", ...rateKeys.map((k) => labels[k])],
      data.latest.map((r) => [
        provenance(r.snapshot),
        ...rateKeys.map((k) => metric(r.derived[k], k)),
      ]),
    );
  if (data.latest.some(r => rateKeys.some(k => r.derived[k] != null))) put("detail-derived", derivedTable);
  else {
    const detail = node("details",null,"history-box"); detail.append(node("summary","Полная таблица расчётных долей"),derivedTable);
    put("detail-derived",node("p","Расчётные доли пока недоступны: не хватает исходных показателей.","muted"),detail);
  }
  renderHistoryChart(c, history);
  const sourceList = [...new Set(history.map((s) => s.source))];
  const velocity = await Promise.all(
    sourceList.map((s) => api(`/analytics/content/${id}/velocity?source=${s}`)),
  );
  const matches = velocity.flatMap(v => v.points.map(p => ({...p, source:v.source})));
  const nearest = node("details", null, "history-box");
  nearest.append(node("summary", "Ближайшие измерения"), table(
    ["Источник", "Цель, ч.", "Фактический возраст, ч.", "Отклонение, ч.", "Просмотры", "Время"],
    matches.filter(p => !exactWindow(p) && p.actual_age_hours != null).map(p => [sources[p.source], p.requested_age_hours, fmt(p.actual_age_hours), fmt(p.deviation_hours), fmt(p.views), date(p.snapshot_at)]),
  ));
  const windows = matches.length ? table(["Источник", "После публикации, ч.", "Измерение в этот момент"], matches.map(p => [
    sources[p.source], p.requested_age_hours,
    exactWindow(p) ? `${fmt(p.views)} просмотров · ${date(p.snapshot_at)}` : "В это время измерение не сохранено",
  ])) : empty("Измерений по возрасту пока нет", "Нужны время публикации и наблюдения с момента публикации.");
  windows.classList.add("window-readings");
  put("velocity-table",
    node("h3", "Измерения по возрасту публикации"),
    ...(matches.length && !matches.some(exactWindow) ? (() => {
      const detail = node("details",null,"history-box missing-windows"); detail.append(node("summary","Целевые окна — полная таблица"),windows);
      return [node("p","Нет измерений в целевые часы.","muted"),detail];
    })() : [windows]),
    ...(matches.some(p => !exactWindow(p) && p.actual_age_hours != null) ? [nearest] : []),
  );
  put(
    "retention-table",
    retention.length
      ? table(
          [
            "Источник / период",
            "Время",
            "Отвал, сек.",
            "Среднее, сек.",
            "Досмотр, %",
            "Статус",
          ],
          retention.map((s) => [
            observationSource(s, (sources[s.source] || "Источник не указан") + " / " + period(s)),
            date(s.snapshot_at),
            fmt(s.drop_off_second),
            fmt(s.average_watch_seconds),
            fmt(s.completion_rate),
            statuses[s.snapshot_status] || s.snapshot_status,
          ]),
        )
      : empty(
          "Удержание пока не внесено",
          "Добавьте показатели из статистики приложения в «Наблюдениях».",
        ),
  );
  put(
    "detail-history",
    table(
      [
        "Наблюдение / период",
        "Просмотры",
        "Уникальные",
        "Среднее, сек.",
        "Досмотр, %",
        "География",
      ],
      history.map((s) => {
        const geo = node("div");
        geo.append(
          button("Показать страны", async () => {
            const rows = await api(`/content-snapshots/${s.id}/geography`);
            geo.replaceChildren(
              node(
                "span",
                rows.length
                  ? rows
                      .map(
                        (r) =>
                          `${r.country_code} · ${r.country_name || "—"} · ${fmt(r.percentage)}%`,
                      )
                      .join("; ")
                  : "География не указана",
              ),
            );
          }),
        );
        return [
          observationSource(s, provenance(s)),
          fmt(s.views),
          fmt(s.unique_viewers),
          fmt(s.watch_time_avg_seconds),
          fmt(s.completion_rate),
          geo,
        ];
      }),
    ),
  );
  $("history-limit").textContent =
    `${history.length} наблюдений`;
  put(
    "tag-fields",
    ...Object.entries(tags).map(([key, label]) => {
      const l = node("label", label),
        input = node(
          key === "notes" || key === "hook_text" ? "textarea" : "input",
        );
      input.name = key;
      input.value = c[key] || "";
      l.append(input);
      return l;
    }),
  );
  const l = node("label", "Основная гипотеза"),
    select = node("select");
  select.name = "experiment_id";
  select.append(new Option("Не указана", ""));
  state.experiments.forEach((e) => select.append(new Option(e.name, e.id)));
  select.value = c.experiment_id || "";
  l.append(select);
  $("tag-fields").append(l);
  message("tags-message", "");
  put(
    "detail-experiments",
    ...(experiments.links.length
      ? experiments.links.map((r) =>
          node(
            "p",
            `${r.experiment.name} · ${r.experiment.status} · вариант ${r.variant || "—"}`,
          ),
        )
      : [node("p", "Связанных гипотез пока нет.", "muted")]),
  );
  $("link-experiment").replaceChildren(
    ...state.experiments.map((e) => new Option(e.name, e.id)),
  );
  $("link-experiment-form").querySelector("button").disabled =
    !state.experiments.length;
}
