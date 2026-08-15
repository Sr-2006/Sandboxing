import sys
import os
from datetime import timezone
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import parse_iso_dt

def test_pathological_iso_strings():
    # 1. Standard Z
    dt1 = parse_iso_dt("2026-08-15T10:00:00Z")
    assert dt1.tzinfo == timezone.utc
    assert dt1.hour == 10

    # 2. Offset +05:30
    dt2 = parse_iso_dt("2026-08-15T15:30:00+05:30")
    assert dt2.tzinfo == timezone.utc
    assert dt2.hour == 10

    # 3. Naive ISO without offset
    dt3 = parse_iso_dt("2026-08-15T10:00:00")
    assert dt3.tzinfo == timezone.utc
    assert dt3.hour == 10

    # 4. Milliseconds
    dt4 = parse_iso_dt("2026-08-15T10:00:00.123Z")
    assert dt4.tzinfo == timezone.utc
    assert dt4.microsecond == 123000

    # 5. Space separator
    dt5 = parse_iso_dt("2026-08-15 10:00:00Z")
    assert dt5.tzinfo == timezone.utc
    assert dt5.hour == 10
