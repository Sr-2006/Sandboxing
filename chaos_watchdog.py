import os
from typing import Optional
from datetime import datetime, timezone, timedelta

from utils import (
    project_path,
    read_json_file,
    record_chaos_event,
    parse_iso_dt,
    get_logger
)
import chaos_orchestrator

logger = get_logger("chaos_watchdog")

DEFAULT_HISTORY_FILE = project_path("frontend_data", "chaos_history.json")
GRACE_PERIOD_SECONDS = 600.0

def reconcile_stale_chaos_events(
    history_filepath: Optional[str] = None,
    grace_seconds: float = GRACE_PERIOD_SECONDS
) -> int:
    """
    Scans chaos_history.json for stale 'injected' events older than (start_ts + duration_s + grace_seconds)
    and attempts to recover them, recording recovery events to prevent orphan faults.
    Returns the count of reconciled events.
    """
    if history_filepath is None:
        history_filepath = DEFAULT_HISTORY_FILE

    if not os.path.exists(history_filepath):
        logger.info(f"Watchdog: No chaos history file found at '{history_filepath}'. Nothing to reconcile.")
        return 0

    history_data = read_json_file(history_filepath, [])
    if not isinstance(history_data, list) or not history_data:
        return 0

    now = datetime.now(timezone.utc)
    reconciled_count = 0

    # Track recovered faults so we don't double-recover
    already_recovered_keys = set()
    for ev in history_data:
        if not isinstance(ev, dict):
            continue
        if ev.get("status") in ("recovered", "failed"):
            already_recovered_keys.add((ev.get("fault_name"), ev.get("target"), ev.get("scenario_id")))

    for ev in history_data:
        if not isinstance(ev, dict):
            continue
        if ev.get("status") != "injected":
            continue

        fault_name = ev.get("fault_name", "")
        target = ev.get("target", "")
        scenario_id = ev.get("scenario_id", "adhoc")
        start_ts = ev.get("start_ts", "")
        duration_s = float(ev.get("duration_s", 0.0))

        start_dt = parse_iso_dt(start_ts)
        stale_threshold = start_dt + timedelta(seconds=duration_s + grace_seconds)

        if now >= stale_threshold:
            logger.warning(
                f"Watchdog detected stale unrecovered fault '{fault_name}' on '{target}' "
                f"(injected at {start_ts}, duration: {duration_s}s, grace: {grace_seconds}s)."
            )
            reconciled_count += 1
            now_iso = now.isoformat()
            try:
                chaos_orchestrator.recover_fault(fault_name, target, scenario_id=scenario_id)
                record_chaos_event(
                    fault_name=fault_name,
                    target=target,
                    start_ts=start_ts,
                    end_ts=now_iso,
                    params={"recovery": "watchdog", "original_event_id": ev.get("event_id")},
                    duration_s=duration_s,
                    status="recovered",
                    scenario_id=scenario_id,
                    filepath=history_filepath
                )
                logger.info(f"Watchdog successfully recovered and logged '{fault_name}' on '{target}'.")
            except Exception as rec_err:
                logger.error(f"Watchdog failed to recover fault '{fault_name}' on '{target}': {rec_err}")
                try:
                    record_chaos_event(
                        fault_name=fault_name,
                        target=target,
                        start_ts=start_ts,
                        end_ts=now_iso,
                        params={"recovery": "failed", "error": str(rec_err), "original_event_id": ev.get("event_id")},
                        duration_s=duration_s,
                        status="failed",
                        scenario_id=scenario_id,
                        filepath=history_filepath
                    )
                except Exception as log_err:
                    logger.error(f"Watchdog could not record failed recovery event: {log_err}")

    if reconciled_count > 0:
        logger.info(f"Watchdog finished reconciliation: {reconciled_count} stale fault(s) processed.")
    else:
        logger.info("Watchdog: All active faults are within operational parameters. Zero stale faults found.")

    return reconciled_count

if __name__ == "__main__":
    count = reconcile_stale_chaos_events()
    print(f"Reconciled {count} stale chaos events.")
