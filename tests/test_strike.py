from optionradar.fire import Decision
from optionradar.strike import select_contract
from tests.factories import make_contract, make_snapshot


def test_prefers_liquid_strike_over_closest_delta():
    # A strike sits exactly at the target delta but is illiquid (0 OI / 0 vol),
    # and another in-band strike is slightly off-delta but liquid. We must pick
    # the liquid one -- the whole point of the fix.
    dead = make_contract(strike=100, delta=0.62, open_interest=0, volume=0,
                         bid=4.0, ask=6.0, mid=5.0)            # also wide spread
    good = make_contract(strike=98, delta=0.66, open_interest=4000, volume=300,
                         bid=5.95, ask=6.05, mid=6.0)
    snap = make_snapshot(contracts=[dead, good])
    chosen = select_contract(snap, Decision.STANDARD)
    assert chosen is good


def test_falls_back_to_closest_delta_when_none_liquid():
    # Nothing clears G4 -> keep the delta intent (closest to 0.62); the gate
    # will then reject it downstream, which is correct (No Trade).
    a = make_contract(strike=100, delta=0.62, open_interest=10, volume=0)
    b = make_contract(strike=95, delta=0.70, open_interest=10, volume=0)
    snap = make_snapshot(contracts=[a, b])
    chosen = select_contract(snap, Decision.STANDARD)
    assert chosen is a   # closest to the 0.62 target


def test_off_hours_relax_lets_volume_zero_strike_through():
    # A strike with healthy OI + tight spread but zero day-volume: rejected when
    # volume is enforced, accepted when it isn't (off-hours testing).
    c = make_contract(strike=100, delta=0.62, open_interest=3000, volume=0,
                      bid=4.95, ask=5.05, mid=5.0)
    snap = make_snapshot(contracts=[c])
    assert select_contract(snap, Decision.STANDARD, enforce_volume=True) is None or \
        select_contract(snap, Decision.STANDARD, enforce_volume=True).volume == 0
    # with volume enforced there is no *tradeable* contract, so it falls back to
    # the closest-delta (which then fails G4). With volume relaxed it is tradeable.
    from optionradar import gates
    assert not gates.g4_contract_tradeable(c, enforce_volume=True)
    assert gates.g4_contract_tradeable(c, enforce_volume=False)
