# syntax=docker/dockerfile:1
# JECT 백엔드 이미지. 서버는 ARM64(OCI A1)다. CI는 `--platform linux/arm64`로 빌드한다.
#
# - 빌드 단계는 빌드 머신의 플랫폼($BUILDPLATFORM)에서 돈다. JAR는 플랫폼과 무관하므로 x86 CI에서도
#   QEMU 에뮬레이션 없이 빠르게 빌드된다. 실행 단계만 대상 플랫폼(linux/arm64) 이미지다.
# - 서버 배포 스크립트가 요구하는 것: 컨테이너 HEALTHCHECK, 앱 포트 8080의 /readyz, 비root 실행.
# - UID 65532: 서버가 Redis 비밀번호 파일(/run/secrets/redis_password, 0400)을 이 UID 소유로 둔다.
#   바꾸려면 인프라 담당에게 알린다(setup-secrets.sh의 APP_UID).
# - 베이스 이미지는 digest로 고정했다(2026-10-15 기준). 올릴 때는 태그와 digest를 함께 바꾼다.

FROM --platform=$BUILDPLATFORM eclipse-temurin:21-jdk@sha256:f9bf7e9fe2f9bc4657537c1a7e20c768f0c3bafca41598263be4714783dd62eb AS build
WORKDIR /src
# 의존성 층: 빌드 설정이 바뀔 때만 다시 받는다.
COPY gradlew settings.gradle.kts build.gradle.kts ./
COPY gradle gradle
RUN --mount=type=cache,target=/root/.gradle ./gradlew --no-daemon dependencies > /dev/null
COPY src src
# 테스트는 CI의 PR 검사에서 따로 돈다. 이미지 빌드에서는 실행용 JAR만 만든다.
RUN --mount=type=cache,target=/root/.gradle ./gradlew --no-daemon bootJar -x test \
 && find build/libs -name '*.jar' ! -name '*-plain.jar' -exec cp {} /app.jar \;

FROM eclipse-temurin:21-jre@sha256:ccbad9e7cb84c27092b12c40a4143e5733e050db9c3784d84f632dcf423fb2ef
ARG VERSION=dev
LABEL org.opencontainers.image.revision=$VERSION
ENV APP_VERSION=$VERSION
RUN groupadd --system --gid 65532 app \
 && useradd --system --uid 65532 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=65532:65532 /app.jar /app/app.jar
USER 65532:65532
EXPOSE 8080
# 프로세스 생존만 본다(/healthz). DB·Redis 연결은 배포 스크립트가 /readyz로 따로 확인한다.
# 1 OCPU에서 Spring 기동이 느릴 수 있어 start-period를 넉넉히 둔다.
HEALTHCHECK --interval=10s --timeout=3s --start-period=120s --retries=3 \
  CMD curl -fsS -m 2 http://127.0.0.1:8080/healthz > /dev/null || exit 1
# 힙 상한은 서버 Compose의 JAVA_TOOL_OPTIONS(-XX:MaxRAMPercentage=50, 컨테이너 메모리 상한 기준)가 정한다.
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
