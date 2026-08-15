package com.ecommerce.gateway.filter;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import static org.junit.jupiter.api.Assertions.*;

public class JwtValidationFilterTest {

    private JwtValidationFilter filter;

    @BeforeEach
    void setUp() {
        WebClient.Builder webClientBuilder = WebClient.builder();
        filter = new JwtValidationFilter(webClientBuilder);
    }

    @Test
    @DisplayName("Public path (/api/v1/auth/login) bypasses JWT validation")
    void testPublicPathBypassesValidation() {
        MockServerHttpRequest request = MockServerHttpRequest.post("/api/v1/auth/login").build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        final boolean[] chainExecuted = {false};
        GatewayFilterChain chain = ex -> {
            chainExecuted[0] = true;
            return Mono.empty();
        };

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertTrue(chainExecuted[0]);
    }

    @Test
    @DisplayName("Missing Authorization header on protected path returns 401 UNAUTHORIZED")
    void testMissingAuthHeaderReturns401() {
        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/orders/123").build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        GatewayFilterChain chain = ex -> Mono.empty();

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }

    @Test
    @DisplayName("Invalid Bearer header format returns 401 UNAUTHORIZED")
    void testInvalidHeaderFormatReturns401() {
        MockServerHttpRequest request = MockServerHttpRequest.get("/api/v1/orders/123")
                .header(HttpHeaders.AUTHORIZATION, "Basic invalidtoken")
                .build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        GatewayFilterChain chain = ex -> Mono.empty();

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }
}
