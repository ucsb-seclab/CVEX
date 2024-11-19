import logging
import os
import shutil
import subprocess
import sys
import vagrant
import re
import uuid

from cvex.consts import *
from cvex.logger import get_logger
from cvex.ssh import SSH


class VMTemplate:
    VM_TYPE_UBUNTU = "ubuntu"
    VM_TYPE_DEBIAN = "debian"
    VM_TYPE_WINDOWS = "windows"
    VM_TYPE_UNKNOWN = "unknown"

    log: logging.Logger
    vm_name: str
    image: str
    version: str
    vm_type: str
    trace: str | None
    playbooks: list[Path]
    command: list[str]

    def __init__(self,
                 vm_name: str,
                 image: str,
                 version: str,
                 vm_type: str,
                 trace: str | None = None,
                 playbooks: list[Path] = [],
                 command: list[str] = []):
        self.log = get_logger(vm_name)
        self.vm_name = vm_name
        self.image = image
        self.version = version
        if vm_type != self.VM_TYPE_UBUNTU and vm_type != self.VM_TYPE_DEBIAN and vm_type != self.VM_TYPE_WINDOWS:
            self.log.critical("Unknown VM type: %r", vm_type)
            sys.exit(1)
        self.vm_type = vm_type
        if self.is_linux() and trace:
            try:
                re.compile(trace)
            except:
                self.log.critical("Regular expression '%s' is not correct", trace)
                sys.exit(1)
        self.trace = trace
        for playbook in playbooks:
            if not playbook.exists():
                self.log.critical("%r does not exist", playbook)
                sys.exit(1)
        self.playbooks = playbooks
        self.command = command

    def is_linux(self):
        return self.vm_type == self.VM_TYPE_UBUNTU or self.vm_type == self.VM_TYPE_DEBIAN


current_ip = 2

