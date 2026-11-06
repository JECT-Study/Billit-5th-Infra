#!/usr/bin/env python3
"""개발 추적 스택 시작 전 검사. 마운트·포맷·파일 삭제를 수행하지 않는다."""
import os
from pathlib import Path
import subprocess
import stat

DATA = Path('/srv/ject/observability/tempo')
MIB = 1024 * 1024


def check_storage(path):
    if path.is_symlink() or path.resolve() != path or not path.is_dir():
        raise ValueError('Tempo 저장소는 심볼릭링크 없는 절대 디렉터리여야 합니다')
    if not os.path.ismount(path) or path.stat().st_dev == path.parent.stat().st_dev:
        raise ValueError('Tempo 전용 파일시스템이 마운트되지 않았습니다')
    stat = os.statvfs(path)
    total, free = stat.f_blocks * stat.f_frsize, stat.f_bavail * stat.f_frsize
    if not 512 * MIB <= total <= 1024 * MIB:
        raise ValueError('Tempo 전용 파일시스템은 512MiB~1GiB여야 합니다')
    if free < 128 * MIB:
        raise ValueError('Tempo 파일시스템 여유가 128MiB 미만입니다')
    info = path.stat()
    if info.st_uid != 10001 or info.st_mode & 0o777 != 0o700:
        raise ValueError('Tempo 디렉터리 소유자10001·권한0700이 필요합니다')
    return {'total_bytes': total, 'free_bytes': free}


def check_host():
    # 환경파일을 실행하지 않으며 JECT_HOST 한 필드만 읽는다.
    fields = dict(line.split('=', 1) for line in Path('/etc/ject/obs.env').read_text().splitlines()
                  if '=' in line and not line.lstrip().startswith('#'))
    if fields.get('JECT_HOST') != 'dev':
        raise ValueError('개발VM JECT_HOST=dev에서만 허용합니다')
    values = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(values['MemAvailable'].split()[0]) < 1536 * 1024:
        raise ValueError('시작 전 가용메모리 1536MiB 이상 필요')
    root = os.statvfs(DATA.parent)
    if root.f_bavail * root.f_frsize < 3 * 1024 * MIB:
        raise ValueError('호스트 디스크 여유 3GiB 이상 필요')


def check_config_files():
    for name in ('tempo.dev.yaml', 'collector.alloy', 'proxy.conf'):
        path = Path('/opt/ject/otel') / name
        info = path.stat()
        if path.resolve() != path or not stat.S_ISREG(info.st_mode):
            raise ValueError('OTel 설정은 심볼릭링크 없는 일반파일이어야 합니다')
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o644:
            raise ValueError('OTel 설정은 root 소유·0644여야 합니다')


def main():
    check_host()
    check_config_files()
    capacity = check_storage(DATA)
    subprocess.run(['docker', 'compose', '-p', 'ject-otel', '-f',
                    '/opt/ject/compose/otel.yaml', 'config', '--quiet'], check=True)
    print('OTel preflight OK', capacity)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
