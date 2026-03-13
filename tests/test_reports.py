"""Tests for akamai/reports.py — all pure functions, no mocking needed."""
import re
from datetime import datetime, timezone

import pytest

from akamai_api.reports import (
    DEFAULT_DAYS,
    build_cpcode_traffic_body,
    build_hostname_traffic_body,
    build_http_status_body,
    build_offload_body,
    default_end,
    default_start,
)


# ── Time helpers ─────────────────────────────────────────────

def test_default_start_format():
    s = default_start()
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s)


def test_default_end_format():
    e = default_end()
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", e)


def test_default_start_is_15_days_ago():
    s = datetime.strptime(default_start(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    e = datetime.strptime(default_end(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    diff_days = (e - s).total_seconds() / 86400
    assert abs(diff_days - DEFAULT_DAYS) < 1


# ── build_hostname_traffic_body ───────────────────────────────

def test_hostname_body_structure():
    body = build_hostname_traffic_body()
    assert body["dimensions"] == ["hostname"]
    assert "edgeBytesSum" in body["metrics"]
    assert "edgeHitsSum" in body["metrics"]
    assert "originBytesSum" in body["metrics"]


def test_hostname_body_no_filters_by_default():
    body = build_hostname_traffic_body()
    assert "filters" not in body


def test_hostname_body_cpcode_filter():
    body = build_hostname_traffic_body(cpcodes=[1234, 5678])
    assert "filters" in body
    cpcode_filter = next(f for f in body["filters"] if f["dimensionName"] == "cpcode")
    assert cpcode_filter["operator"] == "IN_LIST"
    assert 1234 in cpcode_filter["expressions"]


def test_hostname_body_hostname_filter():
    body = build_hostname_traffic_body(hostnames=["www.example.com"])
    assert "filters" in body
    host_filter = next(f for f in body["filters"] if f["dimensionName"] == "hostname")
    assert "www.example.com" in host_filter["expressions"]


# ── build_cpcode_traffic_body ─────────────────────────────────

def test_cpcode_body_structure():
    body = build_cpcode_traffic_body()
    assert body["dimensions"] == ["cpcode"]
    assert "offloadedBytesPercentage" in body["metrics"]
    assert "edgeBytesSum" in body["metrics"]


def test_cpcode_body_no_filter_when_none():
    body = build_cpcode_traffic_body(cpcodes=None)
    assert "filters" not in body


def test_cpcode_body_with_cpcodes():
    body = build_cpcode_traffic_body(cpcodes=[9999])
    assert "filters" in body
    assert body["filters"][0]["expressions"] == [9999]


# ── build_http_status_body ────────────────────────────────────

def test_http_status_body_has_response_class_filter():
    body = build_http_status_body()
    rc_filter = next(f for f in body["filters"] if f["dimensionName"] == "responseClass")
    assert "4xx" in rc_filter["expressions"]
    assert "5xx" in rc_filter["expressions"]


def test_http_status_body_dimensions():
    body = build_http_status_body()
    assert "responseClass" in body["dimensions"]


def test_http_status_body_cpcode_filter_added():
    body = build_http_status_body(cpcodes=[111])
    cpcode_filter = next(f for f in body["filters"] if f["dimensionName"] == "cpcode")
    assert 111 in cpcode_filter["expressions"]


# ── build_offload_body ────────────────────────────────────────

def test_offload_body_has_percentage_metrics():
    body = build_offload_body()
    assert "offloadedBytesPercentage" in body["metrics"]
    assert "offloadedHitsPercentage" in body["metrics"]


def test_offload_body_no_filter_when_none():
    body = build_offload_body(cpcodes=None)
    assert "filters" not in body


def test_offload_body_cpcode_filter():
    body = build_offload_body(cpcodes=[42])
    assert body["filters"][0]["expressions"] == [42]
