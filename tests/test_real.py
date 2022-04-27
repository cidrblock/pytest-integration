"""Run some tests."""

from uuid import uuid4

import pytest

from .defs import AnsibleAction
from .defs import AnsiblePlay
from .defs import AnsibleTask


def test_version(playbook_runner):
    """Test show version output.

    :param playbook_runner: The playbook runner
    """

    def check_show_version(result, **kwargs):
        assert "Nexus" in result["stdout"][0]

    task = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_command",
            args={
                "commands": [
                    "show version",
                ]
            },
        ),
        on_finish=check_show_version,
    )

    play = AnsiblePlay(tasks=(task,))
    playbook_runner().run(play)


def test_interface(playbook_runner):
    """Test show interface output.

    :param playbook_runner: The playbook runner
    """

    def check_show_interface(result, **kwargs):
        assert "Ethernet1/1" in result["stdout"][0]

    task = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_command",
            args={
                "commands": [
                    "show interface",
                ]
            },
        ),
        on_finish=check_show_interface,
    )

    play = AnsiblePlay(tasks=(task,))
    playbook_runner().run(play)
    task = AnsibleTask(
        action=AnsibleAction(
            module="cisco.nxos.nxos_command",
            args={
                "commands": [
                    "show ip interface brief",
                ]
            },
        ),
    )

    play = AnsiblePlay(tasks=(task,))
    playbook_runner().run(play)
    assert "IP Interface Status for VRF" in task.result._result["stdout"][0]


round_trips = (
    "cisco.nxos.nxos_interfaces",
    "cisco.nxos.nxos_l2_interfaces",
    "cisco.nxos.nxos_l3_interfaces",
)


@pytest.mark.parametrize("module", round_trips)
def test_interfaces_unchanged(module, playbook_runner):
    """Test interfaces round trip.

    :param module: The module to test
    :param playbook_runner: The playbook runner
    """
    task_gather = AnsibleTask(
        action=AnsibleAction(
            module=module,
            args={"state": "gathered"},
        ),
        register="output",
    )
    task_apply = AnsibleTask(
        action=AnsibleAction(
            module=module,
            args={"state": "overridden", "config": "{{ output['gathered'] }}"},
        ),
        check_mode=True,
    )

    play = AnsiblePlay(tasks=(task_gather, task_apply))
    playbook_runner().run(play)
    assert task_apply.result._result["changed"] is False
    assert task_apply.result._result["commands"] == []


@pytest.mark.serial
def test_interfaces_changed(playbook_runner):
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
            if interface["name"] == "Ethernet1/1":
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
        check_mode=True,
        on_start=update_interface,
    )

    play = AnsiblePlay(tasks=(task_gather, task_apply))
    playbook_runner().run(play)
    assert task_apply.result._result["changed"] is True
    expected_commands = [
        "interface Ethernet1/1",
        f"description {new_description}",
    ]
    assert task_apply.result._result["commands"] == expected_commands
