# 개발 업로드 S3 검증

`oci/dev_s3.tf`는 개발 업로드 전용 사용자·그룹·가입·정책·인증 기능 제한을 관리한다.
개발 업로드 버킷의 객체 생성·읽기·삭제만 허용한다. 목록·덮어쓰기·운영/백업 버킷 접근은
허용하지 않는다. 기존 VM Instance Principal 정책과 별도 주체이며 앱의 저장소 설정을 켜지 않는다.

서비스 계정 이메일은 팀 공용 복구 주소를 `dev_s3_service_email`에 넣는다.
공개 파일에는 주소를 넣지 않고, 저장소에서 제외한 `oci/dev-s3.auto.tfvars`를 0600으로 관리한다.
OCI Identity Domain은 기본 이메일을 요구할 수 있다. 이메일 확인/중복 제약은 우회하지 않는다.

Customer Secret Key는 Terraform으로 생성하지 않는다. 키가 state에 저장되는 것을 피하고,
승인된 프로젝트 `.local/s3-dev` 디렉터리(0700)의 `credentials.json`(0600)에 보관한다.
이 파일은 `access_key`, `secret_key`, `endpoint`, `region` 필드를 사용한다.
키 값·서명 URL·Authorization 헤더를 명령행, 로그, 문서에 복사하지 않는다.
서비스 계정은 Customer Secret Key만 사용하며 콘솔 비밀번호·API 키·auth token·SMTP 인증은 끈다.
현재 OCI provider의 capabilities 리소스에는 DB/OAuth2 인증 설정이 없다. 이 둘은 생성 직후
OCI CLI `iam user update-user-capabilities`의 `--can-use-db-credentials false`와
`--can-use-o-auth2-client-credentials false`로 끄고 메타데이터를 확인한다.
사용자 재생성 시 이 두 설정을 다시 확인해야 한다.

프로젝트 루트에서 명시적으로 실행한다:

```sh
python3 -B infra/tests/s3-dev-smoke.py --credentials .local/s3-dev/credentials.json
```

시험은 `infra-validation/` 아래 무작위 객체 한 개만 생성한다. 서명 PUT/GET의 본문 해시,
익명 GET 거부, 운영/백업 버킷 목록 거부를 확인하고 finally에서 생성 객체만 삭제한다.
삭제 후 서명 GET 404까지 확인한다. 서명은 60초만 유효하며 HTTP redirect를 따르지 않는다.
브라우저 CORS, multipart, 앱 통합, 보관 정책·업로드 크기/형식 정책의 검증은 포함하지 않는다.

IAM 전파로 권한 거부가 나면 최대 3회까지만 간격을 두고 재시도한다. 다른 오류는 원인을
확인하기 전 반복하지 않는다. 실패 결과를 성공으로 표시하지 않으며, 정리 실패에는 해당
합성 객체의 키만 보고한다. 기존 사용자 파일을 삭제하거나 버킷을 비우지 않는다.

## 복구·폐기

사용 중단 시 전용 사용자의 Customer Secret Key를 OCI에서 폐기한다. 키 ID는 보호 파일에서
읽어 CLI JSON 입력 파일로 전달하고 명령행/로그로 출력하지 않는다. 키 폐기 후 파일을 제거한다.
인프라 주체까지 제거할 때는 이 파일의 5개 리소스만 삭제되는 저장계획을 검토한 뒤 적용한다.
기존 버킷·객체·VM 정책·앱 설정은 삭제 대상에 포함하지 않는다. 부분 적용 실패 때는 state와
실제 IAM 메타데이터를 확인해 만들어진 전용 자원만 정리한다.

공식 근거:
- [OCI S3 호환 API와 Customer Secret Key](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi.htm)
- [객체별 OCI 권한](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm)

## 확인 범위

2026-11-07: 신규 IAM 리소스 5개와 키 1개를 생성했다. 첫 적용은 기본 이메일 누락으로
그룹·정책만 생성됐으며, 팀 공용 복구 주소를 로컬 변수로 제공한 후 나머지 3개를 적용했다.
기존 자원 변경은 없었다. 사용자·키 ACTIVE, 키 메타데이터와 보호 파일 일치, endpoint와
실시간 namespace 일치, 불필요 인증 기능 비활성화를 확인했다. 이메일 검증은 미완료다.

키 생성 후 초기 3회 signed PUT은 HTTP 403으로 거절됐다. 응답은 서버가 키를 찾지 못한
유형이며, 시간 차이는 약 1초였다. 동일 실패 3회 기준으로 중단했고 객체 생성 성공은 없었다.
따라서 실제 PUT/GET/DELETE·익명/다른 버킷 거부 검증은 **아직 미완료**다.
IAM 전파 지연 가능성은 추정이며 원인으로 확정하지 않는다. 키를 새로 만들거나 권한을
늘려 우회하지 않는다. 단위시험은 경계·정리 동작을 확인하며 실제 연결 성공을 뜻하지 않는다.
