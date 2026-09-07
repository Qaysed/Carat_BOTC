import io
import json
import logging
from typing import Literal, Optional

import nextcord
from nextcord import HTTPException
from nextcord.ext import commands
from nextcord.utils import get

import utility
from State.queue import Entry, QueueStore, StQueue
from State.reserve import ReserveStore

async def update_queue_message(queue: StQueue, helper: utility.Helper) -> bool:
    channel = get(helper.Guild.channels, id=queue.channel_id)
    if channel is None:
        raise ValueError("Could not find the queue channel/the channel containing the queue threads")
    if queue.thread_id is not None:
        thread = get(channel.threads, id=queue.thread_id)
        if thread is None:
            raise ValueError("Could not find queue thread")
        message = await thread.fetch_message(queue.message_id)
    else:
        message = await channel.fetch_message(queue.message_id)
    embed = message.embeds[0]
    embed.clear_fields()
    spot = 1
    for entry in queue.entries:
        user = await helper.fetch_member(entry.st)
        if user is None:
            queue.entries.remove(entry)
            log_message = f"Removed user with ID {entry.st} from queue due to having left the guild"
            logging.warning(log_message)
            await helper.log(log_message)
            continue
        entry_string = f"Script: {entry.script}\nAvailability: {entry.availability}\n"
        if entry.notes is not None:
            entry_string += f"Notes: {entry.notes}\n"
        embed.add_field(name=f"{spot}. {user.display_name}"[:256],
                        value=entry_string[:1024],
                        inline=False)  # length limits by discord
        spot = spot + 1
    await helper.log(
        f"Queue updated - current entries: "
        f"{str([(await helper.fetch_member(qe.st)).display_name for qe in queue.entries])}"[:1950])
    queue_posted_completely = True
    success = False
    while not success:
        try:
            await message.edit(embed=embed)
            success = True
        except HTTPException:
            if len(embed.fields) == 0:
                raise Exception("Unable to post queue")
            embed.remove_field(len(embed.fields) - 1)
            queue_posted_completely = False
    return queue_posted_completely

