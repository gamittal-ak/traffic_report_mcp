"""
AkamaiTrafficMCP — FastMCP server exposing Akamai Reporting API v2 as MCP tools.

Switch keys and credentials are NEVER exposed to the LLM or user.

Typical workflow for an LLM:
  1. search_accounts(query)         → returns [{index, accountName}] — no keys
  2. select_account(index)          → resolves and stores switch key server-side
  3. get_traffic_by_hostname(...)   → uses stored key via account_name
  4. get_traffic_by_cpcode(...)     → uses stored key via account_name
  5. get_http_status_breakdown(...) → check error rates
  6. get_edge_origin_offload(...)   → check cache efficiency
  7. predict_traffic(...)           → forecast future traffic
  8. export_traffic_report(...)     → ONLY if user explicitly asks for Excel
"""
import logging
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

import account_store
from akamai_api.client import get_client
from akamai_api.reports import (
    build_cpcode_traffic_body,
    build_hostname_traffic_body,
    build_http_status_body,
    build_offload_body,
    default_end,
    default_start,
)
from config import LOG_LEVEL, SERVER_HOST, SERVER_PORT
from export import write_traffic_report
from forecast import run_forecast

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="AkamaiTrafficMCP",
    instructions=(
        "Tools for querying Akamai Reporting API v2. "
        "Start with search_accounts() to find an account, then select_account() to activate it. "
        "Switch keys and credentials are managed server-side and never shown to the user."
    ),
)


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _resolve_time(start: str, end: str) -> tuple[str, str]:
    return (start or default_start(), end or default_end())


def _resolve_switch_key(account_name: str) -> str:
    """
    Look up the switch key for account_name from the server-side store.
    Raises ToolError if the account hasn't been selected yet.
    """
    if not account_name:
        # No account specified — use the last active account if available
        active = account_store.get_active_account()
        if active:
            account_name = active
        else:
            raise ToolError(
                "No account selected. Call search_accounts() then select_account() first."
            )
    key = account_store.get_switch_key(account_name)
    if key is None:
        resolved = account_store.list_resolved_accounts()
        hint = f" Available: {resolved}" if resolved else " No accounts selected yet."
        raise ToolError(
            f"Account '{account_name}' not found in session.{hint} "
            "Call search_accounts() then select_account() first."
        )
    return key


def _extract_rows(response: dict) -> list[dict]:
    """Flatten Akamai v2 response into a list of flat dicts.

    The /reports/delivery/traffic/current/data endpoint returns:
      {"data": [{"dimensions": {"cpcode": "..."}, "metrics": {"edgeBytesSum": ...}}, ...]}
    Each row's dimensions and metrics are merged into a single flat dict.
    """
    data = response.get("data", [])
    if not data:
        return []
    first = data[0]
    if isinstance(first, dict) and ("dimensions" in first or "metrics" in first):
        return [{**row.get("dimensions", {}), **row.get("metrics", {})} for row in data]
    return data


# Metrics that are raw byte counts and should be converted to GB for readability
_BYTE_METRICS = {"edgeBytesSum", "originBytesSum", "midgressBytesSum"}
_BYTES_PER_GB = 1_073_741_824  # 2^30


def _convert_bytes_to_gb(rows: list[dict]) -> list[dict]:
    """Return a new list of rows with known byte metrics converted to GB (rounded to 3 dp)."""
    converted = []
    for row in rows:
        new_row = dict(row)
        for field in _BYTE_METRICS:
            if field in new_row and new_row[field] is not None:
                new_row[field] = round(new_row[field] / _BYTES_PER_GB, 3)
        converted.append(new_row)
    return converted


# ─────────────────────────────────────────────────────────────
# Tool 1 — Account search (returns names only, no switch keys)
# ─────────────────────────────────────────────────────────────

@mcp.tool
def search_accounts(
    query: Annotated[str, "Account name to search for (minimum 3 characters)"],
) -> dict:
    """
    Search for Akamai accounts by name. Returns a numbered list of matching
    account names — no switch keys or credentials are exposed.

    If multiple accounts match, the user must call select_account(index) to
    choose one. If only one account matches, call select_account(1) automatically.

    Minimum 3 characters required for the search query.
    """
    if len(query.strip()) < 3:
        raise ToolError("Search query must be at least 3 characters.")
    try:
        accounts = get_client().list_account_switch_keys(search=query)
    except Exception as exc:
        raise ToolError(f"Failed to search accounts: {exc}") from exc

    if not accounts:
        raise ToolError(f"No accounts found matching '{query}'. Try a different search term.")

    account_store.store_candidates(accounts)

    menu = [
        {"index": i + 1, "accountName": a["accountName"]}
        for i, a in enumerate(accounts)
    ]

    if len(menu) == 1:
        return {
            "accounts": menu,
            "message": f"Found 1 account. Call select_account(index=1) to activate it.",
        }

    return {
        "accounts": menu,
        "message": f"Found {len(menu)} accounts. Call select_account(index=N) to choose one.",
    }


