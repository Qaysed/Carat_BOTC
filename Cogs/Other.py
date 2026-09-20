import asyncio
from typing import List, Optional

import nextcord
from nextcord.ext import commands

import utility
from State.townsquare import TownSquareStore, TownSquare

class CreateThreadsModal(nextcord.ui.Modal):
    game_channel: nextcord.TextChannel
    players: List[nextcord.Member]
    sts: List[nextcord.Member]
    townSquare: Optional[TownSquare]

    def __init__(self, game_channel: nextcord.TextChannel, 
                 players: List[nextcord.Member], 
                 sts: List[nextcord.Member], 
                 townSquare: Optional[TownSquare]) -> None:
        super().__init__("Initial message")
        self.game_channel = game_channel
        self.players = players
        self.sts = sts
        self.townSquare = townSquare

        self.message = nextcord.ui.TextInput(label="Setup Message", 
                                             style=nextcord.TextInputStyle.paragraph, 
                                             placeholder="Enter a setup message that will be posted to each created thread (optional)",
                                             required=False,
                                             max_length=2000)
        self.add_item(self.message)

    async def callback(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Creating threads...", ephemeral=True)
        for player in self.players:
            name = player.display_name
            if self.townSquare is not None:
                name = next((p.alias for p in self.townSquare.players if p.id == player.id), name)
            thread = await self.game_channel.create_thread(
                    name=f"ST Thread {name}"[:100],
                    auto_archive_duration=4320,  # 3 days
                    type=nextcord.ChannelType.private_thread,
                    invitable=False,
                    reason=f"Creating ST threads"
                )
            await thread.add_user(player)
            for st in self.sts:
                await thread.add_user(st)
            if self.message.value is not None and self.message.value != "":
                await thread.send(self.message.value)
            await asyncio.sleep(10)
        await interaction.followup.send("Done")

class SendToThreadsModal(nextcord.ui.Modal): 
    game_channel: nextcord.TextChannel

    def __init__(self, game_channel: nextcord.TextChannel) -> None:
        super().__init__("Message")
        self.game_channel = game_channel

        self.message = nextcord.ui.TextInput(label="Message to send (max 2000 characters)",
                                             style=nextcord.TextInputStyle.paragraph,
                                             placeholder="Enter your message",
                                             required=True,
                                             max_length=2000)
        self.add_item(self.message)

    async def callback(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        threads = self.game_channel.threads
        for thread in threads:
            if "ST Thread" in thread.name:
                await thread.send(self.message.value)
        await interaction.followup.send("Done")
    
class Other(commands.Cog):

    def __init__(self, bot: commands.Bot, helper: utility.Helper, townsquares: TownSquareStore):
        self.bot = bot
        self.helper = helper
        self.townsquares = townsquares

    def _help_pages(self) -> dict[str, list[nextcord.Embed]]:
        """Build the slash-command help pages, grouped by their intended users."""
        def page(title: str, description: str) -> nextcord.Embed:
            return nextcord.Embed(title=title, description=description, color=0xe100ff)

        anyone = page(
            "Carat help — everyone",
            "Use Discord's `/` picker to see each command's arguments and types.\n\n"
            "**Getting a game**\n"
            "`/grimoire find` — DM all games and their current STs.\n"
            "`/grimoire claim` — Become the ST of an available game.\n"
            "`/queue join` — Join a text-game storytelling queue.\n"
            "`/queue leave` — Leave your current storytelling queue.\n"
            "`/queue move_down` — Move lower in your current queue.\n"
            "`/queue edit_entry` — Change your script and availability.\n"
            "`/queue edit_notes` — Change only your queue notes.\n\n"
            "**Reserved games**\n"
            "`/rsvp reserve_game` — Reserve a future game in your forum post.\n"
            "`/rsvp signups` — Post sign-up buttons for your reserved game.\n"
            "`/rsvp add_st` — Add a co-ST to your reservation.\n"
            "`/rsvp remove_st` — Remove a co-ST from your reservation.\n"
            "`/rsvp switch_to_queue` — Cancel reservation and join a queue.\n"
            "`/rsvp cancel_game` — Cancel your reserved game.\n"
            "`/rsvp list` — List upcoming reserved games.\n\n"
            "**Other**\n"
            "`/signups send_list` — DM a game's STs, players, and kibitzers.\n"
            "`/archive include` — Include the current thread in the archive.\n"
            "`/archive exclude` — Exclude the current thread from the archive.\n"
            "`/reminders show` — Show a game's scheduled reminders.\n"
            "`/start_whisper` / `/sw` — Create a private thread with users.\n"
            "`/help` — Show these command summaries.",
        )
        storyteller = page(
            "Carat help — storytellers",
            "These commands require the relevant game's ST role; moderators can also use them.\n\n"
            "**Game management**\n"
            "`/grimoire give` — Transfer your ST role to another user.\n"
            "`/grimoire drop` — Give up your ST role.\n"
            "`/grimoire share` — Add a co-ST without leaving the game.\n"
            "`/signups show` — Post a player sign-up sheet in-game.\n"
            "`/player add` — Add players to the game role.\n"
            "`/player remove` — Remove players from the game role.\n"
            "`/kibitz add` — Give users the kibitz role.\n"
            "`/kibitz remove` — Remove users from the kibitz role.\n"
            "`/open_kibitz` — Make a kibitz channel visible publicly.\n"
            "`/close_kibitz` — Hide a kibitz channel from the public.\n"
            "`/end_game` — Open kibitz and clean up finished game roles.\n"
            "`/archive_game` — Archive the game and create a replacement channel.\n\n"
            "**Game tools**\n"
            "`/create_threads` — Create an ST thread for every player.\n"
            "`/send_to_threads` — Send a message to every ST thread.\n"
            "`/reminders set` — Schedule reminders for a game event.\n"
            "`/reminders delete` — Delete all reminders for a game.\n"
            "`/substitute_player` — Replace a player and retain game state.",
        )
        townsquare = page(
            "Carat help — town square",
            "**Setup and nominations**\n"
            "`/setup_town_square` — Create a town square with seated players.\n"
            "`/update_town_square` — Update seating while preserving town-square state.\n"
            "`/create_nomination_thread` — Create a thread for nominations.\n"
            "`/nominate` — Start a nomination for a player.\n"
            "`/add_accusation` — Add an accusation to a nomination.\n"
            "`/add_defense` — Add a defense to a nomination.\n"
            "`/close_nomination` — Close a nomination manually.\n"
            "`/set_vote_threshold` — Set votes needed to put someone on the block.\n"
            "`/set_deadline` — Set one nomination's deadline.\n"
            "`/set_default_deadline` — Set future nominations' default deadline.\n\n"
            "**Voting**\n"
            "`/vote` — Set or change your public vote.\n"
            "`/private_vote` — Set a vote visible only to storytellers.\n"
            "`/remove_private_vote` — Use your public vote again.\n"
            "`/count_votes` — Start counting a nomination's votes.\n"
            "`/set_vote` — Set another player's vote as storyteller.\n\n"
            "**Settings**\n"
            "`/set_alias` — Set the name shown in the town square.\n"
            "`/toggle_organ_grinder` — Hide or show nomination identities.\n"
            "`/toggle_player_noms` — Allow or prevent player-run nominations.\n"
            "`/toggle_marked_dead` — Mark a player alive or dead.\n"
            "`/toggle_can_vote` — Allow or disallow a player's vote.\n"
            "`/recreate_noms` — Repost nomination messages from saved state.\n"
            "`/get_ts_status` — Show the town square's current status.\n\n"
            "Commands that change game settings require an ST.",
        )
        moderator = page(
            "Carat help — moderators",
            "`/queue initialize` — Create or reset a storytelling queue.\n"
            "`/queue remove_from_queue` — Remove a user from a queue.\n"
            "`/queue move_to_spot` — Move a user to a queue position.\n"
            "`/rsvp create_game` — Create an r-game for a user.\n"
            "`/rsvp remove_reservation` — Delete a user's reservation.\n"
            "`/rsvp change_start_date` — Change a reservation's planned start date.\n"
            "`/rsvp change_player_minimum` — Change a reservation's player requirement.\n"
            "`/rsvp remove_player` — Remove a player from a reservation.\n"
            "`/archive off_server_archive` — Copy this channel to another server archive.\n\n"
            "Developer-only data commands are intentionally omitted.",
        )
        return {
            "anyone": [anyone], "st": [storyteller], "townsquare": [townsquare],
            "mod": [moderator], "no-mod": [anyone, storyteller, townsquare],
            "all": [anyone, storyteller, townsquare, moderator],
        }

    @nextcord.slash_command(name="help", description="Shows Carat's available slash commands.")
    async def HelpMe(
            self,
            interaction: nextcord.Interaction,
            command_type: str = nextcord.SlashOption(
                name="category", description="Which commands to show", required=False,
                default="no-mod",
                choices={
                    "Commands for everyone": "anyone", "Storyteller commands": "st",
                    "Town square commands": "townsquare", "Moderator commands": "mod",
                    "Everything except moderator commands": "no-mod", "All commands": "all",
                },
            ),
    ):
        """Show category-filtered help privately to the requesting user."""
        await interaction.response.send_message(
            embeds=self._help_pages()[command_type], ephemeral=True
        )

    @nextcord.slash_command(name="start_whisper", description="Start a private thread with the chosen user(s)")
    async def StartWhisper(self, interaction: nextcord.Interaction,
                           title: str = nextcord.SlashOption(required=True, description="Thread title"),
                           p1: nextcord.Member = nextcord.SlashOption(required=False, name="player1"),
                           p2: nextcord.Member = nextcord.SlashOption(required=False, name="player2"),
                           p3: nextcord.Member = nextcord.SlashOption(required=False, name="player3"),
                           p4: nextcord.Member = nextcord.SlashOption(required=False, name="player4"),
                           p5: nextcord.Member = nextcord.SlashOption(required=False, name="player5")):
        channel = interaction.channel.parent if isinstance(interaction.channel, nextcord.Thread) else interaction.channel
        if not isinstance(channel, nextcord.TextChannel):
            await utility.deny_command(interaction, utility.DenialReason.NotATextChannel)
            return
        await interaction.response.defer()
        auth_perms = channel.permissions_for(interaction.user)
        if auth_perms.create_private_threads and auth_perms.send_messages_in_threads:
            if len(title) > 100:
                await interaction.followup.send("Thread title too long, will be shortened", ephemeral=True)
            thread = await channel.create_thread(
                name=title[:100],
                type=nextcord.ChannelType.private_thread,
                reason=f"Starting whisper for {interaction.user.display_name}"
            )
            whisperers = [p for p in [interaction.user, p1, p2, p3, p4, p5 ] if p is not None]
            for player in whisperers:
                permissions = channel.permissions_for(player)
                if permissions.send_messages_in_threads:
                    await thread.add_user(player)
                else:
                    await interaction.followup.send(f"{player.display_name} cannot send messages in threads so they "
                                                      f"were not added to \"{title}\"", ephemeral=True)
            await interaction.followup.send(f"Started whisper with {", ".join([w.display_name for w in whisperers])}")
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    # shorter alias for StartWhisper
    @nextcord.slash_command(name="sw", description="Start a private thread with the chosen user(s)")
    async def sw(self, interaction: nextcord.Interaction,
                           title: str = nextcord.SlashOption(required=True, description="Thread title"),
                           p1: nextcord.Member = nextcord.SlashOption(required=False, name="player1"),
                           p2: nextcord.Member = nextcord.SlashOption(required=False, name="player2"),
                           p3: nextcord.Member = nextcord.SlashOption(required=False, name="player3"),
                           p4: nextcord.Member = nextcord.SlashOption(required=False, name="player4"),
                           p5: nextcord.Member = nextcord.SlashOption(required=False, name="player5")):
        await self.StartWhisper(interaction, title, p1, p2, p3, p4, p5)

    @nextcord.slash_command(name="create_threads", description="Create an ST thread for each player")
    async def CreateThreads(self, interaction: nextcord.Interaction, game_number: str):
        if self.helper.authorize_st_command(interaction.user, game_number):
            game_channel = self.helper.get_game_channel(game_number)
            players = self.helper.get_game_role(game_number).members
            if game_number in self.townsquares.town_squares:
                townsquare = self.townsquares.town_squares[game_number]
            else:
                townsquare = None
            sts = self.helper.get_st_role(game_number).members
            modal = CreateThreadsModal(game_channel, players, sts, townsquare)
            await interaction.response.send_modal(modal)
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    @nextcord.slash_command(name="send_to_threads", description="Send a message to each ST thread")
    async def SendToThreads(self, interaction: nextcord.Interaction, game_number: str):
        if self.helper.authorize_st_command(interaction.user, game_number):
            game_channel = self.helper.get_game_channel(game_number)
            modal = SendToThreadsModal(game_channel)
            await interaction.response.send_modal(modal)
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)



def setup(bot: commands.Bot):
    bot.add_cog(Other(bot, utility.Helper(bot), bot.data.townsquare))
