# 개발 VM 선택 설치: trace 저장소

기존 로그/메트릭 Alloy와 별도 프로세스다. `infra-validation` 서비스의 합성 trace만
수용한다. `billit-be`와 Java agent는 연결하지 않았다. 서비스 허용목록을 넓히기 전에
실제 앱의 개인정보·샘플링 계약, SDK 재시도, 개발 VM 메모리를 다시 검토한다.
기본 설치 스크립트에서 자동 활성화하지 않는다. 운영 VM에는 설치하지 않는다.

## 경계

- 호스트에는 `127.0.0.1:4318`(OTLP HTTP), `:3200`(Tempo), `:12346`(collector 진단)만 연다.
  Tempo와 collector는 Docker 내부 전용 네트워크에만 연결하며 앱 네트워크·공개 OTLP·gRPC는 없다.
  Docker internal-only 컨테이너에는 기본 gateway가 없어 host publish가 작동하지 않으므로
  전용 Nginx proxy만 내부 traces + 별도 ingress bridge에 연결하여 루프백 포트를 게시한다.
  **외부 경로를 갖는 것은 proxy뿐**이다. 고정된 Tempo/collector DNS upstream만 전달하며
  임의 목적지를 받는 forward proxy가 아니다. proxy 자체가 침해될 때의 egress 차단까지
  보장하지는 않는다. 기존 앱/호스트 Nginx는 변경하지 않는다.
- collector 256MiB/0.15CPU, Tempo 512MiB/0.35CPU, proxy 64MiB/0.05CPU. 기존 Alloy 256MiB는 유지한다.
  시작 시 MemAvailable 1536MiB 이상·호스트 디스크 여유 3GiB 이상을 요구한다.
- 요청 1MiB, 무압축 HTTP만 허용한다. 메모리 limiter 128MiB, 배치 최대32 span,
  메모리 전송 큐2MiB/1 consumer, 재시도 최대30초다. 초과·장애·재시작 시 trace 유실을 허용한다.
- 원문 이름·URL·쿼리·본문·SQL·식별자·이벤트·scope/resource metadata를 제거한다.
  links가 있는 span과 허용되지 않은 서비스는 버린다. 허용 HTTP method, 정수 상태코드,
  DB 종류만 유지한다. trace/span ID·시간·부모 관계는 보존하므로 실제 사용자 ID를 넣으면 안 된다.
- Tempo 입력4KiB/s·burst1MiB, 동시 trace100·trace당256KiB.
  로컬 전용 파일시스템 최대1GiB가 WAL/블록의 물리적 경계다.
  retention6h는 비동기 정리 기준이며 6시간 즉시 삭제 보증이 아니다.
  용량 부족 시 수집 실패를 허용하며 자동으로 다른 디스크에 쓰거나 데이터를 지우지 않는다.
  컨테이너 로그는 각5MiB×2, 임시공간도 별도 제한한다.
- proxy는 UID101, read-only, capabilities 없음, pids32, tmpfs8MiB다.
  1MiB 요청 상한·헤더/본문5초·upstream연결3초·읽기30초 제한을 둔다.
  Tempo `/ready`, `/api/*`는 GET/HEAD만, OTLP는 `/v1/traces` POST만,
  collector 진단은 `/-/ready`, `/-/healthy`, `/metrics` GET/HEAD만 허용한다.
  Docker DNS를10초마다 재조회해 upstream 컨테이너 IP 변화에 대응한다.
  access log는 기록하지 않는다.

## 설치 전 준비

관리자가 개발 VM에서만 수행한다. `preflight.py`는 검사만 하며 디스크 생성·포맷을 하지 않는다.
`/srv/ject/observability/tempo`는 **전용 512MiB~1GiB 파일시스템**이어야 한다.
루트 디스크의 보통 디렉터리나 bind mount는 거절한다.

새 클라우드 볼륨 없이 기존 디스크의 새 1GiB 파일을 loop mount할 경우 아래 원칙을 지킨다.

1. 호스트 여유 4GiB 이상과 기존 mount/파일 부재를 확인한다. 기존
   `/srv/ject/observability/tempo.ext4` 또는 내용 있는 mountpoint가 있으면 중단한다.
2. `O_CREAT|O_EXCL`로 **새 일반 파일만** 만들고 1GiB를 실제 할당한다.
   실패한 기존 파일을 truncate하거나 재사용하지 않는다. symlink를 거절한다.
3. 만든 파일의 inode·일반파일 여부·정확한 경로를 다시 확인한 뒤 그 파일에만
   `mkfs.ext4`를 실행한다. `/dev/*`, 기존 파일시스템, 타 볼륨에는 실행하지 않는다.
   자동 설치 스크립트에서 이 작업을 실행하지 않는다.