# ─────────────────────────────────────────────────────────────
# Tool 2 — Select account (stores switch key server-side)
# ─────────────────────────────────────────────────────────────

@mcp.tool
def select_account(
    index: Annotated[int, "The index number shown by search_accounts()"],
) -> dict:
    """
    Activate an account by its index from the last search_accounts() result.
    The switch key is stored server-side and never shown to the user.

    After calling this, all traffic tools will use this account automatically.
    """
    try:
        name = account_store.resolve_candidate(index)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    return {
        "selected": name,
        "message": f"Account '{name}' is now active. You can now query traffic data.",
    }


# ─────────────────────────────────────────────────────────────
# Tool 3 — Traffic by hostname
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_traffic_by_hostname(
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start, e.g. 2025-02-01T00:00:00Z (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    hostname: Annotated[list[str] | None, "Filter to specific hostname strings; None returns all"] = None,
) -> dict:
    """
    Get edge and origin traffic broken down by hostname.

    Returns edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum, midgressBytesSum
    per hostname for the selected account and time range.
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    body = build_hostname_traffic_body(cpcode, hostname)
    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
        rows = _convert_bytes_to_gb(_extract_rows(raw))
        return {"rows": rows, "start": s, "end": e, "note": "edgeBytesSum, originBytesSum, midgressBytesSum are in GB"}
    except Exception as exc:
        raise ToolError(f"Failed to fetch hostname traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 4 — Traffic by CP code
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_traffic_by_cpcode(
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get traffic grouped by CP code showing bytes delivered, origin bytes, midgress bytes,
    and bytes offload percentage.

    offloadedBytesPercentage: percentage of bytes served from Akamai edge (higher = better caching).
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    body = build_cpcode_traffic_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
        rows = _convert_bytes_to_gb(_extract_rows(raw))
        return {"rows": rows, "start": s, "end": e, "note": "edgeBytesSum, originBytesSum, midgressBytesSum are in GB"}
    except Exception as exc:
        raise ToolError(f"Failed to fetch CP code traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 5 — HTTP status breakdown
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_http_status_breakdown(
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get HTTP hit counts broken down by response class (2xx, 3xx, 4xx, 5xx).

    Useful for understanding traffic composition, spotting error rate spikes,
    and diagnosing origin health issues.
    Returns edgeHitsSum and originHitsSum for each response class.
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    body = build_http_status_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch HTTP status breakdown: {exc}") from exc



# ─────────────────────────────────────────────────────────────
# Tool 6 — Edge/origin offload
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_edge_origin_offload(
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get cache offload percentages by CP code.

    offloadedBytesPercentage and offloadedHitsPercentage show how much traffic
    was served from Akamai edge versus pulled from origin. Higher values = better cache.
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    body = build_offload_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
        rows = _convert_bytes_to_gb(_extract_rows(raw))
        return {"rows": rows, "start": s, "end": e, "note": "edgeBytesSum, originBytesSum are in GB"}
    except Exception as exc:
        raise ToolError(f"Failed to fetch offload data: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 7 — Raw / flexible query
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_raw_traffic(
    dimensions: Annotated[list[str], "Dimensions to group by, e.g. ['cpcode', 'hostname']. Max 4."],
    metrics: Annotated[list[str], "Metrics to retrieve, e.g. ['edgeBytesSum', 'offloadedBytesPercentage']"],
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    limit: Annotated[int, "Max rows to return (default 50000, max 250000)"] = 50000,
) -> dict:
    """
    Flexible raw query with custom dimensions and metrics.

    Available dimensions: cpcode, hostname, responseCode, responseClass,
                          time5minutes, time1hour, time1day, httpMethod, deliveryType
    Available metrics:    edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum,
                          midgressBytesSum, midgressHitsSum,
                          offloadedBytesPercentage, offloadedHitsPercentage
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    body: dict = {"dimensions": dimensions, "metrics": metrics, "limit": limit}
    if cpcode:
        body["filters"] = [
            {"dimensionName": "cpcode", "operator": "IN_LIST", "expressions": cpcode}
        ]
    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
        byte_fields_requested = _BYTE_METRICS & set(metrics)
        rows = _convert_bytes_to_gb(_extract_rows(raw)) if byte_fields_requested else _extract_rows(raw)
        result: dict = {"rows": rows, "start": s, "end": e}
        if byte_fields_requested:
            result["note"] = f"{', '.join(sorted(byte_fields_requested))} are in GB"
        return result
    except Exception as exc:
        raise ToolError(f"Failed to fetch raw traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 8 — Timeseries prediction
# ─────────────────────────────────────────────────────────────

@mcp.tool
def predict_traffic(
    metric: Annotated[str, "Metric to forecast: edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum"],
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start of historical window (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end of historical window (default: today midnight UTC)"] = "",
    forecast_periods: Annotated[int, "Number of future data points to predict (default: 7)"] = 7,
    granularity: Annotated[str, "Time granularity: time1day, time1hour, or time5minutes (default: time1day)"] = "time1day",
    method: Annotated[str, "linear (OLS regression) or ema (exponential moving average) (default: linear)"] = "linear",
    alpha: Annotated[float, "EMA smoothing factor 0 < alpha <= 1 (only used when method=ema, default 0.3 — higher = more weight on recent data)"] = 0.3,
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    hostname: Annotated[list[str] | None, "Filter to specific hostnames, e.g. ['example.akamaized.net']; None returns all"] = None,
) -> dict:
    """
    Forecast future traffic based on historical trends.

    Returns trend (increasing/decreasing/stable), summary stats,
    historical data points, and forecasted data points.
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)

    body: dict = {"dimensions": [granularity], "metrics": [metric]}
    filters = []
    if cpcode:
        filters.append({"dimensionName": "cpcode", "operator": "IN_LIST", "expressions": cpcode})
    if hostname:
        filters.append({"dimensionName": "hostname", "operator": "IN_LIST", "expressions": hostname})
    if filters:
        body["filters"] = filters
    body["sortBys"] = [{"name": granularity, "sortOrder": "ASCENDING"}]

    try:
        raw = get_client().fetch_traffic(body, s, e, switch_key)
    except Exception as exc:
        raise ToolError(f"Failed to fetch historical data for prediction: {exc}") from exc

    rows = _extract_rows(raw)
    if len(rows) < 3:
        raise ToolError(
            f"Not enough data points for forecasting (got {len(rows)}, need at least 3). "
            "Try a wider time range or finer granularity."
        )

    timestamps = [row.get(granularity, "") for row in rows]
    raw_values = [float(row.get(metric, 0)) for row in rows]

    is_bytes_metric = metric in _BYTE_METRICS
    values = [v / _BYTES_PER_GB for v in raw_values] if is_bytes_metric else raw_values

    try:
        result = run_forecast(timestamps, values, forecast_periods, granularity, metric, method, alpha)
    except Exception as exc:
        raise ToolError(f"Forecast computation failed: {exc}") from exc

    if is_bytes_metric:
        result["note"] = f"{metric} values are in GB"
    return result


# ─────────────────────────────────────────────────────────────
# Tool 9 — Excel export
# ─────────────────────────────────────────────────────────────

@mcp.tool
def export_traffic_report(
    account_name: Annotated[str, "Account name from select_account(); leave empty to use the last selected account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: today midnight UTC)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    hostname: Annotated[list[str] | None, "Filter hostname traffic to these hostnames"] = None,
    output_path: Annotated[str, "Destination .xlsx file path"] = "akamai_traffic_report.xlsx",
) -> str:
    """
    Fetch all four traffic reports (hostname, CP code, HTTP status, offload) and export
    them to a professional multi-sheet Excel (.xlsx) file.

    IMPORTANT: Only call this when the user explicitly asks to export or save to Excel.

    Returns the absolute path of the saved file.
    """
    s, e = _resolve_time(start, end)
    switch_key = _resolve_switch_key(account_name)
    display_name = account_name or account_store.get_active_account() or "Akamai Account"
    client = get_client()

    try:
        hostname_raw = client.fetch_traffic(build_hostname_traffic_body(cpcode, hostname), s, e, switch_key)
        cpcode_raw   = client.fetch_traffic(build_cpcode_traffic_body(cpcode), s, e, switch_key)
        status_raw   = client.fetch_traffic(build_http_status_body(cpcode), s, e, switch_key)
        offload_raw  = client.fetch_traffic(build_offload_body(cpcode), s, e, switch_key)
    except Exception as exc:
        raise ToolError(f"Failed to fetch data for export: {exc}") from exc

    results = {
        "By Hostname": _extract_rows(hostname_raw),
        "By CP Code":  _extract_rows(cpcode_raw),
        "HTTP Status": _extract_rows(status_raw),
        "Offload":     _extract_rows(offload_raw),
    }

    try:
        path = write_traffic_report(results, output_path, display_name, s, e)
    except Exception as exc:
        raise ToolError(f"Failed to write Excel file: {exc}") from exc

    return f"Report saved to: {path}"


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting AkamaiTrafficMCP on %s:%s", SERVER_HOST, SERVER_PORT)
    mcp.run(
        transport="streamable-http",
        host=SERVER_HOST,
        port=SERVER_PORT,
        stateless_http=True,
    )
