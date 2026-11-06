#!/usr/bin/env python3
"""합성 OTLP JSON→Alloy 변환→내부 HTTP sink 시험. 운영 접근/본문 로그 없음."""
import ast
from pathlib import Path
import subprocess
import tempfile
import uuid

D = ['docker', '--context', 'colima-billit-verify']
ALLOY = 'grafana/alloy:v1.20.1'
PYTHON = 'python:3.13-slim-bookworm'
CONFIG = Path(__file__).resolve().parents[1] / 'observability/otel/trace-sanitize.alloy.example'
RUNTIME = r'''
import copy, http.server, json, pathlib, socket, sys, time, urllib.request
OUT = pathlib.Path('/tmp/received.json')
class Sink(http.server.BaseHTTPRequestHandler):
 def log_message(self, *args): pass
 def do_POST(self):
  assert self.path == '/v1/traces'
  body = self.rfile.read(int(self.headers['Content-Length']))
  OUT.write_bytes(body)
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{}')
def attr(k,v):
 return {'key':k,'value':{'intValue':str(v)} if isinstance(v,int) else {'stringValue':v}}
def client():
 for _ in range(40):
  try:
   with socket.create_connection(('alloy',4318), timeout=1): break
  except OSError: time.sleep(.25)
 else: raise RuntimeError('OTLP receiver not ready')
 base={'traceId':'0123456789abcdef0123456789abcdef','spanId':'0123456789abcdef',
  'name':'PRIVATE_name','traceState':'vendor=PRIVATE_state','kind':2,
  'startTimeUnixNano':'1700000000000000000','endTimeUnixNano':'1700000000123000000',
  'status':{'code':2,'message':'PRIVATE_error'},
  'attributes':[attr('http.request.method','GET'),attr('http.response.status_code',503),attr('db.system','postgresql'),
   attr('url.full','PRIVATE_url'),attr('db.statement','PRIVATE_sql'),attr('user.id','PRIVATE_user'),
   attr('http.request.header.authorization','PRIVATE_token')],
  'events':[{'name':'PRIVATE_exception','timeUnixNano':'1700000000001000000','attributes':[attr('exception.stacktrace','PRIVATE_stack')]}]}
 child=copy.deepcopy(base);child['spanId']='1123456789abcdef';child['parentSpanId']=base['spanId']
 child['attributes']=[attr('http.request.method','PRIVATE_method'),attr('http.response.status_code','PRIVATE_code'),attr('db.system','PRIVATE_db')]
 linked=copy.deepcopy(base);linked['spanId']='2123456789abcdef';linked['links']=[{'traceId':base['traceId'],'spanId':base['spanId'],'traceState':'vendor=PRIVATE_link','attributes':[attr('token','PRIVATE_link_attr')]}]
 data={'resourceSpans':[{'schemaUrl':'PRIVATE_resource_schema','resource':{'attributes':[attr('service.name','PRIVATE_service'),attr('deployment.environment.name','PRIVATE_env'),attr('host.name','PRIVATE_host')]},
  'scopeSpans':[{'schemaUrl':'PRIVATE_scope_schema','scope':{'name':'PRIVATE_scope','version':'PRIVATE_version','attributes':[attr('scope.secret','PRIVATE_scope_attr')]},'spans':[base,child,linked]}]}]}
 req=urllib.request.Request('http://alloy:4318/v1/traces',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as response: assert response.status==200
 for _ in range(40):
  if OUT.exists(): break
  time.sleep(.25)
 else: raise RuntimeError('sink received no export')
 body=OUT.read_text(); assert 'PRIVATE_' not in body, 'synthetic sensitive marker escaped'
 resource,=json.loads(body)['resourceSpans'];scope,=resource['scopeSpans'];spans=scope['spans']
 assert not resource.get('schemaUrl') and not scope.get('schemaUrl')
 assert scope['scope'].get('name')=='sanitized' and not scope['scope'].get('version') and not scope['scope'].get('attributes')
 attrs={a['key']:a['value']['stringValue'] for a in resource['resource']['attributes']}
 assert attrs=={'service.name':'synthetic','deployment.environment.name':'test'}
 assert len(spans)==2, 'linked span must be dropped, two unlinked spans retained'
 byid={s['spanId']:s for s in spans}
 for original in (base,child):
  span=byid[original['spanId']]
  for field in ('traceId','spanId','startTimeUnixNano','endTimeUnixNano'):
   assert span[field]==original[field], field
  assert span.get('parentSpanId','')==original.get('parentSpanId','')
  assert span['name']=='operation' and not span.get('traceState')
  assert not span.get('events') and not span.get('links') and not span['status'].get('message')
  assert span['status']['code']==2
 assert {a['key'] for a in byid[base['spanId']]['attributes']}=={'http.request.method','http.response.status_code','db.system'}
 assert not byid[child['spanId']].get('attributes')
 print('PASS synthetic fields sanitized; 2 spans retain trace/parent IDs and duration; linked span dropped')
if sys.argv[1]=='server': http.server.HTTPServer(('0.0.0.0',8080),Sink).serve_forever()
else: client()
'''


