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

시험은 `infra-validation/` 아래 무작위 객체 한 개만 생성한다. 서명 PUT/GET의 본문 해시와 HEAD,
5분 전 발급한 60초 유효 서명의 GET 거절(403 AccessDenied/RequestExpired),
익명 GET 거부, 운영/백업 버킷 목록 거부를 확인하고 finally에서 생성 객체만 삭제한다.
삭제 후 서명 GET 404까지 확인한다. 서명은 60초만 유효하며 HTTP redirect를 따르지 않는다.
브라우저 CORS, multipart, 앱 통합, 보관 정책·업로드 크기/형식 정책의 검증은 포함하지 않는다.
HEAD·만료 요청 거절 검사는 합성 회귀시험과 아래 실제 서비스 검증을 통과했다.

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

### 후속 실제 검증

2026-11-07 재인증 후, 존재하지 않는 시험 객체 GET이404 NoSuchKey로 응답했다.
이후 임시 객체 한 개의 PUT/GET 본문 일치·HEAD200·만료 서명403 AccessDenied·익명GET404,
운영/백업 버킷 목록404 NoSuchBucket·삭제 후404를 확인했다. 시험기 종료0.
계정 이메일은 미확인 상태였다. 초기 오류가 해소된 원인은 확정하지 않는다.
CORS·multipart·실제 앱 연동·제품 보관정책은 여전히 미검증이다.

### 웹 Origin·메서드·재업로드 경계

선택 입력 `--origin-file`에 개발 FE의 HTTPS Origin만 담은 0600 파일을 지정하면,
기본 시험과 별도로 고유 합성 객체 하나의 OPTIONS(PUT, Content-Type), Origin을 동반한
PUT/GET/HEAD의 CORS·ETag 노출, GET 서명을 PUT으로 재사용했을 때의 거절,
같은 키 재업로드 거절과 원본 불변을 확인하고 삭제한다. 파일값·서명 URL은 출력하지 않는다.
OCI가 권한을 숨기는 404 NoSuchBucket도 재업로드 거절로 취급하지만 원본 불변을 함께 요구한다.

2026-11-07 실제 개발 Origin 시험: OPTIONS·PUT·GET·HEAD 모두200, Origin/PUT/Content-Type
허용과 ETag 노출 확인. 메서드 변경은403 SignatureDoesNotMatch, 같은 키 재업로드는404
NoSuchBucket였고 원본은 그대로였다. 시험 객체 삭제 후404 확인. 최초 시험기는 재업로드403만
예상해 종료1로 기록했으며, 관찰된404 경계는 합성 회귀시험으로 보완했다. 실제 요청을 반복해
성공 기록으로 바꾸지 않았다. 이는 HTTP CORS 계약 확인이며 브라우저 UI/업무 업로드 E2E는 아니다.

[OCI 공식 FAQ](https://www.oracle.com/cloud/storage/object-storage/faq/)에 따르면 S3 호환 API의
CORS 응답 헤더는 고정이며 변경할 수 없다. 서버 간 요청에는 CORS가 필요하지 않으며,
웹 직접 업로드는 실제 Origin과 사용 메서드·헤더의 호환성을 확인한다. AWS의 버킷 CORS
설정 기능이 OCI에도 있다고 가정하지 않는다. 정책·키·앱 설정은 이 시험에서 변경하지 않는다.
