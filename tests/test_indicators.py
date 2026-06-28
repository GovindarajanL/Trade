from optionradar import indicators as ind


def _candles(closes):
    out = []
    for i, c in enumerate(closes):
        out.append({"date": f"d{i}", "open": c, "high": c + 1,
                    "low": c - 1, "close": c, "volume": 1000})
    return out


def test_ema_constant_series():
    vals = [10.0] * 30
    e = ind.ema(vals, 10)
    assert e[-1] == 10.0           # EMA of a flat series is the value
    assert e[8] is None            # not enough data before period


def test_rsi_all_gains_is_100():
    vals = [float(i) for i in range(1, 40)]   # strictly increasing
    r = ind.wilder_rsi(vals, 14)
    assert r[-1] == 100.0


def test_rsi_bounds():
    vals = [10 + (i % 3) for i in range(60)]
    r = ind.wilder_rsi(vals, 14)
    assert all(0.0 <= x <= 100.0 for x in r if x is not None)


def test_atr_positive():
    candles = _candles([float(10 + (i % 5)) for i in range(60)])
    a = ind.wilder_atr(candles, 14)
    assert a[-1] is not None and a[-1] > 0


def test_pct_return():
    candles = _candles([100.0] * 10 + [110.0])
    assert abs(ind.pct_return(candles, 1) - 0.10) < 1e-9
