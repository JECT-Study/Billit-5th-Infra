#!/usr/bin/env python3
"""승인된 billit-verify VM 전용 합성 라벨 E2E. 운영 접근/포트 공개/호스트 마운트 없음."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

DOCKER = ['docker', '--context', 'colima-billit-verify']
INFRA = Path(__file__).resolve().parents[1]
REDIS_IMAGE = 'redis:7.4.11-bookworm'
ALLOY_IMAGE = 'grafana/alloy:v1.20.1'
PROM_IMAGE = 'prom/prometheus:v3.13.4'


def docker(*args, check=True):
    return subprocess.run(DOCKER + list(args), text=True, capture_output=True,
                          check=check, timeout=120)


def clean_owned(containers, network):
    for name in reversed(containers):
        docker('rm', '-fv', name, check=False)
    if network:
        docker('network', 'rm', network, check=False)
    # 조회 오류를 '없음'으로 오인하지 않는다. 정확한 소유 이름만 대조한다.
    listing = docker('container', 'ls', '-a', '--format', '{{.Names}}', check=False)
    if listing.returncode or set(containers).intersection(listing.stdout.splitlines()):
        raise RuntimeError('시험 컨테이너 정리 확인 실패')
    if network:
        listing = docker('network', 'ls', '--format', '{{.Name}}', check=False)
        if listing.returncode or network in listing.stdout.splitlines():
            raise RuntimeError('시험 네트워크 정리 확인 실패')


def main():
    prefix = 'billit-redis-rw-' + uuid.uuid4().hex[:12]
    redis, alloy, prom = (prefix + '-' + part for part in ('redis', 'alloy', 'prom'))
    network = prefix + '-net'
    containers = []
    network_created = False
    passed = False
    try:
        # 이미지 인증/제한 실패를 재시도하거나 다른 registry로 우회하지 않는다.
        docker('image', 'inspect', REDIS_IMAGE)
        docker('image', 'inspect', ALLOY_IMAGE)
        check_name = prefix + '-disk'
        containers.append(check_name)
        space = docker('run', '--name', check_name, '--network', 'none', '--entrypoint', 'sh',
                       ALLOY_IMAGE, '-c', "df -Pm / | awk 'NR==2 {print $4}'")
        available = int(space.stdout.strip())
        print(f'VM available: {available} MiB', flush=True)
        if available < 1024:
            raise RuntimeError('1 GiB 미만: 이미지 pull/시험 시작 중단')
        docker('rm', '-v', check_name)
        containers.remove(check_name)
        if docker('image', 'inspect', PROM_IMAGE, check=False).returncode:
            docker('pull', PROM_IMAGE)
        containers.append(check_name)
        space = docker('run', '--name', check_name, '--network', 'none', '--entrypoint', 'sh',
                       ALLOY_IMAGE, '-c', "df -Pm / | awk 'NR==2 {print $4}'")
        available = int(space.stdout.strip())
        print(f'VM available after image check: {available} MiB', flush=True)
        if available < 1024:
            raise RuntimeError('1 GiB 미만: 컨테이너 시험 시작 중단')
        docker('rm', '-v', check_name)
        containers.remove(check_name)
        docker('network', 'create', '--internal', network)
        network_created = True
        with tempfile.TemporaryDirectory(prefix=prefix) as directory:
            root = Path(directory)
            (root / 'redis.conf').write_text('''bind 0.0.0.0
protected-mode yes
save ""
appendonly no
maxmemory 8mb
maxmemory-policy allkeys-lru
user default off
user metrics on >synthetic-rw-password -@all +ping +info +config|get +slowlog|get +slowlog|len +latency|latest +latency|histogram
''')
            (root / 'prom.yml').write_text('global:\n  scrape_interval: 30s\nscrape_configs: []\n')
            # 실제 example과 실제 공통 host/env/instance relabel 블록을 재사용한다.
            example = (INFRA / 'observability/alloy/redis.alloy.example').read_text()
            common = (INFRA / 'observability/alloy/common.alloy').read_text()
            relabel = common.split('prometheus.relabel "host" {', 1)[1].split('prometheus.remote_write "obs" {', 1)[0]
            config = example + '\nprometheus.relabel "host" {' + relabel
            config += '''prometheus.remote_write "obs" {
  endpoint {
    url = "http://prom:9090/api/v1/write"
  }
}
'''
            (root / 'config.alloy').write_text(config)
            (root / 'secrets').mkdir()
            secret = root / 'secrets/redis_metrics_password'
            secret.write_text('synthetic-rw-password\n')
            secret.chmod(0o600)
            for name, image, memory, arguments, extra in [
                (redis, REDIS_IMAGE, '128m', ['redis-server', '/tmp/redis.conf'],
                 ['--network-alias', 'redis', '--tmpfs', '/data:size=16m']),
                (prom, PROM_IMAGE, '256m', ['--config.file=/etc/prometheus/prometheus.yml',
                 '--storage.tsdb.path=/prometheus', '--storage.tsdb.retention.time=15m',
                 '--web.enable-remote-write-receiver'],
                 ['--network-alias', 'prom', '--tmpfs', '/prometheus:uid=65534,gid=65534,size=128m']),
                (alloy, ALLOY_IMAGE, '256m', ['run', '--disable-reporting', '--storage.path=/tmp/alloy',
                 '--server.http.listen-addr=127.0.0.1:12345', '/etc/alloy/config.alloy'],
                 ['-e', 'JECT_REDIS_METRICS_ADDR=redis://redis:6379', '-e', 'JECT_REDIS_METRICS_USER=metrics',
                  '-e', 'JECT_HOST=synthetic', '-e', 'JECT_ENV=test']),
            ]:
                docker('create', '--name', name, '--network', network, '--memory', memory,
                       *extra, image, *arguments)
                containers.append(name)
            docker('cp', str(root / 'redis.conf'), redis + ':/tmp/redis.conf')
            docker('cp', str(root / 'prom.yml'), prom + ':/etc/prometheus/prometheus.yml')
            docker('cp', str(root / 'config.alloy'), alloy + ':/etc/alloy/config.alloy')
            docker('cp', str(root / 'secrets'), alloy + ':/run/secrets')
            for name in (redis, prom, alloy):
                docker('start', name)
            docker('exec', alloy, '/bin/alloy', 'validate', '/etc/alloy/config.alloy')
            results = None
            # 상태 조건을 기다린다. 30초 scrape와 최초 remote write를 포함한 제한된 대기.
            for _ in range(70):
                response = docker('exec', alloy, 'bash', '-c',
                    'exec 3<>/dev/tcp/prom/9090; printf "GET /api/v1/query?query=redis_up HTTP/1.0\\r\\nHost: prom\\r\\n\\r\\n" >&3; cat <&3', check=False)
                if response.returncode == 0 and '\r\n\r\n' in response.stdout:
                    body = response.stdout.split('\r\n\r\n', 1)[1]
                else:
                    body = response.stdout.split('\n\n', 1)[-1]
                try:
                    results = json.loads(body)['data']['result']
                except (ValueError, KeyError):
                    results = None
                if results:
                    break
                time.sleep(1)
            if not results or len(results) != 1:
                raise RuntimeError('70초 내 단일 Redis 시계열이 유입되지 않음')
            observed = results[0]
            expected = {'job': 'integrations/redis', 'host': 'synthetic', 'env': 'test', 'instance': 'synthetic'}
            assert all(observed['metric'].get(k) == v for k, v in expected.items()), observed
            assert float(observed['value'][1]) == 1, observed
            for metric in ('redis_memory_used_bytes', 'redis_memory_max_bytes'):
                raw = docker('exec', alloy, 'bash', '-c',
                    'exec 3<>/dev/tcp/prom/9090; printf "GET /api/v1/query?query=' + metric +
                    ' HTTP/1.0\\r\\nHost: prom\\r\\n\\r\\n" >&3; cat <&3').stdout
                item, = json.loads(raw.split('\n\n', 1)[1])['data']['result']
                assert all(item['metric'].get(k) == v for k, v in expected.items()), item
                assert float(item['value'][1]) > 0, item
                if metric == 'redis_memory_max_bytes':
                    assert float(item['value'][1]) == 8388608, item
            passed = True
    finally:
        clean_owned(containers, network if network_created else None)
    if passed:
        print('PASS: Redis→scrape→실제 host/env relabel→remote_write→Prometheus query; '
              'job=integrations/redis host=synthetic env=test instance=synthetic; '
              'redis_up=1, memory>0, maxmemory=8388608; 시험 컨테이너/네트워크 정리 확인')


if __name__ == '__main__':
    main()
