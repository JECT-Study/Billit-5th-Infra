package com.ject.tripsheet.infra

import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.micrometer.metrics.test.autoconfigure.AutoConfigureMetrics
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.core.env.Environment
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import java.net.ServerSocket
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

// 서버(인프라)와의 약속을 확인한다. DB·Redis가 필요하다: 로컬은 compose.yaml(15432·16379), CI는 서비스 컨테이너(같은 포트).
abstract class EndpointTestSupport {
    @Autowired
    lateinit var env: Environment

    companion object {
        // 서버와 같게 "고정된 서로 다른 두 포트"(앱 8080·관리 8081 역할)로 띄운다. 비어 있는 포트 두 개를 골라 쓴다.
        @JvmStatic
        @DynamicPropertySource
        fun ports(registry: DynamicPropertyRegistry) {
            val (app, management) = ServerSocket(0).use { a -> ServerSocket(0).use { b -> a.localPort to b.localPort } }
            registry.add("server.port") { app }
            registry.add("management.server.port") { management }
        }
    }

    private val http = HttpClient.newHttpClient()

    fun get(
        portProperty: String,
        path: String,
    ): HttpResponse<String> {
        val port = env.getRequiredProperty(portProperty)
        val request = HttpRequest.newBuilder(URI("http://127.0.0.1:$port$path")).build()
        return http.send(request, HttpResponse.BodyHandlers.ofString())
    }
}

// 테스트는 기본적으로 메트릭 내보내기(Prometheus)를 끈다 → 서버와 같게 켠다.
@AutoConfigureMetrics
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT)
class InfraEndpointsTest : EndpointTestSupport() {
    @Test
    fun `readyz는 인증 없이 DB·Redis가 붙으면 200`() {
        assertEquals(200, get("local.server.port", "/readyz").statusCode())
        assertEquals(200, get("local.server.port", "/healthz").statusCode())
    }

    @Test
    fun `관리 포트에서 Prometheus 지표를 준다`() {
        val res = get("local.management.port", "/actuator/prometheus")
        assertEquals(200, res.statusCode())
        assertTrue(res.body().contains("jvm_memory_used_bytes"), "JVM 지표")
        assertTrue(res.body().contains("hikaricp_connections"), "DB 커넥션 풀 지표")
        assertTrue(res.body().contains("application=\"tripsheet\""), "공통 태그 application")
    }

    @Test
    fun `앱 포트에는 actuator가 없다`() {
        assertNotEquals(200, get("local.server.port", "/actuator/prometheus").statusCode())
    }

    @Test
    fun `로컬에서는 API 문서를 연다`() {
        assertEquals(200, get("local.server.port", "/v3/api-docs").statusCode())
    }
}

@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT,
    properties = [
        // 운영 프로필에는 접속값이 없다(서버가 환경변수로 넣음). 시험에서는 로컬 DB·Redis를 쓴다.
        "spring.datasource.url=jdbc:postgresql://localhost:15432/ject",
        "spring.datasource.username=ject",
        "spring.datasource.password=ject",
        "spring.data.redis.port=16379",
    ],
)
@ActiveProfiles("prod")
class ProdProfileTest : EndpointTestSupport() {
    @Test
    fun `운영 프로필에서는 API 문서가 꺼져 있다`() {
        assertNotEquals(200, get("local.server.port", "/v3/api-docs").statusCode())
        assertNotEquals(200, get("local.server.port", "/swagger-ui/index.html").statusCode())
    }
}
