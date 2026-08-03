package com.ecommerce.gateway.filter;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.time.Duration;

@Component
public class FailureInjectionFilter implements GlobalFilter, Ordered {

    @Value("${failure.gateway.latency-ms:0}")
    private volatile long latencyMs;

    @Value("${failure.gateway.rate-limit-enabled:false}")
    private volatile boolean rateLimitEnabled;

    public void setLatencyMs(long latencyMs) {
        this.latencyMs = latencyMs;
    }

    public void setRateLimitEnabled(boolean rateLimitEnabled) {
        this.rateLimitEnabled = rateLimitEnabled;
    }

    public long getLatencyMs() {
        return latencyMs;
    }

    public boolean isRateLimitEnabled() {
        return rateLimitEnabled;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        if (rateLimitEnabled) {
            ServerHttpResponse response = exchange.getResponse();
            response.setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
            return response.setComplete();
        }

        if (latencyMs > 0) {
            return Mono.delay(Duration.ofMillis(latencyMs))
                    .then(chain.filter(exchange));
        }

        return chain.filter(exchange);
    }

    @Override
    public int getOrder() {
        return -2;
    }
}
