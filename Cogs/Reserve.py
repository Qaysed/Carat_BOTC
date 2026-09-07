import datetime
import io
import json
import logging
import traceback
from datetime import date, timedelta, time
from typing import Optional, Dict, List

import nextcord
from nextcord.ext import commands, tasks
from nextcord.utils import get, utcnow, format_dt

import utility
from Cogs.TextQueue import update_queue_message
from State.queue import Entry, QueueStore
from State.reserve import RSVPEntry, ReserveStore

green_square_emoji = '\U0001F7E9'
red_square_emoji = '\U0001F7E5'
refresh_emoji = '\U0001F504'
min_advance_days = 14


def default_game_channel_overwrites(game_role: nextcord.Role, st_role: nextcord.Role, helper: utility.Helper) \
        -> Dict[nextcord.Role, nextcord.PermissionOverwrite]:
    permissions = {}
    total_ban_role = get(helper.Guild.roles, name="tb")
    if total_ban_role is not None:
        permissions[total_ban_role] = nextcord.PermissionOverwrite(send_messages=False, send_messages_in_threads=False,
                                                                   create_public_threads=False,
                                                                   create_private_threads=False, add_reactions=False)
    game_ban_role = get(helper.Guild.roles, name="gb")
    if game_ban_role is not None:
        permissions[game_ban_role] = nextcord.PermissionOverwrite(send_messages=False, view_channel=False)
    ni_text_role = get(helper.Guild.roles, name="NIText")
    if ni_text_role is not None:
        permissions[ni_text_role] = nextcord.PermissionOverwrite(view_channel=False)
    hide_text_games_role = get(helper.Guild.roles, name="hideTextGames")
    if hide_text_games_role is not None:
        permissions[hide_text_games_role] = nextcord.PermissionOverwrite(view_channel=False)
    permissions[game_role] = nextcord.PermissionOverwrite(send_messages_in_threads=True, create_public_threads=False,
                                                          create_private_threads=True, manage_messages=True,
                                                          manage_threads=False)
    permissions[st_role] = nextcord.PermissionOverwrite(manage_channels=True, send_messages_in_threads=True,
                                                        create_public_threads=True, create_private_threads=True,
                                                        manage_messages=True, manage_threads=True)
    return permissions


