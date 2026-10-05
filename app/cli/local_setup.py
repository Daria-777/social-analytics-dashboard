"""Create private local credentials once, or copy the owner key without displaying it."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
from dotenv import dotenv_values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--copy-key', action='store_true')
    args = parser.parse_args(argv)
    target = Path(args.env_file)
    try:
        if args.copy_key:
            key = dotenv_values(target).get('INTERNAL_API_KEY')
            if not key or not key.strip():
                print('Owner key отсутствует.'); return 2
            subprocess.run(['pbcopy'], input=key.encode(), check=True)
            print('Owner key скопирован в буфер обмена; вставьте в форму входа и очистите буфер.')
            return 0
        password = secrets.token_hex(32)
        key = secrets.token_urlsafe(48)
        values = {
            'POSTGRES_USER': 'dash', 'POSTGRES_DB': 'dash',
            'POSTGRES_PASSWORD': password,
            'DATABASE_URL': f'postgresql+psycopg://dash:{password}@db:5432/dash',
            'INTERNAL_API_KEY': key, 'DISPLAY_TIMEZONE': 'UTC',
            'SCHEDULER_ENABLED': 'false', 'INSTAGRAM_ACCESS_TOKEN': '',
            'INSTAGRAM_USER_ID': '', 'TIKTOK_ACCESS_TOKEN': '',
            'TIKTOK_OPEN_ID': '', 'TIKTOK_REFRESH_TOKEN': '',
        }
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            print('Существующий .env сохранён без изменений.'); return 0
        with os.fdopen(fd, 'w') as stream:
            stream.write(''.join(f'{name}={value}\n' for name, value in values.items()))
        print('Создан private .env (0600). Provider tokens пустые, scheduler выключен.')
        return 0
    except (OSError, subprocess.SubprocessError):
        print('Локальная настройка не выполнена; проверьте доступ к файлу/буферу обмена.'); return 2


if __name__ == '__main__':
    raise SystemExit(main())
