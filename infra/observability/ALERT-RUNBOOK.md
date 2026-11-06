# 서버 알림 대응 절차

2026-11-07 기준. 담당은 인프라 담당, 앱 오류·배포 계약은 BE/FE 담당과 협의한다. 24시간 당직·응답시간 보장은 합의되지 않았다.

## 알림을 받으면

1. 발생/복구, 대상 환경·호스트, 시작 시각, 지속시간을 확인한다. 미수집을 정상이나 사용량 0으로 해석하지 않는다.
2. Grafana는 관리자 SSH 터널로만 접속한다. 접근 절차는 `infra/README.md`를 따른다. 공유 알림에 비밀번호·토큰·사용자 자료·원본 로그를 붙이지 않는다.
3. 아래 읽기 전용 확인부터 한다. 변경은 대상·영향·복구 경로를 정한 뒤 진행한다. 앱 코드 변경·운영 배포·삭제를 알림 수신만으로 승인된 것으로 해석하지 않는다.
4. 복구는 동일 지표 회복, 해당 기능의 실제 동작, 복구 알림 수신을 각각 확인한다. VM Running이나 컨테이너 healthy만으로 업무 복구라고 쓰지 않는다.

## 규칙별 첫 확인

| 알림 | 첫 확인 | 조치 경계 |
|---|---|---|
| 서버 지표 끊김 | 해당 JECT VM 상태, `docker compose -p ject-agent ps`, Alloy/Node Exporter 상태와 수집 경로 | VM 재시작 전에 원인·접속·복구 계획 확인 |
| 디스크 80%/90% | `df -h`, `docker system df`, 승인된 JECT 데이터 경로의 사용량 | 자동 prune·DB/백업 삭제 금지. 실행·롤백 이미지 보존 |
| 가용 메모리/CPU | `free -m`, `docker stats --no-stream`, 최근 배포·백업 시각 | 회수 방지 목적의 부하를 만들지 않음 |
| 앱 지표 끊김 | 앱 컨테이너·metrics endpoint·수집 인증과 경로 | 현재 스모크 앱 지표와 실제 Billit 업무 지표 구분 |
| HTTP 5xx/응답 지연 | 요청량과 오류량, 성공/실패 응답시간, 최근 배포·의존성 | 소량 트래픽 비율만으로 전체 장애 단정 금지 |
| DB 커넥션 대기 | 앱 pool 지표·DB 연결 수·긴 트랜잭션 | 연결 강제 종료·DB 재시작은 별도 승인 |
| 오류 로그 급증 | 시간대·서비스·오류 유형을 제한해 조회 | 원본 로그를 Discord로 복사하지 않음 |
| 백업 실패/오래됨 | 운영 데이터 VM의 `/srv/ject/backup-status/last.json`, 백업 unit 로그, 객체 manifest | 성공 파일 존재와 복원 가능성은 별도. 오래된 백업 임의 삭제 금지 |
| 복원 실행 오래됨/지표 누락 | prod-data의 timer·restore-last.json·textfile 수집 확인. 32일 초과·누락·미래 시각·180초 이상 오래된 표본 감시 | 정확한 월별 마감 감시는 아님. 최근 실행만으로 성공 판정 금지, 운영 DB 복원 금지 |
| 관측 구성요소 중단 | 개발 VM의 Grafana·Loki·Prometheus 상태와 수집 시각 확인 | Grafana 전체 중단은 자기 경보로 발송 불가. OCI 독립 알람 확인 |
| 지표 전송 실패/로그 폐기 | Alloy 전송 오류·수신측 용량·연결·큐를 제한된 시간대로 조회 | 원본 민감 로그 공유 금지. 손실한 로그가 자동 복구된다고 가정하지 않음 |
| 복원 시험 실패 | 격리 복원 결과·실패 단계·globals 복원·행 수 검증 | 운영 DB에 복원 금지. 실패 결과를 성공으로 덮어쓰지 않음 |
| 공인 주소 접속 실패 | DNS·TLS·gateway·내부 ready를 순서대로 확인 | 내부 ready만으로 외부 사용자 경로 정상 단정 금지 |
| 인증서 만료 | 실제 인증서 만료일·갱신 unit 결과 | 도메인 변경·포트 개방은 별도 대상 검토 |
| Redis 관측(선택 구성) | redis_up·수집 freshness·maxmemory·사용량 확인 | 앱 키 읽기·삭제 금지. 축출 정책 변경은 BE 합의 후 |

## 알림 경로와 사각지대

- 실제 적용 확인: Grafana 13.2.4, 기본19개와 선택 Redis4개로 규칙23개, 이메일 relay·Discord receiver2개. 각 운영 규칙 자체의 실장애 발동 시험까지 완료한 것은 아니다.
- 기존 경로는 Grafana → 개발 VM relay → OCI Notifications → 이메일이다.
- Discord 공식 integration을 병행한다. 11/07 별도 합성규칙의 발생·복구 메시지를 팀 서버상태 채널에서 모두 확인하고 임시규칙은 제거했다. 메시지의 localhost Grafana 링크는 관리자 SSH 터널을 연 상태에서 사용한다.
- 개발 VM/Grafana가 멈추면 위 경로가 멈춘다. OCI 직접 VM 알람 → ACTIVE 이메일 구독이 별도 경로다. Discord가 이 장애도 독립적으로 전달한다고 주장하지 않는다.
- 이메일 구독 생성, ACTIVE, 시험 발송 API 성공, 실제 수신은 각각 다른 검증 단계다.

## 안전한 검증 순서

테스트 표시 메시지 → 합성 규칙 발동 → 대상별 수신 → 합성 규칙 해제 → 복구 수신 → 합성 설정 제거 및 기존 설정 대조. 운영 VM/DB를 고장 내거나 사용자 자료로 시험하지 않는다. 실패 시 원래 설정 사본으로 되돌리고 기존 메일 경로부터 재확인한다.

## 사건 기록 양식

사건/기간 · 영향(미확인 포함) · 탐지/대응/복구 시간선과 근거 · 직접 원인/기여 조건 · 개선 조치/담당 역할/기한/검증 조건 · 남은 위험. 개인 책임 추궁이나 관측되지 않은 성과를 적지 않는다.

## 참고

- [Google SRE monitoring](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Prometheus alerting](https://prometheus.io/docs/practices/alerting/)
- [Grafana Discord](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/configure-discord/)
- [Google SRE postmortem](https://sre.google/workbook/postmortem-culture/)

이 문서는 위 원칙을 현재 구성에 맞춰 재구성했다. 모든 대응 절차의 실전 검증 완료를 뜻하지 않는다.
