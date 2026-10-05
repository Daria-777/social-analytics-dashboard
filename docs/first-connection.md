# Первое подключение всей системы

Код и mocked integrations проверены; локальный runtime развёрнут, реальные аккаунты
пока не подключены. Credentials/redirect codes храните и вводите **только локально**,
никогда в чат, repository или frontend. Не перезаписывайте существующий `.env`;
новый создайте из `.env.example`, установите `chmod 600 .env`.

## Единая последовательность

1. Запустите локальные PostgreSQL/API/dashboard по [local-deployment.md](local-deployment.md).
   Mac остаётся runtime до будущего переноса на сервер. Изолированные тесты
   описаны в [compose-smoke.md](compose-smoke.md); рабочая база без synthetic data.
2. Выполните `app.cli.local_setup`, если `.env` ещё отсутствует, и offline readiness.
   Без provider tokens dashboard работает с пустыми состояниями. Scheduler выключен.
3. Instagram: настройте Meta app / Instagram API with Instagram login, owner/test
   Professional account и два read permissions. Выполните локальный OAuth helper
   `python -m app.cli.instagram_auth`. **Generate token не гарантирует только read-only
   permissions:** до входа/consent проверьте фактически запрашиваемые права. Уберите
   лишние, если UI позволяет; иначе остановите этот flow и используйте helper с
   двумя scopes и зарегистрированным HTTPS callback. Не включайте publish/messages/
   comments permissions для обхода. Подробности — [README Instagram setup](../README.md#instagram-setup--phase-3)
   и [проверка grant](instagram-api.md#проверка-запрошенных-и-выданных-прав).
   OAuth требует зарегистрированный точный публичный HTTPS redirect.
   `INSTAGRAM_USER_ID` не угадывайте: discovery получает authoritative ID.
4. TikTok: выберите Web (exact public HTTPS redirect) или Desktop на Mac
   (exact HTTP loopback + PKCE); [инструкция](tiktok-api.md#owner-setup-web-or-desktop).
   Настройте доступные read scopes;
   выполните `python -m app.cli.tiktok_auth`. Helper сохраняет access/refresh/open_id,
   фактически выданные scopes и expiry metadata атомарно. Контракт/setup —
   [tiktok-api.md](tiktok-api.md). Username не заменяет app-scoped open_id.
5. Сохраните обновлённый приватный `.env` локально (при переносе — доставьте по SSH/SFTP),
   пересоздайте API, затем выполните **оба настоящих dry run**:

   ```sh
   docker compose -p social-analytics run --rm --no-deps api python -m app.cli.collect_instagram --dry-run
   docker compose -p social-analytics run --rm --no-deps api python -m app.cli.collect_tiktok --dry-run
   ```

   Они вызывают provider API, но не пишут в БД. Проверьте owner identity,
   permission/capability limitations. Только после разрешения владельца приступайте
   к genuine collection. Наличие token в readiness не подтверждает этот этап.
6. Выполните оба collectors с новым UUID каждого measurement. Для повторной доставки
   того же job передайте **тот же UUID**: successful run возвращается без duplicate
   snapshots; failed/partial retry пропускает уже записанные immutable observations.
   Для нового genuine measurement используйте новый UUID. Не меняйте даты snapshots
   для имитации старого отчёта. CLI команды и `--run-id` — в README.
7. Откройте `http://127.0.0.1:8000/dashboard` (на будущем сервере — HTTPS), войдите INTERNAL_API_KEY. Проверьте
   раздельные source/period/status и history. `/health` подтверждает только DB;
   `/collectors/status` показывает last status/error type, не token validity.
8. После успешных dry runs/collections установите SCHEDULER_ENABLED=true и явно
   включите profile scheduler. Расписание выключено до этой проверки.
   [scheduler.md](scheduler.md) описывает daily/age jobs, retries и recovery.

## Одна offline readiness команда

Из корня проекта с существующим Python environment:

```sh
.venv/bin/python -m app.cli.readiness
```

Допустим `--env-file /локальный/путь/.env`. Проверка читает конфигурацию, ничего
не записывает, не открывает HTTP/DB connections и не выводит values. Exit 2 —
недостающая/невалидная базовая runtime configuration; exit 0 — значения заданы, **не**
подтверждение доступа, DNS/TLS, daemon, scopes, token validity или server deployment.
Показаны отдельные Instagram/TikTok token/OAuth/refresh/grant metadata, явный
PostgreSQL URL, internal access, DASH_DOMAIN (обязателен только с `--server`, DNS не проверен), scheduler flag и наличие Docker binary.
`next_steps` даёт команды/действия; scheduler --plan читает БД, поэтому не offline.

Provider tokens и доступ проверяются отдельно от runtime. Для сервера используйте
`--server` и [server-deployment.md](server-deployment.md). Актуальные фактические
результаты — [system-verification.md](system-verification.md).

## Долгая работа и renewal

TikTok access token ограничен сроком (типовой контракт — 24h); honor returned expiry.
В legacy env mode автоматического refresh нет. Для Docker-only opt-in TikTok renewal
используйте [token-only named volume](tiktok-volume.md). Без opt-in нужен owner manual renewal:

```sh
.venv/bin/python -m app.cli.tiktok_auth --refresh
.venv/bin/python -m app.cli.instagram_auth --refresh
```

Instagram refresh применим только к eligible, ещё действующему long-lived token;
при expiry/revocation нужен новый login. Не нужно обновлять Instagram при каждом
TikTok renewal. При необходимости оба helpers сохраняют credentials локально;
доставьте файл на сервер и **пересоздайте оба worker containers**, как описано ниже.
Один `restart` не перечитывает Compose environment из изменённого host `.env`.

Признак проблемы: failed/partial + `TikTokAuthError` / `InstagramAuthError` в
существующем dashboard/status; PermissionError требует проверки read scopes/owner
setup. Статус token-present не является доказательством авторизации. Mocked тесты
подтверждают сохранение этого failed run/status и отсутствие credential writes/log leaks.
Инструкции renewal/recreate/retry: [server-deployment.md](server-deployment.md#renewal).
Для opt-in автоматического TikTok renewal реализован отдельный private store;
[инструкция](tiktok-api.md#opt-in-private-store-and-automatic-renewal). Legacy mode
сохраняет manual refresh. Реальная unattended работа на месяцы ещё не проверена.

Для Instagram на Mac подготовлен отдельный временный loopback callback на 8766
за будущим HTTPS tunnel: [процедура и ограничения](instagram-api.md#временный-локальный-callback-для-instagram).
Публичный tunnel и реальный OAuth требуют отдельного согласования; API8000 через
него не публикуется.
