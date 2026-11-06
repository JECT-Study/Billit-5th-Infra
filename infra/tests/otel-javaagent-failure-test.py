#!/usr/bin/env python3
"""합성 OTLP503/지연 수신기에서 HTTP 앱 요청 성공 확인. 운영 장애를 만들지 않는다."""
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

spec = importlib.util.spec_from_file_location('agent_http_fixture', Path(__file__).with_name('otel-javaagent-http-test.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

class Collector(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if self.path != '/v1/traces' or not 0 < length < 1048576:
            self.send_error(400);return
        self.rfile.read(length)  # 합성 protobuf만 수신·즉시 폐기. 원문 저장/출력 없음.
        self.server.received += 1
        if self.server.slow:
            time.sleep(1)
        self.send_response(503)
        self.send_header('Content-Length', '0')
        self.end_headers()

def main():
    version=json.loads(fixture.VERSIONS.read_text())['javaagent']
    agent=fixture.ROOT/'.local/otel'/f'opentelemetry-javaagent-v{version["version"]}.jar'
    assert hashlib.sha256(agent.read_bytes()).hexdigest()==version['sha256']
    java=shutil.which('java');assert java
    env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG') if k in os.environ}
    results=[]
    with tempfile.TemporaryDirectory(prefix='billit-agent-failure-') as directory:
        subprocess.run([str(Path(java).resolve().with_name('javac')),'-d',directory,
                        str(fixture.ROOT/'infra/tests/fixtures/OtelHttpSmoke.java')],
                       env=env,capture_output=True,text=True,check=True,timeout=30)
        for slow in (False,True):
            with http.server.ThreadingHTTPServer(('127.0.0.1',0),Collector) as server:
                server.received=0;server.slow=slow
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    cmd=[java,'-Xmx128m','-javaagent:'+str(agent),
                         '-Dotel.service.name=billit-local-failure-test',
                         '-Dotel.traces.exporter=otlp','-Dotel.metrics.exporter=none','-Dotel.logs.exporter=none',
                         '-Dotel.exporter.otlp.protocol=http/protobuf',
                         f'-Dotel.exporter.otlp.endpoint=http://127.0.0.1:{server.server_port}',
                         '-Dotel.exporter.otlp.timeout=300','-Dotel.bsp.export.timeout=500',
                         '-Dotel.bsp.max.queue.size=16','-Dotel.bsp.max.export.batch.size=8',
                         '-Dotel.bsp.schedule.delay=100','-Dotel.traces.sampler=always_on',
                         '-cp',directory,'OtelHttpSmoke']
                    start=time.monotonic()
                    process=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20)
                    elapsed=time.monotonic()-start
                    assert process.returncode==0,'Java failure or synthetic request failed'
                    measured=re.search(r'REQUEST_MS=(\d+)',process.stdout)
                    assert measured and int(measured[1])<5000,'request deadline exceeded'
                    assert 'TRACEPARENT=00-' in process.stdout,'context propagation missing'
                    assert server.received>0,'failure collector never exercised'
                    assert re.search(r'Failed to export (?:\d+ )?spans',process.stderr),'export failure not observed'
                    results.append({'collector':'slow_1s' if slow else 'http503',
                                    'collector_attempts':server.received,'app_http_status':200,
                                    'request_ms':int(measured[1]),'process_seconds':round(elapsed,3),
                                    'export_failure_observed':True})
                finally:
                    server.shutdown();thread.join(timeout=3)
    print(json.dumps({'cases':results,'billit_app_verified':False,'performance_slo_proven':False}))

if __name__=='__main__':main()
