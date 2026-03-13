# Akamai Traffic MCP

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that exposes the **Akamai Reporting API v2** as tools an LLM can call directly — via [Claude Desktop](https://claude.ai/download), any MCP-compatible client, or your own agent.

Generate traffic reports by hostname or CP code, analyse HTTP error rates, measure cache offload, and forecast future traffic trends — all through natural language.

---

## Features

| Tool | What it does |
|---|---|
| `list_accounts` | Discover all Akamai accounts accessible with your credentials |
| `get_traffic_by_hostname` | Edge/origin bytes and hits grouped by hostname |
| `get_traffic_by_cpcode` | Bytes, midgress, and offload % grouped by CP code |
| `get_http_status_breakdown` | 4xx / 5xx error hit counts at edge and origin |
| `get_edge_origin_offload` | Cache offload percentage by CP code |
| `get_raw_traffic` | Flexible query with custom dimensions and metrics |
| `predict_traffic` | Timeseries forecast (linear regression or EMA) |
| `export_traffic_report` | Export all four reports to a multi-sheet Excel file |

**Key behaviours:**
- Default time window: **last 15 days** (adjustable per call)
- Multi-account support via `accountSwitchKey` — call `list_accounts()` first
- Forecasting requires no heavy ML dependencies — uses `numpy` only
- Credentials never leave your machine; all auth is via Akamai EdgeGrid

---

## Architecture

```
Claude Desktop / MCP client
        │  MCP (streamable-http)
        ▼
  server.py  (FastMCP)
        │
        ├── akamai_api/client.py    EdgeGrid auth + HTTP session
        ├── akamai_api/reports.py   Request body builders
        ├── forecast.py             Linear regression & EMA forecasting
        ├── export.py               Excel report writer (openpyxl)
        └── config.py               .edgerc + .env config loader
```

---

## Prerequisites

- Python 3.11+
- An Akamai `~/.edgerc` file with a `[default]` section (or the section name of your choice)
- API credentials with access to:
  - **Identity Management API v3** (for account switching)
  - **Reporting API v2** (for traffic data)

---

## Quick Start (local)

### 1. Clone and install

```bash
git clone https://github.com/gamittal-ak/traffic_report_mcp.git
cd traffic_report_mcp
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
EDGERC_PATH=/home/you/.edgerc   # path to your .edgerc file
EDGERC_SECTION=default           # section name inside .edgerc
MCP_HOST=0.0.0.0
MCP_PORT=8000
LOG_LEVEL=INFO
```

### 3. Start the server

```bash
python server.py
```

The MCP server is now available at `http://localhost:8000/mcp`.

---

## Connect to Claude Desktop

Edit your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "akamai-traffic": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8000/mcp",
        "--allow-http"
      ]
    }
  }
}
```

Restart Claude Desktop. The Akamai traffic tools will appear automatically.

---

## Example conversations

> *"Show me traffic for all my accounts over the last 7 days"*

> *"Which hostnames had the most edge hits in the past 15 days for account ACME Corp?"*

> *"What were my 5xx error rates last week for CP codes 12345 and 67890?"*

> *"Forecast my edge bytes for the next 7 days using exponential moving average"*

> *"Export a full traffic report to Excel for account XYZ"*

---

## Tool reference

### `list_accounts(search="")`
Returns all accounts accessible via your API credentials.
`search` filters by account name (optional).
**Always call this first** to get the `accountSwitchKey` needed by other tools.

```
→ [{accountSwitchKey, accountName, accountId}, ...]
```

---

### `get_traffic_by_hostname(...)`
Traffic broken down by hostname.

| Param | Default | Description |
|---|---|---|
| `account_switch_key` | `""` | From `list_accounts()` |
| `start` | 15 days ago | ISO-8601 UTC, e.g. `2025-02-01T00:00:00Z` |
| `end` | now | ISO-8601 UTC |
| `cpcode` | all | List of CP code integers to filter |
| `hostname` | all | List of hostname strings to filter |

Metrics returned: `edgeBytesSum`, `edgeHitsSum`, `originBytesSum`, `originHitsSum`, `midgressBytesSum`

---

### `get_traffic_by_cpcode(...)`
Traffic grouped by CP code with offload percentage.

Metrics returned: `edgeBytesSum`, `originBytesSum`, `midgressBytesSum`, `offloadedBytesPercentage`

---

### `get_http_status_breakdown(...)`
4xx and 5xx error hit counts at edge and origin.
Useful for spotting error spikes and diagnosing origin health issues.

---

### `get_edge_origin_offload(...)`
Cache offload percentage by CP code.
Higher `offloadedBytesPercentage` = more traffic served from Akamai edge = less load on your origin.

---

### `get_raw_traffic(dimensions, metrics, ...)`
Flexible raw query with custom dimensions and metrics.

**Available dimensions:** `cpcode`, `hostname`, `responseCode`, `responseClass`, `time5minutes`, `time1hour`, `time1day`, `httpMethod`, `deliveryType`

**Available metrics:** `edgeBytesSum`, `edgeHitsSum`, `originBytesSum`, `originHitsSum`, `midgressBytesSum`, `midgressHitsSum`, `offloadedBytesPercentage`, `offloadedHitsPercentage`

---

### `predict_traffic(metric, ...)`
Forecast future traffic values from historical data.

| Param | Default | Description |
|---|---|---|
| `metric` | required | e.g. `edgeBytesSum`, `edgeHitsSum` |
| `forecast_periods` | `7` | Number of future data points to predict |
| `granularity` | `time1day` | `time1day`, `time1hour`, or `time5minutes` |
| `method` | `linear` | `linear` (OLS regression) or `ema` (exponential moving average) |

Response includes:
- `trend` — `increasing`, `decreasing`, or `stable`
- `summary` — historical avg, forecast avg, % change
- `historical` — list of `{timestamp, value}` from the API
- `forecast` — list of `{timestamp, value}` predicted values

---

### `export_traffic_report(...)`
Fetches all four reports and saves them to a multi-sheet `.xlsx` file.
Only call this when the user explicitly asks to export to Excel.

---

## Deploying on Linode

See [`deploy/README_deploy.md`](deploy/README_deploy.md) for the complete step-by-step guide, including VM provisioning, systemd service setup, and firewall configuration.

**Quick summary:**

```bash
# On Linode
git clone https://github.com/gamittal-ak/traffic_report_mcp.git /opt/trafficMCP
cd /opt/trafficMCP
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Copy credentials from your local machine
scp ~/.edgerc deploy@<LINODE_IP>:/home/deploy/.edgerc

