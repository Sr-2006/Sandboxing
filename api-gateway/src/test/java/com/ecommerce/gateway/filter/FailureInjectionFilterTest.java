package com.ecommerce.gateway.filter;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;

public class FailureInjectionFilterTest {

    private FailureInjectionFilter filter;

    @BeforeEach
    void setUp() {
        filter = new FailureInjectionFilter();
    }

    @Test
    @DisplayName("Normal execution when no faults are enabled")
    void testNoFaultEnabled() {
        filter.setRateLimitEnabled(false);
        filter.setLatencyMs(0);

        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/test").build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        final boolean[] executed = {false};
        GatewayFilterChain chain = ex -> {
            executed[0] = true;
            return Mono.empty();
        };

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertTrue(executed[0]);
    }

    @Test
    @DisplayName("Rate limit fault returns 429 TOO_MANY_REQUESTS")
    void testRateLimitFault() {
        filter.setRateLimitEnabled(true);

        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/test").build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        GatewayFilterChain chain = ex -> Mono.empty();

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertEquals(HttpStatus.TOO_MANY_REQUESTS, exchange.getResponse().getStatusCode());
    }

    @Test
    @DisplayName("Latency injection delays execution")
    void testLatencyInjection() {
        filter.setRateLimitEnabled(false);
        filter.setLatencyMs(100);

        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/test").build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        GatewayFilterChain chain = ex -> Mono.empty();

        StepVerifier.withVirtualTime(() -> filter.filter(exchange, chain))
                .expectSubscription()
                .expectNoEvent(Duration.ofMillis(99))
                .thenAwait(Duration.ofMillis(100))
                .verifyComplete();
    }
}