class TextQueue(commands.Cog):
    bot: commands.Bot
    helper: utility.Helper
    store: QueueStore

    def __init__(self, bot: commands.Bot, helper: utility.Helper, store: QueueStore, reserve_store: ReserveStore):
        self.bot = bot
        self.helper = helper
        self.store = store
        self.reserve_store = reserve_store
        self.queues = self.store.queues

    async def announce_free_channel(self, game_number, queue_position: int):
        channel = self.helper.get_game_channel(game_number)
        if game_number[0] == 'b':
            channel_type = "Base"
        elif game_number[0] == 'x':
            channel_type = "Experimental"
        else:
            channel_type = "Regular"
        if queue_position >= len(self.queues[channel_type].entries):
            await channel.send("There are no further entries in the queue.")
            return
        next_entry = self.queues[channel_type].entries[queue_position]
        user = await self.helper.fetch_member(next_entry.st)
        if user is not None:
            content = f"{user.mention} This game channel has become free! You are next in the queue.\n" \
                      f"You may claim the grimoire with /grimoire claim {game_number} or the button below.\n" \
                      f"If you are not currently able to run the game, use the button below to decline the grimoire " \
                      f"and inform the next person in the queue."
            await channel.send(content=content,
                               view=FreeChannelNotificationView(self, self.helper, self.queues[channel_type].entries,
                                                                game_number, queue_position))
        else:
            await self.announce_free_channel(game_number, queue_position + 1)

    async def user_leave_queue(self, user: nextcord.Member):
        for queue in self.store.remove_user(user.id):
            await update_queue_message(queue, self.helper)

    def get_queue(self, user_id: int) -> Optional[StQueue]:
        return self.store.get_queue(user_id)

    @nextcord.slash_command(name="queue", description="Deals with everything text game queue related.")
    async def queue(self, interaction: nextcord.Interaction):
        pass

    @queue.subcommand(name="initialize", name_localizations={"en-US": "initialize", "en-GB": "initialise"}, 
                      description="Initializes an ST queue for base, regular or experimental games in this channel or thread.", 
                      description_localizations={"en-US": "Initializes an ST queue for base, regular or experimental games in this channel or thread.", 
                                                 "en-GB": "Initialises an ST queue for base, regular or experimental games in this channel or thread."})
    async def initialize(self, interaction: nextcord.Interaction, 
                         channel_type: str = nextcord.SlashOption(required=True, choices=["Base","Regular","Experimental"]),
                         reset: bool = nextcord.SlashOption(required=False, default=False)):
        if await self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer(ephemeral=True)
            embed = nextcord.Embed(title=channel_type + " storytelling queue", description="Use '/queue join' to join")
            if isinstance(interaction.channel, nextcord.Thread):
                queue = StQueue(interaction.channel.parent.id, -1, interaction.channel.id)
            elif isinstance(interaction.channel, nextcord.TextChannel):
                queue = StQueue(interaction.channel.id, -1)
            else:
                await interaction.followup.send("Please use this command in a text channel or a thread")
                return
            if channel_type in self.queues and reset is None:
                queue.entries = self.queues[channel_type].entries

            queue_message = await interaction.channel.send(embed=embed)
            queue.message_id = queue_message.id
            self.queues[channel_type] = queue

            self.store.save()
            await interaction.followup.send(f"{channel_type} queue created!")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)
        await self.helper.log(f"{interaction.user.mention} has run the queue initialize command in {interaction.channel.mention}")

    @queue.subcommand(name="join", description="Adds you to the end of the text game queue for your chosen channel type.")
    async def join(self, interaction: nextcord.Interaction,
                         channel_type: str = nextcord.SlashOption(required=True, choices=["Base","Regular","Experimental"]),
                         script: str = nextcord.SlashOption(required=True),
                         availability: str = nextcord.SlashOption(required=True), 
                         notes: str = nextcord.SlashOption(required=False, default=None)):
        if interaction.user.id in self.reserve_store.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.AlreadyReserved)
            return
        if channel_type not in self.queues.keys():
            await utility.deny_app_command(interaction, utility.DenialReason.QueueTypeNotInitialised)
            return
        if self.get_queue(interaction.user.id) is None:
            await interaction.response.defer() 
            entry = Entry(interaction.user.id, script, availability)
            if notes:
                entry.notes = notes
            self.queues[channel_type].entries.append(entry)
            full_queue_posted = await update_queue_message(self.queues[channel_type], self.helper)

            self.store.save()
            await interaction.followup.send(f"You have joined the {channel_type} queue:"
                                            f"\nScript: {script}"
                                            f"\nAvailability: {availability}" +
                                            (f"\nNotes: {notes}" if notes else ""))

            if not full_queue_posted:
                await self.helper.log("Queue too long for message - final entry/entries not displayed")
                await interaction.followup.send(f"The queue is too long to display in full. Your entry may not be "
                                                f"displayed currently, but it has been added to the queue.", ephemeral=True)
            await self.helper.log(f"{interaction.user.mention} has joined the {channel_type} queue")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.InQueue)

    @queue.subcommand(name="leave", description="Removes you from the queue you are in currently.")
    async def leave(self, interaction: nextcord.Interaction):
        queue = self.get_queue(interaction.user.id)
        if not queue:
            await utility.deny_app_command(interaction, utility.DenialReason.NotInQueue)
            return

        await interaction.response.defer()
        queue.entries = [e for e in queue.entries if e.st != interaction.user.id]
        full_queue_posted = await update_queue_message(queue, self.helper)
        if not full_queue_posted:
            await self.helper.log("Queue too long for message - final entry/entries not displayed")

        self.store.save()
        await interaction.followup.send("You have left the text game queue")
        await self.helper.log(f"{interaction.user.mention} has left the text game queue")

    @queue.subcommand(name="move_down", description="Moves you down the given number of spaces in your queue.")
    async def move_down(self, interaction: nextcord.Interaction, 
                       number_of_spots: int = nextcord.SlashOption(required=True, min_value=1)):
        queue = self.get_queue(interaction.user.id)
        if not queue:
            await utility.deny_app_command(interaction, utility.DenialReason.NotInQueue)
            return
        await interaction.response.defer()
        for index, entry in enumerate(queue.entries):
            if entry.st == interaction.user.id:
                current_index = index
        queue.entries.insert(current_index + number_of_spots, queue.entries.pop(current_index))

        full_queue_posted = await update_queue_message(queue, self.helper)
        if not full_queue_posted:
            await self.helper.log("Queue too long for message - final entry/entries not displayed")
        self.store.save()
        await interaction.followup.send(f"You have moved down {number_of_spots} place(s) in your queue")

    @queue.subcommand(name="edit_entry", description="Edits your queue entry. You can not change your channel type.")
    async def edit_entry(self, interaction: nextcord.Interaction, 
                         script: str = nextcord.SlashOption(required=True),
                         availability: str = nextcord.SlashOption(required=True), 
                         notes: str = nextcord.SlashOption(required=False, default=None)):
        queue = self.get_queue(interaction.user.id)
        if not queue:
            await utility.deny_app_command(interaction, utility.DenialReason.NotInQueue)
            return
        await interaction.response.defer()
        entry = next(e for e in queue.entries if e.st == interaction.user.id)
        entry.script = script
        entry.availability = availability
        if notes:
            entry.notes = notes

        full_queue_posted = await update_queue_message(queue, self.helper)
        if not full_queue_posted:
            await self.helper.log("Queue too long for message - final entry/entries not displayed")
        self.store.save()
        await interaction.followup.send(f"Queue entry updated:"
                                        f"\nScript: {script}"
                                        f"\nAvailability: {availability}" +
                                        (f"\nNotes: {notes}" if notes else ""))
        await self.helper.log(f"{interaction.user.mention} has run the edit_entry command")

    @queue.subcommand(name="edit_notes", description="Edits only the notes part of your entry.")
    async def edit_notes(self, interaction: nextcord.Interaction, 
                         notes: str = nextcord.SlashOption(required=True)):
        queue = self.get_queue(interaction.user.id)
        if queue is None:
            await utility.deny_app_command(interaction, utility.DenialReason.NotInQueue)
            return
        await interaction.response.defer()
        entry = next(e for e in queue.entries if e.st == interaction.user.id)
        entry.notes = notes

        full_queue_posted = await update_queue_message(queue, self.helper)
        if not full_queue_posted:
            await self.helper.log("Queue too long for message - final entry/entries not displayed")
        self.store.save()
        await interaction.followup.send(f"Queue entry updated: \nNotes: {notes}")
        await self.helper.log(f"{interaction.user.mention} has run the edit_notes command")

    @queue.subcommand(name="remove_from_queue", description="Removes a player from the queue. Moderator only!")
    async def remove_from_queue(self, interaction: nextcord.Interaction, 
                           member: nextcord.Member = nextcord.SlashOption(required=True)):
        if await self.helper.authorize_mod_command(interaction.user):
            queue = self.get_queue(member.id)
            if not queue:
                await interaction.send("That member is not in a queue at the moment", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            queue.entries = [e for e in queue.entries if e.st != member.id]

            full_queue_posted = await update_queue_message(queue, self.helper)
            if not full_queue_posted:
                await self.helper.log("Queue too long for message - final entry/entries not displayed")
            self.store.save()
            try: # incase the member has left the server - to stop unresolved commands
                channel = get(self.helper.Guild.channels, id=queue.channel_id)
                if queue.thread_id:
                    channel = get(channel.threads, id=queue.thread_id)
                await channel.send(f"{member.mention} has been removed from the queue.")
                await interaction.followup.send(f"{member.display_name} has been removed from queue.")
                await self.helper.log(f"{interaction.user.mention} has run the remove command on {member.mention}")
            except:
                await interaction.followup.send("Member removed from queue. Since they are not currently a member of the server "
                                                "no announcement message has been able to be sent to the queue channel.")
                await self.helper.log(f"{interaction.user.mention} has run the remove command on {member.id}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @queue.subcommand(name="move_to_spot", description="Moves the queue entry of the given user to the given spot in their queue. Moderator only!")
    async def move_to_spot(self, interaction: nextcord.Interaction, 
                           member: nextcord.Member = nextcord.SlashOption(required=True), 
                           spot: int = nextcord.SlashOption(required=True, min_value=1)):
        if await self.helper.authorize_mod_command(interaction.user):
            queue = self.get_queue(member.id)
            if not queue:
                await interaction.send("That member is not in a queue at the moment", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            for index, item in enumerate(queue.entries):
                if item.st == member.id:
                    entry = queue.entries.pop(index)
            queue.entries.insert(spot - 1, entry)

            full_queue_posted = await update_queue_message(queue, self.helper)
            if not full_queue_posted:
                await self.helper.log("Queue too long for message - final entry/entries not displayed")
            self.store.save()
            await interaction.followup.send(f"Moved {member.display_name} to spot {spot}")
            await self.helper.log(f"{interaction.user.mention} has run the move_to_spot command on {member.display_name}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @queue.subcommand(name="get_json", description="Developer command! Sends the user a json of all the queues.")
    async def get_json(self, interaction: nextcord.Interaction):
        if utility.authorize_dev_command(interaction.user):
            json_data = {}
            for queue in self.queues:
                json_data[queue] = self.queues[queue].to_dict()
            json_str = json.dumps(json_data, indent=2)
            bytes_data = io.BytesIO(json_str.encode("utf-8"))
            await interaction.send(f"Text Game Queue json", file=nextcord.File(bytes_data, f"Entries.json"), ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)


class FreeChannelNotificationView(nextcord.ui.View):
    def __init__(self, queue_cog: TextQueue, helper: utility.Helper, queue: list, game_number: str,
                 queue_position: int):
        super().__init__()
        self.queue_cog = queue_cog
        self.helper = helper
        self.queue = queue
        self.game_number = game_number
        self.queue_position = queue_position
        self.timeout = 172800  # two days

    async def on_error(self, error: Exception, item: nextcord.ui.Item, interaction: nextcord.Interaction) -> None:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Ignoring exception in FreeChannelNotificationView:\n{traceback_text}")

    @nextcord.ui.button(label="Claim grimoire", custom_id="claim_grimoire", style=nextcord.ButtonStyle.green)
    async def claim_grimoire_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        st_role = self.helper.get_st_role(self.game_number)
        if st_role.members:
            await interaction.send(
                content=f"The grimoire has been claimed by "
                        f"{', '.join([st.display_name for st in st_role.members])} "
                        f"in the meantime. Try contacting them to clear this up.",
                ephemeral=True)
        else:
            await interaction.user.add_roles(st_role)
            await self.queue_cog.user_leave_queue(interaction.user)
            await interaction.send(content="You have claimed the grimoire. Enjoy your game!", ephemeral=True)
            await self.helper.log(f"{interaction.user.mention} has claimed grimoire {self.game_number} through the queue announcement button")
            if self.helper.SecondaryOutputChannel:
                await self.helper.SecondaryOutputChannel.send(f"{interaction.user.mention} has claimed grimoire {self.game_number} through the queue announcement button")
            self.clear_items()
            self.stop()
            await interaction.message.edit(view=self)

    @nextcord.ui.button(label="Decline grimoire", custom_id="decline_grimoire", style=nextcord.ButtonStyle.red)
    async def decline_grimoire_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send(
            content="You have declined the grimoire. "
                    "Use /queue move_down if you don't want to be pinged the next time a channel becomes free.",
            ephemeral=True)
        await self.queue_cog.announce_free_channel(self.game_number, self.queue_position + 1)
        self.clear_items()
        self.stop()
        await interaction.message.edit(view=self)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id == self.queue[self.queue_position].st:
            return True
        else:
            await interaction.send(ephemeral=True, content="This announcement is not intended for you. To claim the "
                                                           "grimoire, you'll have to use the grimoire claim command.")
            return False

    async def on_timeout(self) -> None:
        game_channel = self.helper.get_game_channel(self.game_number)
        st_role = self.helper.get_st_role(self.game_number)
        if not st_role.members:
            await game_channel.send("Previous queue entry timed out")
            await self.queue_cog.announce_free_channel(self.game_number, self.queue_position + 1)


def setup(bot: commands.Bot):
    bot.add_cog(TextQueue(bot, utility.Helper(bot), bot.data.queue, bot.data.reserve))
