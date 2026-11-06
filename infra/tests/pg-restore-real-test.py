#!/usr/bin/env python3
"""명시적 격리 context에서 합성 PostgreSQL 복원. OCI/실제 백업/운영 접속 없음."""
import json
import secrets
import subprocess
import time

D = ['docker', '--context', 'colima-billit-verify']
IMAGE = 'postgres:17.11-bookworm'
PREFIX = 'billit-restore-verify-' + secrets.token_hex(4)
SOURCE, TARGET = PREFIX + '-source', PREFIX + '-target'
ROLE = 'ject_admin'


def docker(*args, data=None, check=True):
    r = subprocess.run(D + list(args), input=data, capture_output=True)
    if check and r.returncode:
        # 원문 SQL/인증값이 들어갈 수 있는 stderr는 출력하지 않는다.
        raise RuntimeError('isolated docker operation failed: ' + args[0])
    return r


def sql(name, role, statement, db='postgres', check=True):
    return docker('exec', '-i', name, 'psql', '-U', role, '-d', db,
                  '-qAtX', '-v', 'ON_ERROR_STOP=1', data=statement, check=check)


def start(name, role):
    docker('run', '-d', '--name', name, '--network', 'none', '--memory', '384m',
           '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_USER=' + role,
           '-e', 'POSTGRES_PASSWORD=synthetic-only-not-service-secret', IMAGE)
    for _ in range(60):
        if docker('exec', name, 'pg_isready', '-U', role, '-d', 'postgres', '-h', '127.0.0.1', '-q', check=False).returncode == 0:
            return
        time.sleep(.5)
    raise RuntimeError('isolated postgres readiness timeout')


