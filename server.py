"""
AkamaiTrafficMCP — FastMCP server exposing Akamai Reporting API v2 as MCP tools.

Typical workflow for an LLM:
  1. list_accounts()               → pick accountSwitchKey + accountName
  2. get_traffic_by_hostname(...)  → analyse by hostname
  3. get_traffic_by_cpcode(...)    → analyse by CP code
  4. get_http_status_breakdown(...)→ check error rates
  5. get_edge_origin_offload(...)  → check cache efficiency
  6. predict_traffic(...)          → forecast future traffic based on historical trends
  7. export_traffic_report(...)    → ONLY if user explicitly asks for an Excel file
"""
import logging
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

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
        "Start with list_accounts() to discover available accounts and their switch keys."
    ),
)


# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────

def _resolve_time(start: str, end: str) -> tuple[str, str]:
    return (start or default_start(), end or default_end())


def _extract_rows(response: dict) -> list[dict]:
    """Flatten Akamai v2 response into a list of flat dicts."""
    data = response.get("data", [])
    if not data:
        return []
    # v2 returns {"columns": [...], "rows": [[v1, v2, ...]]}  OR  list of dicts
    if isinstance(data, list) and isinstance(data[0], dict):
        return data
    columns = response.get("columns", [])
    return [dict(zip(columns, row)) for row in data]


# ─────────────────────────────────────────────────────────────
# Tool 1 — Account discovery
# ─────────────────────────────────────────────────────────────

