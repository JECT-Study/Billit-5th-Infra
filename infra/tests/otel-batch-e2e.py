#!/usr/bin/env python3
"""기존 격리 정제시험에65span 분할 전달 검증 추가. 운영/부하시험 아님."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('sanitize_batch', Path(__file__).with_name('otel-sanitize-e2e.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

EXTRA = r'''
 batches=pathlib.Path('/tmp/batches.jsonl')
 batches.unlink(missing_ok=True)
 data['resourceSpans'][0]['scopeSpans'][0]['spans']=[]
 for i in range(65):
  span=copy.deepcopy(base);span['spanId']=format(i+100,'016x')
  data['resourceSpans'][0]['scopeSpans'][0]['spans'].append(span)
 req=urllib.request.Request('http://alloy:4318/v1/traces',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as response: assert response.status==200
 for _ in range(40):
  records=[json.loads(line) for line in batches.read_text().splitlines()] if batches.exists() else []
  if sum(r['count'] for r in records)==65: break
  time.sleep(.25)
 else: raise RuntimeError('65 spans not delivered')
 assert all(0<r['count']<=32 for r in records), 'batch exceeded32'
 ids=[sid for r in records for sid in r['ids']]
 assert len(ids)==len(set(ids))==65, 'duplicate/lost span'
 assert all(not r['sensitive'] for r in records)
 print('PASS65unique spans; max batch32; no sensitive marker')
'''

def main():
    text=fixture.RUNTIME.replace('  OUT.write_bytes(body)', '''  OUT.write_bytes(body)
  spans=[s for r in json.loads(body)['resourceSpans'] for scope in r['scopeSpans'] for s in scope['spans']]
  with pathlib.Path('/tmp/batches.jsonl').open('a') as f:
   f.write(json.dumps({'count':len(spans),'ids':[s['spanId'] for s in spans],'sensitive':b'PRIVATE_' in body})+'\\n')''')
    marker="if sys.argv[1]=='server':"
    assert text.count(marker)==1
    fixture.RUNTIME=text.replace(marker,EXTRA+'\n'+marker)
    fixture.main()

if __name__=='__main__':main()
