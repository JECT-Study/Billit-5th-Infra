#!/usr/bin/env python3
"""기존 JDK21/고정agent로 루프백 HTTP 자동계측·전파 확인. SDK/앱 수정 없음."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / 'infra/observability/otel/versions.json'

def main():
    version = json.loads(VERSIONS.read_text())['javaagent']
    agent = ROOT / '.local/otel' / f'opentelemetry-javaagent-v{version["version"]}.jar'
    if hashlib.sha256(agent.read_bytes()).hexdigest() != version['sha256']:
        raise RuntimeError('agent checksum mismatch')
    java = shutil.which('java')
    if not java:
        raise RuntimeError('기존 JDK 필요; 자동 설치 안 함')
    # 사용자 전역 agent/exporter/비밀 설정을 이 합성 시험에 상속하지 않는다.
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG') if key in os.environ}
    cmd = [java, '-Xmx128m', '-javaagent:' + str(agent),
           '-Dotel.service.name=billit-local-synthetic',
           '-Dotel.traces.exporter=console', '-Dotel.metrics.exporter=none', '-Dotel.logs.exporter=none',
           '-Dotel.traces.sampler=always_on', '-Dotel.bsp.schedule.delay=100',
           ]
    with tempfile.TemporaryDirectory(prefix='billit-otel-java-') as directory:
        subprocess.run([str(Path(java).resolve().with_name('javac')), '-d', directory,
                        str(ROOT / 'infra/tests/fixtures/OtelHttpSmoke.java')],
                       env=env, capture_output=True, text=True, timeout=30, check=True)
        result = subprocess.run(cmd + ['-cp', directory, 'OtelHttpSmoke'],
                                env=env, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('합성 Java 시험 실패: ' + result.stderr[-2000:])
    parent = re.search(r'TRACEPARENT=00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})', result.stdout)
    if not parent or not (int(parent[3], 16) & 1):
        raise RuntimeError('traceparent 전파 증거 없음')
    client_lines = [line for line in result.stderr.splitlines()
                    if 'LoggingSpanExporter' in line and 'CLIENT' in line and parent[1] in line and parent[2] in line]
    if not client_lines:
        raise RuntimeError('전파 ID와 일치하는 CLIENT span 내보내기 증거 없음: ' + result.stderr[-2500:])
    if not any('http.response.status_code=200' in line for line in client_lines):
        raise RuntimeError('HTTP200 계측 속성 없음')
    server_lines = [line for line in result.stderr.splitlines()
                    if 'LoggingSpanExporter' in line and 'SERVER' in line and parent[1] in line
                    and 'http.response.status_code=200' in line]
    if not server_lines or any(parent[2] in line for line in server_lines):
        raise RuntimeError('동일 trace의 별도 SERVER span 증거 없음')
    print(json.dumps({'agent_checksum_verified': True, 'http_status': 200,
                      'client_span_exported': True, 'server_span_same_trace': True, 'w3c_traceparent_matches_client_span': True,
                      'billit_app_verified': False, 'tempo_pipeline_verified_by_this_test': False}))

if __name__ == '__main__': main()
