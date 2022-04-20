import os
import shutil
import sys

from dataclasses import asdict

import ansible.constants as C
import pytest

from ansible import context
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.inventory.manager import InventoryManager
from ansible.module_utils.common.collections import ImmutableDict
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play import Play
from ansible.plugins.callback import CallbackBase
from ansible.vars.manager import VariableManager
from filelock import FileLock

from .defs import AnsiblePlay
from .defs import AnsibleTask


@pytest.fixture(autouse=True)
def block_on_serial_mark(request):
    # https://github.com/pytest-dev/pytest-xdist/issues/385
    os.makedirs(".tox", exist_ok=True)
    if request.node.get_closest_marker("serial"):
        # pylint: disable=abstract-class-instantiated
        with FileLock(".tox/semaphore.lock"):
            yield
    else:
        yield


class Callback(CallbackBase):
    """The callback plugin."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.results = []
        self.play: AnsiblePlay
        self._vm: VariableManager

    def _post(self, result):
        task_id = result.task_name.rsplit("~", 1)[-1]
        ansible_task = self.play.task(task_id)
        ansible_task.result = result
        if ansible_task.on_finish is None:
            return
        try:
            ansible_task.on_finish(
                result=result._result, variable_manager=self._vm
            )
        except AssertionError:
            sys.exit()

    def v2_runner_on_unreachable(self, result):
        self._post(result)

    def v2_runner_on_ok(self, result, *args, **kwargs):
        self._post(result)

    def v2_runner_on_failed(self, result, *args, **kwargs):
        self._post(result)

    def v2_playbook_on_play_start(self, play):
        self._vm = play.get_variable_manager()

    def v2_runner_on_start(self, host, task):
        task_id = task.name.rsplit("~", 1)[-1]
        ansible_task = self.play.task(task_id)
        if ansible_task.on_start is None:
            return
        ansible_task.on_start(host=host, task=task, variable_manager=self._vm)


class PlaybookRunner:
    def __init__(self):
        self.results_callback: Callback
        self.tqm: TaskQueueManager
        self.variable_manager: VariableManager

        self.initialize()

    def initialize(self):
        context.CLIARGS = ImmutableDict(verbosity=4)
        sources = "inventory.yaml"

        self.loader = DataLoader()

        self.results_callback = Callback()

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
    return PlaybookRunner
