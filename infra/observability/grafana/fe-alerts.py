#!/usr/bin/env python3
"""개발 FE 배포 후에만 설치하는 별도 접속 경보. 서버 변경 없이 JSON 출력."""
import json
import sys

sys.dont_write_bytecode = True
from generate import rule


def provisioning():
    selector = '{job="integrations/blackbox/dev-fe",host="dev",target="dev-fe"}'
    metric = 'probe_success' + selector
    expr = ('min by(target) (' + metric + ' and (time() - timestamp(' + metric + ') < 180)) '
            'or on(target) label_replace(vector(0), "target", "dev-fe", "", "")')
    alert = rule('ject-fe-probe-fail', '개발 FE 접속 실패 또는 지표 누락', expr,
                 'lt', 1, '3m', 'critical', '개발 FE HTTPS /healthz 응답 실패',
                 'HTTP 200과 ok 본문, TLS 및 180초 이내 지표를 확인합니다. '
                 'FE 컨테이너·개발 웹 라우팅·Alloy를 확인하세요. '
                 'BE /readyz 성공은 FE 정상 증거가 아니며 이 검사도 업무 E2E를 대신하지 않습니다.')
    return {'apiVersion': 1, 'groups': [{'orgId': 1, 'name': 'ject-fe-opt-in',
            'folder': 'JECT', 'interval': '1m', 'rules': [alert]}]}


if __name__ == '__main__':
    print(json.dumps(provisioning(), ensure_ascii=False, indent=2))
