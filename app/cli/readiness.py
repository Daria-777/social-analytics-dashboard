"""Offline configuration checklist: no connections, writes or credential values."""
import argparse
import json
import shutil
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from pydantic import ValidationError
from app.config import Settings


def present(value):
    if hasattr(value, 'get_secret_value'): value=value.get_secret_value()
    return bool(value and str(value).strip())


def report(settings, *, server=False):
    database='missing_explicit_url'
    if 'database_url' in settings.model_fields_set and present(settings.database_url):
        try:
            url=make_url(settings.database_url.get_secret_value())
            database='configured_not_connected' if url.get_backend_name()=='postgresql' and url.database else 'postgresql_required'
        except (ValueError,ArgumentError): database='invalid_url'
    platforms={}
    for platform in ('instagram','tiktok'):
        try:
            getattr(settings,'require_'+platform+'_oauth')()
            oauth='configured_unverified'
        except ValueError: oauth='missing_or_invalid'
        platforms[platform]={'token':'set_unverified' if present(getattr(settings,platform+'_access_token')) else 'missing','oauth':oauth}
    if settings.tiktok_credential_store:platforms['tiktok']['token']='private_store_unverified'
    platforms['tiktok']['credential_source']='private_store_unverified' if settings.tiktok_credential_store else 'legacy_env'
    platforms['tiktok']['renewal_runtime']=settings.tiktok_renewal_runtime
    platforms['tiktok']['auto_refresh']='enabled_configuration_unverified' if settings.tiktok_auto_refresh_enabled else 'disabled'
    platforms['tiktok']['mode']=settings.tiktok_oauth_mode
    platforms['tiktok']['callback']=('http_loopback_configuration_unverified' if settings.tiktok_oauth_mode=='desktop' else 'public_https_configuration_unverified') if platforms['tiktok']['oauth']=='configured_unverified' else 'missing_or_invalid'
    platforms['tiktok']['refresh_token']='private_store_unverified' if settings.tiktok_credential_store else ('set_unverified' if present(settings.tiktok_refresh_token) else 'missing')
    platforms['tiktok']['scopes']='configured_grant_unverified' if 'tiktok_scopes' in settings.model_fields_set else 'grant_not_recorded'
    internal='set_unverified' if present(settings.internal_api_key) else 'missing'
    domain='set_dns_unverified' if present(settings.dash_domain) else 'missing'
    complete=database=='configured_not_connected' and internal!='missing' and (not server or domain!='missing')
    docker=bool(shutil.which('docker') or Path('/Applications/Docker.app/Contents/Resources/bin/docker').is_file())
    steps=[]
    if not docker: steps.append('Запустите Docker Desktop на Mac; CLI binary не найден в PATH. Daemon и deployment ещё не проверены.')
    if server and domain=='missing': steps.append('Заполните DASH_DOMAIN настоящим DNS hostname в private .env; DNS/TLS ещё не проверены.')
    if database!='configured_not_connected': steps.append('Настройте явный PostgreSQL DATABASE_URL в локальном .env; затем проверьте /health в выбранном runtime.')
    if internal=='missing': steps.append('Создайте локальный INTERNAL_API_KEY для API/dashboard; не отправляйте значение в чат.')
    if platforms['instagram']['token']=='missing': steps.append('Instagram: выполните owner setup и app.cli.instagram_auth либо официальный manual bootstrap (README).')
    if platforms['tiktok']['token']=='missing':
        steps.append('TikTok: настройте Desktop Login Kit, exact HTTP loopback redirect и выполните на Mac python -m app.cli.tiktok_auth --mode desktop.' if settings.tiktok_oauth_mode=='desktop' else 'TikTok: настройте Web Login Kit/Display API + exact HTTPS redirect и выполните python -m app.cli.tiktok_auth --mode web.')
    if platforms['tiktok']['refresh_token']=='missing': steps.append('TikTok: сохраните refresh token через OAuth helper; без него manual renewal потребует нового login.')
    steps.append('После owner authorization: python -m app.cli.collect_instagram --dry-run и python -m app.cli.collect_tiktok --dry-run; identity/scopes/access ещё не проверены.')
    steps.append('После genuine collection: включите opt-in scheduler. При private store + opt-in renewal workers читают новые credentials перед collection; verified metadata/store permissions/refresh access ещё не проверены.' if settings.tiktok_credential_store else 'После genuine collection: включите opt-in scheduler. В legacy env режиме TikTok manual refresh и пересоздание API/scheduler обязательны; автономная работа надолго не подтверждена.')
    return {'configuration_complete':complete,'access_verified':False,'database':database,'internal_access':internal,'server_domain':domain,**platforms,'scheduler':('enabled_config_unverified' if complete and all(p['token']!='missing' for p in platforms.values()) else 'enabled_config_incomplete') if settings.scheduler_enabled else 'disabled','docker':'binary_present_daemon_unchecked' if docker else 'not_found','network':'not_attempted','writes':'none','next_steps':steps}


def main(argv=None,*,settings=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',default='.env')
    parser.add_argument('--server',action='store_true',help='Require a server domain in addition to local runtime configuration')
    args=parser.parse_args(argv)
    try: result=report(settings or Settings(_env_file=args.env_file), server=args.server)
    except (ValueError,ValidationError,OSError):
        print(json.dumps({'configuration':'invalid','access_verified':False,'next_steps':['Исправьте формат локальной конфигурации; values скрыты.']},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['configuration_complete'] else 2


if __name__=='__main__': raise SystemExit(main())
