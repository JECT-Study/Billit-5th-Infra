#!/usr/bin/env python3
"""전용 로컬 Docker에서 FE 최초 라우팅 준비/기동/원복 검증. 서버 접근 없음."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

CONTEXT = 'colima-billit-verify'
IMAGE = 'nginx:1.30.6-alpine'
INFRA = Path(__file__).resolve().parents[1]


def docker(*args, check=True):
    return subprocess.run(['docker', '--context', CONTEXT, *args], check=check,
                          capture_output=True, text=True, timeout=120)


def main():
    # 이 context는 격리 시험 전용이며 기본 context/호스트 포트/볼륨을 바꾸지 않는다.
    docker('info', '--format', '{{.OSType}}')
    docker('image', 'inspect', IMAGE)
    prefix = 'ject-fe-routing-' + uuid.uuid4().hex[:12]
    network = prefix + '-net'
    gateway = prefix + '-gateway'
    created = []
    network_created = False
    renderer = (INFRA / 'scripts/render-nginx.sh').read_text()
    functions = renderer[renderer.index('proxy_common='):renderer.index('\ntls_block() {')]
    source = (INFRA / 'scripts/ject-deploy').read_text()
    preflight = source[source.index('fe_routing_preflight() {'):source.index('\nready_checks() {')]

    def route(upstream):
        result = subprocess.run(['bash', '-c', functions + '\napp_locations be:8080 "$FE"'],
                                env={**os.environ, 'FE': upstream}, check=True,
                                capture_output=True, text=True)
        return ('events {}\nhttp { resolver 127.0.0.11 valid=1s ipv6=off;\n'
                'map $http_upgrade $connection_upgrade { default upgrade; "" close; }\n'
                'server { listen 8080;\n' + result.stdout + '\n} }\n')

    def write_config(name, text, directory):
        path = Path(directory) / (name + '.conf')
        path.write_text(text)
        docker('cp', str(path), name + ':/etc/nginx/nginx.conf')

    def start(name, alias, config, directory):
        docker('create', '--name', name, '--network', network, '--network-alias', alias,
               '--memory', '64m', '--cpus', '0.25', '--entrypoint', 'nginx', IMAGE,
               '-g', 'daemon off;')
        created.append(name)
        write_config(name, config, directory)
        docker('start', name)

    def fetch(path):
        return docker('exec', gateway, 'wget', '-q', '-T', '2', '-O', '-',
                      'http://127.0.0.1:8080' + path, check=False)

    def expect(path, body):
        for _ in range(30):
            result = fetch(path)
            if result.returncode == 0 and result.stdout.strip() == body:
                return
            time.sleep(0.2)
        raise AssertionError(f'{path}: expected {body}, got rc={result.returncode} {result.stdout!r}')

    def check_route(upstream, expected):
        harness = ('set -euo pipefail\nlog() { echo "$*"; }\n'
                   'docker() { command docker --context "$VERIFY_CONTEXT" "$@"; }\n'
                   + preflight + '\nfe_routing_preflight fe')
        result = subprocess.run(['bash', '-c', harness], capture_output=True, text=True,
                                env={**os.environ, 'VERIFY_CONTEXT': CONTEXT, 'ENVN': 'dev',
                                     'DEV_FE_UPSTREAM': upstream, 'GATEWAY': gateway}, timeout=15)
        assert (result.returncode == 0) == expected, result.stdout + result.stderr

    def reload_config(config, directory):
        write_config(gateway, config, directory)
        docker('exec', gateway, 'nginx', '-t')
        docker('exec', gateway, 'nginx', '-s', 'reload')

    try:
        docker('network', 'create', '--internal', network)
        network_created = True
        with tempfile.TemporaryDirectory(prefix=prefix) as directory:
            start(prefix + '-be', 'be', 'events {}\nhttp { server { listen 8080; '
                  'location / { return 200 "BE"; } } }', directory)
            original = route('')
            start(gateway, 'gateway', original, directory)
            expect('/', 'BE')
            expect('/healthz', 'BE')  # 이전 검사는 BE의200도 FE 성공으로 오인할 수 있었다.
            check_route('', False)
            check_route('fe:3000', False)  # 환경변수만 바꿔도 생성 설정이 없으면 차단.
            reload_config(route('fe:3000'), directory)
            check_route('fe:3000', True)
            for _ in range(30):
                if fetch('/').returncode != 0:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError('FE 미기동을 성공으로 처리함')
            start(prefix + '-fe', 'fe', 'events {}\nhttp { server { listen 3000; '
                  'location / { return 200 "FE"; } } }', directory)
            expect('/', 'FE')
            expect('/healthz', 'FE')
            expect('/readyz', 'BE')
            expect('/api/check', 'BE')
            # 준비/배포 실패 때 동일한 원복 절차로 기존 BE 경로가 돌아오는지 확인.
            reload_config(original, directory)
            expect('/', 'BE')
            expect('/readyz', 'BE')
            check_route('fe:3000', False)
    finally:
        for name in reversed(created):
            docker('rm', '-fv', name)
        if network_created:
            docker('network', 'rm', network)
        remaining = docker('ps', '-a', '--format', '{{.Names}}').stdout.splitlines()
        assert not set(created).intersection(remaining), '시험 컨테이너 정리 실패'
        assert network not in docker('network', 'ls', '--format', '{{.Name}}').stdout.splitlines()
    print('PASS: 최초 FE 라우팅 차단/활성화/기동, 웹·BE 경로 구분, 라우팅 원복, 시험자원 정리')


if __name__ == '__main__':
    main()
