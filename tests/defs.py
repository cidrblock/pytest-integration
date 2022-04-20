from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from uuid import uuid4


@dataclass
class AnsibleAction:
    module: str
    args: dict = None


@dataclass
class AnsibleTask:
    action: AnsibleAction

    on_finish: Optional[Callable] = None
    check_mode: bool = False
    on_start: Optional[Callable] = None
    result: Dict = field(default_factory=dict)
    name: str = ""
    register: Optional[str] = None
    uuid: str = ""

    def __post_init__(self):
        self.uuid = str(uuid4())

    def as_dict(self):
        dictionary = asdict(self)
        for key in ("on_finish", "on_start", "result", "uuid"):
            dictionary.pop(key)
        return dictionary


@dataclass
class AnsiblePlay:
    tasks: List[AnsibleTask]
    hosts: str = "all"
    gather_facts: bool = False

    def task(self, uuid: str):
        return next(
            (task for task in self.tasks if task.uuid == uuid),
            None,
        )

    def check(self, result):
        for task in self.tasks:
            task.check(result)