# Install and start the systemd service
sudo cp deploy/trafficmcp.service /etc/systemd/system/
sudo systemctl enable --now trafficmcp
```

Claude Desktop config for the remote server:

```json
{
  "mcpServers": {
    "akamai-traffic": {
      "command": "npx",
      "args": ["mcp-remote", "http://<LINODE_IP>:8000/mcp", "--allow-http"]
    }
  }
}
```

To update after a `git push`:

```bash
cd /opt/trafficMCP && git pull && sudo systemctl restart trafficmcp
```

---

## Project structure

```
traffic_report_mcp/
├── server.py                  # FastMCP server + all 8 tool definitions
├── config.py                  # .edgerc + .env config loader
├── forecast.py                # Timeseries forecasting (linear / EMA)
├── export.py                  # Excel report writer
├── requirements.txt
├── .env.example               # Environment variable template
├── akamai_api/
│   ├── __init__.py
│   ├── client.py              # EdgeGrid-authenticated HTTP client
│   └── reports.py             # Request body builders + default time helpers
├── deploy/
│   ├── README_deploy.md       # Full Linode deployment guide
│   └── trafficmcp.service     # systemd unit file
└── tests/
    ├── test_client.py
    ├── test_export.py
    └── test_reports.py
```

---

## Running tests

```bash
pytest tests/ -v
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastmcp` | MCP server framework |
| `edgegrid-python` | Akamai EdgeGrid authentication (`akamai.edgegrid`) |
| `python-dotenv` | `.env` file loading |
| `uvicorn` | ASGI server |
| `pydantic` | Data validation |
| `openpyxl` | Excel export |
| `numpy` | Timeseries forecasting |

---

## Security notes

- **Never commit `.edgerc` or `.env`** — both are in `.gitignore`
- When deploying on Linode, restrict port 8000 to your own IP via `ufw`
- Keep the GitHub repo **Private** if your CP codes or account names are sensitive

---

## License

MIT
