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


def request(url, method, body=None, headers=None, response_headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with opener.open(req, timeout=20) as response:
            if response_headers is not None:
                response_headers.update({k.lower(): v for k, v in response.headers.items()})
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
        status, _, _ = request(presign(data, 'HEAD', BUCKET, key), 'HEAD')
        if status != 200:
            raise RuntimeError('signed HEAD verification failed')
        result['signed_head'] = True
        expired_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
        status, _, code = request(presign(data, 'GET', BUCKET, key, now=expired_at), 'GET')
        if status != 403 or code not in ('AccessDenied', 'RequestExpired'):
            raise RuntimeError('expired signed GET was not rejected as expected')
        result['expired_signed_get_denied'] = {'status': status, 'code': code}
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


def browser_origin(path):
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('origin requires a regular 0600 file')
    value = path.read_text().strip()
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]{1,5})?', value):
        raise ValueError('expected HTTPS origin without path')
    return value


def cors_checks(headers, origin):
    exposed = {v.strip().lower() for v in headers.get('access-control-expose-headers', '').split(',')}
    return {'origin_allowed': headers.get('access-control-allow-origin') in (origin, '*'),
            'etag_present': bool(headers.get('etag')),
            'etag_exposed': 'etag' in exposed or '*' in exposed}


def run_browser(data, origin):
    key = 'infra-validation/' + secrets.token_hex(16) + '.txt'
    payload = b'JECT development browser storage validation\n'
    result = {}
    created = False
    try:
        put_url = presign(data, 'PUT', BUCKET, key)
        response = {}
        status, _, _ = request(put_url, 'OPTIONS', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'content-type'}, response_headers=response)
        methods = {v.strip().upper() for v in response.get('access-control-allow-methods', '').split(',')}
        headers = {v.strip().lower() for v in response.get('access-control-allow-headers', '').split(',')}
        result['preflight'] = {'status': status,
            'origin_allowed': cors_checks(response, origin)['origin_allowed'],
            'put_allowed': 'PUT' in methods or '*' in methods,
            'content_type_allowed': 'content-type' in headers or '*' in headers}
        created = True
        response = {}
        status, _, code = request(put_url, 'PUT', payload,
            headers={'Origin': origin, 'Content-Type': 'text/plain'}, response_headers=response)
        if status not in (200, 201):
            raise RuntimeError('browser synthetic PUT failed: HTTP ' + str(status))
        result['put'] = {'status': status, **cors_checks(response, origin)}
        for method in ('GET', 'HEAD'):
            response = {}
            status, content, _ = request(presign(data, method, BUCKET, key), method,
                headers={'Origin': origin}, response_headers=response)
            result[method.lower()] = {'status': status, **cors_checks(response, origin)}
            if status != 200 or (method == 'GET' and content != payload):
                raise RuntimeError('browser synthetic read verification failed')
        status, _, code = request(presign(data, 'GET', BUCKET, key), 'PUT', b'wrong method',
            headers={'Origin': origin, 'Content-Type': 'text/plain'})
        result['wrong_method'] = {'status': status, 'code': code, 'denied': status == 403}
        status, _, code = request(presign(data, 'PUT', BUCKET, key), 'PUT', b'overwrite attempt',
            headers={'Origin': origin, 'Content-Type': 'text/plain'})
        result['overwrite'] = {'status': status, 'code': code,
            'denied': status in (403, 404) and code in ('AccessDenied', 'NoSuchBucket')}
        status, content, _ = request(presign(data, 'GET', BUCKET, key), 'GET')
        result['original_unchanged'] = status == 200 and content == payload
    finally:
        if created:
            status, _, _ = request(presign(data, 'DELETE', BUCKET, key), 'DELETE')
            if status not in (200, 204):
                raise RuntimeError('browser synthetic cleanup failed; owned key: ' + key)
            status, _, _ = request(presign(data, 'GET', BUCKET, key), 'GET')
            if status != 404:
                raise RuntimeError('browser synthetic deletion unverified')
            result['deleted_and_missing'] = True
    result['passed'] = browser_passed(result)
    return result


def browser_passed(result):
    pre = result['preflight']
    return (200 <= pre['status'] < 300 and all(pre[k] for k in
        ('origin_allowed', 'put_allowed', 'content_type_allowed'))
        and all(result[m]['origin_allowed'] and result[m]['etag_present'] and result[m]['etag_exposed']
                for m in ('put', 'get', 'head'))
        and result['wrong_method']['denied'] and result['overwrite']['denied']
        and result['original_unchanged'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True, type=Path)
    parser.add_argument('--origin-file', type=Path, help='optional private HTTPS development origin file')
    args = parser.parse_args()
    try:
        data = credentials(args.credentials)
        checks = run_browser(data, browser_origin(args.origin_file)) if args.origin_file else run(data)
        passed = checks.get('passed', True)
        print(json.dumps({'result': 'success' if passed else 'failed', 'checks': checks}))
        if not passed:
            return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('S3 validation failed; raw error suppressed to protect credentials', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
