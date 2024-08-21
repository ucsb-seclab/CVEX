from pathlib import Path

INFRASTRUCTURE_FILE = "infrastructure.yml"

CVEX_ROOT = Path.home() / ".cvex"

ROUTER_VM = "router"
ROUTER_DESTINATION = f"{CVEX_ROOT}/{ROUTER_VM}"
ROUTER_CONFIG = {
    "image": "bento/ubuntu-22.04",
    "version": "202404.23.0",
    "type": "linux"
}

INIT_SNAPSHOT = "clean"

CVEX_TEMP_FOLDER_LINUX = "/tmp/cvex"
MITMDUMP_LOG = "router_mitmdump.stream"
MITMDUMP_LOG_PATH = f"{CVEX_TEMP_FOLDER_LINUX}/{MITMDUMP_LOG}"
DEFAULT_MITMDUM_PORT = 443
TCPDUMP_LOG = "router_raw.pcap"
TCPDUMP_LOG_PATH = f"{CVEX_TEMP_FOLDER_LINUX}/{TCPDUMP_LOG}"

CVEX_TEMP_FOLDER_WINDOWS = r"C:\cvex"
PROCMON_PML_LOG = "procmon.pml"
PROCMON_PML_LOG_PATH = rf"{CVEX_TEMP_FOLDER_WINDOWS}\{PROCMON_PML_LOG}"
PROCMON_XML_LOG = "procmon.xml"
PROCMON_XML_LOG_PATH = rf"{CVEX_TEMP_FOLDER_WINDOWS}\{PROCMON_XML_LOG}"
