package com.ecommerce.gateway.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebExceptionHandler;
import reactor.core.publisher.Mono;

@Component
@Order(-2)
public class GlobalWebExceptionHandler implements WebExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalWebExceptionHandler.class);

    @Override
    public Mono<Void> handle(ServerWebExchange exchange, Throwable ex) {
        String traceId = exchange.getAttribute("trace_id");
        String spanId = exchange.getAttribute("span_id");
        if (traceId != null) {
            MDC.put("trace_id", traceId);
            MDC.put("span_id", spanId);
        }
        log.error("Unhandled exception in gateway: {}", ex.getMessage(), ex);
        MDC.remove("trace_id");
        MDC.remove("span_id");
        return Mono.error(ex);
    }
}
