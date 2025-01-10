import argparse
import logging
import os
import shutil
import sys
import re

import yaml

from cvex.consts import *
from cvex.logger import get_logger, set_log_level
from cvex.vm import VM, VMTemplate
from cvex.windowsvm import WindowsVM
from cvex.linuxvm import LinuxVM
from cvex.routervm import RouterVM


class CVEX:
    log: logging.Logger
    vm_templates: list[VMTemplate]
    ports: list[int]

    def _check_for_lfs_files(self, dir: Path):
        for root, dirs, files in os.walk(dir):
            for fil in files:
                with open(Path(root, fil), "rb") as f:
                    if b"git-lfs.github.com" in f.readline(256):
                        self.log.critical("Git LFS files detected. Please install Git LFS and pull the files: sudo apt install git-lfs -y; git lfs pull")
                        sys.exit(1)

    def _read_cvex(self, cve_dir: Path):
        cvex_yml = Path(cve_dir, CVEX_FILE)
        if not cvex_yml.exists():
            self.log.critical("%s does not exist", cvex_yml)
            sys.exit(1)

        self._check_for_lfs_files(Path(cve_dir, "data"))

        try:
            with open(cvex_yml, "r") as f:
                cvex = yaml.safe_load(f)
        except:
            self.log.critical("%s is not a YAML file", cvex_yml)
            sys.exit(1)

        if 'blueprint' not in cvex:
            self.log.critical("%s: configuration mismatch", cvex_yml)
            sys.exit(1)

        blueprint_yml = Path(Path(__file__).parent.parent.parent, "blueprints", cvex['blueprint'], "blueprint.yml")
        if not blueprint_yml.exists():
            self.log.critical("Blueprint %s does not exist", cvex['blueprint'])
            sys.exit(1)
        try:
            with open(blueprint_yml, "r") as f:
                vm_templates = yaml.safe_load(f)
        except:
            self.log.critical("%s is not a YAML file", blueprint_yml.name)
            sys.exit(1)
        for vm_name in vm_templates:
            if vm_name not in cvex:
                self.log.critical("%s: configuration mismatch", cvex_yml)
                sys.exit(1)
        self.vm_templates = []
        for vm_name in cvex:
            if vm_name not in vm_templates:
                continue
            data = vm_templates[vm_name]
            if 'image' not in data or 'version' not in data or 'type' not in data:
                self.log.critical("%s: configuration mismatch", blueprint_yml)
                sys.exit(1)
            playbooks = []
            if 'playbook' in data:
                playbooks.append(Path(Path(__file__).parent.parent.parent, "blueprints", cvex['blueprint'], data['playbook']))
            trace = None
            command = []
            if 'trace' in cvex[vm_name]:
                trace = cvex[vm_name]['trace']
            if 'playbook' in cvex[vm_name]:
                playbooks.append(Path(cve_dir, cvex[vm_name]['playbook']))
            if 'command' in cvex[vm_name]:
                if type(cvex[vm_name]['command']) == str:
                    command = [cvex[vm_name]['command']]
                elif type(cvex[vm_name]['command']) == list:
                    command = cvex[vm_name]['command']
                else:
                    self.log.critical("%s: configuration mismatch", cvex_yml)
                    sys.exit(1)
            self.vm_templates.append(VMTemplate(vm_name,
                                            data['image'],
                                            data['version'],
                                            data['type'],
                                            trace,
                                            playbooks,
                                            command))
        if not self.vm_templates:
            self.log.critical("%s: configuration mismatch", blueprint_yml)
            sys.exit(1)

        if 'ports' in cvex:
            if type(cvex['ports']) == int:
                self.ports = [cvex['ports']]
            elif type(cvex['ports']) == list:
                self.ports = []
                for port in cvex['ports']:
                    if type(port) != int:
                        self.log.critical("%s: bad ports", cvex_yml)
                        sys.exit(1)
                    self.ports.append(port)
            else:
                self.log.critical("%s: bad ports", cvex_yml)
                sys.exit(1)
        else:
            self.ports = [DEFAULT_PORT]
        for port in self.ports:
            if port < 1 or port > 0xFFFF:
                self.log.critical("%s: bad ports", cvex_yml)
                sys.exit(1)

    def _list_vm(self, vm: VM, i: int, arg):
        if not i:
            self.log.info("Cached VMs:")
        self.log.info("%s", vm.destination)

    def _destroy_vm(self, vm: VM, i: int, arg):
        if arg == "all" or str(vm.destination) == str(arg):
            vm.destroy()

    def _remove_snapshot(self, vm: VM, i: int, arg):
        try:
            snapshots = vm.vag.snapshot_list()
            vm._print_vagrant_log(logging.DEBUG)
        except:
            vm._print_vagrant_log(logging.CRITICAL)
            sys.exit(1)
        for snapshot in snapshots:
            if "default" in snapshot or snapshot == INIT_SNAPSHOT:
                continue
            if arg == "all" or arg in snapshot:
                vm.remove_snapshot(snapshot)

    def _enum_vms(self, callback, arg = None) -> int:
        images = [f.name for f in os.scandir(CVEX_ROOT) if f.is_dir()]
        if not images:
            return 0
        i = 0
        if ROUTER_VM_NAME in images:
            router = RouterVM()
            if router.exists():
                callback(router, i, arg)
                i += 1
        for image in images:
            if image == ROUTER_VM_NAME:
                continue
            versions = [f.name for f in os.scandir(Path(CVEX_ROOT, image)) if f.is_dir()]
            for version in versions:
                instances = [f.name for f in os.scandir(Path(CVEX_ROOT, image, version)) if f.is_dir()]
                for instance in instances:
                    destination = Path(CVEX_ROOT, image, version, instance)
                    vm = VM([],
                            VMTemplate(
                                f"{image}/{version}/{instance}",
                                image,
                                version,
                                VMTemplate.VM_TYPE_LINUX),
                            "stub",
                            destination=destination)
                    if vm.exists():
                        callback(vm, i, arg)
                        i += 1
        return i

    def _get_command(self, vms: list[VM], vm: VM, command: str, command_idx: int) -> tuple:
        for vm2 in vms:
            command = command.replace(f"%{vm2.vm_name}%", vm2.ip)
        command_until = command.split("~~~")
        if len(command_until) == 1:
            command = command_until[0]
            until = ""
        else:
            command, until = command_until
        if command.endswith("&"):
            is_async = True
            command = command[:-1]
        else:
            is_async = False
        # Run strace with the commands, otherwise the Linux agent may detect them too late
        if vm.vm_type == VMTemplate.VM_TYPE_LINUX and vm.trace:
            r = re.search(vm.trace, command)
            if r:
                process_name = r.group(0)
                path = f"{CVEX_TEMP_FOLDER_LINUX}/{vm.vm_name}_strace_{process_name}_{command_idx}.log"
                if command.startswith("sudo "):
                    command = f"sudo strace -o {path} {command[5:]}"
                else:
                    command = f"strace -o {path} {command}"
        return command, until, is_async

    def main(self):
        parser = argparse.ArgumentParser(
            prog="cvex",
            description="",
        )
        parser.add_argument("cve", help="CVE directory name", nargs='?')
        parser.add_argument("-o", "--output", help="Directory for generated logs (\"out\" by default)", default="out")
        parser.add_argument("-l", "--list", help="List all cached VMs", default=False, action="store_true")
        parser.add_argument("-d", "--destroy", help="Path to the cached VM to destroy or \"all\"")
        parser.add_argument("-v", "--verbose", help="Verbose logs", default=False, action="store_true")
        parser.add_argument("-k", "--keep", help="Keep VMs running", default=False, action="store_true")
        parser.add_argument("-n", "--new", help="Regenerate snapshots", default=False, action="store_true")
        parser.add_argument("-r", "--remove", help="Partial name of the snapshot to remove or \"all\"")
        args = parser.parse_args()

        if args.verbose:
            set_log_level(logging.DEBUG)
        self.log = get_logger("main")

        if args.destroy:
            if not self._enum_vms(self._destroy_vm, args.destroy):
                self.log.info("VM was not found")
            sys.exit(0)

        if args.list:
            if not self._enum_vms(self._list_vm):
                self.log.info("There are no cached VMs")
            sys.exit(0)

        if args.remove:
            if not self._enum_vms(self._remove_snapshot, args.remove):
                self.log.info("There are no cached VMs")
            sys.exit(0)

        output_dir = Path(args.output)
        if not output_dir.exists():
            output_dir.mkdir()
        elif not output_dir.is_dir():
            self.log.critical("%s is not a directory", output_dir)
            sys.exit(1)

        if not args.cve or not Path(args.cve).exists():
            self.log.critical("CVE directory is mandatory")
            sys.exit(1)

        self._check_for_lfs_files(Path(Path(__file__).parent.parent.parent, "ansible", "data"))

        # Load cvex.yml of the CVE record
        self._read_cvex(Path(args.cve))

        # Create VMs
        vms = []
        if len(self.vm_templates) > 1:
            router = RouterVM(args.keep)
            vms.append(router)
        else:
            router = None
        cve_name = Path(args.cve).absolute().name
        for vm_template in self.vm_templates:
            if vm_template.vm_type == VMTemplate.VM_TYPE_LINUX:
                vm = LinuxVM(vms, vm_template, cve_name, keep=args.keep, new=args.new)
            elif vm_template.vm_type == VMTemplate.VM_TYPE_WINDOWS:
                vm = WindowsVM(vms, vm_template, cve_name, args.keep, new=args.new)
            else:
                self.log.error("VM type is not supported: %r", vm_template.vm_type)
            vms.append(vm)

        # Check that the system has enough free disk space and RAM
        disk_size_needed = REQUIRED_FREE_SPACE   # In gigabytes
        ram_needed = REQUIRED_RAM                # In megabytes
        for vm in vms:
            if vm.vm_name == ROUTER_VM_NAME:
                if not vm.is_created():
                    disk_size_needed += LINUX_VAGRANT_BOX_SIZE + ROUTER_VM_SIZE
                ram_needed += LINUX_VM_RAM
            elif vm.vm_type == VMTemplate.VM_TYPE_LINUX:
                if not vm.is_created():
                    disk_size_needed += LINUX_VAGRANT_BOX_SIZE + UBUNTU_VM_SIZE
                ram_needed += LINUX_VM_RAM
            elif vm.vm_type == VMTemplate.VM_TYPE_WINDOWS:
                if not vm.is_created():
                    disk_size_needed += WINDOWS_VAGRANT_BOX_SIZE + WINDOWS_VM_SIZE
                ram_needed += WINDOWS_VM_RAM
        disk = os.statvfs(Path.home())
        free_space = disk.f_frsize * disk.f_bavail / (1024. ** 3)
        total_ram = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024 ** 2)
        self.log.debug("Execution of %s requires at least %.2fGB of free disk space and %dMB of RAM",
                        cve_name, disk_size_needed, ram_needed)
        self.log.debug("Free disk space: %.2fGB, total RAM: %dMB", free_space, total_ram)
        if disk_size_needed > free_space or ram_needed > total_ram:
            self.log.warning("\x1b[31;1m*************************************************************************\033[0m")
            self.log.warning("\x1b[31;1mExecution of %s requires at least %.2fGB of free disk space and %dMB of RAM\033[0m",
                            cve_name, disk_size_needed, ram_needed)
            self.log.warning("\x1b[31;1mFree disk space: %.2fGB, total RAM: %dMB\033[0m", free_space, total_ram)
            self.log.warning("\x1b[31;1m*************************************************************************\033[0m")

        # Start all VMs
        for vm in vms:
            vm.run(router)

        # Preconfigure VMs
        if router:
            router.set_network_interface_ip()
            router.set_routing()
            router.start_sniffing(self.ports)
        for vm in vms:
            if vm != router:
                vm.set_network_interface_ip(router)
                if router:
                    vm.set_routing(router)
                vm.update_hosts(vms)
                vm.start_api_tracing()

        # Execute commands
        succeed = True
        for vm in vms:
            command_idx = 0
            for command in vm.command:
                command, until, is_async = self._get_command(vms, vm, command, command_idx)
                try:
                    vm.ssh.run_command(
                        command,
                        is_async=is_async,
                        until=until,
                        show_progress=True,
                        output_file=Path(args.output, f"{vm.vm_name}_{COMMAND_NAME}_{command_idx}.{COMMAND_EXT}"))
                except Exception as e:
                    self.log.critical("Command failed: %r", e)
                    succeed = False
                    break
                command_idx += 1

        # Stop network traffic sniffing, mitmproxy, API tracing
        if succeed:
            for vm in vms:
                vm.stop_api_tracing(args.output)
            if router:
                router.stop_sniffing(args.output)

        # Stop all VMs
        if not args.keep:
            for vm in vms:
                vm.stop()

        if succeed:
            sys.exit(0)
        else:
            sys.exit(1)


def main():
    cvex = CVEX()
    cvex.main()


if __name__ == "__main__":
    main()
