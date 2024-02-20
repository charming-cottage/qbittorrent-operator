#!/usr/bin/env python3
# Copyright 2024 Alex Lowe
# See LICENSE file for licensing details.

"""Charm the application."""

import base64
import configparser
import contextlib
import hashlib
import logging
import pathlib
import secrets
import shutil
import subprocess
from urllib.parse import urlparse

import ops

BT_SERVICE_FILE = """
[Unit]
Description=QBittorrent service
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User=qbittorrent
ExecStart=/usr/bin/qbittorrent-nox --profile=/home/qbittorrent

[Install]
WantedBy=multi-user.target
"""

SSHFS_SERVICE_FILE = """
[Unit]
Description=SSHFS service
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User=qbittorrent
ExecStart=/usr/bin/sshfs {path} /srv -f -o max_conns=32

[Install]
WantedBy=multi-user.target
"""

BT_SERVICE_PATH = pathlib.Path("/etc/systemd/system/qbittorrent.service")
CONFIG_PATH = pathlib.Path("/home/qbittorrent/qBittorrent/config/qBittorrent.conf")
SSH_KEY_PATH = pathlib.Path("/home/qbittorrent/.ssh/id_rsa")
SSHFS_SERVICE_PATH = pathlib.Path("/etc/systemd/system/sshfs.service")

logger = logging.getLogger(__name__)


class QBittorrentConfig:
    def __init__(self, file: pathlib.Path = CONFIG_PATH):
        self.file = file
        self.config = configparser.ConfigParser()
        self.config.optionxform = (
            str  # Make the parser case sensitive.  # pyright: ignore[reportAttributeAccessIssue]
        )
        self.config.read(file)

    def set(self, section: str, option: str, value: str) -> None:
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)

    def setup(self) -> None:
        self.set("LegalNotice", "Accepted", "true")
        self.set("Meta", "MigrationVersion", "3")
        self.set("Preferences", r"WebUI\Address", "*")
        self.set("BitTorrent", r"Session\AddExtensionToIncompleteFiles", "true")
        self.set("BitTorrent", r"Session\DefaultSavePath", "/srv")

    def save(self) -> None:
        with self.file.open("w+") as fp:
            self.config.write(fp, space_around_delimiters=False)

    def set_web_port(self, port: int, save: bool = True) -> None:
        self.set("Preferences", r"WebUI\Port", str(port))
        if save:
            self.save()

    def set_web_username(self, username: str, save: bool = True) -> None:
        self.set("Preferences", r"WebUI\Username", username)
        if save:
            self.save()

    def set_web_password(self, password: str, save: bool = True) -> None:
        # See: https://github.com/qbittorrent/qBittorrent/blob/master/src/base/utils/password.cpp#L48
        salt_length = 16  # 16-byte salt
        iterations = 100_000
        salt = secrets.token_bytes(salt_length)
        hash = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, iterations)
        self.set(
            "Preferences",
            r"WebUI\Password_PBKDF2",
            f"@ByteArray({base64.b64encode(salt).decode()}:{base64.b64encode(hash).decode()})"
        )
        if save:
            self.save()

    def set_bittorrent_interface(self, interface: str, save: bool = True) -> None:
        self.set("BitTorrent", r"Session\Interface", interface)
        self.set("BitTorrent", r"Session\InterfaceName", interface)
        if save:
            self.save()



class QbittorrentOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        subprocess.run(["systemctl", "start", "sshfs.service"], check=True)
        subprocess.run(["systemctl", "start", "qbittorrent.service"], check=True)
        self.unit.status = ops.ActiveStatus("running")

    def _on_stop(self, event: ops.StopEvent):
        subprocess.run(["systemctl", "stop", "qbittorrent.service"], check=True)
        self.unit.status = ops.MaintenanceStatus("stopped")

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        config = QBittorrentConfig()
        config.set_web_port(int(self.config["port"]))
        config.set_bittorrent_interface(self.config["torrent-interface"])
        self.unit.set_ports(int(self.config["port"]))

        SSH_KEY_PATH.parent.mkdir(exist_ok=True)
        shutil.chown(SSH_KEY_PATH.parent, "qbittorrent", "qbittorrent")
        SSH_KEY_PATH.parent.chmod(0o700)
        SSH_KEY_PATH.write_text(self.config["dest-key"])
        SSH_KEY_PATH.chmod(0o600)
        shutil.chown(SSH_KEY_PATH, "qbittorrent", "qbittorrent")
        with contextlib.suppress(PermissionError):
            shutil.chown("/srv", "qbittorrent", "qbittorrent")
        SSHFS_SERVICE_PATH.parent.mkdir(exist_ok=True)
        SSHFS_SERVICE_PATH.write_text(SSHFS_SERVICE_FILE.format(path=self.config["dest-path"]))

    def _on_install(self, event: ops.InstallEvent):
        self.unit.status = ops.MaintenanceStatus("installing qbittorrent")
        apt = subprocess.Popen(
            ["apt", "--yes", "install", "qbittorrent-nox", "sshfs"],
        )
        subprocess.run(
            ["useradd", "--shell", "/bin/false", "--create-home", "qbittorrent"],
        )
        BT_SERVICE_PATH.write_text(BT_SERVICE_FILE)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.touch()
        for path in pathlib.Path("/home/qbittorrent").glob("**"):
            shutil.chown(path, "qbittorrent", "qbittorrent")
        port = int(self.config["port"])
        config = QBittorrentConfig()
        config.setup()
        config.set_web_port(port, save=False)
        config.set_web_username(self.config["user"], save=False)
        config.set_web_password(self.config["password"], save=False)
        config.set_bittorrent_interface(self.config["torrent-interface"], save=False)
        config.save()
        self.unit.set_ports(port)

        apt.wait()



if __name__ == "__main__":  # pragma: nocover
    ops.main(QbittorrentOperatorCharm)  # type: ignore
