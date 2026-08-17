package com.ecommerce.gateway.filter;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

public class JwtValidationFilterTest {

    private JwtValidationFilter filter;

    @BeforeEach
    void setUp() {
        WebClient.Builder webClientBuilder = WebClient.builder();
        filter = new JwtValidationFilter(webClientBuilder);
        filter.setInternalServiceToken("gateway_secret_token_123");
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
    @DisplayName("Client-supplied spoofed headers are stripped and replaced on forwarded request")
    void testClientSuppliedHeadersAreStrippedAndReplaced() {
        MockServerHttpRequest request = MockServerHttpRequest.post("/api/v1/auth/login")
                .header("X-User-Id", "attacker_spoofed_user")
                .header("X-Internal-Service-Token", "attacker_spoofed_token")
                .build();
        ServerWebExchange exchange = MockServerWebExchange.from(request);

        final ServerHttpRequest[] forwardedRequest = new ServerHttpRequest[1];
        GatewayFilterChain chain = ex -> {
            forwardedRequest[0] = ex.getRequest();
            return Mono.empty();
        };

        StepVerifier.create(filter.filter(exchange, chain))
                .verifyComplete();

        assertNotNull(forwardedRequest[0]);
        HttpHeaders forwardedHeaders = forwardedRequest[0].getHeaders();

        // X-User-Id must NOT contain the client-supplied value
        assertNull(forwardedHeaders.getFirst("X-User-Id"));

        // X-Internal-Service-Token must contain ONLY the gateway's token (exactly one value)
        List<String> internalTokens = forwardedHeaders.get("X-Internal-Service-Token");
        assertNotNull(internalTokens);
        assertEquals(1, internalTokens.size());
        assertEquals("gateway_secret_token_123", internalTokens.get(0));
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
