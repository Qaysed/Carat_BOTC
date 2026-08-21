"""The data stores used by Carat."""

from State.archive import ArchiveStore
from State.queue import QueueStore
from State.reminders import ReminderStore
from State.reserve import ReserveStore
from State.townsquare import TownSquareStore


class DataLayer:
    def __init__(self, storage_location: str):
        self.archive = ArchiveStore(storage_location)
        self.queue = QueueStore(storage_location)
        self.reminders = ReminderStore(storage_location)
        self.reserve = ReserveStore(storage_location)
        self.townsquare = TownSquareStore(storage_location)
