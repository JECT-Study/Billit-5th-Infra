#!/usr/bin/env python3
"""합성 OTLP→실제 Alloy 정제→Tempo 저장/조회. 운영/앱/Grafana 검증 아님."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sanitize_fixture', HERE / 'otel-sanitize-e2e.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)  # 해당 모듈 main 가드 확인: import 시 컨테이너 실행 없음.
TEMPO = 'grafana/tempo@sha256:ef71057012c3135fce32cc227fb027d69b94b8d387f581242916f449199febc8'
D = ['docker', '--context', 'colima-billit-verify']


def runtime():
    text = fixture.RUNTIME
    text = text.replace('import copy,', 'import base64, copy,')
    anchor = " base={'traceId'"
    assert anchor in text
    readiness = ''' for _ in range(45):
  try:
   with urllib.request.urlopen('http://tempo:3200/ready',timeout=2) as response:
    if response.status==200: break
  except (OSError,TimeoutError): time.sleep(1)
 else: raise RuntimeError('Tempo readiness timeout')
 now=time.time_ns()
'''
    text = text.replace(anchor, readiness + anchor)
    text = text.replace("'1700000000000000000'", 'str(now-123000000)').replace("'1700000000123000000'", 'str(now)')
    start = text.index(' for _ in range(40):\n  if OUT.exists()')
    end = text.index(" resource,=json.loads(body)", start)
    query = ''' for _ in range(45):
  try:
   request=urllib.request.Request('http://tempo:3200/api/v2/traces/'+base['traceId'],headers={'Accept':'application/json'})
   with urllib.request.urlopen(request,timeout=5) as response: result=json.load(response)
   if result.get('trace',{}).get('resourceSpans'): break
  except (OSError,TimeoutError): pass
  time.sleep(1)
 else: raise RuntimeError('Tempo trace lookup timeout')
 assert 'PRIVATE_' not in json.dumps(result), 'synthetic sensitive marker reached Tempo'
 body=json.dumps(result['trace'])
 # Tempo protobuf JSON ID 표현은 bytes 의미로 비교한다(원문 로그 출력 없음).
 for resource in result['trace']['resourceSpans']:
  for scope in resource['scopeSpans']:
   for span in scope['spans']:
    for field in ('traceId','spanId','parentSpanId'):
     if span.get(field) and len(span[field]) not in (16,32):
      span[field]=base64.b64decode(span[field],validate=True).hex()
    if span.get('parentSpanId')=='0000000000000000': span.pop('parentSpanId')
    if span.get('status',{}).get('code')=='STATUS_CODE_ERROR': span['status']['code']=2
 body=json.dumps(result['trace'])
'''
    text = text[:start] + query + text[end:]
    ast.parse(text)
    return text


def d(*args, check=True):
    out = subprocess.run(D + list(args), capture_output=True, text=True, timeout=150)
    if check and out.returncode:
        raise RuntimeError(out.stderr[:3000])
    return out


def main():
    name = 'billit-otel-tempo-' + uuid.uuid4().hex[:10]
    names = []
    network = name + '-net'
    created = False
    summary = ''
    try:
        for image in (TEMPO, fixture.ALLOY, fixture.PYTHON):
            d('image', 'inspect', image)
        disk=name+'-disk';names.append(disk)
        space=d('run','--name',disk,'--network','none','--entrypoint','sh',fixture.ALLOY,'-c',"df -Pm / | awk 'NR==2 {print $4}'")
        assert int(space.stdout.strip()) >= 1024, '1 GiB 미만: 중단'
        print('available MiB:',space.stdout.strip(),flush=True)
        d('rm','-v',disk);names.remove(disk)
        d('network','create','--internal',network);created=True
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            root=Path(directory)
            config=fixture.CONFIG.read_text()
            assert config.count('http://sink:8080')==1
            (root/'config.alloy').write_text(config.replace('http://sink:8080','http://tempo:4318'))
            (root/'client.py').write_text(runtime())
            tempo=name+'-tempo';alloy=name+'-alloy';client=name+'-client'
            d('create','--name',tempo,'--network',network,'--network-alias','tempo','--memory','512m',
              '--tmpfs','/var/tempo:uid=10001,gid=10001,mode=0700,size=128m',TEMPO,'-config.file=/tmp/tempo.yaml');names.append(tempo)
            d('cp',str(HERE.parent/'observability/otel/tempo.synthetic.yaml'),tempo+':/tmp/tempo.yaml')
            d('create','--name',alloy,'--network',network,'--network-alias','alloy','--memory','256m',fixture.ALLOY,
              'run','--disable-reporting','--storage.path=/tmp/alloy','--server.http.listen-addr=127.0.0.1:12345','/etc/alloy/config.alloy');names.append(alloy)
            d('cp',str(root/'config.alloy'),alloy+':/etc/alloy/config.alloy')
            d('create','--name',client,'--network',network,'--memory','128m',fixture.PYTHON,'python','/tmp/client.py','client');names.append(client)
            d('cp',str(root/'client.py'),client+':/tmp/client.py')
            d('start',tempo);d('start',alloy)
            d('exec',alloy,'/bin/alloy','validate','/etc/alloy/config.alloy')
            output=d('start','-a',client)
            code=d('inspect','--format','{{.State.ExitCode}}',client).stdout.strip()
            assert code=='0', output.stderr[:1500]
            summary=output.stdout.strip()
    finally:
        for container in reversed(names): d('rm','-fv',container,check=False)
        if created: d('network','rm',network,check=False)
        for container in names:
            result=d('container','inspect',container,check=False)
            assert result.returncode != 0 and 'No such container' in result.stderr, '정리 조회 실패'
        if created:
            result=d('network','inspect',network,check=False)
            assert result.returncode != 0 and 'not found' in result.stderr, '정리 조회 실패'
    print(summary+'; Alloy→Tempo API v2 query PASS; exact cleanup verified')


if __name__ == '__main__': main()
