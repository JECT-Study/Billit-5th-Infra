# JECT 서버 접속

대상: BE 3명, FE 2명. PM, 디자이너는 서버 계정이 없다.

## 어떻게 들어가나

- 서버 22번은 인터넷에 안 열려 있다. **Tailscale**로 들어간다 (2026-10-16부터).
  - 인프라 담당의 Tailscale 네트워크(tailnet)에 서버 3대가 `tag:ject`로 들어가 있고, 팀원은 초대받은 멤버.
  - 접근 정책(콘솔 Access controls): 팀원은 `tag:ject`의 tcp/22만. 담당자의 다른 기기는 팀원에게 안 보인다.
  - 서버 이름: `ject-prod-app`, `ject-prod-data`, `ject-dev`. MagicDNS라 이름으로 바로 ssh 된다.
- 로그인은 서버에 등록한 **각자 공개키**로. 비밀번호 로그인 없음. 계정은 `ject-admins` 그룹(sudo).
- CI(deploy 계정)는 그대로 OCI Bastion으로 들어온다. 사람은 Bastion을 비상용으로만 쓴다(아래).

호스트 키 지문 (처음 접속할 때 뜨는 값과 같아야 한다)

| 서버 | SHA256 |
| --- | --- |
| ject-prod-app | `R7estBH8fd1sAUsmRy5a0uIbjC1PnHoU86w/y7ILzvY` |
| ject-prod-data | `7w9aJRmiLkJMC8IiS+53aQcdfQlbclycjkzsggpRE7c` |
| ject-dev | `BOaNMvOwxaITg+0tqf7qDhD6IKhf9YdS8d1q2/zbdMg` |

## 팀원이 보낼 것

1. SSH 공개키 한 줄 (`~/.ssh/id_ed25519.pub` 내용). 개인키는 절대 안 받는다.
2. Tailscale 초대받을 이메일 (구글, 마이크로소프트, 깃허브, 애플 계정 중 하나).

## 인프라 담당이 할 일 (받은 사람만)

1. 공개키를 `.local/ject-access/<username>.pub`에 저장하고 `team.yaml`의 상태를 고친다(이메일은 파일에 적지 않는다). username은 본인에게 묻는다(영문 소문자). 정해진 것: sangcci(BE 리더). 나머지 기본안 junwon / dana / minseo
2. 서버 3대에서 계정 생성(공개키는 표준입력으로 넘긴다)
   ```sh
   for h in ject-dev ject-prod-app ject-prod-data; do
     ssh seongju@$h 'f=$(mktemp); cat > "$f"; sudo ject-user add <username> "$f" "<이름>"; rm -f "$f"' < .local/ject-access/<username>.pub
   done
   ```
3. Tailscale 콘솔 → Users → Invite users → 이메일 입력. 무료 Personal은 6명까지(담당자 포함).
4. 본인이 `ssh <username>@ject-dev` 되는지 확인받기.
5. 나갈 때: `sudo ject-user lock <username>` 3대 + Tailscale 콘솔에서 사용자 제거.

## 비상용: Bastion (Tailscale이 안 될 때)

A1(ARM) + Ubuntu는 Bastion 관리형 SSH가 안 돼서 포트 포워딩 세션만 쓴다. OCI 콘솔 계정과 MFA가 필요하다.

```sh
OCI_PROFILE=JECT infra/access/ject-ssh.sh <username> <prod-app|prod-data|dev>
```

세션은 최대 3시간이고 Bastion 하나당 동시 세션 수 제한이 있다(공식 FAQ 기준 약 20개, 2026-10-16에 한도에 걸린 적 있음).
팀원 OCI 계정은 지금 안 만든다. 필요해지면 `ject-developers` 그룹에 넣는다.

## 서버에서 지키기

- DB, Redis, nginx는 `docker compose`로 직접 올리고 내리지 않는다. 배포는 CI 또는 `sudo ject-deploy`.
- `/srv/ject/secrets` 안의 값을 출력, 복사, 커밋하지 않는다.
- 운영 데이터 서버에서 뭔가 지우거나 복원하려면 먼저 인프라 담당과 얘기한다.
- 서버 도구: `sudo ject-deploy status prod|dev`(배포 상태), `sudo cat /srv/ject/backup-status/last.json`(마지막 백업), `sudo docker ps`.
