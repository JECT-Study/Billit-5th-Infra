#!/usr/bin/env python3
"""Tempo3.1.1 격리 저장/조회 시험. 실제 앱·Alloy·Grafana 시험과 구분한다."""
import json
from pathlib import Path
import subprocess
import uuid

D = ['docker', '--context', 'colima-billit-verify']
IMAGE = 'grafana/tempo@sha256:ef71057012c3135fce32cc227fb027d69b94b8d387f581242916f449199febc8'
PYTHON = 'python@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72'
prefix = 'billit-tempo-' + uuid.uuid4().hex[:10]
names = [prefix, prefix + '-client']


def run(*args, data=None):
    return subprocess.run(D + list(args), input=data, capture_output=True, text=True, timeout=90, check=True)


client = r'''
import json,time,urllib.request,urllib.error
base='http://127.0.0.1:3200'
for _ in range(45):
 try:
  urllib.request.urlopen(base+'/ready',timeout=2).read();break
 except (urllib.error.URLError,TimeoutError):time.sleep(1)
else:raise RuntimeError('readiness timeout')
tid='1234567890abcdef1234567890abcdef';now=time.time_ns()
spans=[{'traceId':tid,'spanId':'1234567890abcdef','name':'synthetic-http','kind':2,'startTimeUnixNano':str(now-2000000),'endTimeUnixNano':str(now)},
{'traceId':tid,'spanId':'2234567890abcdef','parentSpanId':'1234567890abcdef','name':'synthetic-db','kind':3,'startTimeUnixNano':str(now-1000000),'endTimeUnixNano':str(now)}]
payload={'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'billit-synthetic'}}]},'scopeSpans':[{'scope':{'name':'synthetic-fixture'},'spans':spans}]}]}
r=urllib.request.Request('http://127.0.0.1:4318/v1/traces',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
response=urllib.request.urlopen(r,timeout=5)
assert response.status==200
for _ in range(45):
 try:
  request=urllib.request.Request(base+'/api/v2/traces/'+tid,headers={'Accept':'application/json'})
  result=json.load(urllib.request.urlopen(request,timeout=5))
  text=json.dumps(result)
  if 'synthetic-http' in text and 'synthetic-db' in text:
   print(json.dumps({'ready':True,'ingest_http':200,'trace_lookup':True,'two_synthetic_spans':True}));break
 except (urllib.error.URLError,TimeoutError):pass
 time.sleep(1)
else:raise RuntimeError('trace lookup timeout')
'''
try:
    run('create', '--name', names[0], '--network', 'none', '--memory', '512m', '--cpus', '0.5',
        '--tmpfs', '/var/tempo:uid=10001,gid=10001,mode=0700,size=128m', IMAGE,
        '-config.file=/tmp/tempo.yaml')
    run('cp', str(Path(__file__).resolve().parents[1] / 'observability/otel/tempo.synthetic.yaml'), names[0] + ':/tmp/tempo.yaml')
    run('start', names[0])
    result = run('run', '--name', names[1], '--network', 'container:' + names[0], '--memory', '96m', '-i', PYTHON, 'python', '-', data=client)
    summary = json.loads(result.stdout)
finally:
    for name in reversed(names):
        subprocess.run(D + ['rm', '-fv', name], capture_output=True)
    remaining = run('container', 'ls', '-a', '--format', '{{.Names}}').stdout.splitlines()
    if set(names).intersection(remaining):
        raise RuntimeError('owned test containers remain')
print(json.dumps({'result':summary,'cleanup_verified':True,'not_verified':['Alloy sanitization path','Javaagent app instrumentation','Grafana UI','retention and restart','production resources']}))
