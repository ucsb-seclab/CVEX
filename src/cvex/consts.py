from pathlib import Path

CVEX_ROOT = Path.home() / ".cvex"

DEFAULT_PORT = 443

CVEX_FILE = "cvex.yml"

ROUTER_VM_NAME = "router"
ROUTER_VM_DESTINATION = CVEX_ROOT / ROUTER_VM_NAME
ROUTER_VM_IMAGE = "cvex/ubuntu-22.04"
ROUTER_VM_VERSION = "0.0.1"

INIT_SNAPSHOT = "clean"

CVEX_TEMP_FOLDER_LINUX = "/tmp/cvex"
MITMDUMP_LOG = "router_mitmdump.stream"
MITMDUMP_LOG_PATH = f"{CVEX_TEMP_FOLDER_LINUX}/{MITMDUMP_LOG}"
TCPDUMP_LOG = "router_raw.pcap"
TCPDUMP_LOG_PATH = f"{CVEX_TEMP_FOLDER_LINUX}/{TCPDUMP_LOG}"

CVEX_TEMP_FOLDER_WINDOWS = r"C:\cvex"
PROCMON_PML_LOG = "procmon.pml"
PROCMON_XML_LOG = "procmon.xml"

COMMAND_NAME = "command"
COMMAND_EXT = "txt"

# In GB
# Size of ~/.vagrant.d/boxes/bento-VAGRANTSLASH-ubuntu-22.04
LINUX_VAGRANT_BOX_SIZE = 0.78
# Size of ~/.vagrant.d/boxes/gusztavvargadr-VAGRANTSLASH-windows-10
WINDOWS_VAGRANT_BOX_SIZE = 11.0
# Size of ~/VirtualBox VMs/router_default_xxxxxxxxxxxx_xxxxxx based off bento/ubuntu-22.04: VM + snapshot 'clean' + snapshot 'router'
ROUTER_VM_SIZE = 3.5
# Size of ~/VirtualBox VMs/x_default_xxxxxxxxxxxx_xxxxxx based off bento/ubuntu-22.04: VM + snapshot 'clean' + snapshot 'CVE-XXXX-XXXXX/xxxxx'
UBUNTU_VM_SIZE = 7.6
# Size of ~/VirtualBox VMs/x_default_xxxxxxxxxxxx_xxxxxx based off gusztavvargadr/windows-10: VM + snapshot 'clean' + snapshot 'CVE-XXXX-XXXXX/xxxxx'
WINDOWS_VM_SIZE = 25.2
REQUIRED_FREE_SPACE = 0.5
# In MB
LINUX_VM_RAM = 2048
WINDOWS_VM_RAM = 4096
REQUIRED_RAM = 2048