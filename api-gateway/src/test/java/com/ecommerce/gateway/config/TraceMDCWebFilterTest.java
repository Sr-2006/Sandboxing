package com.ecommerce.gateway.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import static org.junit.jupiter.api.Assertions.*;

public class TraceMDCWebFilterTest {

    @Test
    @DisplayName("TraceMDCWebFilter executes cleanly and clears MDC upon completion")
    void testFilterExecutionAndMDCCleanup() {
        TraceMDCWebFilter filter = new TraceMDCWebFilter();
        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/orders")
                .header("X-Correlation-ID", "test-corr-id-1234")
                .build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        final boolean[] filterRan = {false};
        WebFilterChain chain = ex -> {
            filterRan[0] = true;
            return Mono.empty();
        };

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertTrue(filterRan[0], "Chain should be executed");
        assertNull(MDC.get("trace_id"), "MDC trace_id should be cleared");
        assertNull(MDC.get("span_id"), "MDC span_id should be cleared");
    }
}
