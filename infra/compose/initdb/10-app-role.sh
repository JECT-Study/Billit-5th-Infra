#!/bin/bash
# 최초 initdb 때만 실행된다. 앱 전용 역할과 DB를 만든다(관리자 계정과 분리).
# DB 이름·역할 이름은 APP_DB/APP_ROLE로 바꿀 수 있다(개발 환경은 ject_dev).
set -euo pipefail
APP_DB="${APP_DB:-ject}"
APP_ROLE="${APP_ROLE:-ject_app}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v role="$APP_ROLE" -v db="$APP_DB" <<'SQL'
-- 비밀번호를 명령행 인자·서버 로그에 남기지 않는다(log_statement=ddl이 초기화 중에도 켜져 있음).
\set pw `cat /run/secrets/pg_app_password`
SET log_statement = 'none';
CREATE ROLE :"role" LOGIN PASSWORD :'pw';
CREATE DATABASE :"db" OWNER :"role" ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
SQL