@mcp.tool
def list_accounts(
    search: Annotated[str, "Optional search string to filter accounts by name"] = "",
) -> list[dict]:
    """
    List all Akamai accounts accessible with the current API credentials.

    Returns a list of objects with:
      - accountSwitchKey: pass this value as account_switch_key in other tools
      - accountName: human-readable account label
      - accountId: numeric Akamai account identifier

    Always call this first to discover available accounts.
    """
    try:
        return get_client().list_account_switch_keys(search=search)
    except Exception as exc:
        raise ToolError(f"Failed to list accounts: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 2 — Traffic by hostname
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_traffic_by_hostname(
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start, e.g. 2025-02-01T00:00:00Z (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    hostname: Annotated[list[str] | None, "Filter to specific hostname strings; None returns all"] = None,
) -> dict:
    """
    Get edge and origin traffic broken down by hostname.

    Returns edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum, midgressBytesSum
    per hostname for the specified account and time range.

    Useful for identifying which properties drive the most traffic.
    """
    s, e = _resolve_time(start, end)
    body = build_hostname_traffic_body(cpcode, hostname)
    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch hostname traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 3 — Traffic by CP code
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_traffic_by_cpcode(
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get traffic grouped by CP code showing bytes delivered, origin bytes, midgress bytes,
    and bytes offload percentage.

    offloadedBytesPercentage: percentage of bytes served from Akamai edge (higher = better caching).
    """
    s, e = _resolve_time(start, end)
    body = build_cpcode_traffic_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch CP code traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 4 — HTTP status breakdown
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_http_status_breakdown(
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get 4xx and 5xx HTTP error hit counts broken down by response class (4xx / 5xx).

    Useful for spotting error rate spikes and diagnosing origin health issues.
    Returns edgeHitsSum and originHitsSum for each error class.
    """
    s, e = _resolve_time(start, end)
    body = build_http_status_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch HTTP status breakdown: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 5 — Edge/origin offload
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_edge_origin_offload(
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Get cache offload percentages by CP code.

    offloadedBytesPercentage and offloadedHitsPercentage show how much traffic
    was served from Akamai edge versus pulled from origin. Higher values indicate
    better cache performance and lower origin load.
    """
    s, e = _resolve_time(start, end)
    body = build_offload_body(cpcode)
    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch offload data: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 6 — Raw / flexible query
# ─────────────────────────────────────────────────────────────

@mcp.tool
def get_raw_traffic(
    dimensions: Annotated[list[str], "Dimensions to group by, e.g. ['cpcode', 'hostname']. Max 4."],
    metrics: Annotated[list[str], "Metrics to retrieve, e.g. ['edgeBytesSum', 'offloadedBytesPercentage']"],
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    limit: Annotated[int, "Max rows to return (default 50000, max 250000)"] = 50000,
) -> dict:
    """
    Flexible raw query against /delivery/traffic/current with custom dimensions and metrics.

    Available dimensions: cpcode, hostname, responseCode, responseClass,
                          time5minutes, time1hour, time1day, httpMethod, deliveryType
    Available metrics:    edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum,
                          midgressBytesSum, midgressHitsSum,
                          offloadedBytesPercentage, offloadedHitsPercentage

    Use this for custom analysis not covered by the pre-built tools.
    """
    s, e = _resolve_time(start, end)
    body: dict = {
        "dimensions": dimensions,
        "metrics": metrics,
        "limit": limit,
    }
    if cpcode:
        body["filters"] = [
            {"dimensionName": "cpcode", "operator": "IN_LIST", "expressions": cpcode}
        ]
    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
        return {"rows": _extract_rows(raw), "start": s, "end": e}
    except Exception as exc:
        raise ToolError(f"Failed to fetch raw traffic: {exc}") from exc


# ─────────────────────────────────────────────────────────────
# Tool 7 — Timeseries prediction
# ─────────────────────────────────────────────────────────────

@mcp.tool
def predict_traffic(
    metric: Annotated[
        str,
        "Metric to forecast, e.g. 'edgeBytesSum', 'edgeHitsSum', 'originBytesSum', 'originHitsSum'"
    ],
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    start: Annotated[str, "ISO-8601 UTC start of historical window (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end of historical window (default: now)"] = "",
    forecast_periods: Annotated[int, "Number of future data points to predict (default: 7)"] = 7,
    granularity: Annotated[str, "Time granularity: 'time1day', 'time1hour', or 'time5minutes' (default: time1day)"] = "time1day",
    method: Annotated[str, "'linear' for linear regression or 'ema' for exponential moving average (default: linear)"] = "linear",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
) -> dict:
    """
    Forecast future traffic based on historical trends.

    Fetches historical timeseries data for the given metric, then applies
    either linear regression or exponential moving average to predict
    future values.

    Returns:
      - trend: "increasing", "decreasing", or "stable"
      - summary: historical avg, forecast avg, and pct_change
      - historical: list of {timestamp, value} data points
      - forecast: list of {timestamp, value} predicted data points

    Example: predict_traffic(metric="edgeBytesSum", forecast_periods=7)
    forecasts 7 days of edge bytes based on the last 15 days of history.
    """
    s, e = _resolve_time(start, end)

    body: dict = {
        "dimensions": [granularity],
        "metrics": [metric],
    }
    if cpcode:
        body["filters"] = [
            {"dimensionName": "cpcode", "operator": "IN_LIST", "expressions": cpcode}
        ]
    body["sortBys"] = [{"name": granularity, "sortOrder": "ASCENDING"}]

    try:
        raw = get_client().fetch_traffic(body, s, e, account_switch_key)
    except Exception as exc:
        raise ToolError(f"Failed to fetch historical data for prediction: {exc}") from exc

    rows = _extract_rows(raw)
    if len(rows) < 3:
        raise ToolError(
            f"Not enough data points for forecasting (got {len(rows)}, need at least 3). "
            "Try a wider time range or finer granularity."
        )

    timestamps = [row.get(granularity, "") for row in rows]
    values = [float(row.get(metric, 0)) for row in rows]

    try:
        result = run_forecast(timestamps, values, forecast_periods, granularity, metric, method)
    except Exception as exc:
        raise ToolError(f"Forecast computation failed: {exc}") from exc

    return result


# ─────────────────────────────────────────────────────────────
# Tool 8 — Excel export
# ─────────────────────────────────────────────────────────────

@mcp.tool
def export_traffic_report(
    account_switch_key: Annotated[str, "Account switch key from list_accounts(); leave empty for your own account"] = "",
    account_name: Annotated[str, "Human-readable account label for the report cover page"] = "Akamai Account",
    start: Annotated[str, "ISO-8601 UTC start (default: 15 days ago)"] = "",
    end: Annotated[str, "ISO-8601 UTC end (default: now)"] = "",
    cpcode: Annotated[list[int] | None, "Filter to specific CP code integers; None returns all"] = None,
    hostname: Annotated[list[str] | None, "Filter hostname traffic to these hostnames"] = None,
    output_path: Annotated[str, "Destination .xlsx file path"] = "akamai_traffic_report.xlsx",
) -> str:
    """
    Fetch all four traffic reports (hostname, CP code, HTTP status, offload) and export
    them to a professional multi-sheet Excel (.xlsx) file.

    IMPORTANT: Only call this tool when the user explicitly asks to export or save to Excel.
    Do not call automatically after every query — ask the user first.

    Returns the absolute path of the saved file.
    """
    s, e = _resolve_time(start, end)
    client = get_client()

    try:
        hostname_raw = client.fetch_traffic(
            build_hostname_traffic_body(cpcode, hostname), s, e, account_switch_key
        )
        cpcode_raw = client.fetch_traffic(
            build_cpcode_traffic_body(cpcode), s, e, account_switch_key
        )
        status_raw = client.fetch_traffic(
            build_http_status_body(cpcode), s, e, account_switch_key
        )
        offload_raw = client.fetch_traffic(
            build_offload_body(cpcode), s, e, account_switch_key
        )
    except Exception as exc:
        raise ToolError(f"Failed to fetch data for export: {exc}") from exc

    results = {
        "By Hostname": _extract_rows(hostname_raw),
        "By CP Code": _extract_rows(cpcode_raw),
        "HTTP Status": _extract_rows(status_raw),
        "Offload": _extract_rows(offload_raw),
    }

    try:
        path = write_traffic_report(results, output_path, account_name, s, e)
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
    )
