from optionradar import telegram
from optionradar.fire import Decision
from optionradar.iv_store import IVStore
from optionradar.strike import build_exit_plan
from tests.factories import make_contract

SIGNAL = {"date": "2026-06-22", "decision": "STANDARD", "symbol": "UBER",
          "ref_close": 72.0, "confidence": 84.0}


def _exits(c):
    return build_exit_plan(c, Decision.STANDARD, atr=2.0)


def test_signal_roundtrip(tmp_path):
    store = IVStore(tmp_path / "iv.sqlite")
    store.record_signal("2026-06-22", SIGNAL)
    assert store.latest_signal()["symbol"] == "UBER"
    assert store.signal_for("2026-06-22")["decision"] == "STANDARD"
    assert store.signal_for("2999-01-01") is None
    store.close()


def test_entry_card_still_valid():
    c = make_contract()
    text = telegram.entry_check_card(SIGNAL, c, _exits(c), gate_failed=None,
                                     gap_pct=0.006, gap_atr=0.2, gap_warn=False)
    assert "STILL VALID" in text
    assert "UBER" in text
    assert "Limit" in text          # fresh cost range present


def test_entry_card_skips_on_broken_gate():
    c = make_contract()
    text = telegram.entry_check_card(SIGNAL, c, _exits(c), gate_failed=["G1"],
                                     gap_pct=-0.03, gap_atr=-1.1, gap_warn=True)
    assert "SKIP" in text
    assert "trend broke" in text


def test_entry_card_caution_on_gap():
    c = make_contract()
    text = telegram.entry_check_card(SIGNAL, c, _exits(c), gate_failed=None,
                                     gap_pct=0.04, gap_atr=1.4, gap_warn=True)
    assert "CAUTION" in text
    assert "Limit" in text          # still shows the trade, just flags caution
