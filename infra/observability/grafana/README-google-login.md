# Grafana Google 로그인(선택)

Grafana는 개발 VM의 127.0.0.1:3000에만 떠 있고 SSH 터널로 본다. 이 설정은 터널을 연 상태에서 비밀번호 대신 Google 계정으로 로그인하게 한다.
외부에 Grafana를 여는 설정이 아니다.

## 동작

- 로그인할 수 있는 사람은 Grafana에 이미 있는 사용자뿐이다(`allow_sign_up=false`). Google 계정의 이메일이 Grafana 사용자의 이메일과 같으면 그 사용자로 들어간다.
- 이메일로 사용자를 찾도록 `oauth_allow_insecure_email_lookup`을 켰다. OAuth 제공자가 Google 하나뿐이고 Google 이메일은 확인된 값이라 켠다. 다른 OAuth 제공자를 추가하면 다시 검토한다.
- OAuth 앱이 테스트 상태인 동안에는 Google Cloud 「대상」의 테스트 사용자만 Google 로그인 화면을 통과한다.
- 비밀번호 로그인(`admin` 포함)은 그대로 된다.
- Google로 처음 로그인하면 그 Grafana 사용자의 아이디가 Google 이메일로 바뀐다. 비상용 `admin`(비밀번호 로그인, 점검 스크립트가 사용)은 Google 계정과 같은 이메일로 두지 않는다.
- 역할: BE는 Editor, 그 밖의 팀원은 Viewer다. 로그 본문이 보이는 「JECT 로그」 대시보드는 Editor 이상만 볼 수 있게 권한을 좁혔다.
- 브라우저 주소는 `http://localhost:3000`을 쓴다. Google에서 돌아오는 주소가 `http://localhost:3000/login/google`이라 `127.0.0.1`로 열면 로그인 상태 쿠키가 맞지 않는다.

## 설정

1. Google Cloud 개발용 프로젝트의 Google 인증 플랫폼 → 클라이언트 → 웹 애플리케이션을 만든다. 승인된 리디렉션 URI: `http://localhost:3000/login/google`.
2. 개발 VM에 `/etc/ject/grafana-google.env`(root, 0600)를 둔다. 클라이언트 보안 비밀번호가 들어가므로 저장소에 넣지 않는다.

   ```sh
   GF_SERVER_ROOT_URL=http://localhost:3000/
   GF_AUTH_GOOGLE_ENABLED=true
   GF_AUTH_GOOGLE_CLIENT_ID=<클라이언트 ID>
   GF_AUTH_GOOGLE_CLIENT_SECRET=<클라이언트 보안 비밀번호>
   GF_AUTH_GOOGLE_SCOPES=openid email profile
   GF_AUTH_GOOGLE_ALLOW_SIGN_UP=false
   GF_AUTH_GOOGLE_USE_PKCE=true
   GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP=true
   ```

3. Grafana만 다시 만든다.

   ```sh
   sudo docker compose -p ject-obs -f /opt/ject/compose/obs.yaml --env-file /etc/ject/host.env up -d grafana
   ```

4. 사람을 추가할 때: Grafana 사용자를 만들고 이메일을 그 사람의 Google 계정으로 넣는다. 테스트 상태면 Google Cloud 「대상」의 테스트 사용자에도 추가한다.

끄기: `/etc/ject/grafana-google.env`를 지우고 3번을 다시 실행한다.

## 확인

```sh
curl -s -o /dev/null -D - http://127.0.0.1:3000/login/google | grep -i '^location'
```

`accounts.google.com`으로 넘어가고 `redirect_uri`가 `http://localhost:3000/login/google`이면 된다.
