package com.ecommerce.gateway.filter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpRequestDecorator;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Shadow Traffic Mirror Filter
 *
 * Asynchronously mirrors incoming production HTTP requests to the shadow gateway.
 *
 * DESIGN TRADE-OFFS:
 * - Body mirroring uses DataBufferUtils.join() which fuses buffers into a single contiguous DataBuffer.
 * - The 1MB cap prevents OOM on large uploads; payloads exceeding 1MB are mirrored headers-only.
 * - Fire-and-forget WebClient execution ensures shadow request failures never block production.
 * - AutoFailover: after FAILURE_THRESHOLD (5) consecutive shadow failures within a 60s window,
 *   mirroring auto-disables and logs a warning.
 */
@Component
public class ShadowTrafficMirrorFilter implements GlobalFilter, Ordered {

    private static final Logger log = LoggerFactory.getLogger(ShadowTrafficMirrorFilter.class);

    @Value("${shadow.gateway.url:}")
    private String shadowGatewayUrl;

    @Value("${shadow.gateway.enabled:false}")
    private boolean mirrorEnabled;

    private static final int MAX_MIRROR_BODY_BYTES = 1_048_576; // 1MB
    private static final int FAILURE_THRESHOLD = 5;
    private static final Duration FAILURE_WINDOW = Duration.ofSeconds(60);

    private final AtomicBoolean autoDisabled = new AtomicBoolean(false);
    private final AtomicInteger consecutiveFailures = new AtomicInteger(0);
    private final AtomicReference<Instant> windowStart = new AtomicReference<>(Instant.now());

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        if (!mirrorEnabled || shadowGatewayUrl == null || shadowGatewayUrl.isBlank() || autoDisabled.get()) {
            return chain.filter(exchange);
        }

        ServerHttpRequest request = exchange.getRequest();

        return DataBufferUtils.join(request.getBody())
            .defaultIfEmpty(exchange.getResponse().bufferFactory().wrap(new byte[0]))
            .flatMap(dataBuffer -> {
                byte[] bodyBytes;
                try {
                    int readableByteCount = dataBuffer.readableByteCount();
                    if (readableByteCount > MAX_MIRROR_BODY_BYTES) {
                        // Mirror headers-only for oversized payloads
                        bodyBytes = new byte[0];
                    } else {
                        bodyBytes = new byte[readableByteCount];
                        dataBuffer.read(bodyBytes);
                    }
                } finally {
                    DataBufferUtils.release(dataBuffer);
                }

                mirrorToShadowAsync(request, bodyBytes);

                // Re-decorate request so downstream chain can still read the body
                ServerHttpRequest mutatedRequest = new ServerHttpRequestDecorator(request) {
                    @Override
                    public Flux<DataBuffer> getBody() {
                        if (bodyBytes.length == 0) {
                            return Flux.empty();
                        }
                        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bodyBytes);
                        return Flux.just(buffer);
                    }
                };
                return chain.filter(exchange.mutate().request(mutatedRequest).build());
            });
    }

    private void mirrorToShadowAsync(ServerHttpRequest request, byte[] bodyBytes) {
        String path = request.getURI().getPath();
        String query = request.getURI().getQuery();
        String targetUri = shadowGatewayUrl + path + (query != null ? "?" + query : "");

        WebClient.create()
            .method(request.getMethod())
            .uri(targetUri)
            .headers(headers -> headers.addAll(request.getHeaders()))
            .header("X-Mirrored-From", "production")
            .bodyValue(bodyBytes)
            .retrieve()
            .toBodilessEntity()
            .timeout(Duration.ofSeconds(5))
            .doOnError(this::handleMirrorFailure)
            .doOnSuccess(resp -> handleMirrorSuccess())
            .subscribe(
                resp -> {},
                err -> {} // already logged in handleMirrorFailure; never propagate to caller
            );
    }

    private void handleMirrorFailure(Throwable err) {
        Instant now = Instant.now();
        Instant start = windowStart.get();

        if (Duration.between(start, now).compareTo(FAILURE_WINDOW) > 0) {
            windowStart.set(now);
            consecutiveFailures.set(1);
        } else {
            int failures = consecutiveFailures.incrementAndGet();
            if (failures >= FAILURE_THRESHOLD) {
                if (autoDisabled.compareAndSet(false, true)) {
                    log.warn("shadow mirror auto-disabled: reached {} consecutive failures within {} seconds window. Reason: {}",
                            failures, FAILURE_WINDOW.getSeconds(), err.getMessage());
                }
            }
        }
    }

    private void handleMirrorSuccess() {
        consecutiveFailures.set(0);
        windowStart.set(Instant.now());
    }

    @Override
    public int getOrder() {
        return -1; // run early, before auth filters mutate the request further
    }
}
