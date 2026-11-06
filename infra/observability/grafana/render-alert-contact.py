#!/usr/bin/env python3
"""Discord 수신처 선택 생성. 기본은 검사만, 비밀값은 절대 출력하지 않는다."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'provisioning/alerting/contact-points.yaml'
SECRET = Path('/srv/ject/secrets/discord_webhook')
OUTPUT = Path('/etc/ject/grafana/provisioning/alerting/contact-points.yaml')
BEGIN = '      # BEGIN managed Discord receiver\n'
END = '      # END managed Discord receiver\n'
CONTACT = '''apiVersion: 1
contactPoints:
  - orgId: 1
    name: ject-oci-email
    receivers:
      - uid: ject-relay
        type: webhook
        disableResolveMessage: false
        settings:
          url: http://127.0.0.1:9095/grafana
          httpMethod: POST
'''
URL = re.compile(r'https://discord\.com/api/webhooks/[0-9]{10,30}/[A-Za-z0-9_.-]{20,200}')


def read_secret(path):
    if path.resolve() != path:
        raise ValueError('비밀파일 경로에 심볼릭링크가 있습니다')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('비밀파일은 root 소유 일반파일·0600이어야 합니다')
        value = stream.read(1025).strip()
    if not URL.fullmatch(value):
        raise ValueError('허용된 Discord 웹후크 주소 형식이 아닙니다')
    return value


def validate_source(source):
    # YAML 파서를 추가하지 않는다. 지원하는 기존 contact 형식만 수용하며 정책은 그대로 둔다.
    clean = ''.join(line for line in source.splitlines(keepends=True) if not line.startswith('#'))
    if not clean.startswith(CONTACT + 'policies:\n') or clean.count('\npolicies:\n') != 1:
        raise ValueError('원본 contact 구조가 바뀌었습니다. 자동 덮어쓰기를 중단합니다')
    if BEGIN in source or END in source or 'ject-discord' in source:
        raise ValueError('원본은 비밀값 없는 기본 contact 파일이어야 합니다')


def render(source, webhook):
    validate_source(source)
    if not URL.fullmatch(webhook):
        raise ValueError('허용된 Discord 웹후크 주소 형식이 아닙니다')
    receiver = BEGIN + '''      - uid: ject-discord
        type: discord
        disableResolveMessage: false
        settings:
          use_discord_username: true
          title: "[{{ .Status }}] Billit 서버 알림"
          message: '{{ range .Alerts }}{{ .Labels.alertname }} / {{ .Labels.host }} ({{ .Status }}){{ "\\n" }}{{ end }}'
          url: ''' + json.dumps(webhook) + '\n' + END
    return source.replace('policies:\n', receiver + 'policies:\n', 1)


def base_content(current):
    if BEGIN not in current and END not in current:
        return current
    if current.count(BEGIN) != 1 or current.count(END) != 1:
        raise ValueError('기존 출력의 관리 구간이 잘못되었습니다')
    before, tail = current.split(BEGIN)
    _, after = tail.split(END)
    return before + after


def write_output(path, source, content):
    if path != OUTPUT or path.resolve() != path:
        raise ValueError('출력은 정해진 Grafana provisioning 경로만 허용합니다')
    parent = path.parent.stat()
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError('출력 디렉터리는 root 소유이며 그룹/기타 쓰기가 없어야 합니다')
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('기존 출력 파일의 소유권·권한이 안전하지 않습니다')
        if base_content(path.read_text()) != source:
            raise ValueError('운영 contact 또는 policy가 원본과 다릅니다. 보존을 위해 중단합니다')
    fd, tmp = tempfile.mkstemp(prefix='.contact-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchown(stream.fileno(), 0, 472)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE, help='비밀값 없는 기본 contact 파일')
    parser.add_argument('--output', type=Path, help='명시할 때만 운영 provisioning 파일을 기록')
    args = parser.parse_args()
    try:
        source = args.source.read_text()
        content = render(source, read_secret(SECRET))
        if args.output:
            write_output(args.output, source, content)
            print('Discord contact 파일 기록 완료. 재로드·발송은 수행하지 않았습니다.')
        else:
            print('Discord contact 검증 통과. 파일 기록·재로드·발송 없음.')
    except (OSError, ValueError):
        # 라이브러리 예외가 입력 값/URL을 포함할 수 있으므로 세부 예외를 출력하지 않는다.
        raise SystemExit('Discord contact 처리 실패: 경로·권한·URL 형식·원본/운영 설정 일치를 확인하세요.') from None


if __name__ == '__main__': main()
