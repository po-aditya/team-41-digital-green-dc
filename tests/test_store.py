import json
import threading

import pytest

from mel_agent.store import MAX_PAGE_SIZE, Store, StoreError


def _insight_row(i: int) -> dict:
    return {"insight_id": f"I-{i:06d}", "farmer_id": f"F-{i % 3:06d}", "created_at": f"2026-11-{1 + i % 28:02d}T08:00:00+05:30",
            "conversation_language": "hi-IN", "resolution_type": "direct_action", "asset_name": "wheat", "concern": "pest_disease",
            "severity": "low", "quality_flag": "clean", "schema_valid": 1, "quarantine_reason": None, "source_file": "t.jsonl",
            "line_no": i, "content_hash": "x", "raw_json": json.dumps({"insight_id": f"I-{i:06d}"}), "ingested_at": "2026-11-01T00:00:00+05:30"}


@pytest.fixture
def store():
    return Store(":memory:")


def test_upsert_is_idempotent_and_updates(store):
    with store.write() as conn:
        store.upsert_insight(conn, _insight_row(1))
        store.upsert_insight(conn, {**_insight_row(1), "severity": "high"})
    assert store.count_insights() == 1
    assert store.get_insight("I-000001")["severity"] == "high"


def test_pagination_bounds_and_stable_order(store):
    with store.write() as conn:
        for i in range(1, 8):
            store.upsert_insight(conn, _insight_row(i))
    page = store.list_insights(limit=3, offset=0)
    assert [r["insight_id"] for r in page.items] == ["I-000001", "I-000002", "I-000003"]
    assert page.total == 7 and page.to_dict()["next_offset"] == 3
    last = store.list_insights(limit=3, offset=6)
    assert len(last.items) == 1 and last.to_dict()["next_offset"] is None
    for bad in ({"limit": 0}, {"limit": MAX_PAGE_SIZE + 1}, {"offset": -1}):
        with pytest.raises(StoreError):
            store.list_insights(**bad)


def test_filters(store):
    with store.write() as conn:
        for i in range(1, 7):
            store.upsert_insight(conn, _insight_row(i))
    assert store.list_insights(farmer_id="F-000001").total == 2
    assert store.list_insights(created_from="2026-11-05T00:00:00+05:30").total == 3  # days 5, 6, 7
    assert store.list_insights(created_to="2026-11-03T23:59:59+05:30").total == 2  # days 2, 3


def test_response_insert_once(store):
    row = {"response_key": "rk-1", "survey_id": "S-00001", "farmer_id": "F-1", "channel": "app", "status": "completed", "failure_code": None,
           "needs_follow_up": 0, "counts_toward_cap": 1, "recorded_at": "2026-12-01T10:00:00+05:30", "record_json": "{}"}
    with store.write() as conn:
        assert store.insert_response(conn, row) is True
        assert store.insert_response(conn, row) is False
    assert store.list_responses().total == 1


def test_write_rolls_back_on_error(store):
    with pytest.raises(RuntimeError):
        with store.write() as conn:
            store.upsert_insight(conn, _insight_row(1))
            raise RuntimeError("boom")
    assert store.count_insights() == 0


def test_audit_sequence_increments(store):
    with store.write() as conn:
        store.audit(conn, "2026-11-01T00:00:00+05:30", "x", "1", "a")
        store.audit(conn, "2026-11-01T00:00:00+05:30", "x", "1", "b")
    items = store.list_audit().items
    assert [i["seq"] for i in items] == [1, 2]


def test_kv_and_url(tmp_path):
    store = Store.from_url(f"sqlite:///{tmp_path / 'x.db'}")
    store.kv_set("a", "1"); store.kv_set("a", "2")
    assert store.kv_get("a") == "2" and store.kv_get("b") is None
    with pytest.raises(StoreError):
        Store.from_url("postgresql://x")


def test_concurrent_writers_serialised(tmp_path):
    store = Store(tmp_path / "c.db")
    errors = []

    def work(n):
        try:
            with store.write() as conn:
                store.upsert_insight(conn, _insight_row(n))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(1, 25)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors and store.count_insights() == 24
