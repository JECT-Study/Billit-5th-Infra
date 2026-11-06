#!/usr/bin/env python3
"""Redis opt-in 경보 초안. 파일/서버를 변경하지 않고 provisioning JSON만 stdout 출력."""
import argparse
import json
import re
import sys

# 일반 실행에서도 import 대상의 __pycache__ 파일을 만들지 않는다.
sys.dont_write_bytecode = True
from generate import expected, rule


def provisioning(hosts):
    if not hosts or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,63}", h) for h in hosts):
        raise ValueError("명시적인 host 라벨 목록이 필요합니다(영숫자/_/- 최대 63자).")
    if len(set(hosts)) != len(hosts):
        raise ValueError("host 라벨이 중복되었습니다.")
    hosts = sorted(hosts)
    selector = '{job="integrations/redis",host=~"' + '|'.join(hosts) + '"}'
    up = 'up' + selector
    redis = 'redis_up' + selector
    used = 'redis_memory_used_bytes' + selector
    limit = 'redis_memory_max_bytes' + selector
    # 기본 lookback 안의 오래된 마지막 1을 현재 정상으로 간주하지 않는다.
    fresh_up = f'({up} == 1) and (time() - timestamp({up}) < 120)'
    fresh_redis = f'({redis} >= 0) and (time() - timestamp({redis}) < 120)'
    missing = (f'({expected(hosts)}) unless on(host) '
               f'(({fresh_up}) and on(host) ({fresh_redis}))')
    rules = [
        rule('ject-redis-memory-80', 'Redis 할당 메모리 80% 초과',
             f'({used} / {limit}) and ({limit} > 0)', 'gt', 0.8, '5m', 'warning',
             '{{ $labels.host }} Redis 할당 메모리 80% 초과',
             '초안: 실제 사용량·상한·증가 추세를 확인합니다. 축출정책이나 상한을 자동 변경하지 않습니다.'),
        rule('ject-redis-down', 'Redis 연결 또는 인증 실패', redis,
             'lt', 1, '2m', 'critical', '{{ $labels.host }} Redis 연결 실패',
             '초안: Redis 실행·접속 주소·관측 전용 ACL·secret을 확인합니다. 앱 비밀번호로 대체하지 않습니다.'),
        rule('ject-redis-missing', 'Redis 지표 수집 실패 또는 누락', missing,
             'gt', 0, '2m', 'critical', '{{ $labels.host }} Redis 수집 상태 누락',
             '초안: up 실패/부재, redis_up 부재, 두 지표의 120초 이상 지연을 감지합니다. '
             'Alloy·remote write·host/job 라벨과 Prometheus를 확인합니다. 사용량 0으로 해석하지 않습니다.'),
        rule('ject-redis-unlimited', 'Redis 메모리 상한 미설정', f'{limit} == 0',
             'lt', 1, '5m', 'warning', '{{ $labels.host }} Redis maxmemory=0',
             '초안: 메모리 비율 계산에서 제외된 무제한 설정입니다. 승인 없이 정책/상한을 변경하지 않습니다.'),
    ]
    return {'apiVersion': 1, 'groups': [{'orgId': 1, 'name': 'ject-redis-opt-in',
            'folder': 'JECT', 'interval': '1m', 'rules': rules}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hosts', nargs='+', required=True, help='승인된 Redis 대상의 정확한 host 라벨')
    args = parser.parse_args()
    try:
        doc = provisioning(args.hosts)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
