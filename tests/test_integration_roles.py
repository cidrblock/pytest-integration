from pathlib import Path

import pytest

from .defs import AnsibleAction
from .defs import AnsiblePlay
from .defs import AnsibleTask


def find_roles():
    rootdir = "./collections/ansible_collections/cisco/nxos/tests/integration/targets"
    roles = [path for path in Path(rootdir).iterdir() if path.is_dir()]
    return roles


@pytest.mark.parametrize("role", find_roles(), ids=lambda x: x.name)
def test_role(role, network_test_vars, playbook_runner):
    task = AnsibleTask(
        action=AnsibleAction(
            module="include_role",
            args={"name": str(role.resolve())},
        ),
    )

    play = AnsiblePlay(tasks=(task,), vars=network_test_vars)
    playbook_runner().run(play)
