"""Storyteller queues."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dataclasses_json import dataclass_json

ExplainInvalidChannelType = "Not a valid channel type - accepted forms are `base, b3, b` for base, " \
                            "`regular, standard, normal, reg, r, s, n` for regular, " \
                            "`experimental, exp, x` for experimental - capitalization doesn't matter."


@dataclass_json
@dataclass
class Entry:
    st: int
    script: str
    availability: str
    notes: Optional[str] = None


@dataclass_json
@dataclass
class StQueue:
    channel_id: int
    message_id: int
    thread_id: Optional[int] = None
    entries: List[Entry] = field(default_factory=list)


class QueueStore:
    def __init__(self, storage_location: str):
        self.path = os.path.join(storage_location, "queue.json")
        self.queues: Dict[str, StQueue] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as file:
                self.queues = {name: StQueue.from_dict(value) for name, value in json.load(file).items()}
        else:
            self.save()

    def save(self) -> None:
        with open(self.path, "w") as file:
            json.dump({name: queue.to_dict() for name, queue in self.queues.items()}, file, indent=2)

    def get_queue(self, user_id: int) -> Optional[StQueue]:
        return next((queue for queue in self.queues.values() if user_id in [entry.st for entry in queue.entries]), None)

    def remove_user(self, user_id: int) -> List[StQueue]:
        changed = []
        for queue in self.queues.values():
            entries = [entry for entry in queue.entries if entry.st != user_id]
            if len(entries) != len(queue.entries):
                queue.entries = entries
                changed.append(queue)
        if changed:
            self.save()
        return changed
