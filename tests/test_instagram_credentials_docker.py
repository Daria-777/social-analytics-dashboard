"""Two isolated Linux workers; fake Instagram tokens, no DB, no network."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import pytest
from app.connectors.instagram.credentials import CredentialStore, Credential
from app.connectors.instagram.auth import SCOPES

pytestmark=pytest.mark.skipif(os.environ.get('TEST_INSTAGRAM_DOCKER')!='1',reason='Opt-in isolated Docker credential lock verification')

GUEST='''import httpx,time
from app.config import Settings
from app.connectors.instagram.credentials import resolve_settings
def provider(request):
    print('MOCK_REFRESH',flush=True)
    time.sleep(.5)
    return httpx.Response(200,json={'access_token':'fake-rotated','expires_in':5184000})
settings=Settings(_env_file=None,instagram_credential_store='/run/.instagram-credentials',instagram_auto_refresh_enabled=True,instagram_renewal_runtime='docker',instagram_user_id='123')
result=resolve_settings(settings,allow_refresh=True,transport=httpx.MockTransport(provider))
assert result.require_instagram_token()=='fake-rotated'
print('ROTATED_TOKEN_SEEN',flush=True)
'''


def test_independent_docker_workers_share_atomic_rotation(tmp_path):
    store=CredentialStore(tmp_path/'.instagram-credentials')
    store.seed(Credential(access_token='fake-old',expires_in=5184000,issued_at=datetime.now(timezone.utc)-timedelta(days=54),user_id='123',scopes=list(SCOPES)))
    script=tmp_path/'check.py';script.write_text(GUEST)
    guest_uid=0 if sys.platform=='darwin' else os.getuid()
    services={name:{'image':'dash-local-api:latest','pull_policy':'never','user':str(guest_uid),'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'read_only':True,'network_mode':'none','command':['python','/check.py'],'volumes':[{'type':'bind','source':str(store.directory),'target':'/run/.instagram-credentials','bind':{'create_host_path':False}},{'type':'bind','source':str(script),'target':'/check.py','read_only':True}]} for name in ['worker-a','worker-b']}
    compose=tmp_path/'compose.json';compose.write_text(json.dumps({'services':services}))
    env_file=tmp_path/'.env.fake';env_file.write_text('');env_file.chmod(0o600)
    environment={k:v for k,v in os.environ.items() if not k.startswith(('INSTAGRAM_','TIKTOK_','POSTGRES_','SCHEDULER_','DASH_')) and k not in ('DATABASE_URL','INTERNAL_API_KEY')}
    command=['docker','compose','-p','dash-ig-test-'+uuid4().hex[:12],'--env-file',str(env_file),'-f',str(compose)]
    def run(*args):
        result=subprocess.run(command+list(args),env=environment,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,'Isolated Docker verification failed'
        return result.stdout
    try:
        run('up','-d','worker-a','worker-b')
        deadline=time.monotonic()+20
        while True:
            rows=[]
            for line in run('ps','-a','--format','json').splitlines():
                value=json.loads(line);rows.extend(value if isinstance(value,list) else [value])
            if len(rows)==2 and all(r['State']=='exited' for r in rows):
                assert all(r['ExitCode']==0 for r in rows),run('logs','--no-log-prefix')
                break
            assert time.monotonic()<deadline,'Isolated workers timed out'
            time.sleep(.2)
        logs=run('logs','--no-log-prefix')
        assert logs.count('MOCK_REFRESH')==1 and logs.count('ROTATED_TOKEN_SEEN')==2
        assert store.read().access_token.get_secret_value()=='fake-rotated'
        assert store.path.stat().st_mode & 0o777==0o600
    finally:run('down','--remove-orphans')
