"""Daily workflow orchestration (spec section 9).

    pricehistory (universe + sector ETFs + SPY)  -> EMAs, RSI, ATR, rel-strength
    chains (45-60 DTE)                            -> strikes, greeks, IV; snapshot
                                                     today's ATM IV to the store
    Stage 1: gates G1-G5                          -> survivors
    Stage 2: score F1-F7                          -> composite + rank
    Stage 3: test #1 against Standard fire logic
                fails -> No Trade Today
                fires -> Moonshot upgrade? yes -> Moonshot card / no -> Standard
    commit IV-history store · send Telegram (always send something)

Run once daily, ~30 min before close. Signals are for next-session entry;
strike/delta is re-validated against G4 at emit time.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from . import data, factors, fire, gates, market
from .config import MARKET_BENCHMARK, PARAMS, UNIVERSE, Params, validate_params
from .data import atm_iv_snapshot
from .indicators import closes, ema
from .iv_store import IVStore
from .models import Candidate, MarketRegime, NameSnapshot
from .providers import DataProvider
from .strike import build_exit_plan, select_contract
from . import telegram


@dataclass
class PipelineResult:
    date: str
    scanned: int
    past_gates: int
    fire_result: fire.FireResult
    alert: telegram.Alert
    moonshots_allowed: bool
    warmup_note: str | None


def _market_regime(spy_candles: list[dict], p: Params) -> MarketRegime:
    cs = closes(spy_candles)
    _, e50p, e200p = p.ema_periods
    e50 = ema(cs, e50p)[-1]
    e200 = ema(cs, e200p)[-1]
    close = cs[-1]
    return MarketRegime(spy_above_50_200=(e50 is not None and e200 is not None
                                          and close > e50 and close > e200))


def _warmup(min_depth: int, p: Params) -> tuple[bool, str | None]:
    """Forward-collection ladder (spec 11.3). Returns (moonshots_allowed, note)."""
    if min_depth >= p.iv_warmup_full_days:
        return True, None
    if min_depth >= p.iv_warmup_standard_days:
        return False, f"IV history: {min_depth} days (standard OK, moonshots suppressed)"
    return False, f"IV history: {min_depth} days (warming up)"


def run(
    provider: DataProvider,
    store: IVStore,
    today: str | None = None,
    p: Params = PARAMS,
    enforce_volume: bool | None = None,
) -> PipelineResult:
    validate_params(p)
    today = today or _dt.date.today().isoformat()
    # Enforce the G4 day-volume floor only when volume is a real signal (market
    # open / post-close on a trading day); off-hours it would be a zero artifact.
    if enforce_volume is None:
        enforce_volume = market.volume_meaningful()

    # --- prices: universe + sector ETFs + benchmark ---
    needed = sorted({n.symbol for n in UNIVERSE}
                    | {n.sector_etf for n in UNIVERSE} | {MARKET_BENCHMARK})
    candle_cache: dict[str, list[dict]] = {}
    for sym in needed:
        try:
            candle_cache[sym] = provider.candles(sym)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] candles failed for {sym}: {exc}")
            candle_cache[sym] = []

    spy = candle_cache.get(MARKET_BENCHMARK, [])
    regime = _market_regime(spy, p) if spy else MarketRegime(False)

    # --- per-name: chain, IV snapshot, gates, scoring ---
    candidates: list[Candidate] = []
    scanned = 0
    past_gates = 0
    min_depth = p.iv_warmup_full_days  # tracks shallowest IV history among scored

    for name in UNIVERSE:
        scanned += 1
        candles = candle_cache.get(name.symbol, [])
        sector_candles = candle_cache.get(name.sector_etf, [])
        if len(candles) < p.min_history_days or not sector_candles or not spy:
            continue

        try:
            contracts = provider.chain(name.symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] chain failed for {name.symbol}: {exc}")
            contracts = []

        spot = float(candles[-1]["close"])
        atm_iv = atm_iv_snapshot(contracts, spot, p) if contracts else None

        # snapshot today's ATM IV into the store BEFORE computing percentile,
        # but compute the percentile against history strictly before today so a
        # name isn't compared to itself.
        iv_pct = None
        if atm_iv is not None:
            iv_pct = store.iv_percentile(name.symbol, atm_iv,
                                         window=p.iv_percentile_window,
                                         before_date=today)
            store.append_snapshot(today, name.symbol, atm_iv)
            min_depth = min(min_depth, store.history_depth(name.symbol))

        snap = data.build_snapshot(
            name=name, candles=candles, sector_candles=sector_candles,
            spy_candles=spy, chain_contracts=contracts,
            iv_percentile=iv_pct, atm_iv=atm_iv,
            days_to_earnings=provider.days_to_earnings(name.symbol), p=p,
        )
        if snap is None:
            continue

        # Stage 1 underlying gates first (G1,G2,G3,G5), then pick a strike and
        # check the contract gate G4 against it.
        best_call = select_contract(snap, fire.Decision.STANDARD, p, enforce_volume)
        # Record the actual G4 inputs for the chosen strike so diagnose.py can
        # show *which* sub-condition (spread / OI / day-volume) bound, and we
        # can tell a strict threshold from a data problem.
        g4 = None
        if best_call is not None:
            g4 = {
                "strike": best_call.strike,
                "dte": best_call.dte,
                "delta": round(best_call.delta, 3),
                "spread_pct": round(best_call.spread_pct, 4),
                "oi": best_call.open_interest,
                "vol": best_call.volume,
            }
        gate = gates.evaluate(snap, best_call, p, enforce_volume)
        audit = {
            "gates": gate.gates,
            "iv_percentile": iv_pct,
            "close": spot,
            "g4": g4,
            "contracts_in_chain": len(contracts),
            "volume_enforced": enforce_volume,
        }
        if not gate.passed:
            store.record_audit(today, name.symbol, audit)
            continue

        past_gates += 1
        sc = factors.score(snap, p)
        candidates.append(Candidate(snapshot=snap, score=sc))
        audit.update({"passed": True, "factors": sc.factors, "composite": sc.composite})
        store.record_audit(today, name.symbol, audit)

    moonshots_allowed, warmup_note = _warmup(min_depth, p)

    # --- Stage 3: fire logic ---
    fr = fire.evaluate(candidates, regime, p, moonshots_allowed=moonshots_allowed)

    # --- build the alert ---
    contract = None
    exits = None
    if fr.decision != fire.Decision.NO_TRADE and fr.top is not None:
        contract = select_contract(fr.top.snapshot, fr.decision, p, enforce_volume)
        # Re-validate G4 on the exact emit-time strike (chain liquidity drifts).
        if not gates.g4_contract_tradeable(contract, p, enforce_volume):
            fr = fire.FireResult(fire.Decision.NO_TRADE, fr.top, fr.runner_up,
                                 fr.separation,
                                 block_reason="chosen strike failed G4 at emit time")
            contract = None
        else:
            exits = build_exit_plan(contract, fr.decision, fr.top.snapshot.atr, p)

    alert = telegram.render(fr, contract, exits, regime, scanned, past_gates,
                            store=store, warmup_note=warmup_note)

    # Persist what was decided so the next-morning entry check can re-validate
    # the fired name against the live chain (records NO_TRADE too, so the
    # morning run knows there is nothing to act on).
    top = fr.top
    store.record_signal(today, {
        "date": today,
        "decision": fr.decision.value,
        "symbol": top.snapshot.symbol if top else None,
        "ref_close": top.snapshot.close if top else None,
        "confidence": top.score.composite if top else None,
        "strike": contract.strike if contract else None,
        "delta": contract.delta if contract else None,
        "mid": contract.mid if contract else None,
    })

    return PipelineResult(
        date=today, scanned=scanned, past_gates=past_gates,
        fire_result=fr, alert=alert,
        moonshots_allowed=moonshots_allowed, warmup_note=warmup_note,
    )
