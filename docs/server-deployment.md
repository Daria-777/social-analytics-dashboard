# Серверный вариант: подготовлен, не развёрнут

`compose.server.yaml` — отдельная portable конфигурация существующего стека;
её не объединяют с локальным compose.yaml. JSON syntax внутри файла является YAML
subset и позволяет проверить структуру стандартным Python без новой зависимости.
Нужны реальный хост, домен и локально настроенный SSH-доступ. Отдельного сервера/домена пока нет. Docker Desktop установлен для
локального Mac runtime; Caddy adapt/validate, ACME, live TLS, host reboot и server
smoke test **не выполнялись**. Шаблон не равен работающему серверу.

## Размер и внешние условия

Планировочный старт для одного owner/двух платформ: 2 vCPU, 4 GiB RAM и 30 GiB SSD
с постоянным диском. Это оценка для PostgreSQL + одного FastAPI worker + scheduler
+ Caddy, **не измеренный minimum/production benchmark**. Raw payload/history,
backup retention и реальные нагрузки потребуют измерения и изменения размера.

Подходит поддерживаемый 64-bit Linux с Docker Engine/Compose v2, например Ubuntu
24.04 LTS из [официального списка Docker](https://docs.docker.com/engine/install/ubuntu/).
Docker daemon должен запускаться при boot. Также нужны домен/поддомен, DNS A/AAAA
на настоящий адрес сервера, доступные 80/443 и исходящий HTTPS к providers/ACME.
Если IPv6 не настроен, не публикуйте неверный AAAA. Сервер/домен не покупались.

## Изоляция и официальный proxy contract

Наружу опубликованы только proxy 80/443. API, migrate, scheduler и DB портов
не публикуют; DB не подключена к proxy network. Постоянны postgres_data и Caddy
certificate/config volumes. Имена ресурсов project-scoped; нет global container_name.
API/proxy/DB/scheduler имеют unless-stopped: после daemon boot они возобновляются,
если их не остановили вручную. Это [Docker restart contract](https://docs.docker.com/engine/containers/start-containers-automatically/).
Collection job retry budget остаётся в DB; process restart не отменяет его.
При постоянной DB ошибке scheduler container может снова перезапускаться — оператор
должен остановить его и устранить причину, а не обещать бесконечную доступность.

Caddy сохраняет Host и сам устанавливает X-Forwarded-Proto/For/Host, игнорируя
поддельные incoming forwarded headers по умолчанию. Не добавляйте blanket trusted
proxies или CDN без отдельной настройки. [Официальный reverse_proxy contract](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults).
[Automatic HTTPS](https://caddyserver.com/docs/automatic-https) требует DNS/80/443
и persistent writable data. В Caddyfile нет access log; Uvicorn --no-access-log
исключает OAuth callback query strings из access log.

Uvicorn доверяет forwarded headers **только** DASH_PROXY_IP (default private
172.30.252.2), назначенному Caddy в отдельной edge network. Это внутренний адрес
шаблона, не выдуманный публичный IP. DASH_EDGE_SUBNET default 172.30.252.0/24 должен
не конфликтовать с сетями хоста. Если меняете subnet/IP, измените оба согласованно;
никогда не ставьте forwarded-allow-ips='*'. Проверен реальный установленный Uvicorn
ProxyHeadersMiddleware: trusted TLS hop → Secure cookie и same-origin PATCH;
wrong Origin/untrusted forged proto → 403. [Исходный contract Uvicorn](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py).
Физический Docker/Caddy hop пока не проверен.

## Startup и migrations

После получения отдельного хоста загрузите reviewable checkout/Dockerfile/migrations/
server Compose/deploy без секретов; приватный .env загрузите отдельно, mode 600.
Заполните настоящие POSTGRES_* и согласованный DATABASE_URL с hostname db,
INTERNAL_API_KEY и DASH_DOMAIN (DNS hostname, без schema/path). Provider tokens
первоначально можно оставить пустыми, SCHEDULER_ENABLED=false.

```sh
# В каталоге проекта на предоставленном хосте; не печатает resolved values.
docker compose -p dash -f compose.server.yaml config -q
docker compose -p dash -f compose.server.yaml run --rm --no-deps proxy caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
docker compose -p dash -f compose.server.yaml up --build -d
```

migrate ждёт healthy PostgreSQL, делает upgrade head; API ждёт success migration,
proxy ждёт healthy API. Для первого build зафиксируйте фактически проверенные image
versions/digests. Не выполняйте downgrade на рабочих данных вместо restore backup.

```sh
docker compose -p dash -f compose.server.yaml ps
docker compose -p dash -f compose.server.yaml exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').status)"
```

Проверьте HTTPS сертификат и /health через настоящий домен, dashboard login,
Secure/HttpOnly/SameSite cookie, source-empty states, недоступность API 8000 и DB
5432 извне. Dashboard защищён owner session; health/login HTML публичны, данные — нет.
Reboot проверяйте на выделенном хосте после backup; Mac/production не перезапускались.

После owner OAuth/dry runs/genuine collection явно включите scheduler:

```sh
docker compose -p dash -f compose.server.yaml --profile scheduler up -d scheduler
```

Нужно также SCHEDULER_ENABLED=true в private .env. Остальные шаги — first-connection.md.
Не обещайте долгую автономность с текущим manual TikTok refresh.

## Renewal

При AuthError остановите новые collections и scheduler. Выполните owner refresh
локально; при expired/revoked refresh token нужен новый OAuth login. Ни один helper
не следует запускать через bind-mounted единственный .env file: atomic rename
может не работать. Используйте существующий локальный Python environment, затем
передайте приватный файл на хост через SSH/SFTP. Не передавайте tokens в CLI args.

```sh
docker compose -p dash -f compose.server.yaml --profile scheduler stop scheduler api
# Локальный owner refresh/bootstrap; securely обновить server .env.
docker compose -p dash -f compose.server.yaml up -d --no-deps --force-recreate api
# Выполнить оба dry runs (first-connection.md), проверить identity/scopes/status.
# Только после успеха и owner разрешения:
docker compose -p dash -f compose.server.yaml --profile scheduler up -d --no-deps --force-recreate scheduler
```

Второй шаг выполняйте после восстановления DB и разрешения owner; profile нужен
для scheduler. Пересоздание применяет новые environment values. Просто restart
сохраняет старый token. Проверьте dry run/status, повторите failed UUID по README;
running crash сначала требует подтверждённого отсутствия всех workers и operator
recovery. Сохранённые snapshots не меняются; success UUID не даёт нового измерения.

## Backup / restore

На сервере храните backup вне Git, mode 600, с зашифрованной off-host копией и
сроком хранения. Manual dump согласован с PostgreSQL MVCC; включает snapshots,
metadata, migration state и triggers, не меняет observations:

```sh
umask 077
mkdir -p backups
docker compose -p dash -f compose.server.yaml exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/dash.dump
```

Проверьте exit code, размер и `pg_restore --list`, затем реальное восстановление
на **новом отдельном project/volume**, не на рабочей БД. Для restore используйте
тот же template с отдельным project name и private env, но сначала запустите
только db. Убедитесь, что target DB пустая и принадлежит этому restore project. Если production работает на
том же хосте, выделите restore.env другую свободную DASH_EDGE_SUBNET/DASH_PROXY_IP;
не запускайте restore proxy на занятых 80/443. До failover нужны только db/API
без внешних портов, отдельные volumes и host-internal health checks:

```sh
docker compose -p dash-restore -f compose.server.yaml --env-file /PRIVATE/restore.env up -d db
# Дождаться healthy DB; не запускать migrate/API до restore.
docker compose -p dash-restore -f compose.server.yaml --env-file /PRIVATE/restore.env exec -T db sh -c 'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/dash.dump
```

После restore проверьте schema version, историю/count/values, immutable triggers;
при необходимости upgrade head, затем API. Перед реальным failover нужна отдельная
авторизация владельца. .env и Caddy data volume — отдельные приватные резервные
копии; DB dump не содержит OAuth environment. Backup/restore инструкции подготовлены,
реального server backup/restore пока не было.

## Точный следующий внешний шаг

Предоставить хост с Docker Engine/Compose v2 и постоянным диском, DNS hostname и
локально настроенный SSH key access. В чат достаточно hostname, пользователя и пути
к локальному ключу, **не** private key/password/token. Покупка/создание ресурсов и
deployment не выполняются автоматически. Затем изолированный smoke test и review
server config; actual OAuth выполняет owner. Серверный этап ждёт будущего хоста/домена; локальный runtime описан в
[local-deployment.md](local-deployment.md). Готовые файлы и tests сохранены.