try:
    digest = docker('image', 'inspect', IMAGE, '--format', '{{index .RepoDigests 0}}').stdout.decode().strip()
    start(SOURCE, 'ject_admin')
    sql(SOURCE, 'ject_admin', b"CREATE ROLE fixture_owner; CREATE ROLE fixture_reader; CREATE ROLE fixture_member LOGIN; GRANT fixture_reader TO fixture_member; CREATE DATABASE fixture OWNER fixture_owner;")
    sql(SOURCE, 'ject_admin', b'CREATE TABLE public.restore_fixture(id integer PRIMARY KEY, value text NOT NULL); INSERT INTO public.restore_fixture VALUES (1,\'synthetic\'),(2,\'fixture\');', 'fixture')
    sql(SOURCE, 'ject_admin', b"ALTER TABLE public.restore_fixture OWNER TO fixture_owner; CREATE SEQUENCE public.fixture_seq; ALTER SEQUENCE public.fixture_seq OWNER TO fixture_owner; GRANT SELECT ON public.restore_fixture TO fixture_reader; GRANT USAGE ON SEQUENCE public.fixture_seq TO fixture_reader; ALTER DEFAULT PRIVILEGES FOR ROLE fixture_owner IN SCHEMA public GRANT SELECT ON TABLES TO fixture_reader; GRANT CONNECT ON DATABASE fixture TO fixture_reader;", 'fixture')
    globals_sql = docker('exec', SOURCE, 'pg_dumpall', '-U', 'ject_admin', '--globals-only').stdout
    dump = docker('exec', SOURCE, 'pg_dump', '-U', 'ject_admin', '-d', 'fixture', '-Fc').stdout
    start(TARGET, ROLE)
    # 스크립트와 동일한 bootstrap 보존 및 ON_ERROR_STOP 옵션. 전송만 stdin으로 대체.
    # 실행 스크립트의 정확한 필터 본문을 사용한다.
    from pathlib import Path
    import tempfile
    block = (Path(__file__).resolve().parents[1] / 'scripts/ject-pg-restore-test').read_text().split("<<'PYGLOBALS'\n", 1)[1].split('\nPYGLOBALS', 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / 'globals.sql', Path(tmp) / 'filtered.sql'
        src.write_bytes(globals_sql)
        subprocess.run(['python3', '-c', block, str(src), str(dst)], check=True)
        filtered = dst.read_bytes()
    sql(TARGET, ROLE, filtered)
    docker('exec', '-i', TARGET, 'pg_restore', '-U', ROLE, '-d', 'template1',
           '--create', '--clean', '--if-exists', '--exit-on-error', data=dump)
    count = sql(TARGET, 'ject_admin', b'SELECT count(*) FROM public.restore_fixture;', 'fixture').stdout.strip()
    assert count == b'2'
    auth_query = b"SELECT rolpassword FROM pg_authid WHERE rolname='ject_admin';"
    assert sql(SOURCE, ROLE, auth_query).stdout == sql(TARGET, ROLE, auth_query).stdout
    assert sql(TARGET, ROLE, b"SELECT oid=10 AND rolsuper AND rolcanlogin FROM pg_authid WHERE rolname='ject_admin';").stdout.strip() == b't'
    assert sql(TARGET, ROLE, b"SELECT pg_get_userbyid(grantor) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='fixture_member');").stdout.strip() == b'ject_admin'
    assert sql(TARGET, ROLE, b"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='fixture';").stdout.strip() == b'fixture_owner'
    assert sql(TARGET, ROLE, b"SELECT count(*) FROM pg_class WHERE relname IN ('restore_fixture','fixture_seq') AND relowner=(SELECT oid FROM pg_roles WHERE rolname='fixture_owner');", 'fixture').stdout.strip() == b'2'
    assert sql(TARGET, ROLE, b"SELECT pg_has_role('fixture_member','fixture_reader','MEMBER') AND has_table_privilege('fixture_member','public.restore_fixture','SELECT') AND has_sequence_privilege('fixture_member','public.fixture_seq','USAGE') AND has_database_privilege('fixture_member','fixture','CONNECT');", 'fixture').stdout.strip() == b't'
    sql(TARGET, ROLE, b"SET ROLE fixture_owner; CREATE TABLE public.after_restore(id integer);", 'fixture')
    assert sql(TARGET, ROLE, b"SELECT has_table_privilege('fixture_member','public.after_restore','SELECT') AND NOT has_table_privilege('fixture_member','public.after_restore','INSERT');", 'fixture').stdout.strip() == b't'
    # postgres archive can replace the target's initial postgres DB from template1.
    postgres_dump = docker('exec', SOURCE, 'pg_dump', '-U', 'ject_admin', '-d', 'postgres', '-Fc').stdout
    docker('exec', '-i', TARGET, 'pg_restore', '-U', ROLE, '-d', 'template1', '--create', '--clean', '--if-exists', '--exit-on-error', data=postgres_dump)
    assert sql(TARGET, ROLE, globals_sql, check=False).returncode != 0
    assert sql(TARGET, ROLE, b'INVALID SYNTHETIC SQL;', check=False).returncode != 0
    assert sql(TARGET, 'ject_admin', b'SELECT count(*) FROM public.missing_table;', 'fixture', check=False).returncode != 0
    summary = {'result': 'success', 'image_digest': digest,
                      'checks': ['globals_role_restore', 'database_restore', 'rows_2',
                                 'bootstrap_identity_password_and_grantor', 'database_table_sequence_ownership', 'role_membership_and_grants', 'default_privileges', 'postgres_database_recreated', 'duplicate_role_rejected', 'invalid_sql_rejected', 'count_query_error_rejected'],
                      'not_tested': ['OCI_download', 'manifest_checksum', 'full_script_status',
                                     'application_data', 'team_notification']}
finally:
    cleanup_failed = []
    for name in (TARGET, SOURCE):
        if docker('rm', '-fv', name, check=False).returncode:
            remaining = docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$', check=False)
            if remaining.returncode or remaining.stdout.strip():
                cleanup_failed.append(name)
    if cleanup_failed:
        raise RuntimeError('isolated test cleanup failed; inspect owned containers: ' + ','.join(cleanup_failed))
print(json.dumps(summary))
