import inspect

from pathlib import Path
from unittest.mock import patch

import pytest

from ansible.executor import task_executor

from .defs import AnsibleAction
from .defs import AnsiblePlay
from .defs import AnsibleTask


def find_roles():
    rootdir = "./collections/ansible_collections/cisco/nxos/tests/integration/targets"
    roles = [path for path in Path(rootdir).iterdir() if path.is_dir()]
    return roles


@pytest.mark.parametrize("role", find_roles(), ids=lambda x: x.name)
def test_role(role, inventory, network_test_vars, playbook_runner):
    task = AnsibleTask(
        action=AnsibleAction(
            module="include_role",
            args={"name": str(role.resolve())},
        ),
    )

    play = AnsiblePlay(tasks=(task,), vars=network_test_vars)
    playbook_runner(inventory_path=inventory, play=play).run()
