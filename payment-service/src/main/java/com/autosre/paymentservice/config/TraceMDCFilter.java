package com.autosre.paymentservice.config;

import io.micrometer.tracing.Tracer;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.io.IOException;

@Component
@Order(Ordered.LOWEST_PRECEDENCE)
public class TraceMDCFilter implements Filter {

    @Autowired(required = false)
    private Tracer tracer;

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        
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
            MDC.put("trace_id", traceId);
            MDC.put("span_id", spanId);
        }

        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove("trace_id");
            MDC.remove("span_id");
        }
    }
}