class VM:
    log: logging.Logger
    vm_name: str
    image: str
    version: str
    vm_type: str
    trace: str | None
    playbooks: list[Path]
    command: list[str]
    cve: str
    destination: Path
    vag: vagrant.Vagrant
    files: dict
    ip: str
    ssh: SSH
    keep: bool
    new: bool
    created: bool

    def _get_vm_destination(self, vms: list) -> Path:
        path = Path(CVEX_ROOT, self.image.replace("/", "_"), self.version)
        if not path.exists():
            destination = Path(path, "1")
            self.log.info("Taking %s", destination)
            return destination
        instances = [f.name for f in os.scandir(path) if f.is_dir()]
        if not instances:
            destination = Path(path, "1")
            self.log.info("Taking %s", destination)
            return destination
        free_instances = instances
        max_instance = 1
        for instance in instances:
            instance_path = Path(path, instance)
            if int(instance) > max_instance:
                max_instance = int(instance)
            for vm in vms:
                if vm.destination == instance_path:
                    free_instances.remove(instance)
        if free_instances:
            snapshot = f"{self.cve}/{self.vm_name}"
            self.log.info("Looking for a VM with '%s' snapshot...", snapshot)
            for instance in free_instances:
                destination = Path(path, instance)
                if Path(destination, "Vagrantfile").exists():
                    vag = vagrant.Vagrant(destination)
                    snapshots = vag.snapshot_list()
                    if snapshot in snapshots:
                        self.log.info("Found %s", destination)
                        return destination
            destination = Path(path, free_instances[0])
            self.log.info("Taking %s", destination)
            return destination
        else:
            destination = Path(path, str(max_instance + 1))
            self.log.info("Taking %s", destination)
            return destination

    def __init__(self,
                 vms: list,
                 template: VMTemplate,
                 cve: str,
                 destination: Path | None = None,
                 keep: bool = False,
                 new: bool = False):
        self.log = get_logger(template.vm_name)
        self.vm_name = template.vm_name
        self.image = template.image
        self.version = template.version
        self.vm_type = template.vm_type
        self.trace = template.trace
        self.playbooks = template.playbooks
        self.command = template.command
        self.cve = cve
        global current_ip
        self.ip = f"192.168.56.{current_ip}"
        current_ip += 1
        if destination:
            self.destination = destination
        else:
            self.destination = self._get_vm_destination(vms)
        os.makedirs(self.destination, exist_ok=True)
        if Path(self.destination, "Vagrantfile").exists():
            self.created = True
        else:
            self.created = False
        self.vagrant_log = f"/tmp/vagrant_{str(uuid.uuid4())}.log"
        log_cm = vagrant.make_file_cm(self.vagrant_log, "w")
        self.vag = vagrant.Vagrant(self.destination, out_cm=log_cm, err_cm=log_cm)
        self.keep = keep
        self.new = new

    def __del__(self):
        try:
            os.remove(self.vagrant_log)
        except:
            pass

    def is_created(self) -> bool:
        return self.created

    def _get_vagrant_log(self) -> str:
        with open(self.vagrant_log, "r") as f:
            return f.read()
        
    def _print_vagrant_log(self, log_level: int):
        log = self._get_vagrant_log()
        if log:
            if log_level == logging.INFO:
                self.log.info("%s", log)
            elif log_level == logging.CRITICAL:
                self.log.critical("%s", log)
            else:
                self.log.debug("%s", log)

    def _configure_vagrantfile(self):
        vagrantfile = os.path.join(self.destination, "Vagrantfile")
        if not os.path.exists(vagrantfile):
            self.log.critical("Can't find Vagrantfile %s", vagrantfile)
            sys.exit(1)
        with open(vagrantfile, "r") as f:
            data = f.read()
        config = f"  config.vm.box = \"{self.image}\""
        pos = data.find(config)
        if pos == -1:
            self.log.critical("Bad Vagrantfile %s", vagrantfile)
            sys.exit(1)
        with open(vagrantfile, "w") as f:
            f.write(data[:pos + len(config)])
            f.write((f"\n"
                     f"  config.vm.box_version = \"{self.version}\"\n"
                     f"  config.vm.hostname = \"{self.vm_name}\"\n"
                     f"  config.vm.network \"private_network\", ip: \"{self.ip}\"\n"
                     f"\n"
                     ))
            f.write(data[pos + len(config):])

    def _run_shell_command(self, command: list[str], cwd: str | None = None, show_progress: bool = False) -> bytes:
        output = b""
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd)
        for line in iter(p.stdout.readline, b''):
            if show_progress:
                self.log.info(line.decode().rstrip())
            else:
                self.log.debug(line.decode().rstrip())
            output += line.rstrip()
        return output

    def _provision_vm(self, router = None):
        self.init(router)
        if self.playbooks:
            inventory = self.get_ansible_inventory()
            self.log.info("Inventory %s has been created", inventory)
            for playbook in self.playbooks:
                self.log.info("Executing Ansible playbook %s...", playbook)
                result = self._run_shell_command(["ansible-playbook", "-i", inventory, playbook], show_progress=True)
                if b"unreachable=0" not in result or b"failed=0" not in result:
                    sys.exit(1)

    def _init_vm(self):
        self.log.info("Initializing a new VM at %s...", self.destination)
        try:
            self.vag.init(box_url=self.image)
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)
        self._configure_vagrantfile()

    def _get_snapshot_name(self):
        if self.cve:
            return f"{self.cve}/{self.vm_name}"
        else:
            return self.vm_name

    def _start_vm(self, router = None):
        self.log.info("Starting VM...")
        try:
            self.vag.up()
            self.created = True
            self._print_vagrant_log(logging.DEBUG)
        except:
            up_log = self._get_vagrant_log()
            if "VERR_VMX_NO_VMX" in up_log:
                self.log.critical("VT-x is not available. Enable nested virtualization.")
                sys.exit(1)
            if "Timed out" in up_log:
                self.log.critical(
                    "Timed out. Please wait until the VM is started and then re-start CVEX with the '-k' parameter.")
                sys.exit(1)
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)

        self.log.info("Creating snapshot '%s'...", INIT_SNAPSHOT)
        try:
            self.vag.snapshot_save(INIT_SNAPSHOT)
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)

        self.ssh = SSH(self.vag, self.vm_name)
        self._provision_vm(router)

        snapshot = self._get_snapshot_name()
        self.log.info("Creating snapshot '%s'...", snapshot)
        try:
            self.vag.snapshot_save(snapshot)
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)

    def _restore_snapshot(self, snapshot: str):
        self.log.info("Restoring to snapshot '%s'...", snapshot)
        try:
            self.vag.snapshot_restore(snapshot)
            self._print_vagrant_log(logging.DEBUG)
        except:
            restore_log = self._get_vagrant_log()
            if "VERR_VMX_NO_VMX" in restore_log:
                self.log.critical("VT-x is not available. Enable nested virtualization.")
                sys.exit(1)
            if "Vagrant cannot forward" in restore_log:
                try:
                    self.vag.reload()
                    self._print_vagrant_log(logging.DEBUG)
                    return
                except:
                    pass
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)

    def run(self, router = None):
        self.log.info("IP: %s", self.ip)
        if not Path(self.destination, "Vagrantfile").exists():
            self._init_vm()
            self._start_vm(router)
            return

        self.log.info("Retrieving status...")
        try:
            status = self.vag.status()
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)
        snapshot = self._get_snapshot_name()

        if status[0].state == "not_created":
            shutil.rmtree(self.destination)
            os.makedirs(self.destination)
            self._init_vm()
            self._start_vm(router)
        elif self.keep and status[0].state == "running":
            self.log.info("VM is already running")
            self.ssh = SSH(self.vag, self.vm_name)

            self.log.info("Retrieving snapshot list...")
            try:
                snapshots = self.vag.snapshot_list()
                self._print_vagrant_log(logging.DEBUG)
            except:
                self._print_vagrant_log(logging.CRITICAL)
                sys.exit(1)

            if INIT_SNAPSHOT not in snapshots:
                self.log.info("Creating snapshot '%s'...", INIT_SNAPSHOT)
                try:
                    self.vag.snapshot_save(INIT_SNAPSHOT)
                    self._print_vagrant_log(logging.DEBUG)
                except:
                    self._print_vagrant_log(logging.CRITICAL)
                    sys.exit(1)

            if snapshot not in snapshots:
                self._provision_vm(router)
                self.log.info("Creating snapshot '%s'...", snapshot)
                try:
                    self.vag.snapshot_save(snapshot)
                    self._print_vagrant_log(logging.DEBUG)
                except:
                    self._print_vagrant_log(logging.CRITICAL)
                    sys.exit(1)
        else:
            self.log.info("Retrieving snapshot list...")
            try:
                snapshots = self.vag.snapshot_list()
                self._print_vagrant_log(logging.DEBUG)
            except:
                self._print_vagrant_log(logging.CRITICAL)
                sys.exit(1)

            if snapshot in snapshots and not self.new:
                self._restore_snapshot(snapshot)
                self.ssh = SSH(self.vag, self.vm_name)
            elif INIT_SNAPSHOT in snapshots:
                self._restore_snapshot(INIT_SNAPSHOT)

                # Always delete the snapshot after reverting to INIT_SNAPSHOT,
                # otherwise deleting may take too much time
                if self.new:
                    self.log.info("Deleting snapshot '%s'...", snapshot)
                    try:
                        self.vag.snapshot_delete(snapshot)
                        self._print_vagrant_log(logging.DEBUG)
                    except:
                        self._print_vagrant_log(logging.CRITICAL)
                        sys.exit(1)

                self.ssh = SSH(self.vag, self.vm_name)
                self._provision_vm(router)

                self.log.info("Creating snapshot '%s'...", snapshot)
                try:
                    self.vag.snapshot_save(snapshot)
                    self._print_vagrant_log(logging.DEBUG)
                except:
                    self._print_vagrant_log(logging.CRITICAL)
                    sys.exit(1)
            else:
                self._start_vm(router)

    def destroy(self):
        if not self.exists():
            self.log.error("VM does not exist")
            return
        self.log.info("Destroying VM...")
        try:
            self.vag.destroy()
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)
        try:
            shutil.rmtree(self.destination)
        except:
            pass

    def stop(self):
        if not self.exists():
            self.log.error("VM does not exist")
            return
        self.log.info("Stopping VM...")
        try:
            self.vag.halt()
            self._print_vagrant_log(logging.DEBUG)
        except:
            self._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)

    def exists(self):
        return Path(self.destination, "Vagrantfile").exists()
