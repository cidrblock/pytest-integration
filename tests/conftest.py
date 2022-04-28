"""Common fixtures for tests."""
import json
import os
import shutil
import sys

from dataclasses import asdict
from pathlib import Path

import ansible.constants as C
import pytest

from ansible import context
from ansible.executor import task_executor
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.inventory.manager import InventoryManager
from ansible.module_utils.common.collections import ImmutableDict
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play import Play
from ansible.plugins.callback.default import (
    CallbackModule as DefaultCallbackModule,
)
from ansible.plugins.loader import connection_loader
from ansible.utils.display import Display
from ansible.utils.display import initialize_locale
from ansible.vars.manager import VariableManager
from filelock import FileLock

from .defs import AnsiblePlay


@pytest.fixture(autouse=True)
def block_on_serial_mark(request):
    """Block on serial mark.

    :param request: The pytest request
    :yields: If serial when the lock is gone, else always
    """
    # https://github.com/pytest-dev/pytest-xdist/issues/385
    os.makedirs(".tox", exist_ok=True)
    if request.node.get_closest_marker("serial"):
        # pylint: disable=abstract-class-instantiated
        with FileLock(".tox/semaphore.lock"):
            yield
    else:
        yield


@pytest.fixture(scope="function")
def inventory(tmp_path):
    inventory = {
        "all": {
            "children": {
                "nxos": {
                    "hosts": {
                        "nxos101": {
                            "ansible_become": False,
                            "ansible_host": "nxos101",
                            "ansible_user": "admin",
                            "ansible_password": "password",
                            "ansible_connection": "ansible.netcommon.network_cli",
                            "ansible_network_cli_ssh_type": "libssh",
                            "ansible_python_interpreter": "python",
                            "ansible_network_import_modules": True,
                        }
                    },
                    "vars": {"ansible_network_os": "cisco.nxos.nxos"},
                }
            }
        }
    }
    inventory_path = tmp_path / "inventory.json"
    with open(inventory_path, "w") as f:
        json.dump(inventory, f)
    return inventory_path


class CallbackModule(DefaultCallbackModule):
    """The callback plugin."""

    def __init__(self, *args, **kwargs):
        """Initialize the callback plugin.

        :param args: Positional arguments
        :param kwargs: Keyword arguments
        """
        super().__init__(*args, **kwargs)

        self.display_ok_hosts = True
        self.display_skipped_hosts = True
        self.display_failed_stderr = True
        self.show_per_host_start = False
        self.check_mode_markers = True

        self.set_option("show_task_path_on_failure", True)

        self.results = []
        self.play: AnsiblePlay
        self._vm: VariableManager

    def _post(self, result):
        task_id = result.task_name.rsplit("~", 1)[-1]
        ansible_task = self.play.task(task_id)
        if not ansible_task:
            return
        ansible_task.result = result
        if ansible_task.on_finish is None:
            return
        try:
            ansible_task.on_finish(
                result=result._result, variable_manager=self._vm
            )
        except AssertionError:
            sys.exit()

    def v2_runner_on_unreachable(self, result, *args, **kwargs):
        """React to host unreachable.

        :param result: The task result
        :param args: Positional arguments
        :param kwargs: Keyword arguments
        """
        self._post(result)
        super().v2_runner_on_unreachable(result, *args, **kwargs)

    def v2_runner_on_ok(self, result, *args, **kwargs):
        """React to host ok.

        :param result: The task result
        :param args: Positional arguments
        :param kwargs: Keyword arguments
        """
        self._post(result)
        super().v2_runner_on_ok(result, *args, **kwargs)

    def v2_runner_on_failed(self, result, *args, **kwargs):
        """React to host failed.

        :param result: The task result
        :param args: Positional arguments
        :param kwargs: Keyword arguments
        """
        self._post(result)
        super().v2_runner_on_failed(result, *args, **kwargs)

    def v2_playbook_on_play_start(self, play):
        """React to play start.

        :param play: The play
        """
        self._vm = play.get_variable_manager()
        super().v2_playbook_on_play_start(play)

    def v2_runner_on_start(self, host, task):
        """React to task start.

        :param host: The host
        :param task: The task
        """
        task_id = task.name.rsplit("~", 1)[-1]
        ansible_task = self.play.task(task_id)
        if not ansible_task:
            return
        if ansible_task.on_start is None:
            return
        ansible_task.on_start(host=host, task=task, variable_manager=self._vm)
        super().v2_runner_on_start(host, task)


class PlaybookRunner:
    """The playbook runner."""

    def __init__(self, inventory_path, play):
        """Initialize the playbook runner."""
        self._inventory_path = str(inventory_path)
        self._play = play
        display = Display()
        display.verbosity = 0
        initialize_locale()

    def run(self):
        """Run the playbook."""

        context.CLIARGS = ImmutableDict()

        loader = DataLoader()
        inventory = InventoryManager(
            loader=loader,
            sources=self._inventory_path,
        )
        results_callback = CallbackModule()
        results_callback.play = self._play

        variable_manager = VariableManager(loader=loader, inventory=inventory)

        tqm = TaskQueueManager(
            inventory=inventory,
            variable_manager=variable_manager,
            loader=loader,
            passwords={},
            stdout_callback=results_callback,
        )

        play_dict = asdict(self._play)
        tasks = []
        for task_obj in self._play.tasks:
            task_dict = task_obj.as_dict()
            task_dict["name"] = f"{task_obj.name}~{task_obj.uuid}"
            tasks.append(task_dict)
        play_dict["tasks"] = tasks

        play = Play().load(
            play_dict,
            variable_manager=variable_manager,
            loader=loader,
        )

        try:
            tqm.run(play)
        finally:
            tqm.cleanup()
            if loader:
                loader.cleanup_all_tmp_files()

        shutil.rmtree(C.DEFAULT_LOCAL_TMP, True)


@pytest.fixture(scope="function")
def playbook_runner():
    """Provide the playbook runner.

    :yields: The playbook runner
    """
    yield PlaybookRunner


@pytest.fixture(scope="function")
def network_test_vars(monkeypatch, request):
    """Provide the network test vars."""

    requesting_test = Path(request.node.nodeid)

    test_fixture_directory = Path(
        Path(requesting_test.parts[0])
        / "integration/fixtures"
        / Path(*requesting_test.parts[1:])
    ).resolve()
    test_mode = os.environ.get("ANSIBLE_NETWORK_TEST_MODE", "playback").lower()

    original = task_executor.start_connection

    def start_connection(play_context, variables, task_uuid):
        """
        Starts the persistent connection
        """
        ssh = connection_loader.get("ssh", class_only=True)
        ansible_playbook_pid = os.getppid()
        cp = ssh._create_control_path(
            play_context.remote_addr,
            play_context.port,
            play_context.remote_user,
            play_context.connection,
            ansible_playbook_pid,
        )
        tmp_path = C.PERSISTENT_CONTROL_PATH_DIR
        socket_path = cp % dict(directory=tmp_path)
        if os.path.exists(socket_path):
            return socket_path
        return original(play_context, variables, task_uuid)

    if test_mode == "playback":
        monkeypatch.setattr(
            task_executor, "start_connection", start_connection
        )

    vars = {
        "ansible_network_test_parameters": {
            "fixture_directory": str(test_fixture_directory),
            "match_threshold": 0.90,
            "mode": test_mode,
        }
    }
    return vars
