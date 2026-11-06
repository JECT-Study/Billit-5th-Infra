# 선택 Discord 알림 수신처

`render-alert-contact.py`는 기존 contact point `ject-oci-email`에 `ject-discord` receiver를
추가한다. `ject-relay` 이메일 중계와 기존 notification policy는 그대로 보존한다.
네트워크 호출·Grafana 재로드·시험 발송은 수행하지 않는다. 기본 실행은 검사만 한다.

## 비밀과 대상

- 입력은 개발 VM의 `/srv/ject/secrets/discord_webhook` 한 파일이다.
  root 소유 일반파일·0600이며 심볼릭링크가 없어야 한다. URL을 argv/env/stdout에 넣지 않는다.
- 주소는 `https://discord.com/api/webhooks/<숫자>/<토큰>`만 허용한다.
  다른 호스트·쿼리·fragment·여러 줄·URL userinfo를 거절한다.
- `--output`은 `/etc/ject/grafana/provisioning/alerting/contact-points.yaml`만 허용한다.
  결과는 root:472·0640으로 원자적으로 교체한다. 임시파일도 같은 보호된 디렉터리에 생성한다.
  저장소·임의 경로·stdout 출력은 지원하지 않는다.
- 기존 운영 파일에 원본과 다른 relay/정책/추가 수신처가 있으면 덮어쓰지 않고 중단한다.
  오류는 비밀값 없는 고정 문구만 출력한다.

## 적용

비밀값 없는 원본 `provisioning/alerting/contact-points.yaml`과 스크립트를 서버의 배포 원본
디렉터리에 둔다. 기존 기본 provisioning 파일은 저장소에서 수정하지 않는다.

```sh
# 설치한 코드/기본 contact 원본의 절대 경로로 실행한다.
sudo python3 /opt/ject/observability/grafana/render-alert-contact.py \
  --source /opt/ject/observability/grafana/provisioning/alerting/contact-points.yaml

# 위 검사가 성공한 뒤에만 실제 전달 파일을 만든다.
sudo python3 /opt/ject/observability/grafana/render-alert-contact.py \
  --source /opt/ject/observability/grafana/provisioning/alerting/contact-points.yaml \
  --output /etc/ject/grafana/provisioning/alerting/contact-points.yaml
```

같은 UID를 다른 provisioning 파일에도 중복 정의하지 않는다. 생성 후 관리자가 기존
Grafana만 재시작하거나 alerting provisioning reload를 수행한다. API/UI로 receiver UID·종류,
이메일 보존, policy 보존을 확인한다. URL 포함 출력·전체 설정 export를 로그에 남기지 않는다.
실제 발송 시험은 연결 대상 채널을 확인한 뒤 별도로 수행한다.

Discord 사용자명은 웹후크에서 정한 이름을 사용한다. 메시지는 알림 이름·호스트·상태만
포함하며 원문 annotations, 전체 labels, 링크, 로그를 전송하지 않는다. 복구 알림도 켠다.
단, Grafana 기본 embed에는 Grafana 링크 등이 추가될 수 있으므로 실제 표시 내용은
운영 시험에서 확인한다. 전체 알림 payload의 익명화를 보증하는 구성은 아니다.

기본 인프라 설치가 원본 provisioning을 다시 복사하면 선택 수신처가 빠질 수 있다.
그때 생성기를 다시 실행한다. 자동 배포 경로는 이번 변경에 포함하지 않는다.
롤백은 보호된 운영 파일을 비밀값 없는 기본 원본으로 복원하고, Grafana provisioning에
`deleteContactPoints: [{orgId: 1, uid: ject-discord}]`를 일회성으로 추가하여 reload한다.
파일에서 제거하는 것만으로 DB receiver 삭제를 보장하지 않는다. 삭제 확인 뒤 일회성
삭제 파일을 지우고 이메일 수신처·정책을 다시 확인한다. 웹후크 자체 삭제는 별도 작업이다.

## 검증 범위

```sh
python3 -B -m unittest discover -s infra/tests -p test_grafana_alert_contact.py -v
```

합성 토큰만 사용해 원본/정책 보존, URL 허용목록, 입력 권한·symlink 거절,
원자적 출력·지정 uid/gid/mode, 운영 drift 거절, dry-run·오류 비밀값 비노출을 확인한다.
macOS 단위시험에서 root chown은 mock이며 실제 Linux 소유권 및 Grafana 로드는 별도 확인한다.
실제 비밀을 읽거나 발송하지 않는다.

## 공식 스키마 근거

- [Grafana 13.2.4 ReceiverV1](https://github.com/grafana/grafana/blob/v13.2.4/pkg/services/provisioning/alerting/contact_point_types.go):
  `uid`, `type`, `settings`, `disableResolveMessage`를 받는다. `secure_settings` 필드는 없으며
  disk settings는 평문을 입력받는다. datasource의 secureJsonData나 구형 notifier 설정과 혼동하지 않는다.
- [해당 버전 go.mod](https://github.com/grafana/grafana/blob/v13.2.4/go.mod)의 alerting 의존성은
  `7f02604ca93b`다. [Discord v1 Config/Schema](https://github.com/grafana/alerting/blob/7f02604ca93b/receivers/discord/v1/config.go)는
  `url`, `title`, `message`, `use_discord_username`을 제공하며 `url`을 Secure/Protected로 표시한다.
  이 스키마에는 `url_file`이 없다. 직접 파일 비밀 참조를 가정하지 않는다.
- [공식 file provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/):
  Discord `settings.url`, 복구 알림 설정, contact UID 삭제 및 reload 절차.
