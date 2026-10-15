package com.ject.tripsheet.sample

import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.web.SecurityFilterChain
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RestController

// 검증용 샘플(템플릿에 포함하지 않음): DB 쓰기·Redis 쓰기가 실제로 되는지 확인한다.
@RestController
class SampleApi(
    private val jdbc: JdbcTemplate,
    private val redis: StringRedisTemplate,
    @Value("\${APP_VERSION:dev}") private val version: String,
) {
    @GetMapping("/api/ping")
    fun ping(): Map<String, Any?> {
        jdbc.update("insert into sample_ping default values")
        val n = redis.opsForValue().increment("sample:ping")
        return mapOf(
            "status" to "ok",
            "version" to version,
            "rows" to jdbc.queryForObject("select count(*) from sample_ping", Long::class.java),
            "redisCounter" to n,
        )
    }
}

@Configuration
class SampleSecurityConfig {
    @Bean
    fun sampleSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
        http
            .authorizeHttpRequests {
                it.requestMatchers("/api/ping").permitAll()
                it.anyRequest().authenticated()
            }.csrf { it.disable() }
        return http.build()
    }
}
