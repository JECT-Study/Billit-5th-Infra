// ject-smoke: 실제 JECT 앱이 아니다. 배포 파이프라인(ARM64 빌드 → GHCR → 서버 pull →
// healthcheck/readiness → 이전 이미지 복구)을 앱 코드 없이 검증하기 위한 최소 HTTP 서버.
//
//	GET /healthz  프로세스 생존 (외부 의존성 없음)
//	GET /readyz   DB(TCP)와 Redis(AUTH+PING) 연결 확인. 상세 정보는 응답하지 않는다.
//	GET /version  빌드 커밋
//	관리 포트 8081: GET /actuator/prometheus  최소 지표(Spring 앱과 같은 경로라 서버의 수집 설정을 그대로 쓴다)
//
// 환경변수: PORT, MANAGEMENT_PORT(기본 8081), DB_HOST, DB_PORT, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD_FILE, FAIL_READY(시험용)
// 빌드 인자 FAIL_READY_DEFAULT=1로 만든 이미지는 /readyz가 항상 실패한다(배포 실패·자동 복구 시험용 "broken" 변형).
package main

import (
	"bufio"
	"context"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	version   = "dev"
	failReady = "" // 빌드 때 -X main.failReady=1 이면 readiness가 항상 실패
)

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func checkTCP(addr string) error {
	c, err := net.DialTimeout("tcp", addr, 2*time.Second)
	if err != nil {
		return err
	}
	return c.Close()
}

func checkRedis(addr, passwordFile string) error {
	c, err := net.DialTimeout("tcp", addr, 2*time.Second)
	if err != nil {
		return err
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(2 * time.Second))
	r := bufio.NewReader(c)
	if passwordFile != "" {
		pw, err := os.ReadFile(passwordFile)
		if err != nil {
			return fmt.Errorf("read redis password: %w", err)
		}
		p := strings.TrimSpace(string(pw))
		fmt.Fprintf(c, "*2\r\n$4\r\nAUTH\r\n$%d\r\n%s\r\n", len(p), p)
		line, err := r.ReadString('\n')
		if err != nil || !strings.HasPrefix(line, "+OK") {
			return fmt.Errorf("redis auth failed")
		}
	}
	fmt.Fprint(c, "*1\r\n$4\r\nPING\r\n")
	line, err := r.ReadString('\n')
	if err != nil || !strings.HasPrefix(line, "+PONG") {
		return fmt.Errorf("redis ping failed")
	}
	return nil
}

// 요청 수(경로·상태 코드별). 경로는 등록된 패턴만 쓰므로 라벨 수가 늘지 않는다.
type counter struct {
	mu sync.Mutex
	n  map[[2]string]uint64
}

func (c *counter) inc(path string, code int) {
	c.mu.Lock()
	c.n[[2]string{path, strconv.Itoa(code)}]++
	c.mu.Unlock()
}

type statusWriter struct {
	http.ResponseWriter
	code int
}

func (w *statusWriter) WriteHeader(code int) { w.code = code; w.ResponseWriter.WriteHeader(code) }

func main() {
	// distroless 이미지에는 curl이 없으므로 컨테이너 healthcheck를 같은 바이너리로 수행한다.
	if len(os.Args) > 1 && os.Args[1] == "-healthcheck" {
		c := http.Client{Timeout: 2 * time.Second}
		resp, err := c.Get("http://127.0.0.1:" + env("PORT", "8080") + "/healthz")
		if err != nil || resp.StatusCode != http.StatusOK {
			os.Exit(1)
		}
		os.Exit(0)
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", "ject-smoke", "environment", env("APP_ENV", "unknown"), "version", version)
	dbAddr := net.JoinHostPort(env("DB_HOST", ""), env("DB_PORT", "5432"))
	redisAddr := net.JoinHostPort(env("REDIS_HOST", ""), env("REDIS_PORT", "6379"))
	redisPwFile := os.Getenv("REDIS_PASSWORD_FILE")

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte("ok\n"))
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, _ *http.Request) {
		if os.Getenv("FAIL_READY") == "1" || failReady == "1" {
			http.Error(w, "not ready\n", http.StatusServiceUnavailable)
			return
		}
		if os.Getenv("DB_HOST") != "" {
			if err := checkTCP(dbAddr); err != nil {
				logger.Warn("readiness db failed", "error", err.Error())
				http.Error(w, "not ready\n", http.StatusServiceUnavailable)
				return
			}
		}
		if os.Getenv("REDIS_HOST") != "" {
			if err := checkRedis(redisAddr, redisPwFile); err != nil {
				logger.Warn("readiness redis failed", "error", err.Error())
				http.Error(w, "not ready\n", http.StatusServiceUnavailable)
				return
			}
		}
		w.Write([]byte("ready\n"))
	})
	mux.HandleFunc("GET /version", func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(version + "\n"))
	})

	started := time.Now()
	reqs := &counter{n: map[[2]string]uint64{}}
	counted := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sw := &statusWriter{ResponseWriter: w, code: http.StatusOK}
		_, pattern := mux.Handler(r)
		if pattern == "" {
			pattern = "unmatched"
		}
		mux.ServeHTTP(sw, r)
		reqs.inc(pattern, sw.code)
	})
	mgmt := http.NewServeMux()
	mgmt.HandleFunc("GET /actuator/prometheus", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprintf(w, "# TYPE ject_smoke_info gauge\nject_smoke_info{version=%q} 1\n", version)
		fmt.Fprintf(w, "# TYPE process_start_time_seconds gauge\nprocess_start_time_seconds %d\n", started.Unix())
		fmt.Fprint(w, "# TYPE ject_smoke_http_requests_total counter\n")
		reqs.mu.Lock()
		for k, v := range reqs.n {
			fmt.Fprintf(w, "ject_smoke_http_requests_total{pattern=%q,status=%q} %d\n", k[0], k[1], v)
		}
		reqs.mu.Unlock()
	})
	mgmtSrv := &http.Server{Addr: ":" + env("MANAGEMENT_PORT", "8081"), Handler: mgmt, ReadHeaderTimeout: 5 * time.Second}
	go func() {
		if err := mgmtSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("management server failed", "error", err.Error())
		}
	}()

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8080"),
		Handler:           counted,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		logger.Info("listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server failed", "error", err.Error())
			os.Exit(1)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	_ = mgmtSrv.Shutdown(ctx)
	logger.Info("stopped")
}
