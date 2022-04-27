"""Run some tests."""

import collections

from uuid import uuid4

import pytest

from .defs import AnsibleAction
from .defs import AnsiblePlay
from .defs import AnsibleTask


def test_version(network_test_vars, playbook_runner):
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

    play = AnsiblePlay(tasks=(task,), vars=network_test_vars)
    playbook_runner().run(play)
    import q

    q(task.result._result)
