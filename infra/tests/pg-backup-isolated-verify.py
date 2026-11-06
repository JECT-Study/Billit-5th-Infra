#!/usr/bin/env python3
"""명시적인 로컬 백업 디렉터리를 격리 복원. 운영/OCI 접속 없음, 원문 출력 없음."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

D = ['docker', '--context', 'colima-billit-verify']
IMAGE = 'postgres@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994'


def run(*args, data=None, check=True):
    r = subprocess.run(D + list(args), input=data, capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError('isolated backup validation operation failed: ' + args[0])
    return r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup_directory', type=Path)
    root = parser.parse_args().backup_directory.resolve()
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    entries = [manifest['globals']] + manifest['databases']
    for entry in entries:
        p = root / entry['file']
        if Path(entry['file']).name != entry['file'] or p.is_symlink() or not p.is_file():
            raise ValueError('unsafe backup path')
        if hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('checksum mismatch')
    name = 'billit-backup-verify-' + secrets.token_hex(6)
    role = 'ject_restore_' + secrets.token_hex(12)
    table_count = row_count = 0
    try:
        run('create', '--name', name, '--network', 'none', '--memory', '768m', '--cpus', '0.5',
            '--tmpfs', '/var/lib/postgresql/data:mode=0700,size=256m',
            '-e', 'POSTGRES_USER=' + role, '-e', 'POSTGRES_PASSWORD=' + secrets.token_hex(24), IMAGE)
        run('cp', str(root), name + ':/restore')
        run('start', name)
        for _ in range(60):
            if run('exec', name, 'pg_isready', '-U', role, '-d', 'postgres', '-h', '127.0.0.1', '-q', check=False).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('readiness timeout')
        run('exec', name, 'psql', '-U', role, '-d', 'postgres', '-qX', '-v', 'ON_ERROR_STOP=1', '-f', '/restore/' + manifest['globals']['file'])
        for db in manifest['databases']:
            if db['name'] != 'postgres':
                run('exec', '-i', name, 'psql', '-U', 'ject_admin', '-d', 'postgres', '-qAtX',
                    '-v', 'ON_ERROR_STOP=1', '-v', 'db=' + db['name'], data='CREATE DATABASE :"db";\n')
            run('exec', name, 'pg_restore', '-U', 'ject_admin', '-d', db['name'], '--exit-on-error', '--no-owner', '--role=ject_admin', '/restore/' + db['file'])
            # manifest table keys originate from PostgreSQL format('%I.%I'). Restrict to two identifiers.
            ident = r'(?:[A-Za-z_][A-Za-z_0-9$]*|"(?:[^"]|"")+")'
            for table, expected in db['tables'].items():
                if not re.fullmatch(ident + r'\.' + ident, table):
                    raise ValueError('unsafe table identifier')
                r = run('exec', name, 'psql', '-U', 'ject_admin', '-d', db['name'], '-AtqX', '-c', 'SELECT count(*) FROM ' + table)
                if int(r.stdout.strip()) != expected:
                    raise RuntimeError('row count mismatch')
                table_count += 1
                row_count += expected
    finally:
        run('rm', '-fv', name, check=False)
        if name in run('container', 'ls', '-a', '--format', '{{.Names}}').stdout.splitlines():
            raise RuntimeError('owned restore container remains')
    print(json.dumps({'result':'success','databases':len(manifest['databases']), 'tables':table_count,'rows':row_count,
                      'checksums':'all_match','globals_restored':True,'cleanup_verified':True,
                      'not_verified':['original object ownership','complete role privileges','Billit application workflow','full production restore script']}))


if __name__ == '__main__':
    main()
