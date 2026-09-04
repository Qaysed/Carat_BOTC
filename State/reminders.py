"""Scheduled reminders."""

import json
import os
import datetime
from dataclasses import dataclass
from typing import List

from dataclasses_json import dataclass_json
from nextcord.utils import format_dt


@dataclass_json
@dataclass(order=True)
class Reminder:
    time: str
    channel: int
    text: str

    def explain(self) -> str:
        text_elements = self.text.split(" ")
        text_elements = [item for item in text_elements[:2] if not item.startswith("<@&")] + text_elements[2:]
        reminder_time = datetime.datetime.fromisoformat(self.time)
        if self.text.endswith(":t>)"):
            return f"{format_dt(reminder_time, 'R')} ({format_dt(reminder_time, 'f')}): Reminder that " \
                   f"`{' '.join(text_elements[:-2])}` at {text_elements[-1][1:-3]}f>"
        return f"{format_dt(reminder_time, 'R')} ({format_dt(reminder_time, 'f')}): Announcement that " \
               f"`{' '.join(text_elements)}`"

    @staticmethod
    def create(reminder_time: datetime.datetime, channel: int, text: str,
               end_of_countdown: datetime.datetime) -> "Reminder":
        reminder_text = text + f" {format_dt(end_of_countdown, 'R')} ({format_dt(end_of_countdown, 't')})"
        return Reminder(reminder_time.isoformat(), channel, reminder_text)


class ReminderStore:
    def __init__(self, storage_location: str):
        self.path = os.path.join(storage_location, "reminders.json")
        self.reminders: List[Reminder] = []
        if os.path.exists(self.path):
            with open(self.path, "r") as file:
                self.reminders = [Reminder.from_dict(item) for item in json.load(file)]
            self.reminders.sort()
        else:
            self.save()

    def save(self) -> None:
        with open(self.path, "w") as file:
            json.dump([item.to_dict() for item in self.reminders], file, indent=2)
