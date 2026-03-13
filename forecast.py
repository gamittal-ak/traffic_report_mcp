"""
Lightweight timeseries forecasting for Akamai traffic data.
Uses numpy only — no heavy ML dependencies.

Supports two methods:
  - linear: OLS linear regression (good for steady trends)
  - ema:    Exponential Moving Average (good for volatile / seasonal data)
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class ForecastResult:
    historical_timestamps: list[str]
    historical_values: list[float]
    forecast_timestamps: list[str]
    forecast_values: list[float]
    method: str
    metric: str
    trend: str          # "increasing", "decreasing", or "stable"
    avg_historical: float
    avg_forecast: float
    pct_change: float   # forecast avg vs historical avg


def _detect_trend(values: list[float]) -> str:
    if len(values) < 2:
        return "stable"
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    mean = np.mean(y)
    if mean == 0:
        return "stable"
    relative_slope = slope / mean
    if relative_slope > 0.01:
        return "increasing"
    elif relative_slope < -0.01:
        return "decreasing"
    return "stable"


def _parse_timestamp(ts) -> "datetime":
    """Parse an Akamai timestamp — either a Unix int (seconds or ms) or ISO-8601 string."""
    from datetime import datetime, timezone
    if isinstance(ts, (int, float)):
        # Akamai returns seconds; guard against accidental milliseconds (>1e10)
        epoch = ts / 1000 if ts > 1e10 else ts
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _ts_to_iso(ts) -> str:
    """Normalise any Akamai timestamp to an ISO-8601 UTC string."""
    return _parse_timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_future_timestamps(
    last_ts,
    interval: str,
    periods: int,
) -> list[str]:
    """Generate future ISO-8601 timestamps based on the interval granularity."""
    from datetime import timedelta

    dt = _parse_timestamp(last_ts)

    valid = {"time1day", "time1hour", "time5minutes"}
    if interval not in valid:
        raise ValueError(f"Unknown granularity '{interval}'. Must be one of: {sorted(valid)}")

    if interval == "time1hour":
        delta = timedelta(hours=1)
    elif interval == "time5minutes":
        delta = timedelta(minutes=5)
    else:  # time1day
        delta = timedelta(days=1)

    return [
        (dt + delta * (i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(periods)
    ]


def forecast_linear(
    timestamps: list[str],
    values: list[float],
    periods: int,
    interval: str,
    metric: str,
) -> ForecastResult:
    """
    OLS linear regression forecast.
    Fits y = mx + b on historical data and extrapolates forward.
    """
    n = len(values)
    x = np.arange(n, dtype=float)
    y = np.array(values, dtype=float)

    coeffs = np.polyfit(x, y, 1)  # [slope, intercept]
    poly = np.poly1d(coeffs)

    future_x = np.arange(n, n + periods, dtype=float)
    forecast_vals = [max(0.0, float(v)) for v in poly(future_x)]  # clamp to >=0

    iso_timestamps = [_ts_to_iso(t) for t in timestamps]
    future_ts = _generate_future_timestamps(timestamps[-1], interval, periods)
    avg_hist = float(np.mean(y))
    avg_fc = float(np.mean(forecast_vals)) if forecast_vals else 0.0
    pct = ((avg_fc - avg_hist) / avg_hist * 100) if avg_hist != 0 else 0.0

    return ForecastResult(
        historical_timestamps=iso_timestamps,
        historical_values=values,
        forecast_timestamps=future_ts,
        forecast_values=forecast_vals,
        method="linear",
        metric=metric,
        trend=_detect_trend(values),
        avg_historical=round(avg_hist, 2),
        avg_forecast=round(avg_fc, 2),
        pct_change=round(pct, 2),
    )


def forecast_ema(
    timestamps: list[str],
    values: list[float],
    periods: int,
    interval: str,
    metric: str,
    alpha: float = 0.3,
) -> ForecastResult:
    """
    Exponential Moving Average forecast.
    Uses the EMA of the last data points and projects it forward,
    incorporating recent trend.
    """
    n = len(values)
    y = np.array(values, dtype=float)

    # Compute EMA series
    ema = np.zeros(n)
    ema[0] = y[0]
    for i in range(1, n):
        ema[i] = alpha * y[i] + (1 - alpha) * ema[i - 1]

    # Recent trend: average of last 3 diffs (or fewer if series is short)
    lookback = min(3, n - 1)
    if lookback > 0:
        recent_diffs = [ema[n - i] - ema[n - i - 1] for i in range(1, lookback + 1)]
        avg_diff = float(np.mean(recent_diffs))
    else:
        avg_diff = 0.0

    # Project forward: EMA + trend * steps
    last_ema = float(ema[-1])
    forecast_vals = [max(0.0, last_ema + avg_diff * (i + 1)) for i in range(periods)]

    iso_timestamps = [_ts_to_iso(t) for t in timestamps]
    future_ts = _generate_future_timestamps(timestamps[-1], interval, periods)
    avg_hist = float(np.mean(y))
    avg_fc = float(np.mean(forecast_vals)) if forecast_vals else 0.0
    pct = ((avg_fc - avg_hist) / avg_hist * 100) if avg_hist != 0 else 0.0

    return ForecastResult(
        historical_timestamps=iso_timestamps,
        historical_values=values,
        forecast_timestamps=future_ts,
        forecast_values=forecast_vals,
        method="ema",
        metric=metric,
        trend=_detect_trend(values),
        avg_historical=round(avg_hist, 2),
        avg_forecast=round(avg_fc, 2),
        pct_change=round(pct, 2),
    )


def run_forecast(
    timestamps: list[str],
    values: list[float],
    periods: int,
    interval: str,
    metric: str,
    method: str = "linear",
    alpha: float = 0.3,
) -> dict:
    """
    Run forecast and return a serialisable dict.

    Args:
        timestamps: ordered list of ISO-8601 timestamps from the historical data
        values:     corresponding metric values
        periods:    number of future data points to forecast
        interval:   time granularity — "time1day", "time1hour", or "time5minutes"
        metric:     metric name (for labelling)
        method:     "linear" or "ema"
        alpha:      EMA smoothing factor 0 < alpha <= 1 (only used when method="ema", default 0.3)

    Returns:
        Dict with historical, forecast, summary, and trend info.
    """
    if len(timestamps) < 3:
        return {"error": "Need at least 3 historical data points for forecasting."}

    if method == "ema":
        if not (0 < alpha <= 1):
            raise ValueError(f"alpha must be between 0 (exclusive) and 1 (inclusive), got {alpha}")
        result = forecast_ema(timestamps, values, periods, interval, metric, alpha=alpha)
    else:
        result = forecast_linear(timestamps, values, periods, interval, metric)

    return {
        "metric": result.metric,
        "method": result.method,
        "trend": result.trend,
        "summary": {
            "historical_avg": result.avg_historical,
            "forecast_avg": result.avg_forecast,
            "pct_change": result.pct_change,
        },
        "historical": [
            {"timestamp": t, "value": v}
            for t, v in zip(result.historical_timestamps, result.historical_values)
        ],
        "forecast": [
            {"timestamp": t, "value": round(v, 2)}
            for t, v in zip(result.forecast_timestamps, result.forecast_values)
        ],
    }
