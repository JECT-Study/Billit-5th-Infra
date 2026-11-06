#!/usr/bin/env python3
"""개발 S3 합성 객체 한 개만 생성/검증/삭제. 키·서명 URL·원문 응답은 출력하지 않는다."""
import argparse
import datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BUCKET = 'ject-dev-uploads'


def credentials(path):
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('credentials require a regular 0600 file')
    data = json.loads(path.read_text())
    if data['region'] != 'ap-chuncheon-1' or not re.fullmatch(
            r'https://[a-z0-9]+\.compat\.objectstorage\.ap-chuncheon-1\.oraclecloud\.com', data['endpoint']):
        raise ValueError('only the configured OCI development region endpoint is allowed')
    if not all(isinstance(data.get(k), str) and data[k] for k in ('access_key', 'secret_key')):
        raise ValueError('credentials are missing')
    return data


def presign(data, method, bucket, key='', query=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp, date = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    scope = date + '/' + data['region'] + '/s3/aws4_request'
    host = urllib.parse.urlsplit(data['endpoint']).netloc
    path = '/' + bucket + ('/' + urllib.parse.quote(key, safe='/~') if key else '')
    params = dict(query or {})
    params.update({'X-Amz-Algorithm': 'AWS4-HMAC-SHA256', 'X-Amz-Credential': data['access_key'] + '/' + scope,
                   'X-Amz-Date': stamp, 'X-Amz-Expires': '60', 'X-Amz-SignedHeaders': 'host'})
    encoded = '&'.join(urllib.parse.quote(k, safe='~') + '=' + urllib.parse.quote(v, safe='~')
                       for k, v in sorted(params.items()))
    canonical = '\n'.join([method, path, encoded, 'host:' + host + '\n', 'host', 'UNSIGNED-PAYLOAD'])
    message = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    derived = ('AWS4' + data['secret_key']).encode()
    for part in (date, data['region'], 's3', 'aws4_request'):
        derived = hmac.new(derived, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(derived, message.encode(), hashlib.sha256).hexdigest()
    return data['endpoint'] + path + '?' + encoded + '&X-Amz-Signature=' + signature


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(url, method, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, method=method, data=body)
    try:
        with opener.open(req, timeout=20) as response:
            return response.status, response.read(4097), ''
    except urllib.error.HTTPError as exc:
        code = ''
        try:
            code = ET.fromstring(exc.read(4097)).findtext('Code') or ''
        except ET.ParseError:
            pass
        return exc.code, b'', code if re.fullmatch(r'[A-Za-z0-9]+', code) else 'unknown'


def run(data):
    key = 'infra-validation/' + secrets.token_hex(16) + '.txt'
    payload = b'JECT development S3 synthetic validation\n'
    created = False
    result = {}
    try:
        # 응답을 받기 전 연결이 끊겨도 생성됐을 수 있으므로 자기 키를 정리한다.
        created = True
        status, _, code = request(presign(data, 'PUT', BUCKET, key), 'PUT', payload)
        if status not in (200, 201):
            created = False
            raise RuntimeError('signed PUT failed: HTTP ' + str(status) + ' ' + code)
        status, content, _ = request(presign(data, 'GET', BUCKET, key), 'GET')
        if status != 200 or hashlib.sha256(content).digest() != hashlib.sha256(payload).digest():
            raise RuntimeError('signed GET/hash verification failed')
        result['signed_put_get_hash'] = True
        status, _, _ = request(data['endpoint'] + '/' + BUCKET + '/' + key, 'GET')
        if status not in (403, 404):
            raise RuntimeError('anonymous GET was not denied')
        result['anonymous_get_denied'] = status
        for bucket in ('ject-prod-uploads', 'ject-db-backups'):
            status, _, code = request(presign(data, 'GET', bucket, query={'list-type': '2', 'max-keys': '1'}), 'GET')
            if status not in (403, 404):
                raise RuntimeError('out-of-scope bucket listing was not denied')
            result[bucket + '_list_denied'] = {'status': status, 'code': code}
    finally:
        if created:
            status, _, _ = request(presign(data, 'DELETE', BUCKET, key), 'DELETE')
            if status not in (200, 204):
                raise RuntimeError('synthetic object cleanup failed; owned key: ' + key)
            status, _, code = request(presign(data, 'GET', BUCKET, key), 'GET')
            if status != 404:
                raise RuntimeError('synthetic object deletion could not be verified')
            result['signed_delete_and_missing'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps({'result': 'success', 'checks': run(credentials(args.credentials))}))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('S3 validation failed; raw error suppressed to protect credentials', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
