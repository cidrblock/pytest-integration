"""Run some tests."""

from uuid import uuid4

import pytest

from .defs import AnsibleAction
from .defs import AnsiblePlay
from .defs import AnsibleTask


show_version = """
Cisco NX-OS Software
Copyright (c) 2002-2019, Cisco Systems, Inc. All rights reserved.
Nexus 9000v software ("Nexus 9000v Software") and related documentation,
files or other reference materials ("Documentation") are
the proprietary property and confidential information of Cisco
Systems, Inc. ("Cisco") and are protected, without limitation,
pursuant to United States and International copyright and trademark
laws in the applicable jurisdiction which provide civil and criminal
penalties for copying or distribution without Cisco's authorization.

Any use or disclosure, in whole or in part, of the Nexus 9000v Software
or Documentation to any third party for any purposes is expressly
prohibited except as otherwise authorized by Cisco in writing.
The copyrights to certain works contained herein are owned by other
third parties and are used and distributed under license. Some parts
of this software may be covered under the GNU Public License or the
GNU Lesser General Public License. A copy of each such license is
available at
http://www.gnu.org/licenses/gpl.html and
http://www.gnu.org/licenses/lgpl.html
***************************************************************************
*  Nexus 9000v is strictly limited to use for evaluation, demonstration   *
*  and NX-OS education. Any use or disclosure, in whole or in part of     *
*  the Nexus 9000v Software or Documentation to any third party for any   *
*  purposes is expressly prohibited except as otherwise authorized by     *
*  Cisco in writing.                                                      *
***************************************************************************
sbx-ao# sho version
Cisco Nexus Operating System (NX-OS) Software
TAC support: http://www.cisco.com/tac
Documents: http://www.cisco.com/en/US/products/ps9372/tsd_products_support_series_home.html
Copyright (c) 2002-2019, Cisco Systems, Inc. All rights reserved.
The copyrights to certain works contained herein are owned by
other third parties and are used and distributed under license.
Some parts of this software are covered under the GNU Public
License. A copy of the license is available at
http://www.gnu.org/licenses/gpl.html.

Nexus 9000v is a demo version of the Nexus Operating System

Software
  BIOS: version
 NXOS: version 9.3(3)
  BIOS compile time:
  NXOS image file is: bootflash:///nxos.9.3.3.bin
  NXOS compile time:  12/22/2019 2:00:00 [12/22/2019 14:00:37]


Hardware
  cisco Nexus9000 C9300v Chassis
  Intel(R) Xeon(R) CPU E5-4669 v4 @ 2.20GHz with 16408988 kB of memory.
  Processor Board ID 9N3KD63KWT0

  Device name: sbx-ao
  bootflash:    4287040 kB
Kernel uptime is 1 day(s), 20 hour(s), 53 minute(s), 38 second(s)

Last reset
  Reason: Unknown
  System version:
  Service:

plugin
  Core Plugin, Ethernet Plugin

Active Package(s):
        mtx-openconfig-all-1.0.0.0-9.3.3.lib32_n9000
"""

show_inventory = """
NAME: "Chassis",  DESCR: "Nexus9000 C9300v Chassis"
PID: N9K-C9300v          ,  VID:     ,  SN: 9QXOX90PJ62

NAME: "Slot 1",  DESCR: "Nexus 9000v 64 port Ethernet Module"
PID: N9K-X9364v          ,  VID:     ,  SN: 9ZOFUQ9AWGP

NAME: "Slot 27",  DESCR: "Supervisor Module"
PID: N9K-vSUP            ,  VID:     ,  SN: 9N3KD63KWT0
"""

show_license_host_id = """
License hostid: VDH=9QXOX90PJ62
"""


def test_version(connection, playbook_runner):
    """Test show version output.

    :param connection: The connection
    :param playbook_runner: The playbook runner
    """
    task = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_command",
            args={
                "commands": [
                    "show version",
                ]
            },
        ),
    )
    task_42 = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_command",
            args={
                "commands": [
                    "show 42",
                ]
            },
        ),
    )

    play = AnsiblePlay(tasks=(task, task_42))
    connection.return_values = {
        "show inventory": show_inventory,
        "show license host-id": show_license_host_id,
        "show version": "Nexus",
        "show 42": "42",
    }
    playbook_runner().run(play)
    assert task.result._result["stdout"] == ["Nexus"]
    assert task_42.result._result["stdout"] == ["42"]
    pass


def test_interfaces_gathered(connection, playbook_runner):
    """Test interfaces output.

    :param connection: The connection
    :param playbook_runner: The playbook runner
    """
    task = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_interfaces",
            args={
                "state": "gathered",
            },
        ),
    )

    play = AnsiblePlay(tasks=(task,))
    config = [
        "interface Eth0/0",
        "description test",
    ]
    connection.return_values = {
        "show inventory": show_inventory,
        "show license host-id": show_license_host_id,
        "show running-config | section ^interface": "\n".join(config),
        "show version": show_version,
    }
    playbook_runner().run(play)
    assert task.result._result["gathered"] == [
        {
            "description": "test",
            "name": "Eth0/0",
        }
    ]


@pytest.mark.serial
def test_interfaces_changed(connection, playbook_runner):
    """Test interfaces changed.

    :param playbook_runner: The playbook runner
    """
    module = "cisco.nxos.nxos_interfaces"

    task_gather = AnsibleTask(
        action=AnsibleAction(
            module=module,
            args={"state": "gathered"},
        ),
        register="output",
    )

    new_description = str(uuid4())

    def update_interface(host, task, variable_manager, **kwargs):
        host_vars = variable_manager.get_vars(host=host)
        gathered = host_vars["output"]["gathered"]
        for interface in gathered:
            if interface["name"] == "Ethernet0/0":
                interface["description"] = new_description
        task.args["config"] = gathered

    task_apply = AnsibleTask(
        action=AnsibleAction(
            module=module,
            args={
                "state": "merged",
                "config": [],
            },
        ),
        on_start=update_interface,
    )

    play = AnsiblePlay(tasks=(task_gather, task_apply))
    config = """interface Ethernet0/0
    description test
    """
    switchport = """
    system default switchport
    no system default switchport fabricpath
    no system default switchport shutdown
    """
    connection.return_values = {
        "show inventory": show_inventory,
        "show license host-id": show_license_host_id,
        "show running-config | section ^interface": config,
        "show running-config all | incl 'system default switchport'": switchport,
        "show version": show_version,
    }
    playbook_runner().run(play)
    assert task_apply.result._result["changed"] is True
    expected_commands = [
        "interface Ethernet0/0",
        f"description {new_description}",
    ]
    assert task_apply.result._result["commands"] == expected_commands
