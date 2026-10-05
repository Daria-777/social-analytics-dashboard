"""Explicit isolated Docker Desktop check; fake credentials, no DB or network."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import time
from uuid import uuid4
import pytest
from app.connectors.tiktok.credentials import CredentialStore,Credential
from app.connectors.tiktok.schemas import Token
from tests.test_tiktok_auth import token_payload

pytestmark=pytest.mark.skipif(os.environ.get('TEST_TIKTOK_DOCKER')!='1',reason='Opt-in isolated Docker bind/lock verification')

GUEST='''from datetime import datetime,timezone
import time
import os
from pathlib import Path
import httpx
from app.config import Settings
from app.connectors.tiktok.credentials import resolve_settings
print('READY',flush=True)
print('UID',os.geteuid(),'DIR',Path('/run/.tiktok-credentials').stat().st_uid,oct(Path('/run/.tiktok-credentials').stat().st_mode & 0o777),flush=True)
def provider(request):
    print('MOCK_REFRESH',flush=True)
    time.sleep(.2)
    return httpx.Response(200,json={'access_token':'docker-fake-new','refresh_token':'docker-fake-refresh','open_id':'test-open','token_type':'Bearer','scope':'user.info.basic,user.info.profile,video.list','expires_in':86400,'refresh_expires_in':31536000})
try:
    result=resolve_settings(Settings(_env_file=None,tiktok_credential_store='/run/.tiktok-credentials',tiktok_auto_refresh_enabled=True,tiktok_renewal_runtime='docker',tiktok_client_key='docker-fake-key',tiktok_client_secret='docker-fake-secret'),allow_refresh=True,transport=httpx.MockTransport(provider))
    assert result.require_tiktok_token()=='docker-fake-new'
    print('NEW_TOKEN_SEEN',flush=True)
except Exception as error:
    print('CHECK_FAILED',type(error).__name__,flush=True)
    raise SystemExit(1)
'''


def test_real_compose_directory_bind_rotation_in_one_docker_kernel(tmp_path):
    executable=shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
    if not Path(executable).is_file():pytest.fail('Docker CLI required for explicitly requested integration')
    project='dash-token-test-'+uuid4().hex[:12]
    directory=tmp_path/'.tiktok-credentials';store=CredentialStore(directory)
    def seed():
        store.seed(Credential.from_token(Token.model_validate(token_payload(expires_in=1)),issued_at=datetime.now(timezone.utc)-timedelta(minutes=10),owner_confirmed=True))
    seed();script=tmp_path/'check.py';script.write_text(GUEST)
    services={}
    guest_uid,guest_gid=(0,0) if sys.platform=='darwin' else (os.getuid(),os.getgid())
    for name in ('worker-a','worker-b'):
        services[name]={'image':'social-analytics-api:latest','pull_policy':'never','user':f'{guest_uid}:{guest_gid}','cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'read_only':True,'network_mode':'none','command':['python','/check.py'],'volumes':[{'type':'bind','source':str(directory),'target':'/run/.tiktok-credentials','bind':{'create_host_path':False}},{'type':'bind','source':str(script),'target':'/check.py','read_only':True}]}
    compose=tmp_path/'compose.json';compose.write_text(json.dumps({'services':services}))
    private_env=tmp_path/'.env.fake';private_env.write_text('');private_env.chmod(0o600)
    command=[executable,'compose','-p',project,'--env-file',str(private_env),'-f',str(compose)]
    environment={key:value for key,value in os.environ.items() if not key.startswith(('INSTAGRAM_','TIKTOK_','POSTGRES_','SCHEDULER_','DASH_')) and key not in ('DATABASE_URL','INTERNAL_API_KEY')}
    def run(*arguments):
        result=subprocess.run(command+list(arguments),env=environment,capture_output=True,text=True,timeout=30)
        assert result.returncode==0, 'Isolated Docker credential check failed; no production configuration involved'
        return result.stdout
    def wait_completed(*names):
        deadline=time.monotonic()+15
        while True:
            rows=[]
            for line in run('ps','-a','--format','json').splitlines():
                value=json.loads(line);rows.extend(value if isinstance(value,list) else [value])
            selected=[row for row in rows if row['Service'] in names]
            if len(selected)==len(names) and all(row['State']=='exited' for row in selected):
                assert all(row['ExitCode']==0 for row in selected),run('logs','--no-log-prefix',*names)
                return
            assert time.monotonic()<deadline,'Guest completion timed out'
            time.sleep(.1)
    try:
        # Mac seed/reseed happens before workers start; all renewal writers share Linux flock.
        run('up','-d','--force-recreate','worker-a','worker-b')
        wait_completed('worker-a','worker-b')
        logs=run('logs','--no-log-prefix','worker-a','worker-b')
        assert logs.count('MOCK_REFRESH')==1 and logs.count('NEW_TOKEN_SEEN')==2 and 'CHECK_FAILED' not in logs
        assert store.read().access_token.get_secret_value()=='docker-fake-new'
        assert directory.stat().st_mode & 0o777==0o700 and store.path.stat().st_mode & 0o777==0o600
    finally:
        run('down','--remove-orphans')
