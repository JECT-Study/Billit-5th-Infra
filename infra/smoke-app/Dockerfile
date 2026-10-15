# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS build
ARG TARGETOS TARGETARCH VERSION=dev FAIL_READY_DEFAULT=
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags "-s -w -X main.version=${VERSION} -X main.failReady=${FAIL_READY_DEFAULT}" -o /out/ject-smoke .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/ject-smoke /ject-smoke
USER nonroot:nonroot
EXPOSE 8080 8081
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD ["/ject-smoke", "-healthcheck"]
ENTRYPOINT ["/ject-smoke"]
