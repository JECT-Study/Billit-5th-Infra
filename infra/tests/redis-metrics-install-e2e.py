#!/usr/bin/env python3
"""실제 Redis/Alloy로 무재시작 ACL 설치·권한·재시작 영속·제거 검증. 합성자료 전용."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/ject-redis-metrics.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CONTEXT = 'colima-billit-verify'


def docker(*args, check=True, input=None):
    return subprocess.run(['docker', '--context', CONTEXT, *args], input=input, text=True,
                          capture_output=True, check=check, timeout=120)


def main():
    prefix = 'ject-redis-install-' + uuid.uuid4().hex[:12]
    redis_name, alloy_name = prefix + '-redis', prefix + '-alloy'
    created = []
    with tempfile.TemporaryDirectory(prefix=prefix) as temp:
        root = Path(temp)
        secret = root / 'srv/ject/secrets'
        secret.mkdir(parents=True)
        config = secret / 'redis.conf'
        base = ('bind 127.0.0.1\nprotected-mode yes\nrequirepass synthetic-admin-only\n'
                'save ""\nappendonly no\nmaxmemory 8mb\nmaxmemory-policy allkeys-lru\n').encode()
        config.write_bytes(base)
        config.chmod(0o600)
        (secret / 'redis_password').write_text('synthetic-admin-only')
        (secret / 'redis_password').chmod(0o400)
        redis = m.Redis(redis_name, CONTEXT)

        def wait_redis():
            for _ in range(30):
                try:
                    if redis.command('PING') == 'PONG':
                        return
                except m.SafeError:
                    pass
                time.sleep(0.2)
            raise AssertionError('합성 Redis 시작 실패')

        def metric():
            result = docker('exec', alloy_name, 'bash', '-c',
                            'exec 3<>/dev/tcp/127.0.0.1/12345; '
                            'printf "GET /api/v0/component/prometheus.exporter.redis.ject/metrics HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n" >&3; cat <&3', check=False)
            return result.stdout

        def wait_metric(up):
            for _ in range(30):
                value = metric()
                if re.search(r'^redis_up ' + str(up) + r'$', value, re.M):
                    return value
                time.sleep(0.25)
            raise AssertionError('합성 exporter 상태 불일치')

        try:
            docker('create', '--name', redis_name, '--network', 'none', '--user', '0',
                   '--memory', '96m', '--tmpfs', '/data', '--entrypoint', 'redis-server',
                   'redis:7.4.11-alpine', '/run/secrets/redis.conf')
            created.append(redis_name)
            docker('cp', str(secret), redis_name + ':/run/secrets')
            docker('start', redis_name)
            wait_redis()
            before = redis.command('INFO', 'server')
            defaults = redis.command('ACL', 'GETUSER', 'default')
            redis.command('SET', 'synthetic-key', 'synthetic-value')
            password = m.install_acl(root, redis)
            assert defaults == redis.command('ACL', 'GETUSER', 'default')
            assert 'run_id:' + before.split('run_id:')[1].splitlines()[0] in redis.command('INFO', 'server')
            assert redis.command('GET', 'synthetic-key') == 'synthetic-value'
            m.verify_acl(redis, password)
            assert m.install_acl(root, redis) == password
            # 실제 관측 자격증명으로 CONFIG/slowlog 본문 접근 거부 확인. 비밀은 stdin 전용.
            commands = '\n'.join(' '.join(json.dumps(x) for x in row) for row in
                                 [('AUTH', m.USER, password.decode()), ('CONFIG', 'GET', 'requirepass'),
                                  ('SLOWLOG', 'GET', '1'), ('GET', 'synthetic-key')]) + '\n'
            response = docker('exec', '-i', redis_name, 'redis-cli', '--json', input=commands)
            assert response.stdout.count('NOPERM') == 3
            alloy_config = root / 'config.alloy'
            alloy_config.write_text((ROOT / 'observability/alloy/redis.alloy.example').read_text() +
                                    '\nprometheus.relabel "host" { forward_to = [] }\n')
            docker('create', '--name', alloy_name, '--network', 'container:' + redis_name,
                   '--memory', '192m', '-e', 'JECT_REDIS_METRICS_ADDR=redis://127.0.0.1:6379',
                   '-e', 'JECT_REDIS_METRICS_USER=' + m.USER,
                   'grafana/alloy:v1.20.1', 'run', '--disable-reporting',
                   '--server.http.listen-addr=127.0.0.1:12345', '/etc/alloy/config.alloy')
            created.append(alloy_name)
            docker('cp', str(alloy_config), alloy_name + ':/etc/alloy/config.alloy')
            metrics_secret = root / 'metrics-secrets'
            metrics_secret.mkdir()
            (metrics_secret / 'redis_metrics_password').write_bytes(password)
            (metrics_secret / 'redis_metrics_password').chmod(0o400)
            docker('cp', str(metrics_secret), alloy_name + ':/run/secrets')
            docker('start', alloy_name)
            docker('exec', alloy_name, '/bin/alloy', 'validate', '/etc/alloy/config.alloy')
            value = wait_metric(1)
            assert 'redis_memory_max_bytes 8.388608e+06' in value
            assert re.search(r'^redis_memory_used_bytes [1-9]', value, re.M)
            assert 'redis_exporter_last_scrape_error{err=""} 0' in value
            assert not any(x in value for x in ('synthetic-admin-only', password.decode(), 'synthetic-key'))
            print('PASS 무재시작 설치/default·기존키 보존/금지명령 거절/Alloy memory·maxmemory 수집')
            # 설정파일을 합성 컨테이너에 복사 후 재시작. 운영 Redis는 재시작하지 않는다.
            docker('stop', alloy_name)
            docker('cp', str(config), redis_name + ':/run/secrets/redis.conf')
            docker('restart', redis_name)
            wait_redis()
            m.verify_acl(redis, password)
            assert defaults == redis.command('ACL', 'GETUSER', 'default')
            assert m.fields(redis.command('CONFIG', 'GET', 'maxmemory-policy')) == {'maxmemory-policy': 'allkeys-lru'}
            print('PASS Redis 재시작 후 ACL/default 인증/축출 정책 유지')
            m.remove_acl(root, redis)
            assert config.read_bytes() == base
            assert redis.command('ACL', 'GETUSER', m.USER) is None
            assert defaults == redis.command('ACL', 'GETUSER', 'default')
            print('PASS 관측 계정 제거·설정 원문 복구/default 유지')
        finally:
            failures = []
            for name in reversed(created):
                if docker('rm', '-fv', name, check=False).returncode:
                    failures.append(name)
            remaining = docker('ps', '-a', '--format', '{{.Names}}').stdout.splitlines()
            if failures or set(remaining).intersection(created):
                raise AssertionError('합성 컨테이너 정리 실패')
    print('PASS 격리 시험자원 정리 완료')


if __name__ == '__main__':
    main()
