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
from ansible.module_utils import connection as network_connection
from ansible.module_utils.common.collections import ImmutableDict
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play import Play
from ansible.plugins.callback.default import (
    CallbackModule as DefaultCallbackModule,
)
from ansible.plugins.loader import callback_loader
from ansible.plugins.loader import connection_loader
from ansible.plugins.loader import get_with_context_result
from ansible.utils.display import Display
from ansible.utils.display import initialize_locale
from ansible.vars.manager import VariableManager
from ansible_collections.cisco.nxos.plugins.cliconf.nxos import Cliconf
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

    def __init__(self):
        """Initialize the playbook runner."""
        self.results_callback: CallbackModule
        self.tqm: TaskQueueManager
        self.variable_manager: VariableManager

        self.initialize()

    def initialize(self):
        """Initialize the playbook runner."""

        display = Display()
        display.verbosity = 0
        initialize_locale()

        context.CLIARGS = ImmutableDict()

        sources = "inventory.yaml"

        self.loader = DataLoader()

        self.results_callback = CallbackModule()

        inventory = InventoryManager(loader=self.loader, sources=sources)

        self.variable_manager = VariableManager(
            loader=self.loader, inventory=inventory
        )

        self.tqm = TaskQueueManager(
            inventory=inventory,
            variable_manager=self.variable_manager,
            loader=self.loader,
            passwords={},
            stdout_callback=self.results_callback,
        )

    def run(self, play):
        """Run the playbook.

        :param play: The play
        """
        self.results_callback.play = play

        play_dict = asdict(play)
        tasks = []
        for task_obj in play.tasks:
            task_dict = task_obj.as_dict()
            task_dict["name"] = f"{task_obj.name}~{task_obj.uuid}"
            tasks.append(task_dict)
        play_dict["tasks"] = tasks

        play = Play().load(
            play_dict,
            variable_manager=self.variable_manager,
            loader=self.loader,
        )

        try:
            self.tqm.run(play)
        finally:
            self.tqm.cleanup()
            if self.loader:
                self.loader.cleanup_all_tmp_files()

        shutil.rmtree(C.DEFAULT_LOCAL_TMP, True)


@pytest.fixture(scope="function")
def playbook_runner():
    """Provide the playbook runner.

    :yields: The playbook runner
    """
    yield PlaybookRunner


@pytest.fixture(scope="function")
def connection(monkeypatch):
    class Connection:
        """The connection, mocked."""

        force_persistence = True
        return_values = {}

        def __init__(self, *args, **kwargs):
            """Initialize the connection."""
            self.config_modified = False

        def edit_config(self, *args, **kwargs):
            self.config_modified = True
            return

        @classmethod
        def get(cls, *args, **kwargs):
            return cls.return_values.get(args[0])

        def get_capabilities(self):
            return Cliconf(connection=self).get_capabilities()

        @classmethod
        def send(cls, *args, **kwargs):
            return cls.return_values.get(kwargs["command"].decode("utf-8"))

        def set_option(self, *args, **kwargs):
            return

        def set_options(self, *args, **kwargs):
            return

        def reset(self):
            return

        @classmethod
        def run_commands(cls, *args, **kwargs):
            commands = [entry["command"] for entry in args[0]]
            result = [cls.return_values.get(command) for command in commands]
            return result

    monkeypatch.setattr(network_connection, "Connection", Connection)

    def start_connection(*args, **kwargs):
        return "/dev/null"

    monkeypatch.setattr(task_executor, "start_connection", start_connection)
    return Connection


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
