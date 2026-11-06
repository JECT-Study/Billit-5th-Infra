#!/usr/bin/env python3
"""Redis 관측 opt-in. default/앱 계정·Redis 프로세스·축출 설정을 변경하지 않는다."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys

USER = 'ject_metrics'
RULES = ['reset', 'on', '-@all', '+ping', '+info', '+slowlog|len',
         '+latency|latest', '+latency|histogram']
BEGIN = b'# BEGIN JECT REDIS METRICS\n'
END = b'# END JECT REDIS METRICS\n'


class SafeError(Exception):
    pass


class Redis:
    def __init__(self, container, context=None):
        self.container = container
        self.docker = ['docker'] + (['--context', context] if context else [])

    def command(self, *args, allow_error=False):
        # 비밀번호는 컨테이너 보호 파일에서만 읽고 argv·도구 출력으로 전달하지 않는다.
        command = ' '.join(json.dumps(str(x)) for x in args) + '\n'
        result = subprocess.run(self.docker + ['exec', '-i', self.container, 'sh', '-c',
                                'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; '
                                'exec redis-cli --json'], input=command, text=True,
                                capture_output=True, timeout=15)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            # redis-cli는 INFO를 JSON 모드에서도 사람이 읽는 원문으로 출력한다.
            if args[0] == 'INFO' and result.stdout.startswith('# '):
                value = result.stdout
            elif allow_error and result.stdout.startswith('error:'):
                value = {'error': 'Redis command denied'}
            else:
                raise SafeError('Redis 응답 오류 — 비밀 보호를 위해 원문 생략') from None
        if result.returncode or (not allow_error and isinstance(value, dict) and 'error' in value):
            raise SafeError('Redis 명령 실패 — 비밀 보호를 위해 원문 생략')
        return value


def split_config(data):
    if BEGIN not in data and END not in data:
        return data, b''
    if data.count(BEGIN) != 1 or data.count(END) != 1:
        raise SafeError('Redis 관리 구간이 손상됨')
    before, tail = data.split(BEGIN)
    block, after = tail.split(END)
    if after:
        raise SafeError('관리 구간 뒤 추가 설정 발견 — 수동 검토 필요')
    return before, BEGIN + block + END


def managed_block(password):
    digest = hashlib.sha256(password).hexdigest()
    return BEGIN + ('user ' + USER + ' ' + ' '.join(RULES + ['#' + digest]) + '\n').encode() + END


def protected_file(path):
    if path.is_symlink() or not path.is_file():
        raise SafeError('필수 보호 파일 누락 또는 심볼릭링크')
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SafeError('보호 파일에 그룹/기타 접근 권한이 있음')


def write_in_place(path, data):
    # redis.conf는 파일 bind mount다. inode 교체 없이 갱신해 restart에도 같은 파일이 보인다.
    with path.open('r+b') as stream:
        stream.write(data)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def ensure_mountpoint(directory):
    # 기본 /etc/alloy 디렉터리 bind는 read-only다. nested bind의 빈 대상 파일을
    # 먼저 준비한다. overlay를 제거하면 빈 파일만 남으므로 기본 수집은 유지된다.
    path = directory / 'redis.alloy'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes():
            raise SafeError('Redis Alloy mountpoint에 기존 내용/심볼릭링크가 있음')
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.close(fd)


def validate_alloy(command):
    name = 'ject-redis-validate-' + secrets.token_hex(8)
    try:
        subprocess.run(command + ['run', '--name', name, '--rm', '--no-deps',
                                  'alloy', 'validate', '/etc/alloy'],
                       check=True, capture_output=True, timeout=60)
    finally:
        # runc 시작 실패 시 --rm만으로 Created 컨테이너가 지워지지 않을 수 있다.
        subprocess.run(['docker', 'rm', '-fv', name], capture_output=True, timeout=30)
        remaining = subprocess.run(['docker', 'container', 'ls', '-aq', '--filter',
                                    'name=^/' + name + '$'],
                                   check=True, capture_output=True, text=True, timeout=15)
        if remaining.stdout.strip():
            raise SafeError('전용 Alloy 검증 컨테이너 정리 실패')


def inspect_config(conf, admin_password):
    base, block = split_config(conf)
    directives = [shlex.split(line, comments=True) for line in base.decode().splitlines()]
    directives = [line for line in directives if line]
    if any(line[0].lower() in ('aclfile', 'include') for line in directives):
        raise SafeError('aclfile/include 구성은 자동 변경하지 않음')
    passwords = [line[1:] for line in directives if line[0].lower() == 'requirepass']
    if passwords != [[admin_password.decode()]]:
        raise SafeError('requirepass와 기존 비밀번호 파일 불일치')
    if any(line[:2] == ['user', USER] for line in directives):
        raise SafeError('관리 구간 밖 동명 사용자 설정 발견')
    if base and not base.endswith(b'\n'):
        raise SafeError('Redis 설정 끝 줄바꿈 필요 — 원문 자동 수정 중단')
    return base, block


def fields(value):
    if isinstance(value, dict):
        return value
    return dict(zip(value[::2], value[1::2])) if value else {}


def verify_acl(redis, password):
    value = fields(redis.command('ACL', 'GETUSER', USER))
    if value.get('passwords') != [hashlib.sha256(password).hexdigest()]:
        raise SafeError('관측 계정 비밀번호 해시 불일치')
    for command in [('GET', 'synthetic-key'), ('SET', 'synthetic-key', 'x'),
                    ('CONFIG', 'GET', 'requirepass'), ('SLOWLOG', 'GET', '1'),
                    ('CONFIG', 'SET', 'maxmemory', '0'), ('KEYS', '*'),
                    ('EVAL', 'return 1', '0'), ('ACL', 'LIST')]:
        if redis.command('ACL', 'DRYRUN', USER, *command, allow_error=True) == 'OK':
            raise SafeError('관측 계정 금지 명령이 허용됨')
    for command in [('PING',), ('INFO', 'memory')]:
        if redis.command('ACL', 'DRYRUN', USER, *command) != 'OK':
            raise SafeError('관측 계정 필수 읽기 권한 누락')


def install_acl(root, redis):
    secret = root / 'srv/ject/secrets'
    config = secret / 'redis.conf'
    admin = secret / 'redis_password'
    password_file = secret / 'redis_metrics_password'
    protected_file(config)
    protected_file(admin)
    base, block = inspect_config(config.read_bytes(), admin.read_bytes().strip())
    existing = redis.command('ACL', 'GETUSER', USER)
    if existing is not None and not block:
        raise SafeError('관리하지 않는 동명 Redis 사용자가 이미 있음')
    if password_file.exists():
        protected_file(password_file)
        password = password_file.read_bytes().strip()
        if not re.fullmatch(rb'[a-f0-9]{64}', password):
            raise SafeError('관측 비밀번호 파일 형식 오류')
    else:
        if block:
            raise SafeError('관리 설정에 대응하는 관측 비밀번호 파일 없음')
        password = secrets.token_hex(32).encode()
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(password)
            stream.flush()
            os.fsync(stream.fileno())
    expected = managed_block(password)
    if block and block != expected:
        raise SafeError('관리 구간 변경 발견 — 덮어쓰지 않음')
    if existing is not None:
        verify_acl(redis, password)
    original_default = redis.command('ACL', 'GETUSER', 'default')
    original_info = redis.command('INFO', 'server')
    if not block:
        write_in_place(config, base + expected)
    try:
        redis.command('ACL', 'SETUSER', USER, *RULES, '#' + hashlib.sha256(password).hexdigest())
        verify_acl(redis, password)
        if redis.command('ACL', 'GETUSER', 'default') != original_default:
            raise SafeError('default 사용자 변경 감지')
        run_id = lambda value: next(line for line in value.splitlines() if line.startswith('run_id:'))
        if run_id(redis.command('INFO', 'server')) != run_id(original_info):
            raise SafeError('Redis 프로세스 변경 감지')
    except Exception:
        # 새로 만든 계정만 되돌린다. 이미 관리 중이던 구성은 보존하고 실패를 보고한다.
        if not block:
            redis.command('ACL', 'DELUSER', USER)
            write_in_place(config, base)
        raise
    return password


def remove_acl(root, redis):
    secret = root / 'srv/ject/secrets'
    config = secret / 'redis.conf'
    protected_file(config)
    base, block = split_config(config.read_bytes())
    if not block:
        raise SafeError('관리 구간 없음 — 동명 계정을 임의 삭제하지 않음')
    password_file = secret / 'redis_metrics_password'
    protected_file(password_file)
    password = password_file.read_bytes().strip()
    if block != managed_block(password):
        raise SafeError('관리 구간 변경 발견 — 제거 중단')
    if redis.command('ACL', 'GETUSER', USER) is not None:
        verify_acl(redis, password)
        redis.command('ACL', 'DELUSER', USER)
    write_in_place(config, base)
    # exporter를 먼저 중지/원복한 후 실행해야 한다. 비밀번호는 재실행/복구용으로 보존.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'verify', 'remove', 'agent-up'])
    parser.add_argument('--role', choices=['dev', 'prod-data'], required=True)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--address', help='인증정보 없는 Redis 주소. 예: redis://127.0.0.1:6379')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SafeError('root로 실행해야 함')
    root = Path('/')
    container = 'ject-dev-data-redis-1' if args.role == 'dev' else 'ject-prod-data-redis-1'
    redis = Redis(container)
    inspected = subprocess.run(['docker', 'inspect', container], check=True,
                               text=True, capture_output=True, timeout=15)
    target = json.loads(inspected.stdout)[0]
    mounts = {item['Destination']: item['Source'] for item in target['Mounts']}
    if (mounts.get('/run/secrets/redis_conf') != '/srv/ject/secrets/redis.conf' or
            mounts.get('/run/secrets/redis_password') != '/srv/ject/secrets/redis_password'):
        raise SafeError('대상 Redis의 설정/비밀번호 mount 경로 불일치')
    lock_path = Path('/run/lock/ject-redis-metrics.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'install':
            if not args.source_dir or not re.fullmatch(r'redis://(?:[0-9]{1,3}\.){3}[0-9]{1,3}:6379', args.address or ''):
                raise SafeError('--source-dir 및 인증정보 없는 IPv4 Redis 주소 필요')
            address = args.address.removeprefix('redis://').removesuffix(':6379')
            try:
                ipaddress.IPv4Address(address)
            except ValueError:
                raise SafeError('Redis IPv4 주소 오류') from None
            ports = target['NetworkSettings']['Ports'].get('6379/tcp') or []
            if not any(port['HostIp'] == address and port['HostPort'] == '6379' for port in ports):
                raise SafeError('관측 주소와 해당 Redis의 published port 불일치')
            example = args.source_dir / 'observability/alloy/redis.alloy.example'
            overlay = args.source_dir / 'compose/agent-redis.yaml'
            if not example.is_file() or not overlay.is_file():
                raise SafeError('관측 원본 파일 누락')
            install_acl(root, redis)
            for source, target in [(example, Path('/etc/ject/redis-metrics.alloy')),
                                   (overlay, Path('/opt/ject/compose/agent-redis.yaml'))]:
                if target.is_symlink():
                    raise SafeError('설치 대상 심볼릭링크 거부')
                shutil.copyfile(source, target)
                target.chmod(0o644)
            env = Path('/etc/ject/redis-metrics.env')
            if env.is_symlink():
                raise SafeError('환경파일 심볼릭링크 거부')
            env.write_text(f'JECT_REDIS_METRICS_ADDR={args.address}\nJECT_REDIS_METRICS_USER={USER}\n'
                           'JECT_REDIS_METRICS_CONFIG_FILE=/etc/ject/redis-metrics.alloy\n'
                           'JECT_REDIS_METRICS_PASSWORD_FILE=/srv/ject/secrets/redis_metrics_password\n')
            env.chmod(0o600)
            print('관측 ACL/재시작 설정 설치 완료. exporter는 agent-up으로 별도 반영.')
        elif args.action == 'verify':
            password = Path('/srv/ject/secrets/redis_metrics_password').read_bytes().strip()
            verify_acl(redis, password)
            config = Path('/srv/ject/secrets/redis.conf').read_bytes()
            if split_config(config)[1] != managed_block(password):
                raise SafeError('재시작 영속 설정 불일치')
            print('관측 ACL·재시작 설정 일치. 실제 exporter 지표는 별도 확인.')
        elif args.action == 'remove':
            remove_acl(root, redis)
            print('관측 전용 사용자와 관리 구간 제거. 앱 설정과 비밀번호 파일 보존.')
        else:
            protected_file(Path('/srv/ject/secrets/redis_metrics_password'))
            verify_acl(redis, Path('/srv/ject/secrets/redis_metrics_password').read_bytes().strip())
            command = ['docker', 'compose', '-p', 'ject-agent', '-f', '/opt/ject/compose/agent.yaml',
                       '-f', '/opt/ject/compose/agent-redis.yaml', '--env-file', '/etc/ject/obs.env',
                       '--env-file', '/etc/ject/redis-metrics.env']
            subprocess.run(command + ['config', '--quiet'], check=True, capture_output=True)
            ensure_mountpoint(Path('/etc/ject/alloy'))
            validate_alloy(command)
            subprocess.run(command + ['up', '-d', '--no-deps', 'alloy'], check=True, capture_output=True)
            print('Alloy overlay 반영. Docker restart 정책은 유지되며 지표 확인 필요.')


if __name__ == '__main__':
    try:
        main()
    except (SafeError, OSError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, SafeError) else '작업 실패 — 비밀 보호를 위해 원문 생략', file=sys.stderr)
        sys.exit(1)
