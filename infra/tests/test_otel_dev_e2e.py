#!/usr/bin/env python3
"""선택 개발 구성의 실제 Alloy/Tempo 시험. 전용 VM·합성 데이터만 사용한다."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
OTEL = HERE.parent / 'observability/otel'
D = ['docker', '--context', 'colima-billit-verify']
TEMPO = 'grafana/tempo@sha256:ef71057012c3135fce32cc227fb027d69b94b8d387f581242916f449199febc8'
ALLOY = 'grafana/alloy@sha256:2aa2099af76c0098d4af7a4d6e48f86cb66dc1a000222ad927a1c67c6542d13f'
NGINX = 'nginx@sha256:564a09935b00f058ca1b28c742169ba817499baa0479807bf7f373fe2804fbf7'
PYTHON = 'python:3.13-slim-bookworm'


def d(*args, check=True):
    result = subprocess.run(D + list(args), capture_output=True, text=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(result.stderr[:2000] or result.stdout[:2000])
    return result


def client_code():
    spec = importlib.util.spec_from_file_location('otel_existing_fixture', HERE / 'otel-tempo-e2e.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.runtime()
    text = text.replace("attr('service.name','PRIVATE_service')", "attr('service.name','infra-validation')")
    text = text.replace("'service.name':'synthetic','deployment.environment.name':'test'",
                        "'service.name':'infra-validation','deployment.environment.name':'dev'")
    return text


PROBES = r'''
import json,time,urllib.request,urllib.error,uuid
def send(tid,service='infra-validation'):
 now=time.time_ns()
 payload={'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':service}}]},
 'scopeSpans':[{'scope':{},'spans':[{'traceId':tid,'spanId':'1234567890abcdef','name':'PRIVATE_name','kind':2,'startTimeUnixNano':str(now-1000000),'endTimeUnixNano':str(now)}]}]}]}
 req=urllib.request.Request('http://alloy:4318/v1/traces',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=5) as response: assert response.status==200
def lookup(tid,exists=True):
 for _ in range(80 if exists else 4):
  try:
   req=urllib.request.Request('http://tempo:3200/api/v2/traces/'+tid,headers={'Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=5) as response:d=json.load(response)
   if d.get('trace',{}).get('resourceSpans'):
    assert exists,'unapproved service was stored'
    assert 'PRIVATE_' not in json.dumps(d)
    return
  except urllib.error.HTTPError as e:
   assert e.code in (404,500,502,503),e.code
  except (urllib.error.URLError, TimeoutError): pass
  time.sleep(.25)
 assert not exists,'trace not stored'
'''


def main():
    prefix = 'billit-otel-dev-' + uuid.uuid4().hex[:10]
    network, volume = prefix+'-net', prefix+'-data'
    config_volume = prefix+'-config'
    ingress, proxy = prefix+'-ingress', prefix+'-proxy'
    tempo, alloy, client = prefix+'-tempo', prefix+'-alloy', prefix+'-client'
    owned = []
    net_created = vol_created = cfg_created = ingress_created = False
    try:
        for img in (TEMPO, ALLOY, PYTHON, NGINX): d('image','inspect',img)
        d('network','create','--internal',network); net_created=True
        d('network','create',ingress); ingress_created=True
        d('volume','create',volume); vol_created=True
        d('volume','create',config_volume); cfg_created=True
        # 이 시험 전용 빈 volume만 초기화한다. 호스트 경로/기존 볼륨을 사용하지 않는다.
        init=prefix+'-init';owned.append(init)
        d('create','--name',init,'--network','none','-v',volume+':/data','-v',config_volume+':/config',PYTHON,
          'python','-c',"import os;os.chown('/data',10001,10001);os.chmod('/data',0o700)")
        d('cp',str(OTEL/'tempo.dev.yaml'),init+':/config/tempo.yaml')
        d('cp',str(OTEL/'collector.alloy'),init+':/config/collector.alloy')
        d('cp',str(OTEL/'proxy.conf'),init+':/config/proxy.conf')
        d('start','-a',init)
        owned.extend([tempo,alloy,client,proxy])
        d('create','--name',tempo,'--network',network,'--network-alias','tempo','--memory','512m','--cpus','0.35',
          '--user','10001:10001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
          '--tmpfs','/tmp:uid=10001,gid=10001,mode=0700,size=16m','-v',volume+':/var/tempo','-v',config_volume+':/config:ro',TEMPO,'-config.file=/config/tempo.yaml')
        # Config verify는 시작 전 같은 고정 binary에 인자를 전달한다.
        verify=prefix+'-verify';owned.append(verify)
        d('create','--name',verify,'--network','none','-v',config_volume+':/config:ro',TEMPO,'-config.file=/config/tempo.yaml','-config.verify=true')
        d('start','-a',verify)
        assert d('inspect','-f','{{.State.ExitCode}}',verify).stdout.strip()=='0'
        d('create','--name',alloy,'--network',network,'--network-alias','collector','--memory','256m','--cpus','0.15',
          '--user','65534:65534','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
          '--tmpfs','/tmp:uid=65534,gid=65534,mode=0700,size=16m',
          '--tmpfs','/var/lib/alloy:uid=65534,gid=65534,mode=0700,size=32m','-v',config_volume+':/config:ro',ALLOY,
          'run','--disable-reporting','--storage.path=/var/lib/alloy','--server.http.listen-addr=0.0.0.0:12345','/config/collector.alloy')
        d('create','--name',proxy,'--network',ingress,'--memory','64m','--cpus','0.05',
          '--pids-limit','32','--user','101:101','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--tmpfs','/tmp:uid=101,gid=101,mode=0700,size=8m',
          '-v',config_volume+':/config:ro','-p','127.0.0.1::3200','-p','127.0.0.1::4318',
          '-p','127.0.0.1::12346','--entrypoint','nginx',NGINX,
          '-c','/config/proxy.conf','-g','daemon off;')
        d('network','connect',network,proxy)
        # Host network is used only by the synthetic client: tests VM loopback, not container DNS.
        d('create','--name',client,'--network','host','--memory','128m',PYTHON,'sleep','300')
        d('start',tempo);d('start',alloy);d('start',proxy);d('start',client)
        d('exec',alloy,'/bin/alloy','validate','/config/collector.alloy')
        d('exec',proxy,'nginx','-t','-c','/config/proxy.conf')
        mappings=json.loads(d('inspect',proxy).stdout)[0]['NetworkSettings']['Ports']
        ports={}
        for port in (3200,4318,12346):
            binding,=mappings[str(port)+'/tcp']
            assert binding['HostIp']=='127.0.0.1'
            ports[port]=binding['HostPort']
        for name in (tempo,alloy):
            inspected=json.loads(d('inspect',name).stdout)[0]
            assert set(inspected['NetworkSettings']['Networks'])=={network}
            assert not any(inspected['NetworkSettings']['Ports'].values())
        def host_urls(code):
            return code.replace('http://tempo:3200', 'http://127.0.0.1:'+ports[3200]).replace(
                'http://alloy:4318','http://127.0.0.1:'+ports[4318]).replace("('alloy',4318)","('127.0.0.1',"+ports[4318]+")")
        probes=host_urls(PROBES)
        with tempfile.TemporaryDirectory(prefix=prefix) as temp:
            path=Path(temp)/'client.py';path.write_text(host_urls(client_code()))
            d('cp',str(path),client+':/tmp/client.py')
        d('exec',client,'python','/tmp/client.py','client')
        check = probes + "\nwith urllib.request.urlopen('http://127.0.0.1:"+ports[12346]+"/-/ready') as r: assert r.status==200\n"
        # Proxy exposes only fixed endpoints; unknown paths cannot select a remote destination.
        check += "\nfor port,path in [("+ports[4318]+",'/v1/logs'),("+ports[12346]+",'/debug/pprof/')]:\n try: urllib.request.urlopen('http://127.0.0.1:'+str(port)+path);raise AssertionError('unexpected route')\n except urllib.error.HTTPError as e: assert e.code==404\n"
        d('exec',client,'python','-c',check)
        # 요청 상한·허용되지 않은 서비스가 저장되지 않음을 확인한다.
        denied=uuid.uuid4().hex
        code=probes+f"\nsend('{denied}','unapproved-app');lookup('{denied}',False)\n"+r'''
try:
 req=urllib.request.Request('http://alloy:4318/v1/traces',data=json.dumps({'resourceSpans':[], 'padding':'x'*(1048576+1)}).encode(),headers={'Content-Type':'application/json'})
 urllib.request.urlopen(req,timeout=5)
 raise AssertionError('oversized request accepted')
except urllib.error.HTTPError as e:
 body=e.read().decode()
 assert e.code==413 or (e.code==400 and 'body too large' in body.lower()),(e.code,body[:300])
'''
        d('exec',client,'python','-c',host_urls(code))
        # 저장한 trace가 Tempo 프로세스 재시작 뒤 조회되는지 확인한다.
        d('restart',tempo)
        d('exec',client,'python','-c',probes+"\nlookup('0123456789abcdef0123456789abcdef')")
        # 짧은 저장소 장애 동안 메모리 큐에 둔 trace가 재시도 후 저장되는지 확인한다.
        queued=uuid.uuid4().hex
        d('stop',tempo)
        d('exec',client,'python','-c',probes+f"\nsend('{queued}')")
        d('start',tempo)
        d('exec',client,'python','-c',probes+f"\nlookup('{queued}')")
        print('PASS host loopback ingress/health/query, internal-only workloads, proxy route restrictions, sanitize/IDs/duration, service rejection, body limit, Tempo restart persistence, bounded retry recovery')
    except Exception:
        print(d('logs','--tail','20',proxy,check=False).stderr[:2000])
        raise
    finally:
        for name in reversed(owned): d('rm','-fv',name,check=False)
        if net_created: d('network','rm',network)
        if ingress_created: d('network','rm',ingress)
        if vol_created: d('volume','rm',volume)
        if cfg_created: d('volume','rm',config_volume)
        remaining=d('container','ls','-a','--format','{{.Names}}').stdout.splitlines()
        assert not set(owned).intersection(remaining),'owned containers remain'
        if net_created: assert network not in d('network','ls','--format','{{.Name}}').stdout.splitlines()
        if vol_created: assert volume not in d('volume','ls','--format','{{.Name}}').stdout.splitlines()
        if cfg_created: assert config_volume not in d('volume','ls','--format','{{.Name}}').stdout.splitlines()
        if ingress_created: assert ingress not in d('network','ls','--format','{{.Name}}').stdout.splitlines()
    print('PASS exact cleanup; operational filesystem/mount, Grafana UI, real app and 6h retention not covered')


if __name__ == '__main__': main()
