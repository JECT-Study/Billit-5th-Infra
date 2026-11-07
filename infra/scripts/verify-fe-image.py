#!/usr/bin/env python3
"""로컬 ARM64 FE 이미지의 격리 기동 계약 검사. 게시·배포·업무 API 호출 없음."""
import argparse
import json
import re
import secrets
import subprocess
import sys
import time

SOURCE = 'https://github.com/JECT-Study/Billit-5th-Client'
INFRA_SOURCE = 'https://github.com/JECT-Study/Billit-5th-Infra'
PROBE = r'''
(async () => {
  const health = await fetch('http://127.0.0.1:3000/healthz', {signal: AbortSignal.timeout(5000), redirect: 'error'});
  if (health.status !== 200 || (await health.text()).trim() !== 'ok') throw new Error('healthz');
  const root = await fetch('http://127.0.0.1:3000/', {signal: AbortSignal.timeout(5000), redirect: 'error'});
  if (root.status !== 200 || !(root.headers.get('content-type') || '').includes('text/html')) throw new Error('root status');
  const html = await root.text();
  if (!html.includes('Billit') || !/<!doctype html>/i.test(html)) throw new Error('root document');
  process.stdout.write('fe-probes-ok');
})().catch(() => process.exit(1));
'''


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError('Docker operation failed; raw output suppressed')
    return result


def verify(image, source_sha, infra_sha):
    if not re.fullmatch(r'[a-f0-9]{40}', source_sha) or not re.fullmatch(r'[a-f0-9]{40}', infra_sha):
        raise ValueError('source and infra revisions must be full commit SHAs')
    if not re.fullmatch(r'ghcr\.io/[a-z0-9_.-]+/ject-fe:[a-zA-Z0-9_.-]+', image):
        raise ValueError('expected a local ject-fe registry tag')
    info = json.loads(docker('image', 'inspect', image).stdout)[0]
    config = info.get('Config') or {}
    labels = config.get('Labels') or {}
    if info.get('Os') != 'linux' or info.get('Architecture') != 'arm64':
        raise ValueError('expected linux/arm64 image')
    if labels.get('org.opencontainers.image.revision') != source_sha or labels.get('io.ject.infra.revision') != infra_sha:
        raise ValueError('image provenance mismatch')
    if (labels.get('org.opencontainers.image.source') != INFRA_SOURCE
            or labels.get('io.ject.app.source') != SOURCE):
        raise ValueError('image source repository mismatch')
    if not config.get('User') or not (config.get('Healthcheck') or {}).get('Test'):
        raise ValueError('image must declare a user and healthcheck')
    name = 'ject-fe-image-check-' + secrets.token_hex(8)
    try:
        docker('run', '-d', '--pull=never', '--name', name, '--network', 'none', '--memory', '384m',
               '--memory-swap', '384m', '--cpus', '0.20', '--pids-limit', '128',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', image)
        uid = docker('exec', name, 'id', '-u').stdout.strip()
        if not uid.isdecimal() or int(uid) == 0:
            raise ValueError('FE process must run as a non-root user')
        deadline = time.monotonic() + 120
        while True:
            state = json.loads(docker('inspect', '--format', '{{json .State}}', name).stdout)
            health = (state.get('Health') or {}).get('Status')
            if not state.get('Running') or state.get('OOMKilled') or health == 'unhealthy':
                raise RuntimeError('FE container stopped, OOM-killed or unhealthy')
            if health == 'healthy':
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('FE healthcheck timeout')
            time.sleep(2)
        if docker('exec', name, 'node', '-e', PROBE).stdout.strip() != 'fe-probes-ok':
            raise RuntimeError('FE HTTP probe failed')
    finally:
        docker('rm', '-fv', name, check=False)
        if docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$').stdout.strip():
            raise RuntimeError('owned FE verification container cleanup failed')
    return {'result': 'success', 'image_id': info['Id'], 'source_sha': source_sha, 'infra_sha': infra_sha,
            'checks': ['linux/arm64', '384MiB', 'non_root', 'image_healthcheck', 'healthz', 'root_html'],
            'not_verified': ['development_routing', 'backend_connection', 'business_e2e', 'production']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--infra-sha', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.image, args.source_sha, args.infra_sha)))
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('FE verification failed; raw output suppressed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
