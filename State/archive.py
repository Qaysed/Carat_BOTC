"""Thread archive choices."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class ThreadList:
    private_to_archive: List[int] = field(default_factory=list)
    public_to_not_archive: List[int] = field(default_factory=list)


class ArchiveStore:
    def __init__(self, storage_location: str):
        self.path = os.path.join(storage_location, "thread_archival.json")
        self.threads_by_channel: Dict[int, ThreadList] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as file:
                self.threads_by_channel = {int(channel): ThreadList.from_dict(value)
                                           for channel, value in json.load(file).items()}
        else:
            self.save()

    def save(self) -> None:
        with open(self.path, "w") as file:
            json.dump({channel: items.to_dict() for channel, items in self.threads_by_channel.items()}, file, indent=2)
