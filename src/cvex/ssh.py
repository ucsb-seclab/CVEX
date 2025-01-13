import logging
import signal
import time
from pathlib import Path
import fabric
import paramiko
import vagrant

from cvex.logger import get_logger

# Fix bug in paramiko ssh key selection
paramiko.transport.Transport._preferred_pubkeys = ('ssh-rsa', *paramiko.transport.Transport._preferred_pubkeys)

class SSH:
    log: logging.Logger
    ssh: fabric.Connection

    def __init__(self, vm: vagrant.Vagrant, vm_name: str):
        self.log = get_logger(vm_name)
        self.ssh = self._ssh_connect(vm)
        self.vm = vm

    def _reconnect(self, retries=5, delay=2):
        for attempt in range(retries):
            try:
                self.log.info("Reconnecting to SSH (Attempt %d/%d)...", attempt + 1, retries)
                self.ssh.close()  # Close the existing connection
                self.ssh = self._ssh_connect(self.vm)  # Re-establish the connection
                self.log.info("Reconnection successful!")
                return
            except Exception as e:
                self.log.warning("Reconnection failed: %s. Retrying in %d seconds...", e, delay)
                time.sleep(delay)

        raise RuntimeError(f"Failed to reconnect to SSH after {retries} attempts.")

    def _ssh_connect(self, vm: vagrant.Vagrant) -> fabric.Connection:
        self.log.debug("Retrieving SSH configuration...")
        hostname = vm.hostname()
        port = vm.port()
        username = vm.user()
        key_filename = vm.keyfile()
        self.log.debug("Connecting to %s:%d over SSH...", hostname, int(port))
        client = fabric.Connection(
            host=hostname, port=port, user=username, connect_kwargs={'key_filename': key_filename})
        return client

    def send_ctrl_c(self, runner: fabric.runners.Remote):
        message = paramiko.Message()
        message.add_byte(paramiko.common.cMSG_CHANNEL_REQUEST)
        message.add_int(runner.channel.remote_chanid)
        message.add_string("signal")
        message.add_boolean(False)
        message.add_string(signal.Signals.SIGTERM.name[3:])
        runner.channel.transport._send_user_message(message)

    def _log_output(self, log: str, show_progress: bool, output_file: Path | None):
        if not log:
            return
        if show_progress:
            self.log.info("%s", log)
        else:
            self.log.debug("%s", log)
        if output_file:
            with open(output_file, "a") as f:
                f.write(log)

    def run_command(self,
                    command: str,
                    is_async: bool = False,
                    until: str = "",
                    show_progress: bool = False,
                    output_file: Path | None = None) -> str | fabric.runners.Remote:
        self.log.info("Executing '%s'...", command)
        if is_async:
            result = self.ssh.run(command, asynchronous=is_async, hide=True)
            if until:
                printed_stdout = 0
                printed_stderr = 0
                while True:
                    printed_stdout_end = len(result.runner.stdout)
                    printed_stderr_end = len(result.runner.stderr)
                    for i in range(printed_stdout, printed_stdout_end):
                        self._log_output(result.runner.stdout[i], show_progress, output_file)
                        if until in result.runner.stdout[i]:
                            return result.runner
                    for i in range(printed_stderr, printed_stderr_end):
                        self._log_output(result.runner.stderr[i], show_progress, output_file)
                        if until in result.runner.stderr[i]:
                            return result.runner
                    printed_stdout = printed_stdout_end
                    printed_stderr = printed_stderr_end
                    time.sleep(0.1)
            return result.runner
        else:
            result = self.ssh.run(command, hide=True)
            if result.stdout and result.stderr:
                self._log_output("stdout:", show_progress, output_file)
            self._log_output(result.stdout, show_progress, output_file)
            if result.stdout and result.stderr:
                self._log_output("stderr:", show_progress, output_file)
            self._log_output(result.stderr, show_progress, output_file)
            return result.stdout + result.stderr

    def upload_file(self, local: str, dest: str):
        """
        Upload a file to the remote server. Retry on connection loss.
        """
        self.log.info("Uploading %s -> %s...", local, dest)
        try:
            self.ssh.put(local, dest)
        except (paramiko.SSHException, OSError) as e:
            if "Socket is closed" in str(e):
                self.log.warning("SSH connection lost during upload. Attempting to reconnect...")
                self._reconnect()
                self.ssh.put(local,dest)
            else:
                raise

    def download_file(self, local: str, dest: str):
        """
        Download a file from the remote server. Retry on connection loss.
        """
        self.log.info("Downloading %s -> %s...", dest, local)
        try:
            self.ssh.get(dest, local)
        except (paramiko.SSHException, OSError) as e:
            if "Socket is closed" in str(e):
                self.log.warning("SSH connection lost during download. Attempting to reconnect...")
                self._reconnect()
                self.ssh.get(dest,local)
            else:
                raise
