import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from akamai.edgegrid import EdgeRc
from dotenv import load_dotenv

load_dotenv()

EDGERC_PATH: str = os.getenv("EDGERC_PATH", str(Path.home() / ".edgerc"))
EDGERC_SECTION: str = os.getenv("EDGERC_SECTION", "default")
SERVER_HOST: str = os.getenv("MCP_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("MCP_PORT", "8000"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


@dataclass
class AccountConfig:
    section: str
    hostname: str
    base_url: str
    reporting_base_url: str


def get_edgerc_section() -> str:
    return EDGERC_SECTION


def get_base_hostname() -> str:
    edgerc = EdgeRc(EDGERC_PATH)
    return edgerc.get(EDGERC_SECTION, "host")


def get_account_config() -> AccountConfig:
    hostname = get_base_hostname()
    return AccountConfig(
        section=EDGERC_SECTION,
        hostname=hostname,
        base_url=f"https://{hostname}",
        reporting_base_url=f"https://{hostname}/reporting-api/v2",
    )


def list_edgerc_sections(edgerc_path: str = EDGERC_PATH) -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(edgerc_path)
    return list(parser.sections())