def d(*args, check=True):
    result = subprocess.run(D + list(args), capture_output=True, text=True, timeout=120)
    if check and result.returncode:
        # 설정 문법 오류만 출력되며 원시 OTLP 본문/도구 debug dump는 출력하지 않는다.
        raise RuntimeError(result.stderr[:3000])
    return result


def main():
    name = 'billit-otel-test-' + uuid.uuid4().hex[:10]
    names = []
    network = name + '-net'
    created_network = False
    success = ''
    try:
        for image in (ALLOY, PYTHON):
            print(d('image','inspect',image,'--format','{{index .RepoDigests 0}}').stdout.strip())
        disk = name + '-disk';names.append(disk)
        space = d('run','--name',disk,'--network','none','--entrypoint','sh',ALLOY,'-c',"df -Pm / | awk 'NR==2 {print $4}'")
        assert int(space.stdout.strip()) >= 1024, 'VM 여유 1 GiB 미만'
        print('available MiB:',space.stdout.strip())
        d('rm','-v',disk);names.remove(disk)
        d('network','create','--internal',network);created_network=True
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            runtime=Path(directory)/'test.py';runtime.write_text(RUNTIME)
            ast.parse(RUNTIME)
            sink=name+'-sink';alloy=name+'-alloy'
            d('create','--name',sink,'--network',network,'--network-alias','sink','--memory','128m',PYTHON,'python','/tmp/test.py','server');names.append(sink)
            d('cp',str(runtime),sink+':/tmp/test.py')
            d('create','--name',alloy,'--network',network,'--network-alias','alloy','--memory','256m',ALLOY,
              'run','--disable-reporting','--storage.path=/tmp/alloy','--server.http.listen-addr=127.0.0.1:12345','/etc/alloy/config.alloy');names.append(alloy)
            d('cp',str(CONFIG),alloy+':/etc/alloy/config.alloy')
            d('start',sink);d('start',alloy)
            d('exec',alloy,'/bin/alloy','validate','/etc/alloy/config.alloy')
            result=d('exec',sink,'python','/tmp/test.py','client')
            success=result.stdout.strip()
    finally:
        for container in reversed(names): d('rm','-fv',container,check=False)
        if created_network: d('network','rm',network,check=False)
        for container in names:
            result=d('container','inspect',container,check=False)
            assert result.returncode != 0 and 'No such container' in result.stderr, '컨테이너 정리 확인 실패'
        if created_network:
            result=d('network','inspect',network,check=False)
            assert result.returncode != 0 and 'not found' in result.stderr, '네트워크 정리 확인 실패'
    print(success+'; exact containers/network cleanup verified')


if __name__ == '__main__': main()
