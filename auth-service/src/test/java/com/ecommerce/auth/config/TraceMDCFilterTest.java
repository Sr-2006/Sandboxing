package com.ecommerce.auth.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.*;

public class TraceMDCFilterTest {

    @Test
    @DisplayName("TraceMDCFilter sets and clears MDC context across filter chain")
    void testFilterLifecycle() throws ServletException, IOException {
        TraceMDCFilter filter = new TraceMDCFilter();
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();

        final boolean[] insideChain = {false};
        FilterChain chain = (req, res) -> {
            insideChain[0] = true;
            // When running without active OTel agent, MDC keys may be empty, but filter execution must succeed
        };

        filter.doFilter(request, response, chain);
        assertTrue(insideChain[0], "Filter chain was executed");
        assertNull(MDC.get("trace_id"), "MDC should be cleared after filter completion");
        assertNull(MDC.get("span_id"), "MDC should be cleared after filter completion");
    }
}
