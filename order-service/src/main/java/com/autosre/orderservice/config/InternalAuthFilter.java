package com.autosre.orderservice.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Collections;

@Component
public class InternalAuthFilter extends OncePerRequestFilter {

    @Value("${INTERNAL_SERVICE_TOKEN:${internal.service.token:}}")
    private String internalServiceToken;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        String path = request.getRequestURI();

        // Allow public/exempt paths
        if (path.startsWith("/actuator/health") || path.startsWith("/actuator/info") || path.startsWith("/actuator/prometheus")
                || path.startsWith("/chaos") || path.equals("/error")) {
            filterChain.doFilter(request, response);
            return;
        }

        // Validate internal token and user identity on /api/**
        if (path.startsWith("/api/")) {
            String tokenHeader = request.getHeader("X-Internal-Service-Token");
            String userId = request.getHeader("X-User-Id");

            if (internalServiceToken == null || internalServiceToken.trim().isEmpty()
                    || tokenHeader == null || !internalServiceToken.equals(tokenHeader)) {
                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.getWriter().write("Unauthorized: Invalid or missing X-Internal-Service-Token");
                return;
            }

            if (userId == null || userId.trim().isEmpty()) {
                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.getWriter().write("Unauthorized: Missing X-User-Id header");
                return;
            }

            UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(
                    userId,
                    null,
                    Collections.singletonList(new SimpleGrantedAuthority("ROLE_USER"))
            );
            SecurityContextHolder.getContext().setAuthentication(auth);

            filterChain.doFilter(request, response);
            return;
        }

        // Deny all other actuator / private endpoints
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.getWriter().write("Unauthorized: Access denied");
    }
}
