"""Reserved game entries."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class RSVPEntry:
    thread: int
    owner: int
    date: str
    min_players: int
    max_players: int = 0
    script: str = "TBA"
    co_sts: List[int] = field(default_factory=list)
    players: List[int] = field(default_factory=list)


class ReserveStore:
    def __init__(self, storage_location: str):
        self.path = os.path.join(storage_location, "reserved.json")
        self.entries: Dict[int, RSVPEntry] = {}
        self.announced: Dict[int, RSVPEntry] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as file:
                data = json.load(file)
            self.entries = {int(owner): RSVPEntry.from_dict(entry) for owner, entry in data.get("entries", {}).items()}
            self.announced = {int(owner): RSVPEntry.from_dict(entry) for owner, entry in data.get("announced", {}).items()}
        else:
            self.save()

    def save(self) -> None:
        with open(self.path, "w") as file:
            json.dump({"entries": {owner: entry.to_dict() for owner, entry in self.entries.items()},
                       "announced": {owner: entry.to_dict() for owner, entry in self.announced.items()}}, file, indent=2)
