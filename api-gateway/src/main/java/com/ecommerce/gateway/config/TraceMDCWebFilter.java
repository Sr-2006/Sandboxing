package com.ecommerce.gateway.config;

import io.micrometer.tracing.Tracer;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
@Order(Ordered.LOWEST_PRECEDENCE)
public class TraceMDCWebFilter implements WebFilter {

    @Autowired(required = false)
    private Tracer tracer;

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        String traceId = null;
        String spanId = null;

        if (tracer != null && tracer.currentSpan() != null) {
            traceId = tracer.currentSpan().context().traceId();
            spanId = tracer.currentSpan().context().spanId();
        }

        if (traceId == null) {
            Span span = Span.current();
            SpanContext spanContext = span.getSpanContext();
            if (spanContext.isValid()) {
                traceId = spanContext.getTraceId();
                spanId = spanContext.getSpanId();
            }
        }

        if (traceId != null) {
            exchange.getAttributes().put("trace_id", traceId);
            exchange.getAttributes().put("span_id", spanId);
            MDC.put("trace_id", traceId);
            MDC.put("span_id", spanId);
        }

        final String finalTraceId = traceId;
        final String finalSpanId = spanId;

        return chain.filter(exchange).doOnEach(signal -> {
            if (finalTraceId != null) {
                MDC.put("trace_id", finalTraceId);
                MDC.put("span_id", finalSpanId);
            }
        }).doFinally(signalType -> {
            MDC.remove("trace_id");
            MDC.remove("span_id");
        });
    }
}
