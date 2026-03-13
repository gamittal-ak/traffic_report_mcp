import threading
from typing import Optional

import requests
from akamai.edgegrid import EdgeGridAuth, EdgeRc

from config import EDGERC_PATH, EDGERC_SECTION, get_account_config

_client_instance: Optional["AkamaiClient"] = None
_lock = threading.Lock()


def get_client() -> "AkamaiClient":
    global _client_instance
    with _lock:
        if _client_instance is None:
            _client_instance = AkamaiClient()
    return _client_instance


HEADERS = {"Content-type": "application/json"}


class AkamaiClient:
    def __init__(self):
        edgerc = EdgeRc(EDGERC_PATH)
        self.config = get_account_config()
        self.session = requests.Session()
        self.session.auth = EdgeGridAuth.from_edgerc(edgerc, EDGERC_SECTION)
        self.session.headers.update(HEADERS)

    def list_account_switch_keys(self, search: str) -> list[dict]:
        """
        GET /identity-management/v3/api-clients/self/account-switch-keys
        search is required (min 3 chars). Returns list of {accountSwitchKey, accountName, accountId}.
        """
        url = f"{self.config.base_url}/identity-management/v3/api-clients/self/account-switch-keys"
        resp = self.session.get(url, params={"search": search})
        resp.raise_for_status()
        return resp.json()

    def get_cpcodes(
        self,
        account_switch_key: str = "",
        contract_id: str = "",
        group_id: str = "",
    ) -> dict:
        """
        GET /papi/v1/cpcodes
        Returns CP codes accessible to the credential. contractId and groupId are optional filters.
        """
        url = f"{self.config.base_url}/papi/v1/cpcodes"
        params: dict = {}
        if account_switch_key:
            params["accountSwitchKey"] = account_switch_key
        if contract_id:
            params["contractId"] = contract_id
        if group_id:
            params["groupId"] = group_id
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def fetch_traffic(
        self,
        body: dict,
        start: str,
        end: str,
        account_switch_key: str = "",
    ) -> dict:
        """
        POST /reporting-api/v2/reports/delivery/traffic/current/data
        Returns traffic data for the given dimensions/metrics/filters and time range.
        """
        url = f"{self.config.reporting_base_url}/reports/delivery/traffic/current/data"
        params: dict = {"start": start, "end": end}
        if account_switch_key:
            params["accountSwitchKey"] = account_switch_key
        resp = self.session.post(url, json=body, params=params)
        resp.raise_for_status()
        return resp.json()
