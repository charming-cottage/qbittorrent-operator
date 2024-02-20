# Copyright 2024 Alex Lowe
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import textwrap
import unittest

import ops
import ops.testing
from charm import QbittorrentOperatorCharm, QBittorrentConfig

EXPECTED_SETUP_CONFIG = r"""
[LegalNotice]
Accepted=true

[Meta]
MigrationVersion=3

[Preferences]
WebUI\Address=*
""".strip()


# class TestCharm(unittest.TestCase):
#     def setUp(self):
#         self.harness = ops.testing.Harness(QbittorrentOperatorCharm)
#         self.addCleanup(self.harness.cleanup)
#
#     def test_start(self):
#         # Simulate the charm starting
#         self.harness.begin_with_initial_hooks()
#
#         # Ensure we set an ActiveStatus with no message
#         self.assertEqual(self.harness.model.unit.status, ops.ActiveStatus())


def test_config_file_setup(tmp_path):
    conf_file = tmp_path / "config"
    conf = QBittorrentConfig(conf_file)
    conf.setup()

    assert conf.config["LegalNotice"]["Accepted"] == "true"
    assert conf.config["Meta"]["MigrationVersion"] == "3"
    assert conf.config["Preferences"][r"WebUI\Address"] == "*"

    conf.save()

    assert conf_file.read_text().strip() == EXPECTED_SETUP_CONFIG
