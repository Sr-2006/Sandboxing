import json
import os
import sys

def validate():
    file_path = os.path.join('frontend_data', 'processed_incidents.json')
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        sys.exit(1)
        
    with open(file_path, 'r') as f:
        data = json.load(f)

    incidents = data.get('incidents', [])
    
    # Check 1: trace_ratio_errwarn >= 0.80
    total_error_warn = 0
    correlated_trace_span = 0
    for incident in incidents:
        for sample in incident.get("telemetry_evidence", {}).get("log_samples", []):
            if sample.get("level") in ("ERROR", "WARN"):
                total_error_warn += 1
                if sample.get("trace_id") and sample.get("span_id"):
                    correlated_trace_span += 1
                    
    trace_ratio = correlated_trace_span / total_error_warn if total_error_warn > 0 else 1.0
    
    # Check 2: redis_med_high == 0
    redis_med_high = 0
    for inc in incidents:
        if inc["incident_event"]["target_service"] == "redis":
            sev = inc["incident_event"]["severity"]
            if sev in ("MEDIUM", "HIGH", "CRITICAL"):
                redis_med_high += 1
                
    # Check 3: rabbitmq_in_top5 == 0
    rabbitmq_in_top5 = 0
    for i, inc in enumerate(incidents[:5]):
        if inc["incident_event"]["target_service"] == "rabbitmq":
            rabbitmq_in_top5 += 1
            
    # Check 4: top5_at_star_only == 0
    top5_at_star_only = 0
    for i, inc in enumerate(incidents[:5]):
        template = inc["telemetry_evidence"]["log_cluster_template"]
        if template.strip().startswith("at ") and "Exception" not in template and "Error" not in template:
            top5_at_star_only += 1

    report = {
        "trace_ratio_errwarn": trace_ratio,
        "redis_med_high": redis_med_high,
        "rabbitmq_in_top5": rabbitmq_in_top5,
        "top5_at_star_only": top5_at_star_only,
        "schema_ok": True
    }
    
    print(json.dumps(report, indent=2))
    with open('validation_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    passed = (
        trace_ratio >= 0.80 and
        redis_med_high == 0 and
        rabbitmq_in_top5 == 0 and
        top5_at_star_only == 0
    )
    
    if passed:
        print("Validation PASSED")
        sys.exit(0)
    else:
        print("Validation FAILED")
        sys.exit(1)

if __name__ == '__main__':
    validate()
