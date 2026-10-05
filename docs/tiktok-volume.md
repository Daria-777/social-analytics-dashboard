# TikTok: постоянное приватное хранилище внутри Docker

Опциональный override `compose.tiktok-volume.yaml` хранит только OAuth token fields
в named volume `social-analytics_tiktok_credentials`. Он не зависит от UID mapping каталога
Documents на Mac. API и scheduler используют UID 10001, directory 0700 и files 0600.
Оба writers работают в одном Linux kernel; Darwin flock не координируется с Docker.
Не сочетайте этот override с `compose.tiktok-credentials.yaml` (host bind).

Одноразовый init service с network_mode none запускается с root только для прав
пустого volume. Непустое хранилище с неверными правами он отвергает; existing files
не изменяет. API/scheduler остаются без root, с cap_drop ALL, read-only root filesystem,
no-new-privileges и writable tmpfs. База PostgreSQL использует прежний отдельный volume.

## Первое включение

Сначала выполнить OAuth, настоящий dry run и первый collection целевого аккаунта.
Все четыре read scopes, open_id и expiry metadata должны быть получены от provider,
не угаданы. Создать private DB backup. На Mac использовать project `social-analytics`.

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker compose -p social-analytics --profile scheduler stop api scheduler
.venv/bin/python tools/seed_tiktok_volume.py --confirm-owner --confirm-workers-stopped
```

Перед seed также остановить любые CLI/другие workers. Helper проверяет отсутствие
running API/scheduler в выбранном project. Подтверждения относятся к реальному
целевому owner и всем writers, включая не видимые Compose процессы.
Helper читает только regular owner .env 0600, валидирует grants и expiry metadata,
передаёт allowlisted token fields через stdin. Значения не попадают в argv/stdout.
PostgreSQL/internal key/app secrets в token volume не копируются. `.env` не изменяется.
Повторный seed непустого store запрещён, чтобы не заменить rotated tokens старым .env.

Приватно установить в .env:

```dotenv
TIKTOK_AUTO_REFRESH_ENABLED=true
TIKTOK_RENEWAL_RUNTIME=docker
TIKTOK_CREDENTIAL_STORE=/run/dash-tiktok/.tiktok-credentials
SCHEDULER_ENABLED=true
```

Store path внутри Docker; на Mac он не предназначен для чтения/refresh. Пустой
TIKTOK_ACCESS_TOKEN внутри override принуждает workers читать актуальный store,
а не старый token из .env. Owner open_id остаётся дополнительной проверкой identity.
Выданные ранее access/refresh fields в private .env могут служить bootstrap history;
они больше не являются актуальным runtime source после rotation.

```sh
docker compose -p social-analytics --env-file .env -f compose.yaml -f compose.tiktok-volume.yaml --profile scheduler up --build -d
docker compose -p social-analytics --env-file .env -f compose.yaml -f compose.tiktok-volume.yaml exec -T api python -m app.cli.scheduler --plan
```

Не используйте полный `compose config`/`docker inspect`: они могут показывать
credentials. Для validation используйте `config -q`. После настройки проверить health,
оба collector statuses, dashboard и history scheduler jobs. Config flag не заменяет
live worker health. Токен обновляется по необходимости перед сбором, за 300 seconds
до expiry; отдельного постоянного refresh loop нет. Provider revocation/expired refresh
token требуют нового согласия владельца. Instagram automatic renewal не реализован:
его eligible long-lived token обновляется отдельно внутри API container.

## Повторный запуск и остановка

Во всех дальнейших командах сохранять оба `-f` и project `social-analytics`.
Одного `restart` достаточно для того же container config; изменённый .env требует
`up -d --force-recreate api scheduler` с этими же файлами. Для полного запуска
после Compose recreation использовать `--profile scheduler`.

Не удаляйте named volumes (`down -v`, volume rm, Docker factory reset): в них находятся
реальные данные/актуальные refresh tokens. Обычный stop/start сохраняет их.
Не запускайте одновременно Mac и Docker refresh, включая старые legacy helpers.
Host helper с выбранным Docker store/runtime отвергает refresh; это полезная защита.
При повторной OAuth остановить все workers и провести контролируемую замену store
после проверки owner/grant, а не повторять first-seed command или подставлять старый .env.

## Проверки

Tests seed helper используют fake credentials и mocked subprocess. Проверяются
отсутствие подтверждения, активные workers, symlink/wrong permissions, malformed/future
metadata, лишние scopes, stdin allowlist и отсутствие secret echo. Dashboard config
читает выбранный store без network/refresh и не fallback-ится к stale legacy token.
Изолированный Docker smoke: fake API+scheduled worker выполнили один mocked refresh,
оба прочитали rotation, новый container прочитал сохранённый результат, повторный seed
был отвергнут. Это не тест настоящего provider refresh и не доказательство работы
на Mac во время сна. Локальная система собирает данные только при работающем Docker/Mac.

Официальные правила Compose:
[общие volumes](https://docs.docker.com/reference/compose-file/volumes/) и
[зависимости запуска](https://docs.docker.com/compose/how-tos/startup-order/).
