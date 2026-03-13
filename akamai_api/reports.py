from datetime import datetime, timedelta, timezone

DEFAULT_DAYS = 15


def default_start() -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def default_end() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cpcode_filter(cpcodes: list[int]) -> dict:
    return {
        "dimensionName": "cpcode",
        "operator": "IN_LIST",
        "expressions": cpcodes,
    }


def _hostname_filter(hostnames: list[str]) -> dict:
    return {
        "dimensionName": "hostname",
        "operator": "IN_LIST",
        "expressions": hostnames,
    }


def build_hostname_traffic_body(
    cpcodes: list[int] | None = None,
    hostnames: list[str] | None = None,
) -> dict:
    """
    Traffic by hostname: edge/origin bytes and hits grouped by hostname.
    Metrics: edgeBytesSum, edgeHitsSum, originBytesSum, originHitsSum, midgressBytesSum
    """
    filters = []
    if cpcodes:
        filters.append(_cpcode_filter(cpcodes))
    if hostnames:
        filters.append(_hostname_filter(hostnames))

    body: dict = {
        "dimensions": ["hostname"],
        "metrics": [
            "edgeBytesSum",
            "edgeHitsSum",
            "originBytesSum",
            "originHitsSum",
            "midgressBytesSum",
        ],
    }
    if filters:
        body["filters"] = filters
    return body


def build_cpcode_traffic_body(cpcodes: list[int] | None = None) -> dict:
    """
    Traffic by CP code: bytes, midgress, and offload percentage grouped by cpcode.
    Metrics: edgeBytesSum, originBytesSum, midgressBytesSum, offloadedBytesPercentage
    """
    body: dict = {
        "dimensions": ["cpcode"],
        "metrics": [
            "edgeBytesSum",
            "originBytesSum",
            "midgressBytesSum",
            "offloadedBytesPercentage",
        ],
    }
    if cpcodes:
        body["filters"] = [_cpcode_filter(cpcodes)]
    return body


def build_http_status_body(cpcodes: list[int] | None = None) -> dict:
    """
    HTTP status breakdown: edge hits by responseClass across all classes (2xx, 3xx, 4xx, 5xx).
    Metrics: edgeHitsSum, originHitsSum
    """
    filters: list[dict] = []
    if cpcodes:
        filters.append(_cpcode_filter(cpcodes))

    body: dict = {
        "dimensions": ["responseClass"],
        "metrics": ["edgeHitsSum", "originHitsSum"],
    }
    if filters:
        body["filters"] = filters
    return body


def build_offload_body(cpcodes: list[int] | None = None) -> dict:
    """
    Edge/origin offload by CP code: cache offload percentage and raw bytes.
    Metrics: offloadedBytesPercentage, offloadedHitsPercentage, edgeBytesSum, originBytesSum
    """
    body: dict = {
        "dimensions": ["cpcode"],
        "metrics": [
            "offloadedBytesPercentage",
            "offloadedHitsPercentage",
            "edgeBytesSum",
            "originBytesSum",
        ],
    }
    if cpcodes:
        body["filters"] = [_cpcode_filter(cpcodes)]
    return body