4. 제공된 `srv-ject-observability-tempo.mount`를 설치하고 먼저 시작한다.
   마운트한 루트 소유자를 `10001:10001`, 권한을 `0700`으로 설정한다.
   `findmnt -T /srv/ject/observability/tempo`, `df -B1`로 장치·용량을 확인한다.

설정 파일 배치는 다음과 같다. 기존 파일이 있으면 diff를 먼저 확인하고 백업한다.

| 원본 | 개발 VM 대상 |
| --- | --- |
| `collector.alloy`, `tempo.dev.yaml`, `proxy.conf`, `preflight.py` | `/opt/ject/otel/` |
| `../../compose/otel.yaml` | `/opt/ject/compose/otel.yaml` |
| `ject-otel.service`, `srv-ject-observability-tempo.mount` | `/etc/systemd/system/` |
| `tempo-datasource.yaml` | 기존 Grafana provisioning의 `datasources/tempo.yaml` (선택) |

`/etc/ject/obs.env`의 `JECT_HOST=dev`를 확인한다. Tempo/Alloy 이미지 digest는 `versions.json`과
Compose에 고정돼 있다. proxy는 Nginx1.30.6-alpine ARM64 manifest
`sha256:564a09935b00f058ca1b28c742169ba817499baa0479807bf7f373fe2804fbf7`로 고정한다. 설정 파일은 root 소유·0644로 두고 아래 순서로 실행한다.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now srv-ject-observability-tempo.mount
sudo python3 /opt/ject/otel/preflight.py
sudo systemctl enable --now ject-otel.service
curl --fail http://127.0.0.1:12346/-/ready
curl --fail http://127.0.0.1:3200/ready
```

서비스는 Docker 직접 재시작 대신 매번 mount/preflight 뒤 Compose를 시작한다.
기동 실패 반복은 systemd의 60초/3회 제한으로 멈춘다. `journalctl -u ject-otel`
및 `docker compose -p ject-otel -f /opt/ject/compose/otel.yaml logs --tail 50`로 확인한다.
Grafana datasource 파일 설치 후 기존 Grafana만 재시작하고 datasource health와
Explore의 합성 trace ID 조회를 확인한다. Grafana는 기존 SSH 터널로 접속한다.
실제 앱 endpoint 설정은 이 절차에 포함되지 않는다.

## 검증과 롤백

```sh
python3 -B -m unittest discover -s infra/tests -p test_otel_dev.py -v
python3 -B infra/tests/test_otel_dev_e2e.py
```

E2E는 `colima-billit-verify` 전용 VM, 내부 네트워크·새 이름의 임시 볼륨을 사용한다.
다른 시험이 끝난 뒤 실행한다. 고정 이미지가 이미 있어야 하며 실제 서버에 접속하지 않는다.
호스트 네트워크의 합성 클라이언트가 실제 VM 루프백 publish를 경유한다.
세 포트 바인딩·워크로드 내부격리·허용 경로·민감 metadata 제거·관계/시간 보존·서비스 거절·요청 상한·재시작 보존·일시 장애 복구와
생성한 자원만 정리하는 것을 검사한다. 실제 loop mount, 장시간 retention,
디스크 가득 참, Grafana UI와 실앱 부하는 별도 운영 확인이며 이 시험의 증거가 아니다.

롤백은 `systemctl disable --now ject-otel.service` 후 해당 Compose `down`을 실행한다.
Tempo datasource 파일만 제거하고 Grafana를 재시작한다. 이후 mount를 중지·비활성화할 수 있다.
저장 파일/데이터는 삭제하지 않고 보존한다. 기존 obs/agent/app Compose는 내리지 않는다.
다시 켤 때는 디스크·메모리 검사부터 반복한다.

## 공식 근거

- [Alloy OTLP HTTP receiver](https://grafana.com/docs/alloy/v1.20/reference/components/otelcol/otelcol.receiver.otlp/)
- [Alloy OTLP HTTP exporter의 큐·재시도](https://grafana.com/docs/alloy/v1.20/reference/components/otelcol/otelcol.exporter.otlphttp/)
- [Tempo 설정 및 로컬 저장소 한계](https://grafana.com/docs/tempo/latest/configuration/)
- [Tempo 3.1.1 retention scheduler](https://github.com/grafana/tempo/blob/v3.1.1/modules/backendscheduler/provider/retention.go)

- [Moby internal-only 네트워크의 publish 동작과 별도 proxy 방식](https://github.com/moby/moby/discussions/53256)
- [Nginx upstream resolve/zone](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
- [Nginx proxy timeout/임시파일 설정](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
