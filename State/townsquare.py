"""Town square game states."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

import nextcord
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class Player:
    id: int
    alias: str
    can_vote: bool = True
    dead: bool = False

    def __eq__(self, other):
        return isinstance(other, (Player, nextcord.User, nextcord.Member)) and self.id == other.id


@dataclass_json
@dataclass
class Vote:
    vote: str
    banshee: bool = False
    bureaucrat: bool = False
    thief: bool = False


@dataclass_json
@dataclass
class Nomination:
    nominator: Player
    nominee: Player
    votes: Dict[int, Vote]
    deadline: str
    private_votes: Dict[int, str] = field(default_factory=dict)
    accusation: str = "TBD"
    defense: str = "TBD"
    message: int = None
    finished: bool = False


@dataclass_json
@dataclass
class TownSquare:
    players: List[Player]
    sts: List[Player]
    nominations: List[Nomination] = field(default_factory=list)
    nomination_thread: int = None
    log_thread: int = None
    organ_grinder: bool = False
    default_nomination_duration: int = 86400
    player_noms_allowed: bool = True
    vote_threshold: int = 0


class TownSquareStore:
    def __init__(self, storage_location: str):
        self.path = os.path.join(storage_location, "townsquares.json")
        self.town_squares: Dict[str, TownSquare] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as file:
                self.town_squares = {game: TownSquare.from_dict(value) for game, value in json.load(file).items()}
        else:
            self.save()

    def save(self) -> None:
        with open(self.path, "w") as file:
            json.dump({game: square.to_dict() for game, square in self.town_squares.items()}, file, indent=2)
