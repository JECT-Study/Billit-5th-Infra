package com.ject.tripsheet.config

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.boot.security.autoconfigure.actuate.web.servlet.EndpointRequest
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.web.SecurityFilterChain

/**
 * 서버(인프라)와 약속한 경로만 여는 Security 체인. 나머지 경로의 인증 규칙은 팀의 SecurityConfig가 정한다.
 * 각 체인은 정해진 경로에만 걸리고(securityMatcher) 우선순위가 높아서 팀 설정과 겹치지 않는다.
 */
@Configuration
class InfraSecurityConfig {
    /** /healthz(컨테이너 HEALTHCHECK, 프로세스 생존), /readyz(배포 스크립트·Nginx, DB·Redis 연결). 응답은 UP/DOWN뿐이다. */
    @Bean
    @Order(0)
    fun healthEndpointSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
        http
            .securityMatcher("/healthz", "/readyz")
            .authorizeHttpRequests { it.anyRequest().permitAll() }
            .csrf { it.disable() }
        return http.build()
    }

    /**
     * 관리 포트 8081의 actuator(health, info, prometheus). 이 포트는 서버 밖으로 열리지 않는다
     * (호스트 127.0.0.1:18081 → 같은 VM의 Alloy만 수집). 앱 포트 8080에는 /actuator가 없고 Nginx도 막는다.
     * 관리 포트를 앱 포트와 합치지 않는다(합치면 이 체인이 공개 경로가 된다).
     * 매처는 Boot의 EndpointRequest(관리 포트·base path를 알고 actuator 엔드포인트만 고른다)를 쓴다.
     */
    @Bean
    @Order(1)
    fun actuatorSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
        http
            .securityMatcher(EndpointRequest.toAnyEndpoint())
            .authorizeHttpRequests { it.anyRequest().permitAll() }
            .csrf { it.disable() }
        return http.build()
    }

    /**
     * API 문서(springdoc). springdoc.api-docs.enabled=true인 로컬·개발에서만 만든다(운영은 꺼져 있고 Nginx도 막는다).
     * 개발 서버에서는 Nginx가 Basic 인증을 건다.
     */
    @Bean
    @Order(2)
    @ConditionalOnProperty("springdoc.api-docs.enabled", havingValue = "true")
    fun apiDocsSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
        http
            .securityMatcher("/swagger-ui.html", "/swagger-ui/**", "/v3/api-docs", "/v3/api-docs/**")
            .authorizeHttpRequests { it.anyRequest().permitAll() }
            .csrf { it.disable() }
        return http.build()
    }
}
