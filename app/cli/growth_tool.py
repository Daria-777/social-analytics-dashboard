"""Allowlisted Growth Analyst tool. Uses only a dedicated HTTPS service credential.

No database, shell, collector, OAuth, deletion, or historical-update actions.
"""
import argparse
import json
import os
from pathlib import Path
import stat
from uuid import UUID
from urllib.parse import urlsplit
import httpx

DEFAULT_CONFIG=Path(os.environ.get('DASH_GROWTH_CONNECTION_FILE',Path.home()/'.config/dash-growth/connection.json'))


def connection(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.getuid():
            raise ValueError('Private connection file required')
        data=json.load(stream)
    uri=urlsplit(data['base_url'])
    if uri.scheme!='https' or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment or uri.path not in ('','/'):
        raise ValueError('HTTPS origin required')
    key=data['api_key']
    if not isinstance(key,str) or len(key)<10 or any(c in key for c in '\r\n'):
        raise ValueError('Invalid service credential')
    return data['base_url'].rstrip('/'),key


def main(argv=None,*,transport=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    commands=parser.add_subparsers(dest='action',required=True)
    resolve=commands.add_parser('resolve');resolve.add_argument('--platform',choices=['instagram','tiktok'],required=True);resolve.add_argument('--platform-content-id',required=True)
    for action in ('context','analyses','create-analysis'):
        command=commands.add_parser(action);command.add_argument('--content-id',type=UUID,required=True)
        if action=='create-analysis':command.add_argument('--input',type=Path,required=True)
        else:command.add_argument('--offset',type=int,default=0);command.add_argument('--limit',type=int,default=100)
    commands.add_parser('schema')
    args=parser.parse_args(argv)
    if args.action=='schema':
        from app.growth_schemas import AnalysisCreate
        print(json.dumps(AnalysisCreate.model_json_schema(),ensure_ascii=False));return 0
    try:
        base,key=connection(args.config)
        params={};body=None;method='GET'
        if args.action=='resolve':
            path='/growth/content/resolve';params={'platform':args.platform,'platform_content_id':args.platform_content_id}
        else:
            path=f'/growth/content/{args.content_id}/'+('context' if args.action=='context' else 'analyses')
            if args.action in ('context','analyses'):params={'offset':args.offset,'limit':args.limit}
            if args.action=='create-analysis':
                from app.growth_schemas import AnalysisCreate
                body=AnalysisCreate.model_validate_json(args.input.read_text()).model_dump(mode='json');method='POST'
        with httpx.Client(transport=transport,timeout=45,follow_redirects=False,trust_env=False) as client:
            response=client.request(method,base+path,params=params,json=body,headers={'X-API-Key':key})
            if response.status_code not in (200,201):
                print(json.dumps({'status':'FAILED','http_status':response.status_code,'action':args.action}));return 1
            data=response.json()
            if args.action=='create-analysis' and (not isinstance(data,dict) or not data.get('id')):
                raise ValueError('Backend did not confirm persisted identity')
            print(json.dumps({'status':'CONFIRMED','action':args.action,'http_status':response.status_code,'data':data},ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,httpx.HTTPError):
        print(json.dumps({'status':'FAILED','action':args.action,'error':'Private connection, payload, or HTTPS request failed'}));return 1


if __name__=='__main__':raise SystemExit(main())
