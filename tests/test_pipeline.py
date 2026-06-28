"""End-to-end smoke test of the daily pipeline against the mock provider."""

from optionradar.iv_store import IVStore
from optionradar.pipeline import run
from optionradar.providers import MockProvider


def test_pipeline_runs_and_always_emits(tmp_path):
    store = IVStore(tmp_path / "iv.sqlite")
    provider = MockProvider()
    result = run(provider, store, today="2026-06-20")
    # always sends something
    assert result.alert.text
    assert result.scanned > 0
    # decision is one of the three valid outputs
    assert result.fire_result.decision.value in ("NO_TRADE", "STANDARD", "MOONSHOT")
    store.close()


def test_pipeline_is_idempotent_on_rerun(tmp_path):
    db = tmp_path / "iv.sqlite"
    provider = MockProvider()
    store = IVStore(db)
    r1 = run(provider, store, today="2026-06-20")
    store.close()
    # rerunning the same date must not double-write the IV store
    store = IVStore(db)
    depth_before = store.history_depth("NVDA")
    r2 = run(provider, store, today="2026-06-20")
    depth_after = store.history_depth("NVDA")
    assert depth_before == depth_after
    assert r1.fire_result.decision == r2.fire_result.decision
    store.close()
