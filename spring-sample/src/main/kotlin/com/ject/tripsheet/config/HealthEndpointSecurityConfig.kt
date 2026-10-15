package com.ject.tripsheet.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.web.SecurityFilterChain

/**
 * 서버 배포가 확인하는 상태 경로(/healthz, /readyz)만 인증 없이 연다.
 *
 * - /healthz: 컨테이너 HEALTHCHECK(프로세스 생존), /readyz: 배포 스크립트·Nginx(DB·Redis 연결 포함).
 * - 응답은 UP/DOWN 정도라 공개돼도 내부 정보가 없다. 나머지 경로의 인증 규칙은 팀의 SecurityConfig가 정한다.
 * - 이 체인은 두 경로에만 걸리고(securityMatcher), 우선순위가 높아(@Order(0)) 팀 설정과 겹치지 않는다.
 */
@Configuration
class HealthEndpointSecurityConfig {
    @Bean
    @Order(0)
    fun healthEndpointSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
        http
            .securityMatcher("/healthz", "/readyz")
            .authorizeHttpRequests { it.anyRequest().permitAll() }
            .csrf { it.disable() }
        return http.build()
    }
}
