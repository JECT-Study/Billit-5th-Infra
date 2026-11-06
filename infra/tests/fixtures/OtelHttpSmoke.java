import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

// 합성 요청 한 번만 실행. 실제 앱·DB·외부 API를 호출하지 않는다.
class OtelHttpSmoke {
    public static void main(String[] args) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/synthetic", exchange -> {
            String parent = exchange.getRequestHeaders().getFirst("traceparent");
            byte[] body = (parent == null ? "missing" : parent).getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            try (var output = exchange.getResponseBody()) { output.write(body); }
        });
        server.start();
        try (var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()) {
            var uri = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/synthetic");
            long requestStarted = System.nanoTime();
            var response = client.send(HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(5)).GET().build(),
                                       HttpResponse.BodyHandlers.ofString());
            long requestMillis = (System.nanoTime() - requestStarted) / 1_000_000;
            System.out.println("REQUEST_MS=" + requestMillis);
            if (response.statusCode() != 200 || !response.body().matches("00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}")) {
                throw new IllegalStateException("synthetic response or trace context invalid");
            }
            if ((Integer.parseInt(response.body().substring(53), 16) & 1) != 1) {
                throw new IllegalStateException("sampled flag missing");
            }
            System.out.println("TRACEPARENT=" + response.body());
            Thread.sleep(500); // 합성시험 한정: 100ms 배치 exporter 출력 확인 전 대기
        } finally {
            server.stop(0);
        }
    }
}
