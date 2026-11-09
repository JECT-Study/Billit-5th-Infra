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
             # I/O 대기(iowait)는 CPU 포화가 아니므로 idle과 함께 뺀다(재부팅 직후 iowait로 85%를 넘는 오탐을 실측).
             '100 * (1 - avg by(host) (sum by(host, cpu) (rate(node_cpu_seconds_total{mode=~"idle|iowait"}[5m]))))',
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
             # 지표가 아예 없을 때(999)는 운영 데이터 VM이 보일 때만 울린다(VM·수집기가 죽은 경우는 「서버 지표 끊김」이 맡는다 — 중복 방지)
             '((time() - ject_backup_last_success_timestamp_seconds) / 3600) or on() '
             '(999 * (absent(ject_backup_last_success_timestamp_seconds) and on() (count(last_over_time(up{job="node", host="prod-data"}[2m]) == 1) > 0)))',
             "gt", 26, "0s", "critical",
             f"마지막 백업 성공 후 {VAL}시간(999는 백업 지표 없음)",
             "매일 04:00 KST 백업이 돌지 않았거나 실패했습니다. ject-pg-backup.timer와 백업 지표 파일(/var/lib/ject/textfile)을 확인하세요."),
        rule("ject-restore-test-failed", "백업 복원 시험 실패",
             '1 - ject_restore_test_last_run_success', "gt", 0, "0s", "critical",
             "월간 백업 복원 시험이 실패했습니다",
             "운영 데이터 VM: sudo cat /srv/ject/backup-status/restore-last.json, journalctl -u ject-pg-restore-test."),
    ],
    "ject-restore-freshness": [
        rule("ject-restore-test-stale", "월간 복원 시험 오래됨 또는 지표 누락",
             '(up{job="node",host="prod-data"} == 1 '
             'and (time() - timestamp(up{job="node",host="prod-data"}) < 180)) '
             'unless on(host) (ject_restore_test_last_run_timestamp_seconds{job="node",host="prod-data"} > 0 '
             'and (time() - ject_restore_test_last_run_timestamp_seconds{job="node",host="prod-data"} <= 32 * 86400) '
             'and (ject_restore_test_last_run_timestamp_seconds{job="node",host="prod-data"} <= time()) '
             'and (time() - timestamp(ject_restore_test_last_run_timestamp_seconds{job="node",host="prod-data"}) < 180))',
             "gt", 0, "5m", "warning",
             "월간 복원 시험 기록이 오래되었거나 유효한 지표가 없습니다",
             "초기값: 매월1일05시KST 일정에 대해 최대32일 경과를 감시합니다. "
             "정확한 월별 실행기한 감시는 아니며 짧은 달에는 탐지가 늦습니다. "
             "지표 누락·180초 이상 오래된 표본·미래 시각도 경고합니다. "
             "ject-pg-restore-test.timer와 restore-last.json을 읽기 전용으로 확인하세요. "
             "최근 실행은 복원 성공 증거가 아니며 기존 실패 경보를 함께 확인합니다."),
    ],
    "ject-external": [
        rule("ject-probe-fail", "공인 주소 접속 실패",
             # 두 대상을 각각 유지한다. 180초 이상 오래된 성공 표본도 누락으로 처리한다.
             '(min by(target) (probe_success{job=~"integrations/blackbox/(dev|prod)",host="dev",target=~"dev|prod"} '
             'and (time() - timestamp(probe_success{job=~"integrations/blackbox/(dev|prod)",host="dev",target=~"dev|prod"}) < 180))) '
             'or on(target) (label_replace(vector(0), "target", "dev", "", "") '
             'or label_replace(vector(0), "target", "prod", "", ""))', "lt", 1, "3m", "critical",
             "{{ $labels.target }} 공인 주소(/readyz) 접속 실패",
             "개발·모니터링 VM에서 NAT를 거쳐 공인 HTTPS 주소를 1분마다 시험합니다. 대상별 실패·누락·180초 이상 오래된 표본을 감지합니다. 운영 Nginx·인증서·앱 readiness(DB·Redis)를 확인하세요. "
             "OCI Health Checks는 무료가 아니어서 이 시험으로 대신합니다."),
        rule("ject-cert-expiry", "인증서 만료 14일 이내",
             '(probe_ssl_earliest_cert_expiry - time()) / 86400', "lt", 14, "0s", "warning",
             "{{ $labels.target }} 인증서 만료까지 {{ $values.A.Value }}일",
             "자동 갱신(ject-certbot-renew.timer, 만료 30일 전부터 시도)이 실패하고 있습니다. sudo /opt/ject/bin/ject-cert renew 로그를 확인하세요."),
    ],
    "ject-observability": [
        rule("ject-obs-component-down", "관측 도구 수집 실패 또는 누락",
             '(' + ' or '.join(f'label_replace(label_replace(vector(1), "host", "dev", "", ""), "component", "{c}", "", "")'
                               for c in ("grafana", "loki", "prometheus")) + ') '
             'unless on(host,component) (up{job="obs",host="dev",component=~"grafana|loki|prometheus"} == 1 '
             'and (time() - timestamp(up{job="obs",host="dev",component=~"grafana|loki|prometheus"}) < 180)) '
             'and on(host) (up{job="node",host="dev"} == 1 and (time() - timestamp(up{job="node",host="dev"}) < 180))',
             "gt", 0, "2m", "critical", "{{ $labels.component }} 관측 지표 수집 실패",
             "초기값: 180초 신선도와 2분 지속을 확인합니다. 개발 노드 지표가 살아 있을 때만 울립니다. "
             "Grafana/Prometheus 자체가 완전히 멈추면 이 내부 경보도 전달하지 못하므로 OCI 직접 이메일 경로를 유지합니다."),
        rule("ject-metrics-write-failed", "메트릭 전송 실패 증가",
             'sum by(host) (increase(prometheus_remote_storage_samples_failed_total{job="integrations/self",host=~"dev|prod-app|prod-data"}[5m])) '
             'and on(host) (up{job="node",host=~"dev|prod-app|prod-data"} == 1 '
             'and (time() - timestamp(up{job="node",host=~"dev|prod-app|prod-data"}) < 180))',
             "gt", 0, "2m", "warning", f"{HOST} 메트릭 전송 실패 증가",
             "초기값: 최근 5분 실패 증가가 2분 지속될 때 확인합니다. Alloy remote-write·인증·수신기 상태를 확인하세요. "
             "노드 미수집은 서버 지표 끊김 경보가 담당하며, 이 규칙만으로 모든 전송 손실을 보장하지 않습니다."),
        rule("ject-logs-write-dropped", "로그 전송 폐기 증가",
             'sum by(host) (increase(loki_write_dropped_entries_total{job="integrations/self",host=~"dev|prod-app|prod-data"}[5m])) '
             'and on(host) (up{job="node",host=~"dev|prod-app|prod-data"} == 1 '
             'and (time() - timestamp(up{job="node",host=~"dev|prod-app|prod-data"}) < 180))',
             "gt", 0, "2m", "warning", f"{HOST} Loki 전송 로그 폐기 증가",
             "초기값: 최근 5분 폐기 증가가 2분 지속될 때 확인합니다. Loki 수신 제한·인증·전송 오류를 확인하고 원본 로그를 알림에 복사하지 않습니다. "
             "정상 마스킹/drop 처리와 전송 실패 카운터를 구분합니다."),
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
# 원칙: 지금 실제로 들어오는 지표·로그만 기본 화면에 둔다. 실제 BE 앱 연결 전에는 데이터가 생길 수 없는
# Spring Boot 지표는 접힌 행에 두고, 비어 있는 이유를 글 패널로 적는다(빈 그래프를 고장으로 오해하지 않게).

DS_TYPE = {PROM: "prometheus", LOKI: "loki"}
TEMPO = "ject-tempo-dev"   # 개발 VM에만 opt-in 설치(otel/README.md). 없으면 링크만 열리지 않는다.

# 범례·통계에 보이는 이름. 라벨 값(host·target)은 바꾸지 않고 표시 이름만 바꾼다.
HOST_NAMES = {"prod-app": "운영 앱 서버", "prod-data": "운영 DB 서버", "dev": "개발·모니터링 서버"}
TARGET_NAMES = {"prod": "운영 API (/readyz)", "dev": "개발 API (/readyz)", "dev-fe": "개발 웹 FE (/healthz)"}

GREEN, ORANGE, RED, BLUE = "green", "orange", "red", "blue"


def thresholds(*steps):
    """steps: (값, 색) … 첫 값은 None(기본색)."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}


def mapping(**kv):
    """값 → 글자·색. mapping(**{"0": ("끊김", RED), "1": ("정상", GREEN)})"""
    return [{"type": "value", "options": {k: {"text": t, "color": c, "index": i}
                                          for i, (k, (t, c)) in enumerate(kv.items())}}]


UPDOWN = mapping(**{"0": ("끊김", RED), "1": ("정상", GREEN)})
OKFAIL = mapping(**{"0": ("실패", RED), "1": ("성공", GREEN)})


def renames(names):
    return [{"matcher": {"id": "byName", "options": k},
             "properties": [{"id": "displayName", "value": v}]} for k, v in names.items()]


HOST_RENAMES = renames(HOST_NAMES)
TARGET_RENAMES = renames(TARGET_NAMES)

STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "background",
        "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center", "orientation": "auto",
        "wideLayout": True, "showPercentChange": False}
STAT_SPARK = dict(STAT, graphMode="area", colorMode="value")
TS = {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True, "calcs": ["lastNotNull", "max"]},
      "tooltip": {"mode": "multi", "sort": "desc"}}
TS_FIELD = {"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "gradientMode": "opacity",
                       "showPoints": "never", "spanNulls": False, "axisSoftMin": 0}}
TS_LIST = dict(TS, legend={"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": []})
TS_NOLEGEND = dict(TS, legend={"displayMode": "list", "placement": "bottom", "showLegend": False, "calcs": []})
TS_SUM_RIGHT = dict(TS, legend={"displayMode": "table", "placement": "right", "showLegend": True, "calcs": ["sum"]})
# 띄엄띄엄 들어오는 로그 기반 값은 선이 이어지지 않으므로 점으로 그린다.
POINTS_FIELD = {"custom": {"drawStyle": "points", "pointSize": 6, "showPoints": "always", "axisSoftMin": 0}}
BARS_FIELD = {"custom": {"drawStyle": "bars", "lineWidth": 1, "fillOpacity": 70, "showPoints": "never",
                         "stacking": {"mode": "normal", "group": "A"}, "axisSoftMin": 0}}


def line_thresholds(field, steps):
    """그래프에 기준선(점선)을 함께 그린다."""
    f = json.loads(json.dumps(field))
    f["custom"]["thresholdsStyle"] = {"mode": "dashed"}
    f["thresholds"] = thresholds(*steps)
    return f


class Board:
    def __init__(self, uid, title, tags, description=None, time_from="now-6h", links=None):
        self.uid, self.title, self.tags = uid, title, tags
        self.description = description
        self.time_from = time_from
        self.links = links or []
        self.panels, self.x, self.y, self.row_h, self.pid = [], 0, 0, 0, 1
        self.templating = []
        self.folded = None   # 접힌 행: 이후 패널을 그 행 안에 넣는다

    def _newline(self):
        if self.x:
            self.x, self.y = 0, self.y + self.row_h
        self.row_h = 0

    def _place(self, w, h):
        if self.x + w > 24:
            self._newline()
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def row(self, title, collapsed=False):
        self._newline()
        if self.folded is not None:
            # 접힌 행의 패널은 펼칠 때만 자리를 차지한다 → 다음 행은 접힌 행 바로 아래
            self.y = self.folded["gridPos"]["y"] + 1
            self.folded = None
        r = {"type": "row", "title": title, "id": self.pid, "collapsed": collapsed,
             "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []}
        self.panels.append(r)
        self.pid += 1
        self.y += 1
        if collapsed:
            self.folded = r

    def _add(self, p):
        (self.folded["panels"] if self.folded is not None else self.panels).append(p)
        self.pid += 1

    def panel(self, kind, title, targets, w=8, h=8, unit=None, ds=PROM, options=None, field=None, desc=None,
              overrides=None, decimals=None, max_=None, min_=None, interval=None):
        defaults = json.loads(json.dumps(field or {}))
        if unit:
            defaults["unit"] = unit
        if decimals is not None:
            defaults["decimals"] = decimals
        if max_ is not None:
            defaults["max"] = max_
        if min_ is not None:
            defaults["min"] = min_
        p = {
            "type": kind,
            "title": title,
            "id": self.pid,
            "gridPos": self._place(w, h),
            "datasource": {"type": DS_TYPE[ds], "uid": ds},
            "targets": [
                dict({"refId": chr(65 + i), "datasource": {"type": DS_TYPE[ds], "uid": ds}}, **t)
                for i, t in enumerate(targets)
            ],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": options or {},
        }
        if interval:
            p["interval"] = interval
        if desc:
            p["description"] = desc
        self._add(p)

    def ts(self, title, targets, w=12, h=8, unit=None, ds=PROM, field=None, **kw):
        self.panel("timeseries", title, targets, w=w, h=h, unit=unit, ds=ds,
                   options=kw.pop("options", TS), field=field or TS_FIELD, **kw)

    def stat(self, title, targets, w=6, h=4, unit=None, ds=PROM, field=None, spark=False, **kw):
        self.panel("stat", title, targets, w=w, h=h, unit=unit, ds=ds,
                   options=kw.pop("options", STAT_SPARK if spark else STAT), field=field, **kw)

    def text(self, title, md, w=24, h=4):
        self._add({"type": "text", "title": title, "id": self.pid, "gridPos": self._place(w, h),
                   "options": {"mode": "markdown", "content": md}})

    def alertlist(self, title, w=24, h=6, desc=None):
        p = {"type": "alertlist", "title": title, "id": self.pid, "gridPos": self._place(w, h),
             "options": {"viewMode": "list", "groupMode": "default", "groupBy": [], "maxItems": 20,
                         "sortOrder": 1, "dashboardAlerts": False, "alertName": "",
                         "alertInstanceLabelFilter": "", "datasource": "grafana",
                         "stateFilter": {"firing": True, "pending": True, "noData": False,
                                         "normal": False, "error": True, "recovering": True}}}
        if desc:
            p["description"] = desc
        self._add(p)

    def var(self, name, query, ds=PROM, label=None, include_all=True):
        self.templating.append({
            "name": name, "label": label or name, "type": "query",
            "datasource": {"type": DS_TYPE[ds], "uid": ds},
            "query": query, "definition": query if isinstance(query, str) else "",
            "refresh": 2, "includeAll": include_all, "multi": True, "sort": 1,
            # Loki는 빈 값도 맞는 선택자({a=~".*"})만으로는 조회를 거부한다 → "전체"를 .+로
            "allValue": ".+" if ds == LOKI else ".*",
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
        })

    def json(self):
        return {
            **({"description": self.description} if self.description else {}),
            "uid": self.uid, "title": self.title, "tags": self.tags, "timezone": "Asia/Seoul",
            "schemaVersion": 39, "version": 1, "editable": False, "refresh": "1m",
            "graphTooltip": 1, "liveNow": False,
            "time": {"from": self.time_from, "to": "now"},
            "timepicker": {"refresh_intervals": ["30s", "1m", "5m", "15m"]},
            "links": self.links,
            "templating": {"list": self.templating}, "panels": self.panels,
        }


def q(expr, legend=None, **kw):
    t = {"expr": expr}
    if legend:
        t["legendFormat"] = legend
    t.update(kw)
    return t


def board_links():
    explore = ('/explore?schemaVersion=1&panes=%7B%22t%22:%7B%22datasource%22:%22' + TEMPO +
               '%22,%22queries%22:%5B%7B%22refId%22:%22A%22,%22datasource%22:%7B%22type%22:%22tempo%22,'
               '%22uid%22:%22' + TEMPO + '%22%7D,%22queryType%22:%22traceqlSearch%22,%22limit%22:20%7D%5D,'
               '%22range%22:%7B%22from%22:%22now-1h%22,%22to%22:%22now%22%7D%7D%7D')
    return [
        {"title": "JECT 대시보드", "type": "dashboards", "tags": ["ject"], "asDropdown": True,
         "includeVars": False, "keepTime": True, "targetBlank": False, "icon": "external link"},
        {"title": "추적 검색(Tempo·개발)", "type": "link", "url": explore, "icon": "info", "keepTime": False,
         "targetBlank": False, "tooltip": "개발 인프라의 OpenTelemetry 추적. 실제 앱 계측 연결 전에는 합성 시험 추적만 있습니다."},
    ]


# Nginx 접근 로그(JSON). 로그의 host 필드는 Loki의 host 라벨과 이름이 겹쳐 domain으로 받는다.
NGINX = '{service="nginx", host=~"$host"}'
NOT_PROBE = '| __error__="" | ua !~ "Blackbox Exporter.*"'  # JSON이 아닌 줄(Nginx 자체 오류 메시지)은 뺀다
HEALTH_PATHS = '| path !~ "/readyz|/healthz|/nginx-health"'

HOST_LEGEND_NOTE = ("서버 이름: 운영 앱 서버(prod-app, 공개 Nginx·운영 앱), 운영 DB 서버(prod-data, PostgreSQL·Redis), "
                    "개발·모니터링 서버(dev, 개발 앱·DB·Redis와 Prometheus·Loki·Grafana).")


def overview():
    b = Board("ject-overview", "JECT 개요", ["ject"], links=board_links())
    b.row("한눈에 보기")
    b.stat("서버 지표 수집", [q('last_over_time(up{job="node"}[2m])', "{{host}}")], w=6,
           field={"mappings": UPDOWN, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           overrides=HOST_RENAMES, desc="2분 안에 Node Exporter 지표가 들어왔는지. 끊김이면 VM·수집기·네트워크를 확인합니다. " + HOST_LEGEND_NOTE)
    b.stat("공인 주소 접속 시험", [q('probe_success', "{{target}}")], w=7,
           field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           overrides=TARGET_RENAMES,
           desc="개발·모니터링 서버가 1분마다 공인 HTTPS 주소에 접속합니다(OCI Health Checks 대신). API는 /readyz(DB·Redis 연결 포함), 웹은 /healthz.")
    b.stat("인증서 남은 기간(가장 짧은 것)", [q('min((probe_ssl_earliest_cert_expiry - time()) / 86400)', "남은 일수")], w=4,
           unit="suffix:일", decimals=0, field={"thresholds": thresholds((None, RED), (14, ORANGE), (30, GREEN))},
           desc="자동 갱신은 만료 30일 전부터 시도합니다. 14일 미만이면 경보가 울립니다. 지금은 임시 이름(sslip.io) 인증서입니다.")
    b.stat("마지막 백업 성공 후", [q('time() - ject_backup_last_success_timestamp_seconds', "경과")], w=4,
           unit="s", decimals=1, field={"thresholds": thresholds((None, GREEN), (90000, ORANGE), (93600, RED))},
           desc="운영 DB는 매일 04:00 KST에 백업합니다. 26시간을 넘으면 경보가 울립니다.")
    b.stat("월간 복원 시험", [q('ject_restore_test_last_run_success', "마지막 결과")], w=3,
           field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           desc="매월 1일 05:00 KST에 백업을 격리 환경에 복원해 봅니다.")
    b.alertlist("지금 울리는 경보", h=4,
                desc="발생·대기·오류 상태인 Grafana 경보만 보입니다. 비어 있으면 울리는 경보가 없다는 뜻입니다. "
                     "실제 앱 연결 전이라 지표가 없는 경보(수집 없음)는 여기서 뺐습니다.")

    b.row("서버 자원")
    cpu = '100 * (1 - avg by(host) (sum by(host, cpu) (rate(node_cpu_seconds_total{mode=~"idle|iowait"}[5m]))))'
    mem = '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'
    disk = '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})'
    pct_field = {"thresholds": thresholds((None, GREEN), (80, ORANGE), (90, RED)), "min": 0, "max": 100}
    b.panel("bargauge", "CPU 사용률", [q(cpu, "{{host}}")], w=6, h=6, unit="percent", decimals=0,
            options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                     "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            field=dict(pct_field, thresholds=thresholds((None, GREEN), (70, ORANGE), (85, RED))), overrides=HOST_RENAMES,
            desc="I/O 대기(iowait)는 빼고 계산합니다. 서버당 1 OCPU라 10분 넘게 85%면 경보가 울립니다.")
    b.panel("bargauge", "메모리 사용률", [q(mem, "{{host}}")], w=6, h=6, unit="percent", decimals=0,
            options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                     "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            field=dict(pct_field, thresholds=thresholds((None, GREEN), (75, ORANGE), (85, RED))), overrides=HOST_RENAMES,
            desc="캐시를 뺀 실제 사용률(1 - 가용/전체). 가용 메모리가 15% 미만(사용률 85% 초과)이면 경보가 울립니다.")
    b.panel("bargauge", "디스크 사용률(/)", [q(disk, "{{host}}")], w=6, h=6, unit="percent", decimals=0,
            options={"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                     "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            field=pct_field, overrides=HOST_RENAMES,
            desc="무료 블록 200GB를 모두 써서 디스크를 늘릴 수 없습니다. 80%·90%에 경보, 여유 15% 미만이면 배포가 거부됩니다.")
    b.stat("가동 시간", [q('time() - node_boot_time_seconds', "{{host}}")], w=6, h=6, unit="s", decimals=0,
           options=dict(STAT, colorMode="none", orientation="horizontal"), overrides=HOST_RENAMES,
           desc="마지막 재부팅 후 경과 시간.")
    b.ts("CPU 사용률", [q(cpu, "{{host}}")], w=8, unit="percent",
         field=line_thresholds(TS_FIELD, [(None, "transparent"), (85, RED)]), overrides=HOST_RENAMES, max_=100)
    b.ts("메모리 사용률", [q(mem, "{{host}}")], w=8, unit="percent",
         field=line_thresholds(TS_FIELD, [(None, "transparent"), (85, RED)]), overrides=HOST_RENAMES, max_=100)
    b.ts("디스크 사용률(/)", [q(disk, "{{host}}")], w=8, unit="percent",
         field=line_thresholds(TS_FIELD, [(None, "transparent"), (80, ORANGE), (90, RED)]), overrides=HOST_RENAMES, max_=100)
    b.ts("네트워크 (위: 수신 · 아래: 송신)",
         [q('sum by(host) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*|tailscale.*"}[5m]))', "{{host}} 수신"),
          q('-sum by(host) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*|tailscale.*"}[5m]))', "{{host}} 송신")],
         w=8, unit="Bps", field={"custom": dict(TS_FIELD["custom"], axisSoftMin=None)}, options=TS_LIST)
    b.ts("디스크 I/O 사용 시간", [q('sum by(host) (rate(node_disk_io_time_seconds_total[5m]))', "{{host}}")], w=8,
         unit="percentunit", overrides=HOST_RENAMES, desc="디스크가 바빴던 시간 비율. 1(100%)에 붙어 있으면 I/O가 병목입니다.")
    b.ts("I/O 대기(iowait)", [q('100 * avg by(host) (rate(node_cpu_seconds_total{mode="iowait"}[5m]))', "{{host}}")], w=8,
         unit="percent", overrides=HOST_RENAMES, desc="CPU가 디스크를 기다린 비율. 재부팅·백업 때 잠깐 오르는 것은 정상입니다.")

    b.row("백업·복원 (운영 DB)")
    b.stat("마지막 백업 결과", [q('ject_backup_last_run_success', "결과")], w=4,
           field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))})
    b.stat("마지막 백업 성공 시각", [q('ject_backup_last_success_timestamp_seconds * 1000', "시각")], w=5, unit="dateTimeAsLocal",
           options=dict(STAT, colorMode="none", textMode="value", text={"valueSize": 26}))
    b.stat("백업 크기", [q('ject_backup_last_success_bytes', "압축본")], w=5, unit="bytes", options=dict(STAT, colorMode="none"))
    b.stat("백업 소요 시간", [q('ject_backup_last_duration_seconds', "소요")], w=3, unit="s", options=dict(STAT, colorMode="none"))
    b.stat("마지막 복원 시험", [q('ject_restore_test_last_run_success', "결과")], w=3,
           field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))})
    b.stat("복원 시험 후 경과", [q('time() - ject_restore_test_last_run_timestamp_seconds', "경과")], w=4, unit="s", decimals=1,
           field={"thresholds": thresholds((None, GREEN), (32 * 86400, ORANGE))},
           desc="매월 1일 실행. 32일을 넘으면 경보가 울립니다. 최근 실행은 복원 성공 증거가 아니니 결과와 같이 봅니다.")
    b.text("백업 보관", "비공개 Object Storage 버킷에 **최근 7일**을 보관하고, 최신 성공본 7개는 항상 남깁니다"
           "(그래서 '최대 7일 후 반드시 삭제'는 아닙니다). 실패하면 경보가 울리고, 고친 뒤 "
           "`sudo systemctl start ject-pg-backup`으로 다시 실행합니다.", w=24, h=3)

    b.row("공인 주소 접속 시험·인증서 (개발·모니터링 서버 → NAT → 공인 HTTPS)")
    b.panel("state-timeline", "접속 시험 이력", [q('probe_success', "{{target}}")], w=12, h=6,
            options={"showValue": "never", "mergeValues": True, "alignValue": "center", "rowHeight": 0.8,
                     "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
            field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN)),
                   "custom": {"fillOpacity": 80, "lineWidth": 0}},
            overrides=TARGET_RENAMES, desc="빨간 구간이 접속 실패입니다.")
    b.ts("응답 시간", [q('probe_duration_seconds', "{{target}}")], w=12, h=6, unit="s", overrides=TARGET_RENAMES, options=TS_LIST,
         desc="DNS·TLS·응답까지 포함한 전체 시간. 서버가 춘천이라 해외에서는 더 느릴 수 있습니다.")
    b.stat("HTTP 상태 코드", [q('probe_http_status_code', "{{target}}")], w=12, h=4, overrides=TARGET_RENAMES,
           field={"thresholds": thresholds((None, RED), (200, GREEN), (300, ORANGE))}, options=dict(STAT, colorMode="value"))
    b.stat("인증서 남은 기간", [q('(probe_ssl_earliest_cert_expiry - time()) / 86400', "{{target}}")], w=12, h=4, unit="suffix:일",
           decimals=0, overrides=TARGET_RENAMES, field={"thresholds": thresholds((None, RED), (14, ORANGE), (30, GREEN))})

    b.row("Redis (운영 DB 서버·개발 서버)")
    rsel = '{job="integrations/redis"}'
    b.stat("연결 상태", [q('redis_up' + rsel, "{{host}}")], w=4,
           field={"mappings": UPDOWN, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           overrides=HOST_RENAMES, desc="관측 전용 제한 계정으로 접속해 확인합니다(앱 비밀번호를 쓰지 않음).")
    b.stat("메모리 사용률(상한 대비)", [q('100 * redis_memory_used_bytes' + rsel + ' / (redis_memory_max_bytes' + rsel + ' > 0)', "{{host}}")],
           w=5, unit="percent", decimals=1, overrides=HOST_RENAMES,
           field={"thresholds": thresholds((None, GREEN), (70, ORANGE), (80, RED))},
           desc="상한(maxmemory): 운영 384MiB, 개발 96MiB. 80%를 넘으면 경보가 울립니다. 지금 축출 정책은 캐시용(allkeys-lru)이라 꽉 차면 오래 안 쓴 키부터 지워집니다.")
    b.stat("저장된 키", [q('sum by(host) (redis_db_keys' + rsel + ') or on(host) (0 * redis_up' + rsel + ')', "{{host}}")], w=5,
           overrides=HOST_RENAMES, options=dict(STAT, colorMode="none"))
    b.stat("접속 클라이언트", [q('redis_connected_clients' + rsel, "{{host}}")], w=5, overrides=HOST_RENAMES,
           options=dict(STAT, colorMode="none"), desc="관측 계정 1개를 포함합니다.")
    b.stat("축출된 키(24시간)", [q('increase(redis_evicted_keys_total' + rsel + '[24h])', "{{host}}")], w=5, decimals=0,
           overrides=HOST_RENAMES, field={"thresholds": thresholds((None, GREEN), (1, ORANGE))},
           desc="메모리가 꽉 차서 지워진 키. 0이 아니면 인증·잠금 키가 지워졌을 수 있으니 바로 확인합니다.")
    b.ts("메모리 사용량·상한", [q('redis_memory_used_bytes' + rsel, "{{host}} 사용"), q('redis_memory_max_bytes' + rsel, "{{host}} 상한")],
         w=8, unit="bytes", options=TS_LIST)
    b.ts("초당 명령 수", [q('rate(redis_commands_processed_total' + rsel + '[5m])', "{{host}}")], w=8, unit="ops",
         overrides=HOST_RENAMES, desc="지금은 관측 계정의 조회가 대부분입니다.")
    b.ts("만료·축출 키(5분)", [q('increase(redis_expired_keys_total' + rsel + '[5m])', "{{host}} 만료"),
                             q('increase(redis_evicted_keys_total' + rsel + '[5m])', "{{host}} 축출")], w=8, unit="short", options=TS_LIST)

    b.row("관측 도구 자체", collapsed=True)
    b.stat("관측 구성요소", [q('up{job="obs"}', "{{component}}")], w=6,
           field={"mappings": UPDOWN, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))})
    b.stat("Prometheus 저장 용량", [q('prometheus_tsdb_storage_blocks_bytes', "디스크 블록")], w=6, unit="bytes",
           options=dict(STAT, colorMode="none"), desc="보존 14일·최대 8GiB 중 먼저 닿는 한도까지 남깁니다.")
    b.stat("Prometheus 시계열 수", [q('prometheus_tsdb_head_series', "현재")], w=6, options=dict(STAT, colorMode="none"))
    b.stat("수집기 메모리(Alloy)", [q('process_resident_memory_bytes{job="integrations/self"}', "{{host}}")], w=6, unit="bytes",
           overrides=HOST_RENAMES, options=dict(STAT, colorMode="none"))
    b.ts("메트릭 전송 실패(Alloy → Prometheus)", [q('sum by(host) (rate(prometheus_remote_storage_samples_failed_total[5m]))', "{{host}}")],
         w=12, unit="short", overrides=HOST_RENAMES, desc="0이 정상입니다.")
    b.ts("로그 전송 폐기(Alloy → Loki)", [q('sum by(host) (rate(loki_write_dropped_entries_total[5m]))', "{{host}}")],
         w=12, unit="short", overrides=HOST_RENAMES, desc="0이 정상입니다.")
    return b


def app():
    b = Board("ject-app", "JECT 앱", ["ject"],
              "수집 성공은 업무 정상 판정이 아닙니다. HTTP/JVM 지표 미연결·요청 없음으로 인한 No data는 0이나 정상과 구분해야 합니다.",
              links=board_links())
    b.var("host", 'label_values(up{job="app"}, host)', label="앱 서버")
    b.text("지금 보이는 것", (
        "- **웹 요청(Nginx 로그 기준)** 행은 지금도 실제 요청으로 채워집니다. 접속 시험(Blackbox)은 요청 수에서 뺐습니다.\n"
        "- 개발·운영 BE는 아직 **배포 시험용 앱(스모크 앱)** 입니다. 실제 BE(Spring Boot)가 관리 포트 8081의 "
        "`/actuator/prometheus`를 열고 배포되면 맨 아래 **Spring Boot 지표** 행(접혀 있음)이 채워집니다. 그 전까지 비어 있는 것이 정상입니다.\n"
        "- 같은 시기 「앱 지표 끊김」 외 HTTP·DB 경보는 지표가 없어 '수집 없음'으로 보입니다."), h=4)

    b.row("상태")
    b.stat("앱 지표 수집", [q('last_over_time(up{job="app", host=~"$host"}[2m])', "{{host}}")], w=6,
           field={"mappings": mapping(**{"0": ("끊김", RED), "1": ("수집 성공", GREEN)}), "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           overrides=HOST_RENAMES)
    b.stat("앱 가동 시간", [q('time() - process_start_time_seconds{job="app", host=~"$host"}', "{{host}}")], w=6, unit="s", decimals=0,
           overrides=HOST_RENAMES, options=dict(STAT, colorMode="none"), desc="마지막 배포·재시작 후 경과 시간.")
    b.panel("table", "실행 중인 앱 버전", [q('max by(host, version) (ject_smoke_info{host=~"$host"})', format="table", instant=True)],
            w=12, h=4, options={"showHeader": True, "cellHeight": "sm"},
            field={"custom": {"align": "left"}},
            overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                       {"matcher": {"id": "byName", "options": "Value"}, "properties": [{"id": "custom.hidden", "value": True}]},
                       {"matcher": {"id": "byName", "options": "host"}, "properties": [{"id": "displayName", "value": "서버"}]},
                       {"matcher": {"id": "byName", "options": "version"}, "properties": [{"id": "displayName", "value": "커밋"}]}],
            desc="지금은 스모크 앱의 빌드 커밋입니다. 실제 앱이 오면 비게 되며, 그때는 배포 기록(ject-deploy status)으로 확인합니다.")

    b.row("웹 요청 (Nginx 접근 로그 기준)")
    by_class = [
        q(f'sum by(host) (count_over_time({NGINX} | json status="status", ua="ua" {NOT_PROBE} | status < 400 [$__auto]))', "{{host}} 정상(2xx·3xx)"),
        q(f'sum by(host) (count_over_time({NGINX} | json status="status", ua="ua" {NOT_PROBE} | status >= 400, status < 500 [$__auto]))', "{{host}} 4xx"),
        q(f'sum by(host) (count_over_time({NGINX} | json status="status", ua="ua" {NOT_PROBE} | status >= 500 [$__auto]))', "{{host}} 5xx"),
    ]
    b.ts("요청 수(상태별)", by_class, w=12, ds=LOKI, unit="short", field=BARS_FIELD,
         overrides=[{"matcher": {"id": "byRegexp", "options": ".*5xx"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": RED}}]},
                    {"matcher": {"id": "byRegexp", "options": ".*4xx"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": ORANGE}}]}],
         desc="운영 앱 서버의 Nginx는 공개 입구라 개발 주소로 들어온 요청도 한 번 지나갑니다(개발 서버 게이트웨이에서 한 번 더 기록). "
              "4xx에는 알 수 없는 주소로 들어온 자동 스캔을 끊은 444가 포함됩니다.")
    b.ts("응답 시간 p95(상태 확인 경로 제외)",
         [q(f'quantile_over_time(0.95, {NGINX} | json rt="request_time", path="path", ua="ua" {NOT_PROBE} {HEALTH_PATHS} | rt != "" | unwrap rt [$__auto]) by (host)', "{{host}}")],
         w=12, ds=LOKI, unit="s", field=line_thresholds(POINTS_FIELD, [(None, "transparent"), (1, RED)]),
         desc="Nginx가 응답을 끝내기까지 걸린 시간의 95번째 값. 1초 기준선을 함께 그립니다.")
    b.ts("5xx 비율", [q(f'(sum by(host) (count_over_time({NGINX} | json status="status", ua="ua" {NOT_PROBE} | status >= 500 [$__auto])) '
                       f'/ sum by(host) (count_over_time({NGINX} | json ua="ua" {NOT_PROBE} [$__auto])))', "{{host}}")],
         w=12, ds=LOKI, unit="percentunit", field=line_thresholds(POINTS_FIELD, [(None, "transparent"), (0.05, RED)]), max_=1,
         desc="요청이 없을 때는 비어 있습니다(0이 아님).")
    b.panel("table", "많이 들어온 경로(선택한 기간)",
            [q(f'topk(15, sum by(path, status) (count_over_time({NGINX} | json path="path", status="status", ua="ua" {NOT_PROBE} [$__range])))',
               format="table", instant=True, queryType="instant")],
            w=12, h=8, ds=LOKI, options={"showHeader": True, "cellHeight": "sm",
                                         "sortBy": [{"displayName": "요청 수", "desc": True}]},
            overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                       {"matcher": {"id": "byName", "options": "Value #A"}, "properties": [{"id": "displayName", "value": "요청 수"}]},
                       {"matcher": {"id": "byName", "options": "path"}, "properties": [{"id": "displayName", "value": "경로"}]},
                       {"matcher": {"id": "byName", "options": "status"}, "properties": [{"id": "displayName", "value": "상태"}]}],
            desc="모르는 경로(/.env 등)가 많으면 자동 스캔입니다. 운영 Nginx가 막고 있는지 상태 코드로 확인합니다.")

    b.row("웹 FE (개발)")
    fe = '{job="integrations/blackbox/dev-fe"}'
    b.stat("FE 접속 시험(개발 웹 /healthz)", [q('probe_success' + fe, "개발 웹 /healthz")], w=6, h=5, options=dict(STAT, textMode="value"),
           field={"mappings": OKFAIL, "color": {"mode": "thresholds"}, "thresholds": thresholds((None, RED), (1, GREEN))},
           desc="FE 컨테이너 생존 확인입니다. BE /readyz 성공과 별개이며 업무 E2E를 대신하지 않습니다.")
    b.ts("FE 응답 시간", [q('probe_duration_seconds' + fe, "개발 웹")], w=9, h=5, unit="s", options=TS_NOLEGEND)
    b.ts("FE 로그 줄 수", [q('sum by(host) (count_over_time({service="fe"} [$__auto]))', "{{host}}")], w=9, h=5, ds=LOKI, options=TS_NOLEGEND,
         unit="short", field=BARS_FIELD, desc="운영 FE는 아직 배포 전이라 개발 서버만 보입니다.")

    b.row("배포 시험용 앱(스모크 앱)")
    b.ts("스모크 앱 요청", [q('sum by(host, pattern, status) (rate(ject_smoke_http_requests_total{host=~"$host"}[5m]))', "{{host}} {{pattern}} {{status}}")],
         w=24, h=8, unit="reqps", options=dict(TS, legend={"displayMode": "table", "placement": "right", "showLegend": True, "calcs": ["lastNotNull"]}), desc="실제 BE가 배포되면 이 지표는 사라지고 아래 Spring Boot 지표로 바뀝니다.")

    b.row("Spring Boot 지표 — 실제 BE 앱 배포 후 표시 (펼치기)", collapsed=True)
    b.ts("요청 수", [q('sum by(host) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', "{{host}}")], w=8, unit="reqps",
         overrides=HOST_RENAMES)
    b.ts("5xx 비율", [q('sum by(host) (rate(http_server_requests_seconds_count{host=~"$host", status=~"5.."}[5m])) / sum by(host) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', "{{host}}")],
         w=8, unit="percentunit", field=line_thresholds(TS_FIELD, [(None, "transparent"), (0.05, RED)]), overrides=HOST_RENAMES)
    b.ts("응답 p95", [q('histogram_quantile(0.95, sum by(le, host) (rate(http_server_requests_seconds_bucket{host=~"$host", uri!~"/actuator.*|/readyz|/healthz"}[5m])))', "{{host}}")],
         w=8, unit="s", field=line_thresholds(TS_FIELD, [(None, "transparent"), (1, RED)]), overrides=HOST_RENAMES)
    b.panel("table", "경로별 요청·평균 응답(5분)",
            [q('sum by(host, method, uri, status) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', format="table", instant=True),
             q('sum by(host, method, uri, status) (rate(http_server_requests_seconds_sum{host=~"$host"}[5m])) / sum by(host, method, uri, status) (rate(http_server_requests_seconds_count{host=~"$host"}[5m]))', format="table", instant=True)],
            w=24, h=8, options={"showHeader": True, "cellHeight": "sm"},
            overrides=[{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.hidden", "value": True}]},
                       {"matcher": {"id": "byName", "options": "Value #A"}, "properties": [{"id": "displayName", "value": "초당 요청"}, {"id": "unit", "value": "reqps"}]},
                       {"matcher": {"id": "byName", "options": "Value #B"}, "properties": [{"id": "displayName", "value": "평균 응답"}, {"id": "unit", "value": "s"}]}])
    b.ts("힙 메모리", [q('sum by(host) (jvm_memory_used_bytes{host=~"$host", area="heap"})', "{{host}} 사용"),
                     q('sum by(host) (jvm_memory_max_bytes{host=~"$host", area="heap"})', "{{host}} 최대")], w=8, unit="bytes")
    b.ts("GC 정지 시간(초/초)", [q('sum by(host) (rate(jvm_gc_pause_seconds_sum{host=~"$host"}[5m]))', "{{host}}")], w=8, unit="s",
         overrides=HOST_RENAMES)
    b.ts("스레드·프로세스 CPU", [q('jvm_threads_live_threads{host=~"$host"}', "{{host}} 스레드"),
                              q('process_cpu_usage{host=~"$host"} * 100', "{{host}} CPU%")], w=8)
    b.ts("DB 커넥션(활성·유휴·대기)", [q('hikaricp_connections_active{host=~"$host"}', "{{host}} 활성"),
                                   q('hikaricp_connections_idle{host=~"$host"}', "{{host}} 유휴"),
                                   q('hikaricp_connections_pending{host=~"$host"}', "{{host}} 대기")], w=12,
         desc="대기가 5분 넘게 0보다 크면 경보가 울립니다(운영 PostgreSQL max_connections 60).")
    b.ts("DB 커넥션 획득 시간·타임아웃", [q('rate(hikaricp_connections_acquire_seconds_sum{host=~"$host"}[5m]) / rate(hikaricp_connections_acquire_seconds_count{host=~"$host"}[5m])', "{{host}} 평균 획득"),
                                      q('increase(hikaricp_connections_timeout_total{host=~"$host"}[5m])', "{{host}} 타임아웃")], w=12)
    return b


def logs():
    b = Board("ject-logs", "JECT 로그", ["ject"], links=board_links())
    b.var("env", 'label_values(env)', ds=LOKI, label="환경")
    b.var("host", 'label_values(host)', ds=LOKI, label="서버")
    b.var("service", 'label_values(service)', ds=LOKI, label="서비스")
    sel = '{env=~"$env", host=~"$host", service=~"$service"}'
    b.ts("서비스별 로그 줄 수", [q(f'sum by(service) (count_over_time({sel} [$__auto]))', "{{service}}")], w=12, h=7, ds=LOKI,
         unit="short", field=BARS_FIELD, options=TS_SUM_RIGHT)
    err_sel = '{env=~"$env", host=~"$host", service=~"$service", service!~"tempo|loki|grafana|prometheus"}'
    b.ts("오류로 보이는 로그(단어 기준, 관측 도구 제외)",
         [q(f'sum by(service) (count_over_time({err_sel} |~ "(?i)(error|exception|fatal|panic)" [$__auto]))', "{{service}}")],
         w=12, h=7, ds=LOKI, unit="short", field=BARS_FIELD, options=TS_SUM_RIGHT,
         desc="error·exception·fatal·panic 단어가 들어간 줄. 관측 도구(Tempo 등)는 평상시에도 이런 단어를 남겨 뺐습니다(로그 본문에서는 보임). 앱이 JSON 로그 수준(level)을 남기면 아래 '로그 수준별'이 더 정확합니다.")
    b.ts("Nginx 상태 코드별 요청",
         [q('sum by(code) (count_over_time({service="nginx", env=~"$env", host=~"$host"} | json code="status" | __error__="" [$__auto]))', "{{code}}")],
         w=12, h=7, ds=LOKI, unit="short", field=BARS_FIELD, options=TS_SUM_RIGHT,
         overrides=[{"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": RED}}]}],
         desc="접속 시험(1분마다)도 포함합니다. 444는 알 수 없는 주소로 들어온 요청을 끊은 것입니다.")
    b.ts("로그 수준별(앱 JSON 로그만 · 실제 BE 배포 후 표시)", [q(f'sum by(level) (count_over_time({{env=~"$env", host=~"$host", service=~"$service", level=~".+"}} [$__auto]))', "{{level}}")],
         w=12, h=7, ds=LOKI, unit="short", field=BARS_FIELD, options=TS_SUM_RIGHT,
         desc="Spring Boot(ECS) 로그의 level 값으로 나눕니다. 실제 BE 앱 배포 전에는 비어 있습니다. 「운영 오류 로그 급증」 경보도 이 값을 씁니다.")
    b.panel("logs", "로그 본문", [q(sel)], w=24, h=16, ds=LOKI,
            desc="Loki 7일 보관. 비밀번호·토큰·이메일·전화번호 등 주요 패턴은 수집 단계에서 가립니다(모양이 정해지지 않은 값은 못 가림).",
            options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                     "prettifyLogMessage": False, "dedupStrategy": "none"})
    b.panel("logs", "JECT 작업(백업·복원 시험·인증서 갱신·알림 중계)", [q('{job="systemd", host=~"$host"}')], w=24, h=10, ds=LOKI,
            options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True},
            desc="서비스 라벨이 없는 systemd 작업 로그라 '서비스' 선택과 관계없이 보입니다. 백업은 운영 DB 서버, 인증서 갱신은 운영 앱 서버에서 돕니다.")
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
