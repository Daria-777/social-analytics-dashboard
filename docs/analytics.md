# Analytics contract

Derived metrics вычисляются в ответах, не записываются в API/manual snapshots.
Все числители и знаменатели берутся из **одного** snapshot. NULL/нулевой знаменатель
→ NULL; reach не заменяет unique_viewers. Аномальные значения не обрезаются.

| Поле | Формула | Единица |
|---|---|---|
| like_rate/comment_rate/share_rate/save_rate | likes/comments/shares/saves ÷ views | доля, UI умножает на 100 |
| follow_conversion | followers_gained ÷ unique_viewers | доля |
| profile_visit_rate | profile_visits ÷ unique_viewers | доля |
| average_watch_pct | watch_time_avg_seconds ÷ content.duration_seconds × 100 | % |
| returning_viewer_rate | returning_viewers_pct ÷ 100 | доля |

Duration — текущая metadata публикации; отсутствие duration не заменяется guessed
значением. Completion берётся из исходного observation, не выводится из watch time.
Avg watch может превышать duration; >100% не превращается молча в 100%.

GET /analytics/content-comparison: platform, source, publication date_from/date_to,
observation snapshot_from/snapshot_to, series/topic/hook_type/content_pillar/format/
cta_type; group_by по этим стратегическим признакам или platform. offset/limit и
truncated показывают границы выборки, не выдавайте усечённый результат за весь аккаунт.
Для каждого content/source/scope/точного period выбирается последний observation.
Groups дополнительно разделены по platform и snapshot_status. Источники не складываются.

Lifetime сравнивается только с lifetime без range boundaries; range — только с
одинаковыми явными start/end. Unknown scope остаётся видимым, но aggregate mean/median
не рассчитываются. Manual import позволяет явно указать metric_scope: content
lifetime/range, account current/range. Для range обе даты обязательны.

Каждый aggregate имеет mean, median, **n доступных значений** и guardrail; отдельно
sample_size группы — число публикаций, не snapshots. n<5 insufficient_sample,
5..9 directional_only, n>=10 observational_signal. Это не доказательство причинности.
Lifetime counts разных публикаций могут иметь разный возраст; не называйте сравнение
нормированным по возрасту. Статусы anomalous/manual/estimated всегда остаются видимыми.

GET /analytics/content/{id}: последние отдельные observations и derived values.
GET /analytics/content/{id}/velocity?source=... требует один source, использует
только lifetime observations. Точки 1h/6h/24h/48h/72h/7d выбирают ближайший snapshot
после публикации, без интерполяции. Возвращаются actual_age_hours, deviation_hours,
snapshot_id/at, source и views (может быть NULL). requested_age_hours=24 и
actual_age_hours=25.3 не называются точным измерением 24h. Нет source/точек — NULL.

PATCH /content/{id}/tags меняет только стратегические поля и experiment_id.
Identity/publication IDs и snapshots не редактируются; неизвестный experiment — 404.
