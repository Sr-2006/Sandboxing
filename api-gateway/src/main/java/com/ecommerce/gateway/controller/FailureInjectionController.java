package com.ecommerce.gateway.controller;

import com.ecommerce.gateway.filter.FailureInjectionFilter;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api/v1/failures/gateway")
@Profile("dev")
public class FailureInjectionController {

    private final FailureInjectionFilter failureFilter;

    public FailureInjectionController(FailureInjectionFilter failureFilter) {
        this.failureFilter = failureFilter;
    }

    @GetMapping
    public Mono<FailureSettingsResponse> getSettings() {
        return Mono.just(new FailureSettingsResponse(
                failureFilter.getLatencyMs(),
                failureFilter.isRateLimitEnabled()
        ));
    }

    @PostMapping
    public Mono<FailureSettingsResponse> updateSettings(@RequestBody FailureSettingsRequest request) {
        failureFilter.setLatencyMs(request.latencyMs());
        failureFilter.setRateLimitEnabled(request.rateLimitEnabled());
        return Mono.just(new FailureSettingsResponse(
                failureFilter.getLatencyMs(),
                failureFilter.isRateLimitEnabled()
        ));
    }

    public record FailureSettingsRequest(long latencyMs, boolean rateLimitEnabled) {}
    public record FailureSettingsResponse(long latencyMs, boolean rateLimitEnabled) {}
}
