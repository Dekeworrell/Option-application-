from __future__ import annotations

from dataclasses import dataclass

from app.services.polygon_client import PolygonClient


SUPPORTED_INDICATORS = {"sma", "ema", "rsi"}


@dataclass(frozen=True)
class IndicatorRequest:
    type: str
    length: int


def _normalize_request(req: IndicatorRequest) -> IndicatorRequest | None:
    t = (req.type or "").lower().strip()

    try:
        n = int(req.length)
    except Exception:
        return None

    if t not in SUPPORTED_INDICATORS:
        return None

    if n <= 0 or n > 500:
        return None

    return IndicatorRequest(type=t, length=n)


def _dedupe_requests(indicators: list[IndicatorRequest]) -> list[IndicatorRequest]:
    seen: set[tuple[str, int]] = set()
    out: list[IndicatorRequest] = []

    for req in indicators:
        normalized = _normalize_request(req)
        if normalized is None:
            continue

        key = (normalized.type, normalized.length)
        if key in seen:
            continue

        seen.add(key)
        out.append(normalized)

    out.sort(key=lambda x: (x.type, x.length))
    return out


def _compute_sma(closes: list[float], length: int) -> float | None:
    if length <= 0:
        return None
    if len(closes) < length:
        return None

    window = closes[-length:]
    return float(sum(window) / length)


def _compute_ema(closes: list[float], length: int) -> float | None:
    if length <= 0:
        return None
    if len(closes) < length:
        return None

    k = 2 / (length + 1)
    ema = sum(closes[:length]) / length

    for price in closes[length:]:
        ema = (price * k) + (ema * (1 - k))

    return float(ema)


def _compute_rsi(closes: list[float], length: int) -> float | None:
    # Wilder RSI
    if length <= 0:
        return None
    if len(closes) < (length + 1):
        return None

    gains: list[float] = []
    losses: list[float] = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length

    for i in range(length, len(gains)):
        avg_gain = ((avg_gain * (length - 1)) + gains[i]) / length
        avg_loss = ((avg_loss * (length - 1)) + losses[i]) / length

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi)


def _extract_daily_closes(daily_resp: dict) -> list[float]:
    bars = daily_resp.get("results") or []
    closes: list[float] = []

    for b in bars:
        if not isinstance(b, dict):
            continue

        c = b.get("c")
        if c is None:
            continue

        try:
            closes.append(float(c))
        except Exception:
            continue

    return closes


async def compute_indicators(
    polygon: PolygonClient,
    symbol: str,
    indicators: list[IndicatorRequest],
) -> dict:
    """
    Returns:
    {
      "ema": {"10": 265.12},
      "rsi": {"14": 52.10},
      "sma": {"30": 263.55}
    }
    """
    out: dict = {}

    normalized_requests = _dedupe_requests(indicators)
    if not normalized_requests:
        return out

    daily_resp = await polygon.get_daily_bars(symbol, days_back=180)
    closes = _extract_daily_closes(daily_resp)

    for req in normalized_requests:
        t = req.type
        n = req.length

        if t == "sma":
            out.setdefault("sma", {})
            out["sma"][str(n)] = _compute_sma(closes, n)

        elif t == "ema":
            out.setdefault("ema", {})
            out["ema"][str(n)] = _compute_ema(closes, n)

        elif t == "rsi":
            out.setdefault("rsi", {})
            out["rsi"][str(n)] = _compute_rsi(closes, n)

    return out