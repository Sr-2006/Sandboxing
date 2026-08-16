import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, field_validator

class DatasetMeta(BaseModel):
    dataset_version: str          # semver (e.g. "2.0.0")
    processor_version: int        # from phase1_processor.PROCESSOR_VERSION
    git_sha: str                  # git commit hash
    source_files: Dict[str, int]  # filename -> record count
    schema_version: str = "1.0"

class SystemContext(BaseModel):
    objective: str
    environment: str
    current_health_score: float
    active_warnings: int

class IncidentEvent(BaseModel):
    incident_id: str
    target_service: str
    priority_score: float
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    occurrence_count: int

    @field_validator("incident_id")
    @classmethod
    def validate_incident_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+_\d+$", v):
            raise ValueError(f"incident_id must match regex ^[a-zA-Z0-9_-]+_\\d+$, got {v}")
        return v

class InfrastructureTopology(BaseModel):
    role: str
    downstream_dependencies: List[str]
    exposed_ports: List[str]

class ServiceHealthStatus(BaseModel):
    docker_status: str
    health_check: str
    dependency_states: Dict[str, Any]  # key = service name

class LogSample(BaseModel):
    timestamp: str  # ISO 8601
    level: str
    content: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

class MetricsSnapshot(BaseModel):
    timestamp: str
    cpu_percent: float
    memory_usage_bytes: int
    memory_usage_percent: float

class TelemetryEvidence(BaseModel):
    log_cluster_template: str
    log_samples: List[LogSample]  # max 5
    metrics_snapshot: List[MetricsSnapshot]  # max 3

class InjectedChaosContext(BaseModel):
    active_infrastructure_mutations: str

class Incident(BaseModel):
    system_context: SystemContext
    incident_event: IncidentEvent
    infrastructure_topology: InfrastructureTopology
    service_health_status: ServiceHealthStatus
    telemetry_evidence: TelemetryEvidence
    injected_chaos_context: InjectedChaosContext

class UnifiedMasterDataset(BaseModel):
    generated_at: str
    metadata: Optional[DatasetMeta] = None
    system_context: SystemContext
    incidents: List[Incident]
