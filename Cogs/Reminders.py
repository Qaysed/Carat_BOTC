from __future__ import annotations

import datetime
import logging
import re
from typing import Optional

import nextcord
from nextcord.ext import commands, tasks
from nextcord.utils import utcnow

import utility
from State.reminders import Reminder, ReminderStore

hours_pattern = re.compile(r"^(\d+):([0-5]\d)$")


def parse_hours(inp: str) -> float:
    matched = hours_pattern.match(inp)
    if matched is not None:
        return int(matched.group(1)) + int(matched.group(2)) / 60.0
    else:
        return float(inp)


class Reminders(commands.Cog):
    bot: commands.Bot
    helper: utility.Helper
    store: ReminderStore

    def __init__(self, bot: commands.Bot, helper: utility.Helper, store: ReminderStore):
        self.bot = bot
        self.helper = helper
        self.store = store
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    def update_storage(self):
        self.store.save()

    @nextcord.slash_command(name="reminders", description="Manages reminders for game channels")
    async def reminders(self, interaction: nextcord.Interaction):
        pass

    @reminders.subcommand(name="set", description="Sets reminders for the given game number.")
    async def set(self, interaction: nextcord.Interaction, 
                  game_number: str = nextcord.SlashOption(required=True),
                  message: str = nextcord.SlashOption(required=True),
                  input_times: str = nextcord.SlashOption(required=True, name="times", description="The times in hours from now you want reminders. Enter as a list of numbers e.g. 24, 18:15, 7.25"),
                  ping_st: bool = nextcord.SlashOption(required=False, default=False, description="Would you like the reminders to ping the st, default is false"),
                  ping_players: bool = nextcord.SlashOption(required=False, default=True, description="Would you like the reminders to ping the players, default is true"),):
        game_channel = self.helper.get_game_channel(game_number)
        if game_channel is None:
            await utility.deny_command(interaction, utility.DenialReason.InvalidGame)
            return

        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer(ephemeral=True)
            split_times = input_times.split(",")
            times = []
            for time in split_times:
                try:
                    times.append(parse_hours(time.strip()))
                except ValueError:
                    try:
                        for t in time.strip().split():
                            times.append(parse_hours(t))
                    except ValueError:
                        await interaction.followup.send(f"Could not parse time: {t.strip()}")
                        await utility.deny_command(interaction, utility.DenialReason.InvalidReminderTime)
                        return
            mention = ""
            if ping_players:
                game_role = self.helper.get_game_role(game_number)
                mention = game_role.mention + " "
            if ping_st:
                st_role = self.helper.get_st_role(game_number)
                mention += st_role.mention + " "
            text = mention + message
            times.sort()
            end_of_countdown = utcnow() + datetime.timedelta(hours=times[-1])
            for time in times:
                reminder = Reminder.create(utcnow() + datetime.timedelta(hours=time), game_channel.id, text,
                                           end_of_countdown)
                self.store.reminders.append(reminder)
                logging.debug(f"Added reminder in game {game_number}: {reminder}")
            self.store.reminders.sort()
            self.store.save()
            await interaction.followup.send(f"Reminders set, ending {times[-1]} hours from now")
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    @reminders.subcommand(name="delete", description="Deletes the reminders for the given game number.")
    async def delete(self, interaction: nextcord.Interaction, 
                     game_number: str = nextcord.SlashOption(required=True)):
        game_channel = self.helper.get_game_channel(game_number)
        if game_channel is None:
            await utility.deny_command(interaction, utility.DenialReason.InvalidGame)
            return
        
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer(ephemeral=True)
            self.store.reminders = [reminder for reminder in self.store.reminders if reminder.channel != game_channel.id]
            self.store.save()
            await interaction.followup.send("Reminders deleted")
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    @reminders.subcommand(name="show", description="Shows all reminders for the given game number.")
    async def show(self, interaction: nextcord.Interaction, 
                   game_number: str = nextcord.SlashOption(required=True)):
        game_channel = self.helper.get_game_channel(game_number)
        if game_channel is None:
            await utility.deny_command(interaction, utility.DenialReason.InvalidGame)
            return
        
        await interaction.response.defer(ephemeral=True)
        reminders = [reminder for reminder in self.store.reminders if reminder.channel == game_channel.id]
        if len(reminders) == 0:
            await interaction.followup.send("There are no reminders for this game")
        else:
            await interaction.followup.send("\n".join([reminder.explain() for reminder in reminders]))

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        if len(self.store.reminders) == 0:
            return
        earliest_reminder = self.store.reminders[0]
        if datetime.datetime.fromisoformat(earliest_reminder.time) <= utcnow():
            try:
                channel = self.bot.get_channel(earliest_reminder.channel)
                await channel.send(earliest_reminder.text)
                self.store.reminders.pop(0)
                self.store.save()
            except Exception as e:
                logging.warning(f"Failed to send reminder: {e}")



def setup(bot: commands.Bot):
    bot.add_cog(Reminders(bot, utility.Helper(bot), bot.data.reminders))
