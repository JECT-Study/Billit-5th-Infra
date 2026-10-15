# JECT 서버 접근 안내 (개발자 5명)

대상: 홍성주·박상혁·김준원·백단아·성민서. PM·디자이너는 서버 계정 대상이 아니다.
상태와 적용 결과는 `docs/인프라-설계.md`의 "구축 결과"를 본다. 이 문서는 절차와 안내문이다.

## 원칙

- 사람마다 **개인 리눅스 계정 + 본인이 만든 SSH 공개키**. 공동 계정(`ubuntu`)·공동 개인키를 쓰지 않는다.
- JECT VM 3대에서 5명 모두 `sudo` 가능(`ject-admins` 그룹). 개인 포트폴리오 서버에는 권한을 주지 않는다.
- 접속은 **OCI Bastion 세션**으로만 한다. VM의 SSH(22)는 인터넷에 열려 있지 않고 Bastion 엔드포인트에서만 허용된다.
- OCI 콘솔 권한은 `ject-developers` 그룹: JECT Compartment의 조회와 Bastion 세션 생성만. 테넌시 관리·개인 자원·
  버킷 객체(백업·업로드 파일) 내용 읽기 권한은 없다. 서버 sudo와 OCI 자원 생성·삭제 권한은 별개다.
- CI 배포는 사람 계정과 분리된 `deploy` 계정과 CI 전용 OCI 사용자(`ject-ci-dev-bot`, `ject-ci-prod-bot`)로 한다.
  `deploy` 계정은 환경별 CI 키만 받고, Bastion IP에서 온 접속만 허용하며, 로그인하면 `ject-deploy-gate`(배포 명령 검사기)만 실행된다.

## 1. 팀원이 보낼 것 (공개키·이메일)

개인키(`id_ed25519`)는 절대 보내지 않는다. **`.pub` 파일 내용 한 줄**과 OCI 초대를 받을 이메일만 보낸다.

macOS / Linux:
```sh
ssh-keygen -t ed25519 -C "<이름>@ject"      # 이미 있으면 생략. 암호(passphrase) 설정 권장
cat ~/.ssh/id_ed25519.pub                   # 이 한 줄을 전달
```

Windows (PowerShell, OpenSSH 클라이언트 기본 포함):
```powershell
ssh-keygen -t ed25519 -C "<이름>@ject"
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

## 2. 관리자가 할 일 (받은 사람만)

1. 공개키를 `.local/ject-access/<username>.pub`에 저장(저장소 제외 경로)하고 `team.yaml`에 경로를 적는다.
2. 각 VM에서 계정 생성: `sudo /opt/ject/bin/ject-user add <username> /tmp/<username>.pub "<이름>"`
   (공개키 형식 검사, 개인키 거부, `ject-admins` 그룹 = sudo). 3대 모두 적용 후 `ject-user list`로 지문 확인.
3. OCI: 콘솔 Identity → Domains → Default → Users에서 이메일로 사용자 생성(초대 메일 발송) →
   그룹 `ject-developers`에 추가 → 본인이 첫 로그인 때 MFA 등록. 이 단계는 이메일을 받은 뒤에만 한다.
4. 접근 해제: `ject-user lock <username>`(3대) + OCI 그룹에서 제거.

## 3. 접속 방법 (팀원용)

사전 준비: OCI 콘솔 로그인(MFA), 본인 SSH 키.

### 콘솔에서 세션 만들기 (가장 쉬움)

JECT VM은 ARM(A1) + Ubuntu라서 OCI Bastion의 **관리형 SSH 세션(Managed SSH)을 쓸 수 없다**(OCI 알려진 문제).
**포트 포워딩 세션**으로 VM의 22번까지 터널을 열고, 로그인은 VM에 등록된 본인 공개키로 한다.

1. OCI 콘솔 → Identity & Security → Bastion → Compartment `JECT` → `jectbastion`.
2. **Create session** → Session type: *SSH port forwarding session* → Connect to the target host by: *Instance name* →
   Compute instance: 접속할 VM(`ject-prod-app` / `ject-prod-data` / `ject-dev-obs`) → Port: `22` →
   SSH key: 본인 `.pub` 붙여넣기(Bastion 접속용. VM 로그인 키와 같아도 된다).
3. 세션이 Active가 되면 세션 OCID를 복사해 아래 명령의 `<세션OCID>`에 넣는다. VM 사설 IP는 관리자가 준 `access.env`에 있다.

macOS / Linux 예:
```sh
ssh -i ~/.ssh/id_ed25519 -o ProxyCommand="ssh -i ~/.ssh/id_ed25519 -W %h:%p -p 22 <세션OCID>@host.bastion.ap-chuncheon-1.oci.oraclecloud.com" <username>@<VM 사설 IP>
```

Windows PowerShell 예:
```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 -o ProxyCommand="ssh -i $env:USERPROFILE\.ssh\id_ed25519 -W %h:%p -p 22 <세션OCID>@host.bastion.ap-chuncheon-1.oci.oraclecloud.com" <username>@<VM 사설 IP>
```

세션은 최대 3시간 유지된다. 끝나면 다시 만든다. 세션 하나는 VM 하나에만 쓴다.

### CLI로 세션 만들기 (선택)

`infra/access/ject-ssh.sh <username> <prod-app|prod-data|dev>` (OCI CLI 로그인 필요)가 포트 포워딩 세션 생성·대기·접속을 한 번에 한다.
같은 세션을 다시 쓰려면 `JECT_SESSION_ID=<세션OCID>`를 앞에 붙인다. 관리자가 준 `access.env`를 `~/.config/ject/access.env`에 둔다.

## 4. 서버에서 지킬 것

- 운영 DB·Redis·Nginx는 `docker compose`로 직접 재시작하지 않는다. 앱 배포는 CI 또는 `sudo ject-deploy`만 쓴다.
- 비밀값(`/srv/ject/secrets`)을 출력·복사·커밋하지 않는다.
- 운영 데이터 VM에서 데이터 삭제·복원은 인프라 담당과 먼저 확인한다.