async def default_kibitz_channel_overwrites(game_role: nextcord.Role,
                                            st_role: nextcord.Role,
                                            kibitz_role: nextcord.Role,
                                            helper: utility.Helper
                                            ) -> Dict[nextcord.Role, nextcord.PermissionOverwrite]:
    permissions = {}
    bot_role = get(helper.Guild.roles, name=(await helper.bot.application_info()).name)
    permissions[bot_role] = nextcord.PermissionOverwrite(view_channel=True)
    total_ban_role = get(helper.Guild.roles, name="tb")
    if total_ban_role is not None:
        permissions[total_ban_role] = nextcord.PermissionOverwrite(send_messages=False, send_messages_in_threads=False,
                                                                   create_public_threads=False,
                                                                   create_private_threads=False, add_reactions=False)
    permissions[st_role] = nextcord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
    permissions[game_role] = nextcord.PermissionOverwrite(view_channel=False, send_messages=False)
    permissions[kibitz_role] = nextcord.PermissionOverwrite(view_channel=True, send_messages=True)
    blind_role = get(helper.Guild.roles, name="blind")
    if blind_role is not None:
        permissions[blind_role] = nextcord.PermissionOverwrite(view_channel=False)
    permissions[helper.Guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
    return permissions


def parse_date(inp: str) -> Optional[date]:
    try:
        # number of days
        days = int(inp)
        return date.today() + timedelta(days=days)
    except ValueError:
        try:
            # ISO 8601
            return date.fromisoformat(inp)
        except ValueError:
            try:
                # MM-DD
                split_date = inp.split("-")
                if len(split_date) == 2:
                    today = date.today()
                    target_date = date(today.year, int(split_date[0]), int(split_date[1]))
                    if target_date < today:
                        target_date = target_date.replace(year=today.year + 1)
                    return target_date
                else:
                    return None
            except ValueError as ve:
                logging.debug(f"Attempted to parse {inp} as date and failed: {ve}")
                return None


async def create_channel(owner: int, helper: utility.Helper,
                         script: str = "", co_sts: List[int] = None, players: List[int] = None):
    # find free game number
    # (will always find one because r-channels will never be every channel in text games category)
    game_number = "r" + str(next(i for i in range(1, len(helper.TextGamesCategory.channels))
                                 if helper.get_game_channel(f"r{i}") is None))
    reason = f"Preparing reserved game {game_number}"
    # get/create roles
    game_role = helper.get_game_role(game_number)
    if game_role is None:
        logging.warning(f"Creating game role for {game_number}")
        game_role = await helper.Guild.create_role(reason=reason, name=f"game{game_number}", mentionable=True)
    st_role = helper.get_st_role(game_number)
    if st_role is None:
        logging.warning(f"Creating ST role for {game_number}")
        st_role = await helper.Guild.create_role(reason=reason, name=f"st{game_number}", mentionable=True)
    kibitz_role = helper.get_kibitz_role(game_number)
    if kibitz_role is None:
        logging.warning(f"Creating kibitz role for {game_number}")
        kibitz_role = await helper.Guild.create_role(reason=reason,
                                                     name=f"kibitz{game_number}",
                                                     mentionable=True)
    # create game channel
    game_channel = await helper.TextGamesCategory.create_text_channel(
        f"{game_number}-starting-{script}",
        reason=reason,
        overwrites=default_game_channel_overwrites(game_role, st_role, helper)
    )
    # move to correct position
    # the try except probably isn't necessary but channel positions are messy and I don't trust them
    try:
        if game_number == "r1":
            # get highest experimental channel
            earlier_channels = [helper.get_game_channel(f"x{i}") for i in range(utility.MaxGameNumber, 0, -1)]
            previous_channel = next(channel for channel in earlier_channels if channel is not None)
        else:
            # get previous r channel
            previous_channel = helper.get_game_channel("r" + str(int(game_number[1:]) - 1))
        # get next r channel
        later_channels = [helper.get_game_channel(f"r{i}") for i in
                          range(int(game_number[1:]) + 1, len(helper.TextGamesCategory.channels))]
        next_channel = next((channel for channel in later_channels if channel is not None), None)
        if previous_channel is not None:
            await game_channel.move(after=previous_channel)
        elif next_channel is not None:
            await game_channel.move(before=next_channel)
        else:
            raise Exception("Could not find previous or next channel")
    except Exception as error:
        traceback_text = traceback_text(error)
        logging.warning(f"Could not move r-game channel to desired position. Exception trace:\n{traceback_text}")

    # get/create kibitz channel
    kibitz_channel = helper.get_kibitz_channel(game_number)
    kibitz_overwrites = await default_kibitz_channel_overwrites(game_role, st_role, kibitz_role, helper)
    if kibitz_channel is None:
        logging.warning(f"Creating kibitz channel for {game_number}")
        kibitz_category = get(helper.Guild.categories, name="kibitz")
        if kibitz_category is not None:
            await kibitz_category.create_text_channel(
                f"rsvp-kibitz-{game_number[1:]}",
                reason=reason,
                overwrites=kibitz_overwrites
            )
        else:
            logging.error("Kibitz category not found")
    else:
        await kibitz_channel.edit(reason=reason, overwrites=kibitz_overwrites)
    # assign roles
    st = await helper.fetch_member(owner)
    await st.add_roles(st_role)
    co_sts = [] if co_sts is None else co_sts
    co_sts = [await helper.fetch_member(st_id) for st_id in co_sts]
    for co_st in co_sts:
        if co_st is not None:
            await co_st.add_roles(st_role)
    players = [] if players is None else players
    players = [(p_id, await helper.fetch_member(p_id)) for p_id in players]
    for p_id, player in players:
        if player is None:
            game_channel.send(f"Warning: Player with ID {p_id} could not be found")
        else:
            await player.add_roles(game_role)
    await game_channel.send(f"{st_role.mention} Channel is ready. Have fun!")
    logging.info(f"Setup for game {game_number} complete")


async def switch_to_queue(queue_store: QueueStore, helper: utility.Helper, entry: RSVPEntry, channel_type: str,
                          availability="At next opportunity"):
    thread = get(helper.ReservingForum.threads, id=entry.thread)
    queue_entry = Entry(entry.owner, entry.script, availability,
                        f"See {thread.mention}")
    queue_store.queues[channel_type].entries.append(queue_entry)
    queue_store.save()
    await update_queue_message(queue_store.queues[channel_type], helper)


async def signup_embed(entry: RSVPEntry, helper: utility.Helper) -> nextcord.Embed:
    owner = await helper.fetch_member(entry.owner)
    co_sts = [(await helper.fetch_member(st_id)).mention for st_id in entry.co_sts]
    info = f"Ran by {owner.mention}"
    if len(co_sts) > 0:
        info += "with " + ", ".join(co_sts)
    info += ", starting " + entry.date
    embed = nextcord.Embed(title=str(entry.script),
                           description=info +
                                       f"\nPress {green_square_emoji} to sign up for the game"
                                       f"\nPress {red_square_emoji} to remove yourself from the game",
                           color=0xff0000)
    for i in range(entry.max_players):
        if i < len(entry.players):
            player = await helper.fetch_member(entry.players[i])
            name = player.display_name
            embed.add_field(name=str(i + 1) + ". " + str(name),
                            value=f"{player.mention} has signed up",
                            inline=False)
        else:
            embed.add_field(name=str(i + 1) + ". ", value=" Awaiting Player", inline=False)
    return embed


class Reserve(commands.Cog):
    bot: commands.Bot
    helper: utility.Helper
    store: ReserveStore

    def __init__(self, bot: commands.Bot, helper: utility.Helper, store: ReserveStore, queue_store: QueueStore):
        self.bot = bot
        self.helper = helper
        self.bot.add_view(PreSignupView(self, helper, RSVPEntry(0, 0, "", 0)))  # registering views for persistence
        self.store = store
        self.queue_store = queue_store
        self.entries = self.store.entries
        self.announced = self.store.announced
        self.check_entries.start()

    def cog_unload(self) -> None:
        self.check_entries.cancel()

    def update_storage(self):
        self.store.save()

    def remove_entry(self, owner: int):
        self.entries.pop(owner)
        self.store.save()

    def remove_announced(self, owner: int):
        self.announced.pop(owner)
        self.store.save()

    @nextcord.slash_command(name="rsvp", description="Deals with everything RSVP entries.")
    async def reserve(self, interaction: nextcord.Interaction):
        pass

    @reserve.subcommand(name="reserve_game", description="Reserves a game for you to ST starting on the given start date (min 2 weeks).")
    async def reserve_game(self, interaction: nextcord.Interaction, 
                          min_players: int = nextcord.SlashOption(required=True, min_value=0), 
                          start: str = nextcord.SlashOption(required = True, description="Accepted date formats are YYYY-MM-DD, MM-DD or the number of days until the date.")):
        if any(entry_owner == interaction.user.id for entry_owner in self.entries):
            await utility.deny_app_command(interaction, utility.DenialReason.AlreadyReserved)
            return
        if self.queue_store.get_queue(interaction.user.id) is not None:
            await utility.deny_app_command(interaction, utility.DenialReason.InQueue)
            return
        start_date = parse_date(start)
        if start_date is None or start_date - date.today() < timedelta(days=min_advance_days):
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidStartDate)
            return
        if isinstance(interaction.channel, nextcord.Thread) and interaction.channel.parent == self.helper.ReservingForum \
                and interaction.user == interaction.channel.owner:
            await interaction.response.defer(ephemeral=True)
            self.entries[interaction.user.id] = RSVPEntry(interaction.channel.id, interaction.user.id, start_date.isoformat(), min_players)
            self.store.save()
            await interaction.followup.send(f"Registered your entry for {start_date.isoformat()}")
            await self.helper.log(f"{interaction.user.mention} has reserved an RSVP game for {start_date}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NotRSVPForum)

    @reserve.subcommand(name="signups", description="Posts a signup message for your RSVP game.")
    async def signups(self, interaction: nextcord.Interaction, 
                      max_players: int = nextcord.SlashOption(required=True), 
                      script: str = nextcord.SlashOption(required=True)):
        if interaction.user.id not in self.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
        else:
            await interaction.response.defer(ephemeral=True)
            entry = self.entries[interaction.user.id]
            entry.max_players = max_players
            entry.script = script
            self.store.save()
            embed = await signup_embed(entry, self.helper)
            thread = get(self.helper.ReservingForum.threads, id=entry.thread)
            await thread.send(embed=embed, view=PreSignupView(self, self.helper, entry))
            await interaction.followup.send(f"Sign up list sent to your forum post")

    @reserve.subcommand(name="add_st", description="Adds a co-ST to your entry.")
    async def add_st(self, interaction: nextcord.Interaction, 
                     co_st: nextcord.Member = nextcord.SlashOption(required=True)):
        if interaction.user.id not in self.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
        else:
            await interaction.response.defer(ephemeral=True)
            entry = self.entries[interaction.user.id]
            entry.co_sts.append(co_st.id)
            self.store.save()
            await interaction.followup.send(f"{co_st.display_name} added as a co-ST!")
            await self.helper.log(f"{interaction.user.mention} has added {co_st.mention} as a co-ST for their RSVP entry")

    @reserve.subcommand(name="remove_st", description="Removes a co-ST from your entry.")
    async def remove_st(self, interaction: nextcord.Interaction, 
                         co_st: nextcord.Member = nextcord.SlashOption(required=True)):
        if interaction.user.id not in self.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
        else:
            await interaction.response.defer(ephemeral=True)
            entry = self.entries[interaction.user.id]
            entry.co_sts = [st for st in entry.co_sts if co_st.id != st]
            self.store.save()
            await interaction.followup.send(f"{co_st.display_name} removed as a co-ST!")
            await self.helper.log(f"{interaction.user.mention} has removed {co_st.mention} as a co-ST for their RSVP entry")

    @reserve.subcommand(name="switch_to_queue", description="Cancels your reserved game and joins one of the queues.")
    async def switch_to_queue_command(self, interaction: nextcord.Interaction, 
                              channel_type: str = nextcord.SlashOption(required=True, choices=["Base","Regular","Experimental"]), 
                              availability: str = nextcord.SlashOption(required=True, default="ASAP")):
        if interaction.user.id not in self.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
        else:
            await interaction.response.defer(ephemeral=True)
            entry = self.entries[interaction.user.id]
            if availability is None:
                availability = f"Starting {entry.date}"
            await switch_to_queue(self.queue_store, self.helper, entry, channel_type, availability)
            self.remove_entry(interaction.user.id)
            thread = get(self.helper.ReservingForum.threads, id=entry.thread)
            await thread.send(f"This game has been moved to the {channel_type} queue")
            await interaction.followup.send(f"Your game has been move to the {channel_type} queue")
            await self.helper.log(f"{interaction.user.mention} moved their RSVP entry to the {channel_type} queue")

    @reserve.subcommand(name="cancel_game", description="Cancels your reserved game.")
    async def cancel_game(self, interaction: nextcord.Interaction):
        if interaction.user.id not in self.entries:
            await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
        else:
            await interaction.response.defer(ephemeral=True)
            thread = self.entries[interaction.user.id].thread
            self.remove_entry(interaction.user.id)
            thread = get(self.helper.ReservingForum.threads, id=thread)
            await thread.send("This game has been cancelled by the ST")
            await interaction.followup.send(f"Your game has been cancelled")
            await self.helper.log(f"{interaction.user.mention} has cancelled their RSVP game")

    @reserve.subcommand(name="list", description="Lists the reserved games starting in the next specified number of days.")
    async def list_reserve_games(self, interaction: nextcord.Interaction, 
                                 days: int = nextcord.SlashOption(required=True, min_value=0)):
        await interaction.response.defer()
        cutoff = date.today() + datetime.timedelta(days=days)
        upcoming = sorted([entry for entry in self.entries.values() if date.fromisoformat(entry.date) <= cutoff],
                          key=lambda e: e.date)
        embed = nextcord.Embed(title="Upcoming games",
                               description=f"All reserved games starting in the next {days} days")
        if self.helper.Guild.icon:
            embed.set_thumbnail(self.helper.Guild.icon.url)
        for entry in upcoming:
            owner = await self.helper.fetch_member(entry.owner)
            if owner is None:
                continue
            co_sts = [await self.helper.fetch_member(co_st) for co_st in entry.co_sts]
            co_st_names = [co_st.display_name for co_st in co_sts if co_st is not None]
            name = f"{owner.display_name} running {entry.script}" if entry.script != "TBA" else f"{owner.display_name}"
            description = f"Starting {entry.date}\n{len(entry.players)}/{entry.min_players} players signed up"
            if entry.max_players != 0:
                description += f" (max {entry.max_players} players)"
            description += f"\n{get(self.helper.ReservingForum.threads, id=entry.thread).mention}"
            if len(co_st_names) > 0:
                description = "with " + ", ".join(co_st_names) + "\n" + description
            embed.add_field(name=name, value=description, inline=False)
        await interaction.followup.send(embed=embed)

    @reserve.subcommand(name="create_game", description="Creates an 'r' channel game for a given user. Moderator only!")
    async def create_game(self, interaction: nextcord.Interaction, 
                          st: nextcord.Member = nextcord.SlashOption(required=True)):
        if await self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer()
            if st.id in self.entries:
                entry = self.entries[st.id]
                await create_channel(entry.owner, self.helper, entry.script, entry.co_sts, entry.players)
                self.remove_entry(st.id)
            elif st.id in self.announced:
                entry = self.announced[st.id]
                await create_channel(entry.owner, self.helper, entry.script, entry.co_sts, entry.players)
                self.remove_announced(st.id)
            else:
                await create_channel(st.id, self.helper)
            await interaction.followup.send(f"RSVP game created for {st.display_name}")
            await self.helper.log(f"{interaction.user.mention} has created an r channel game for {st.mention}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @reserve.subcommand(name="remove_reservation", description="Removes the reservation of the given user. Moderator only!")
    async def remove_reservation(self, interaction: nextcord.Interaction, 
                                 st: nextcord.Member = nextcord.SlashOption(required=True)):
        if await self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer(ephemeral=True)
            if st.id in self.entries:
                thread = self.entries[st.id].thread
                self.remove_entry(st.id)
            elif st.id in self.announced:
                thread = self.announced[st.id].thread
                self.remove_announced(st.id)
            else:
                await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
                return
            thread = get(self.helper.ReservingForum.threads, id=thread)
            await thread.send("This game has been cancelled")
            try: # to suppress unwanted errors with people who left the server
                await interaction.followup.send(f"You removed {st.display_name}'s reservation")
                await self.helper.log(f"{interaction.user.mention} has removed {st.mention}'s reservation")
            except:
                await interaction.followup.send(f"You removed {st.id}'s reservation")
                await self.helper.log(f"{interaction.user.mention} has removed {st.id}'s reservation")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @reserve.subcommand(name="change_start_date", description="Moderator Only! Changes the start date of the reservation of the given user.")
    async def change_start_date(self, interaction: nextcord.Interaction, 
                                st: nextcord.Member = nextcord.SlashOption(required=True), 
                                new_date: str = nextcord.SlashOption(required=True, description="Accepted date formats are YYYY-MM-DD, MM-DD or the number of days until the date.")):
        if await self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer(ephemeral=True)
            start_day = parse_date(new_date)
            if start_day is None:
                await utility.deny_app_command(interaction, utility.DenialReason.InvalidStartDate)
                return
            if st.id in self.entries:
                entry = self.entries[st.id]
                entry.date = start_day.isoformat()
                self.store.save()
            elif st.id in self.announced:
                entry = self.announced[st.id]
                entry.date = start_day.isoformat()
                self.entries[st.id] = entry
                self.remove_announced(st.id)
            else:
                await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
                return
            thread = get(self.helper.ReservingForum.threads, id=entry.thread)
            await thread.send(f"This game's start date has been changed to {entry.date}")
            await interaction.followup.send(f"Start date for {st.display_name}'s RSVP game changed to {entry.date}")
            await self.helper.log(f"{interaction.user.mention} has changed {st.mention}'s reservation start date to {start_day}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @reserve.subcommand(name="change_player_minimum", description="Changes the required number of players for the reservation of the given member. Moderator only")
    async def change_player_minimum(self, interaction: nextcord.Interaction, 
                                    st: nextcord.Member = nextcord.SlashOption(required=True), 
                                    new_min: int = nextcord.SlashOption(required=True, min_value=0)):
        if await self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer(ephemeral=True)
            if st.id in self.entries:
                entry = self.entries[st.id]
                entry.min_players = new_min
                self.store.save()
            elif st.id in self.announced:
                entry = self.announced[st.id]
                if new_min > len(entry.players) >= entry.min_players \
                        or new_min <= len(entry.players) < entry.min_players:
                    entry.min_players = new_min
                    self.entries[st.id] = entry
                    self.remove_announced(st.id)
                else:
                    await interaction.followup.send(f"The reserved game of {st.display_name} has already reached its "
                                                    f"start date and the new minimum would not affect it at this point.")
                    return
            else:
                await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
                return
            thread = get(self.helper.ReservingForum.threads, id=entry.thread)
            await thread.send(f"This game's minimum player count has been changed to {new_min}")
            await interaction.followup.send(f"Player minimum for {st.display_name}'s game changed to {new_min}")
            await self.helper.log(f"{interaction.user.mention} has changed {st.mention}'s reservation min player count to {new_min}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @reserve.subcommand(name="remove_player", description="Moderator only! Manually removes a player from a game")
    async def remove_player(self, interaction: nextcord.Interaction, 
                            player: nextcord.Member = nextcord.SlashOption(required=True), 
                            st: nextcord.Member = nextcord.SlashOption(required=True)):
        if await self.helper.authorize_mod_command(interaction.user):
            if st.id not in self.entries:
                await utility.deny_app_command(interaction, utility.DenialReason.NoReservation)
                return
            await interaction.response.defer(ephemeral=True)
            entry = self.entries[st.id] 
            entry.players = [p for p in entry.players if p != player.id]
            self.store.save()
            try: # to suppress unwanted errors with people who left the server
                await interaction.followup.send(f"{player.display_name} removed from {st.display_name}'s game, "
                                                f"you might need to refresh the sign up list for this to appear")
                await self.helper.log(f"{interaction.user.mention} has removed {player.mention} from {st.mention}'s RSVP entry")
            except:
                await interaction.followup.send(f"Player removed from {st.display_name}'s game, "
                                                f"you might need to refresh the sign up list for this to appear")
                await self.helper.log(f"{interaction.user.mention} has removed {player.id} from {st.mention}'s RSVP entry")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    # will run every day at 5 pm UTC
    # (figure that's a good choice to maximize chances of the ST seeing it not much later)
    @tasks.loop(time=time(hour=17, minute=0))
    async def check_entries(self):
        to_announce = [entry for entry in self.entries.values() if date.fromisoformat(entry.date) <= date.today()]
        if len(to_announce) > 0:
            queue_cog = self.queue_store
        for entry in to_announce:
            thread = get(self.helper.ReservingForum.threads, id=entry.thread)
            owner = await self.helper.fetch_member(entry.owner)
            if owner is None:
                await thread.send("Reserved date has arrived, but owner could not be found")
                logging.warning(f"r-game thread owner {entry.owner} for thread {entry.thread} could not be found")
                continue
            if entry.min_players <= len(entry.players):
                await thread.send(content=EnoughPlayersView.message_string(owner),
                                  view=EnoughPlayersView(self, self.helper, entry, queue_cog))
                self.remove_entry(entry.owner)
                self.announced[entry.owner] = entry
            else:
                await thread.send(content=NotEnoughPlayersView.message_string(owner),
                                  view=NotEnoughPlayersView(self, self.helper, entry, queue_cog))
                self.remove_entry(entry.owner)
                self.announced[entry.owner] = entry

    @reserve.subcommand(name="get_json", description="Developer command! Sends the user a json of all the reserve entries.")
    async def get_json(self, interaction: nextcord.Interaction):
        if utility.authorize_dev_command(interaction.user):
            json_data = {}
            for owner in self.entries:
                json_data[owner] = self.entries[owner].to_dict()
            json_str = json.dumps(json_data, indent=2)
            bytes_data = io.BytesIO(json_str.encode("utf-8"))
            await interaction.send(f"Reserve Entries json", file=nextcord.File(bytes_data, f"Entries.json"), ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)


class PreSignupView(nextcord.ui.View):
    def __init__(self, cog: Reserve, helper: utility.Helper, entry: RSVPEntry):
        super().__init__(timeout=None)
        self.cog = cog
        self.helper = helper
        self.entry = entry

    async def on_error(self, error: Exception, item: nextcord.ui.Item, interaction: nextcord.Interaction) -> None:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Ignoring exception in PreSignupView:\n{traceback_text}")

    @nextcord.ui.button(label="Sign Up", custom_id="Sign_Up_Command", style=nextcord.ButtonStyle.green)
    async def signup_pre_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id in self.entry.players:
            await interaction.send("You are already signed up", ephemeral=True)
        elif interaction.user.id == self.entry.owner or interaction.user.id in self.entry.co_sts:
            await interaction.send("You are a Storyteller for this game and so cannot sign up for it", ephemeral=True)
        elif interaction.user.bot:
            pass
        elif len(self.entry.players) >= self.entry.max_players:
            await interaction.send("The game is currently full, please contact the Storyteller", ephemeral=True)
        else:
            self.entry.players.append(interaction.user.id)
            self.cog.store.save()
            await interaction.message.edit(embed=await signup_embed(self.entry, self.helper), view=self)
            await interaction.send("You have signed up!", ephemeral=True)
            owner = await self.helper.fetch_member(self.entry.owner)
            await utility.dm_user(owner, f"{interaction.user.display_name} ({interaction.user.name}) has signed up for "
                                         f"your reserved {self.entry.script} game")
            await self.helper.log(f"{interaction.user.display_name} ({interaction.user.name}) has signed up for "
                                  f"{owner.name}'s reserved game")

    @nextcord.ui.button(label="Leave Game", custom_id="Leave_Game_Command", style=nextcord.ButtonStyle.red)
    async def leave_pre_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id not in self.entry.players:
            await interaction.send("You are not signed up", ephemeral=True)
        else:
            self.entry.players.remove(interaction.user.id)
            self.cog.store.save()
            await interaction.message.edit(embed=await signup_embed(self.entry, self.helper), view=self)
            await interaction.send("You have left the reserved game!", ephemeral=True)
            owner = await self.helper.fetch_member(self.entry.owner)
            await utility.dm_user(owner, f"{interaction.user.display_name} ({interaction.user.name}) has left your "
                                         f"reserved {self.entry.script} game")
            await self.helper.log(f"{interaction.user.display_name} ({interaction.user.name}) has left"
                                  f"{owner.name}'s reserved game")

    @nextcord.ui.button(label="Refresh List", custom_id="Refresh_List_Command", style=nextcord.ButtonStyle.grey, emoji=refresh_emoji)
    async def refresh_pre_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send(f"{refresh_emoji}Refreshing...", ephemeral=True)
        await interaction.message.edit(embed=await signup_embed(self.entry, self.helper), view=self)


class EnoughPlayersView(nextcord.ui.View):
    @staticmethod
    def message_string(owner: nextcord.Member) -> str:
        timeout = utcnow() + datetime.timedelta(seconds=172800)
        return f"{owner.mention} The date you set for your game has arrived, and you have enough players. Click " \
               f"**Create channel** to get your game channel. If you can't or won't start the game now, you can join " \
               f"the queue or cancel the game.\n" \
               f"This will time out {format_dt(timeout, 'R')} ({format_dt(timeout, 'f')})"

    def __init__(self, cog: Reserve, helper: utility.Helper, entry: RSVPEntry,
                 queue_cog: QueueStore):
        super().__init__()
        self.cog = cog
        self.helper = helper
        self.entry = entry
        self.queue_cog = queue_cog
        self.timeout = 172800  # two days

    @nextcord.ui.button(label="Create channel", custom_id="create_channel", style=nextcord.ButtonStyle.green, row=1)
    async def create_channel_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.entry.owner not in self.cog.announced:
            await interaction.send(
                ephemeral=True,
                content="Your reservation has been removed or altered. You may no longer create a channel."
            )
            return
        await interaction.send("Creating channel", ephemeral=True)
        await create_channel(self.entry.owner, self.helper, self.entry.script, self.entry.co_sts, self.entry.players)
        await self.finish(interaction)

    @nextcord.ui.button(label="Switch to queue", custom_id="switch_to_queue", style=nextcord.ButtonStyle.blurple, row=1)
    async def switch_to_queue_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        queue_buttons = [b for b in self.children
                         if isinstance(b, nextcord.ui.Button) and b.custom_id.startswith("select")]
        for b in queue_buttons:
            b.disabled = False
        await interaction.message.edit(view=self)
        await interaction.send("You have selected: Switch to queue. Choose the appropraite queue to confirm.", ephemeral=True)

    @nextcord.ui.button(label="Cancel the game", custom_id="cancel_game", style=nextcord.ButtonStyle.red, row=1)
    async def cancel_game_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        confirm_button = [b for b in self.children
                          if isinstance(b, nextcord.ui.Button) and b.custom_id == "confirm_cancellation"][0]
        confirm_button.disabled = False
        await interaction.message.edit(view=self)
        await interaction.send("You have selected: Cancel the game. Press Confirm to confirm", ephemeral=True,)

    @nextcord.ui.button(label="Base Queue", custom_id="select_base_queue", style=nextcord.ButtonStyle.blurple,
                        disabled=True, row=2)
    async def select_base_queue_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send("Joining base queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Base")
        await self.finish(interaction)

    @nextcord.ui.button(label="Regular Queue", custom_id="select_regular_queue", style=nextcord.ButtonStyle.blurple,
                        disabled=True, row=2)
    async def select_regular_queue_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send("Joining regular queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Regular")
        await self.finish(interaction)

    @nextcord.ui.button(label="Experimental Queue", custom_id="select_experimental_queue",
                        style=nextcord.ButtonStyle.blurple, disabled=True, row=2)
    async def select_experimental_queue_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send("Joining experimental queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Experimental")
        await self.finish(interaction)

    @nextcord.ui.button(label="Confirm cancellation", custom_id="confirm_cancellation", style=nextcord.ButtonStyle.red,
                        disabled=True, row=3)
    async def confirm_cancel_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send("Game cancelled")
        await self.finish(interaction)

    async def finish(self, interaction: nextcord.Interaction):
        self.clear_items()
        self.stop()
        await interaction.message.edit(view=self)
        self.cog.remove_announced(self.entry.owner)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id == self.entry.owner:
            return True
        else:
            await interaction.send("You are not the thread owner.", ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        thread = get(self.helper.ReservingForum.threads, id=self.entry.thread)
        await thread.send("Timed out")

    async def on_error(self, error: Exception, item: nextcord.ui.Item, interaction: nextcord.Interaction) -> None:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Ignoring exception in EnoughPlayersView:\n{traceback_text}")


class NotEnoughPlayersView(nextcord.ui.View):
    @staticmethod
    def message_string(owner: nextcord.Member) -> str:
        timeout = utcnow() + datetime.timedelta(seconds=172800)
        return f"{owner.mention} The date you set for your game has arrived, but unfortunately you don't have enough " \
               f"players. You can join the queue or cancel the game.\n" \
               f"This will time out {format_dt(timeout, 'R')} ({format_dt(timeout, 'f')})" \
               f"Alternatively, you can reuse this thread to reserve again for another date."

    def __init__(self, cog: Reserve, helper: utility.Helper, entry: RSVPEntry,
                 queue_cog: QueueStore):
        super().__init__()
        self.cog = cog
        self.helper = helper
        self.entry = entry
        self.queue_cog = queue_cog
        self.timeout = 172800  # two days

    @nextcord.ui.button(label="Switch to base queue", custom_id="select_base_queue", style=nextcord.ButtonStyle.blurple,
                        row=1)
    async def not_enough_select_base_queue_callback(self, button: nextcord.ui.Button,
                                                    interaction: nextcord.Interaction):
        await interaction.send("Joining base queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Base")
        await self.finish(interaction)

    @nextcord.ui.button(label="Switch to regular queue", custom_id="select_regular_queue",
                        style=nextcord.ButtonStyle.blurple, row=1)
    async def not_enough_select_regular_queue_callback(self, button: nextcord.ui.Button,
                                                       interaction: nextcord.Interaction):
        await interaction.send("Joining regular queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Regular")
        await self.finish(interaction)

    @nextcord.ui.button(label="Switch to experimental queue", custom_id="select_experimental_queue",
                        style=nextcord.ButtonStyle.blurple, row=1)
    async def not_enough_select_experimental_queue_callback(self, button: nextcord.ui.Button,
                                                            interaction: nextcord.Interaction):
        await interaction.send("Joining experimental queue")
        await switch_to_queue(self.queue_cog, self.helper, self.entry, "Experimental")
        await self.finish(interaction)

    @nextcord.ui.button(label="Cancel game", custom_id="cancel", style=nextcord.ButtonStyle.red, row=2)
    async def not_enough_cancel_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send("Game cancelled")
        await self.finish(interaction)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id == self.entry.owner:
            return True
        else:
            await interaction.send("You are not the thread owner.", ephemeral=True)
            return False

    async def on_timeout(self) -> None:
        thread = get(self.helper.ReservingForum.threads, id=self.entry.thread)
        await thread.send("Timed out")

    async def on_error(self, error: Exception, item: nextcord.ui.Item, interaction: nextcord.Interaction) -> None:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Ignoring exception in NotEnoughPlayersView:\n{traceback_text}")

    async def finish(self, interaction: nextcord.Interaction):
        self.clear_items()
        self.stop()
        await interaction.message.edit(view=self)
        self.cog.remove_announced(self.entry.owner)


def setup(bot: commands.Bot):
    bot.add_cog(Reserve(bot, utility.Helper(bot), bot.data.reserve, bot.data.queue))
