#!/usr/bin/env python3
"""JECT Grafana 알림 규칙·대시보드 생성기(표준 라이브러리만).

    python3 infra/observability/grafana/generate.py

생성물(직접 고치지 말고 이 파일을 고친 뒤 다시 실행한다):
  provisioning/alerting/rules.yaml   알림 규칙(폴더 JECT)
  dashboards/ject-*.json             대시보드 3개(개요·앱·로그)

알림 기준은 docs/인프라-설계.md 「알림 초기값」을 따른다. 수치는 초기값이며 실제 부하·소음을 보고 조정한다.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROM = "prom"
LOKI = "loki"

NODE_HOSTS = ["prod-app", "prod-data", "dev"]
APP_HOSTS = ["prod-app", "dev"]


def expected(hosts):
    return " or ".join(f'label_replace(vector(1), "host", "{h}", "", "")' for h in hosts)


def rule(uid, title, expr, op, threshold, for_, severity, summary, description, ds=PROM, rng=600, nodata="OK"):
    model = {"refId": "A", "expr": expr, "instant": True, "intervalMs": 30000, "maxDataPoints": 43200}
    if ds == LOKI:
        model = {"refId": "A", "expr": expr, "queryType": "instant", "intervalMs": 30000, "maxDataPoints": 43200}
    return {
        "uid": uid,
        "title": title,
        "condition": "C",
        "data": [
            {"refId": "A", "relativeTimeRange": {"from": rng, "to": 0}, "datasourceUid": ds, "model": model},
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "A",
                    "conditions": [{"evaluator": {"type": op, "params": [threshold]}}],
                },
            },
        ],
        "noDataState": nodata,
        "execErrState": "Alerting",
        "for": for_,
        "labels": {"severity": severity},
        "annotations": {"summary": summary, "description": description},
        "isPaused": False,
    }


HOST = "{{ $labels.host }}"
VAL = "{{ $values.A.Value }}"

RULES = {
    "ject-infra": [
        rule("ject-host-down", "서버 지표 끊김",
             f'({expected(NODE_HOSTS)}) unless on(host) (last_over_time(up{{job="node"}}[2m]) == 1)',
             "gt", 0, "2m", "critical",
             f"{HOST} 서버의 지표가 2분 넘게 들어오지 않습니다",
             "VM 정지, Alloy·Node Exporter 중지, 개발·모니터링 VM으로 가는 네트워크(NSG 9090) 문제일 수 있습니다. "
             "docker compose -p ject-agent ps, OCI 콘솔 인스턴스 상태를 확인하세요."),
        rule("ject-disk-80", "디스크 80% 초과",
             '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
             "gt", 80, "5m", "warning",
             f"{HOST} 디스크 사용률 {VAL}%",
             "로그·이미지·DB 증가량을 확인하세요(docker system df, du -sh /srv/ject/*). 무료 블록 200GB를 다 써서 디스크를 늘릴 수 없습니다."),
        rule("ject-disk-90", "디스크 90% 초과",
             '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
             "gt", 90, "2m", "critical",
             f"{HOST} 디스크 사용률 {VAL}% (긴급)",
             "배포는 여유 15% 미만에서 거부됩니다. 오래된 이미지·로그를 정리하세요(실행·복구용 이미지는 남김)."),
        rule("ject-memory-low", "가용 메모리 15% 미만",
             '100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes',
             "lt", 15, "5m", "warning",
             f"{HOST} 가용 메모리 {VAL}%",
             "컨테이너별 사용량(docker stats --no-stream)과 메모리 상한을 확인하세요."),
        rule("ject-cpu-high", "CPU 85% 초과(10분)",
             '100 * (1 - avg by(host) (rate(node_cpu_seconds_total{mode="idle"}[5m])))',
             "gt", 85, "10m", "warning",
             f"{HOST} CPU 사용률 {VAL}%",
             "VM당 1 OCPU입니다. 개발 앱·백업·부하 시험이 겹쳤는지 확인하세요."),
    ],
    "ject-backup": [
        rule("ject-backup-failed", "운영 DB 백업 실패",
             '1 - ject_backup_last_run_success', "gt", 0, "0s", "critical",
             "운영 DB 백업이 실패했습니다",
             "운영 데이터 VM: sudo cat /srv/ject/backup-status/last.json, journalctl -u ject-pg-backup. "
             "고친 뒤 sudo systemctl start ject-pg-backup 으로 다시 실행하세요."),
        rule("ject-backup-stale", "운영 DB 백업 26시간 넘게 성공 없음",
             '((time() - ject_backup_last_success_timestamp_seconds) / 3600) or on() (999 * absent(ject_backup_last_success_timestamp_seconds))',
             "gt", 26, "0s", "critical",
             f"마지막 백업 성공 후 {VAL}시간(999는 백업 지표 없음)",
             "매일 04:00 KST 백업이 돌지 않았거나 실패했습니다. ject-pg-backup.timer와 백업 지표 파일(/var/lib/ject/textfile)을 확인하세요."),
        rule("ject-restore-test-failed", "백업 복원 시험 실패",
             '1 - ject_restore_test_last_run_success', "gt", 0, "0s", "critical",
             "월간 백업 복원 시험이 실패했습니다",
             "운영 데이터 VM: sudo cat /srv/ject/backup-status/restore-last.json, journalctl -u ject-pg-restore-test."),
    ],
    "ject-external": [
        rule("ject-probe-fail", "공인 주소 접속 실패",
             'probe_success or on() (0 * absent(probe_success))', "lt", 1, "3m", "critical",
             "{{ $labels.target }} 공인 주소(/readyz) 접속 실패",
             "개발·모니터링 VM에서 NAT를 거쳐 공인 HTTPS 주소를 1분마다 시험합니다. 운영 Nginx·인증서·앱 readiness(DB·Redis)를 확인하세요. "
             "OCI Health Checks는 무료가 아니어서 이 시험으로 대신합니다."),
        rule("ject-cert-expiry", "인증서 만료 14일 이내",
             '(probe_ssl_earliest_cert_expiry - time()) / 86400', "lt", 14, "0s", "warning",
             "{{ $labels.target }} 인증서 만료까지 {{ $values.A.Value }}일",
             "자동 갱신(ject-certbot-renew.timer, 만료 30일 전부터 시도)이 실패하고 있습니다. sudo /opt/ject/bin/ject-cert renew 로그를 확인하세요."),
    ],
    "ject-app": [
        rule("ject-app-down", "앱 지표 끊김",
             f'({expected(APP_HOSTS)}) unless on(host) (last_over_time(up{{job="app"}}[2m]) == 1)',
             "gt", 0, "3m", "critical",
             f"{HOST} 앱(관리 포트 8081 /actuator/prometheus) 응답 없음",
             "앱 컨테이너가 멈췄거나 재시작 중입니다. sudo /opt/ject/bin/ject-deploy status, docker logs로 확인하세요."),
        rule("ject-http-5xx", "HTTP 5xx 비율 5% 초과",
             '(sum by(host) (rate(http_server_requests_seconds_count{status=~"5.."}[5m])) / sum by(host) (rate(http_server_requests_seconds_count[5m]))) '
             'and on(host) (sum by(host) (increase(http_server_requests_seconds_count[5m])) >= 20)',
             "gt", 0.05, "5m", "critical",
             f"{HOST} 5xx 비율 {VAL}",
             "최근 배포·앱 오류 로그(Grafana 「JECT 로그」)·DB 상태를 확인하세요."),
        rule("ject-latency-p95", "응답 p95 1초 초과",
             'histogram_quantile(0.95, sum by(le, host) (rate(http_server_requests_seconds_bucket{uri!~"/actuator.*|/readyz|/healthz"}[5m])))',
             "gt", 1, "5m", "warning",
             f"{HOST} p95 {VAL}초",
             "CPU·DB·외부 호출을 확인하세요. OCR 같은 장시간 API는 별도 기준이 필요합니다."),
        rule("ject-db-pool-pending", "DB 커넥션 대기",
             'max by(host) (hikaricp_connections_pending)', "gt", 0, "5m", "warning",
             f"{HOST} DB 커넥션 대기 {VAL}개(5분 지속)",
             "느린 쿼리·커넥션 누수·풀 크기를 확인하세요(운영 PostgreSQL max_connections 60)."),
        rule("ject-error-logs", "운영 오류 로그 급증",
             'sum by(host, service) (count_over_time({env="prod", level="error"}[5m]))', "gt", 10, "0s", "warning",
             f"{HOST} {{{{ $labels.service }}}} 오류 로그 5분간 {VAL}건",
             "Grafana 「JECT 로그」에서 level=error로 원인을 확인하세요.", ds=LOKI, rng=300),
    ],
}


# ---- 간단한 YAML 출력(문자열은 JSON 따옴표 = 유효한 YAML) -------------------------

def to_yaml(v, ind=0):
    pad = "  " * ind
    if isinstance(v, dict):
        if not v:
            return " {}"
        out = ""
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                out += f"\n{pad}{k}:{to_yaml(x, ind + 1)}"
            else:
                out += f"\n{pad}{k}: {scalar(x)}"
        return out
    if isinstance(v, list):
        if not v:
            return " []"
        out = ""
        for x in v:
            if isinstance(x, dict) and x:
                body = to_yaml(x, ind + 1).lstrip("\n")
                out += f"\n{pad}- {body[len(pad) + 2:]}"
            elif isinstance(x, list):
                out += f"\n{pad}- {json.dumps(x, ensure_ascii=False)}"
            else:
                out += f"\n{pad}- {scalar(x)}"
        return out
    return " " + scalar(v)


def scalar(x):
    if isinstance(x, dict) or isinstance(x, list):
        return json.dumps(x, ensure_ascii=False)
    return json.dumps(x, ensure_ascii=False)


def write_rules():
    doc = {
        "apiVersion": 1,
        "groups": [
            {"orgId": 1, "name": name, "folder": "JECT", "interval": "1m", "rules": rules}
            for name, rules in RULES.items()
        ],
    }
    path = os.path.join(HERE, "provisioning", "alerting", "rules.yaml")
    with open(path, "w") as f:
        f.write("# 생성 파일: infra/observability/grafana/generate.py 로 다시 만든다(직접 수정 금지).\n")
        f.write(to_yaml(doc).lstrip("\n") + "\n")
    return path


# ---- 대시보드 -----------------------------------------------------------------

class Board:
    def __init__(self, uid, title, tags):
        self.uid, self.title, self.tags = uid, title, tags
        self.panels, self.x, self.y, self.row_h, self.pid = [], 0, 0, 0, 1
        self.templating = []

    def _place(self, w, h):
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.row_h
            self.row_h = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def row(self, title):
        if self.x:
            self.x, self.y = 0, self.y + self.row_h
        self.panels.append({"type": "row", "title": title, "id": self.pid, "collapsed": False,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.pid += 1
        self.y += 1
        self.row_h = 0

    def panel(self, kind, title, targets, w=8, h=8, unit=None, ds=PROM, options=None, field=None, desc=None):
        p = {
            "type": kind,
            "title": title,
            "id": self.pid,
            "gridPos": self._place(w, h),
            "datasource": {"type": "prometheus" if ds == PROM else "loki", "uid": ds},
            "targets": [
                dict({"refId": chr(65 + i), "datasource": {"type": "prometheus" if ds == PROM else "loki", "uid": ds}}, **t)
                for i, t in enumerate(targets)
            ],
            "fieldConfig": {"defaults": dict({"unit": unit} if unit else {}, **(field or {})), "overrides": []},
            "options": options or {},
        }
        if desc:
            p["description"] = desc
        self.panels.append(p)
        self.pid += 1

    def var(self, name, query, ds=PROM, label=None, include_all=True):
        self.templating.append({
            "name": name, "label": label or name, "type": "query",
            "datasource": {"type": "prometheus" if ds == PROM else "loki", "uid": ds},
            "query": query, "definition": query if isinstance(query, str) else "",
            "refresh": 2, "includeAll": include_all, "multi": True,
            # Loki는 빈 값도 맞는 선택자({a=~".*"})만으로는 조회를 거부한다 → "전체"를 .+로
            "allValue": ".+" if ds == LOKI else ".*",
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        })

    def json(self):
        return {
            "uid": self.uid, "title": self.title, "tags": self.tags, "timezone": "Asia/Seoul",
            "schemaVersion": 39, "version": 1, "editable": False, "refresh": "1m",
            "time": {"from": "now-6h", "to": "now"},
            "templating": {"list": self.templating}, "panels": self.panels,
        }


def q(expr, legend=None, **kw):
    t = {"expr": expr}
    if legend:
        t["legendFormat"] = legend
    t.update(kw)
    return t


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background",
        "graphMode": "none", "textMode": "value_and_name"}


def overview():
    b = Board("ject-overview", "JECT 개요", ["ject"])
    b.row("서버 (Node Exporter)")
    b.panel("stat", "지표 수집", [q('last_over_time(up{job="node"}[2m])', "{{host}}")], w=6, h=5, options=STAT,
            field={"mappings": [{"type": "value", "options": {"0": {"text": "끊김", "color": "red"}, "1": {"text": "정상", "color": "green"}}}]})
    b.panel("stat", "디스크 사용률(/)", [q('100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "{{host}}")],
            w=6, h=5, unit="percent", options=STAT,
            field={"thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 80}, {"color": "red", "value": 90}]}})
    b.panel("stat", "가용 메모리", [q('100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes', "{{host}}")],
            w=6, h=5, unit="percent", options=STAT,
            field={"thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 15}, {"color": "green", "value": 30}]}})
    b.panel("stat", "가동 시간", [q('time() - node_boot_time_seconds', "{{host}}")], w=6, h=5, unit="s", options=STAT)
    b.panel("timeseries", "CPU 사용률", [q('100 * (1 - avg by(host) (rate(node_cpu_seconds_total{mode="idle"}[5m])))', "{{host}}")], unit="percent")
    b.panel("timeseries", "가용 메모리", [q('node_memory_MemAvailable_bytes', "{{host}}")], unit="bytes")
    b.panel("timeseries", "디스크 사용량(/)", [q('node_filesystem_size_bytes{mountpoint="/"} - node_filesystem_avail_bytes{mountpoint="/"}', "{{host}}")], unit="bytes")
    b.panel("timeseries", "네트워크 수신", [q('sum by(host) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[5m]))', "{{host}}")], unit="Bps")
    b.panel("timeseries", "네트워크 송신", [q('sum by(host) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}[5m]))', "{{host}}")], unit="Bps")
    b.panel("timeseries", "디스크 I/O 사용 시간", [q('sum by(host) (rate(node_disk_io_time_seconds_total[5m]))', "{{host}}")], unit="percentunit")
    b.row("백업·복원 (운영 DB)")
    b.panel("stat", "마지막 백업 성공 후", [q('time() - ject_backup_last_success_timestamp_seconds', "경과")], w=6, h=5, unit="s", options=STAT,
            field={"thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 93600}]}})
    b.panel("stat", "마지막 백업 결과", [q('ject_backup_last_run_success', "결과")], w=6, h=5, options=STAT,
            field={"mappings": [{"type": "value", "options": {"0": {"text": "실패", "color": "red"}, "1": {"text": "성공", "color": "green"}}}]})
    b.panel("stat", "마지막 백업 크기·소요", [q('ject_backup_last_success_bytes', "크기"), q('ject_backup_last_duration_seconds', "소요(초)")], w=6, h=5, options=STAT)
    b.panel("stat", "마지막 복원 시험", [q('ject_restore_test_last_run_success', "결과")], w=6, h=5, options=STAT,
            field={"mappings": [{"type": "value", "options": {"0": {"text": "실패", "color": "red"}, "1": {"text": "성공", "color": "green"}}}]})
    b.row("공인 주소 시험·인증서 (개발·모니터링 VM → NAT → 공인 HTTPS)")
    b.panel("stat", "접속 시험", [q('probe_success', "{{target}}")], w=8, h=5, options=STAT,
            field={"mappings": [{"type": "value", "options": {"0": {"text": "실패", "color": "red"}, "1": {"text": "정상", "color": "green"}}}]})
    b.panel("stat", "인증서 남은 기간", [q('(probe_ssl_earliest_cert_expiry - time()) / 86400', "{{target}}")], w=8, h=5, unit="d", options=STAT,
            field={"thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 14}, {"color": "green", "value": 30}]}})
    b.panel("timeseries", "응답 시간", [q('probe_duration_seconds', "{{target}}")], w=8, h=5, unit="s")
    b.row("관측 도구")
    b.panel("timeseries", "Prometheus 시계열 수", [q('prometheus_tsdb_head_series', "series")], unit="short")
    b.panel("timeseries", "Alloy 메트릭 전송 실패", [q('sum by(host) (rate(prometheus_remote_storage_samples_failed_total[5m]))', "{{host}}")], unit="short")
    b.panel("timeseries", "Alloy 로그 전송 실패", [q('sum by(host) (rate(loki_write_dropped_entries_total[5m]))', "{{host}}")], unit="short")
    return b


def app():
    b = Board("ject-app", "JECT 앱", ["ject"])
    b.var("host", 'label_values(up{job="app"}, host)', label="서버")
    b.row("상태")
    b.panel("stat", "앱 지표 수집", [q('last_over_time(up{job="app", host=~"$host"}[2m])', "{{host}}")], w=6, h=5, options=STAT,
            field={"mappings": [{"type": "value", "options": {"0": {"text": "끊김", "color": "red"}, "1": {"text": "정상", "color": "green"}}}]})
    b.panel("stat", "앱 가동 시간", [q('time() - process_start_time_seconds{job="app", host=~"$host"}', "{{host}}")], w=6, h=5, unit="s", options=STAT)
    b.panel("timeseries", "스모크 앱 요청(실제 앱이 오면 비어 있음)", [q('sum by(host, pattern, status) (rate(ject_smoke_http_requests_total{host=~"$host"}[5m]))', "{{host}} {{pattern}} {{status}}")], w=12, h=5, unit="reqps")
    b.row("HTTP (Spring Boot Micrometer)")
    b.panel("timeseries", "요청 수", [q('sum by(host) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', "{{host}}")], unit="reqps")
    b.panel("timeseries", "5xx 비율", [q('sum by(host) (rate(http_server_requests_seconds_count{host=~"$host", status=~"5.."}[5m])) / sum by(host) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', "{{host}}")], unit="percentunit")
    b.panel("timeseries", "응답 p95", [q('histogram_quantile(0.95, sum by(le, host) (rate(http_server_requests_seconds_bucket{host=~"$host", uri!~"/actuator.*|/readyz|/healthz"}[5m])))', "{{host}}")], unit="s")
    b.panel("table", "경로별 요청·평균 응답(5분)", [q('sum by(host, method, uri, status) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', format="table", instant=True),
                                              q('sum by(host, method, uri, status) (rate(http_server_requests_seconds_sum{host=~"$host"}[5m])) / sum by(host, method, uri, status) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', format="table", instant=True)],
            w=24, h=8, options={"showHeader": True})
    b.row("JVM")
    b.panel("timeseries", "힙 사용", [q('sum by(host) (jvm_memory_used_bytes{host=~"$host", area="heap"})', "{{host}} used"), q('sum by(host) (jvm_memory_max_bytes{host=~"$host", area="heap"})', "{{host}} max")], unit="bytes")
    b.panel("timeseries", "GC 정지 시간(초/초)", [q('sum by(host) (rate(jvm_gc_pause_seconds_sum{host=~"$host"}[5m]))', "{{host}}")], unit="s")
    b.panel("timeseries", "스레드·프로세스 CPU", [q('jvm_threads_live_threads{host=~"$host"}', "{{host}} 스레드"), q('process_cpu_usage{host=~"$host"} * 100', "{{host}} CPU%")])
    b.row("DB 커넥션 풀 (HikariCP)")
    b.panel("timeseries", "활성·대기", [q('hikaricp_connections_active{host=~"$host"}', "{{host}} active"), q('hikaricp_connections_idle{host=~"$host"}', "{{host}} idle"), q('hikaricp_connections_pending{host=~"$host"}', "{{host}} pending")], w=12)
    b.panel("timeseries", "획득 시간·타임아웃", [q('rate(hikaricp_connections_acquire_seconds_sum{host=~"$host"}[5m]) / rate(hikaricp_connections_acquire_seconds_count{host=~"$host"}[5m])', "{{host}} 평균 획득"), q('increase(hikaricp_connections_timeout_total{host=~"$host"}[5m])', "{{host}} 타임아웃")], w=12)
    return b


def logs():
    b = Board("ject-logs", "JECT 로그", ["ject"])
    b.var("host", 'label_values(host)', ds=LOKI, label="서버")
    b.var("service", 'label_values(service)', ds=LOKI, label="서비스")
    b.panel("timeseries", "수준별 로그 수(5분)", [q('sum by(level) (count_over_time({host=~"$host", service=~"$service"}[5m]))', "{{level}}")], w=12, h=7, ds=LOKI)
    b.panel("timeseries", "Nginx 5xx(5분)", [q('sum by(host) (count_over_time({service="nginx", host=~"$host"} | json | status >= 500 [5m]))', "{{host}}")], w=12, h=7, ds=LOKI)
    b.panel("logs", "로그(민감정보는 수집 단계에서 가림)", [q('{host=~"$host", service=~"$service"}')], w=24, h=16, ds=LOKI,
            options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True})
    b.panel("logs", "JECT 작업(백업·복원 시험·인증서·알림 중계)", [q('{job="systemd"}')], w=24, h=10, ds=LOKI,
            options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"})
    return b


def write_dashboards():
    out = []
    for b in (overview(), app(), logs()):
        path = os.path.join(HERE, "dashboards", f"{b.uid}.json")
        with open(path, "w") as f:
            json.dump(b.json(), f, ensure_ascii=False, indent=1)
            f.write("\n")
        out.append(path)
    return out


if __name__ == "__main__":
    print(write_rules())
    for p in write_dashboards():
        print(p)
