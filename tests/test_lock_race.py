import os
import json
import multiprocessing
from utils import record_chaos_event

def _worker_record_events(file_path: str, count: int, worker_id: int):
    for i in range(count):
        record_chaos_event(
            fault_name=f"fault_w{worker_id}_{i}",
            target="order-service",
            start_ts="2026-08-15T12:00:00+00:00",
            end_ts="2026-08-15T12:00:10+00:00",
            params={"w": worker_id, "i": i},
            duration_s=10.0,
            status="recovered",
            filepath=file_path
        )

def test_multiprocessing_lock_race_durability(tmp_path):
    history_file = str(tmp_path / "chaos_history.json")

    p1 = multiprocessing.Process(target=_worker_record_events, args=(history_file, 100, 1))
    p2 = multiprocessing.Process(target=_worker_record_events, args=(history_file, 100, 2))

    p1.start()
    p2.start()

    p1.join(timeout=30)
    p2.join(timeout=30)

    assert p1.exitcode == 0
    assert p2.exitcode == 0

    assert os.path.exists(history_file)
    with open(history_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert len(data) == 200
