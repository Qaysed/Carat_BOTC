from enum import Enum
import io
import logging
import os
import re
import traceback
from typing import TypeVar, Union, Optional

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands
from nextcord.utils import get

T = TypeVar("T")

WorkingEmoji = '\U0001F504'    # 🔄
CompletedEmoji = '\U0001F955'  # 🥕
DeniedEmoji = '\U000026D4'     # ⛔
ConfusedEmoji = '\U0001F928'   # 🤨
SweatSmileEmoji = '\U0001F605' # 😅

MaxGameNumber = 15
PotentialGames = [game for n in range(1, MaxGameNumber) for game in [str(n), f"b{n}", f"x{n}", f"r{n}"]]
DeveloperIds = [962747550656528425, 966753006227955832, 224643391873482753]

class DenialReason(Enum):
    MemberCommand = f"{DeniedEmoji} This command must be used as a server member, i.e. not via DMs."
    NoPermission = f"{DeniedEmoji} You do not have the permission to use this command"
    InvalidGame = f"{ConfusedEmoji} You gave an invalid game number"
    NoTownSquare = f"{SweatSmileEmoji} The town square for that game hasn't been set up"
    NoNominationThread = f"{SweatSmileEmoji} The nomination thread hasn't been created yet"
    NoSTRole = f"{ConfusedEmoji} There is no ST role for this game"
    AlreadySTS = f"{SweatSmileEmoji} There is already someone with the ST role for this game"
    ArchiveFull = f"{SweatSmileEmoji} The archive category is full"
    InQueue = f"{ConfusedEmoji} You are already in the text game queue"
    NotInQueue = f"{ConfusedEmoji} You are not in the text game queue"
    QueueTypeNotInitialised = f"{ConfusedEmoji} Queue type not initialised"
    AlreadyReserved = f"{ConfusedEmoji} You already have an RSVP entry"
    NoReservation = f"{SweatSmileEmoji} No reservation found"
    InvalidStartDate = f"{SweatSmileEmoji} Invalid start date. Use either a number (of days), YYYY-MM-DD, MM-DD format, or nothing to set to the earliest option (2 weeks)"
    NotRSVPForum = f"{SweatSmileEmoji} You must create a post in the RSVP text game forum and use this command there to reserve a game"

def authorize_dev_command(author: Union[nextcord.Member, nextcord.User]) -> bool:
    return author.id in DeveloperIds

def get_channel_type(channel_type: str) -> Optional[str]:
    if channel_type.lower() in ['base', 'b3', 'b']:
        return "Base"
    elif channel_type.lower() in ['experimental', 'exp', 'x']:
        return "Experimental"
    elif channel_type.lower() in ['regular', 'standard', 'normal', 'r', 'n', 'reg']:
        return "Regular"
    else:
        return None


async def dm_user(user: Union[nextcord.User, nextcord.Member], content: str) -> bool:
    try:
        await user.send(content)
        return True
    except nextcord.Forbidden:
        logging.warning(f"Could not DM {user} - user has DMs disabled")
        return False
    except Exception as e:
        logging.exception(f"Could not DM {user}: {e}")
        return False


async def deny_command(ctx: commands.Context, reason: Optional[str]):
    await ctx.message.add_reaction(DeniedEmoji)
    if reason is not None:
        await dm_user(ctx.author, reason)
        logging.info(f"The {ctx.command.name} command was stopped against {ctx.author.name} because of {reason}")
    else:
        logging.info(f"The {ctx.command.name} command was stopped against {ctx.author.name}")

async def deny_app_command(interaction: nextcord.Interaction, reason: DenialReason):
    if interaction.application_command is None:
        raise ValueError("interaction.application_command is None")
    if interaction.user is None:
        raise ValueError("interaction.user is None")
    reason_str = reason.value
    logging.info(f"The {interaction.application_command.name} command by {interaction.user.name} was stopped. Reason: {reason_str}")
    if interaction.response.is_done():
        await interaction.followup.send(reason_str, ephemeral=True)
    else:
        await interaction.send(reason_str, ephemeral=True)


async def finish_processing(ctx: commands.Context):
    for reaction in ctx.message.reactions:
        if reaction.emoji == WorkingEmoji:
            async for user in reaction.users():
                if user.bot:
                    await reaction.remove(user)
    await ctx.message.add_reaction(CompletedEmoji)
    logging.info(f"The {ctx.command.name} command was used successfully by {ctx.author.name}")


async def start_processing(ctx):
    await ctx.message.add_reaction(WorkingEmoji)


def is_mention(string: str) -> bool:
    return string.startswith("<@") and string.endswith(">") and string[2:-1].isdigit()

def traceback_text(error):
    traceback_buffer = io.StringIO()
    traceback.print_exception(type(error), error, error.__traceback__, file=traceback_buffer)
    return  traceback_buffer.getvalue()

def require(value: T | None, name: str) -> T:
    if value is None:
        raise EnvironmentError(f"Failed to find required Discord entity: {name}")
    return value

class Helper:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        load_dotenv()
        self.Guild = require(get(bot.guilds, id=int(os.environ['GUILD_ID'])), "Guild")
        self.TextGamesCategory = require(get(self.Guild.categories, id=int(os.environ['TEXT_GAMES_CATEGORY_ID'])), "TextGamesCategory")
        self.ReservingForum = require(get(self.Guild.channels, id=int(os.environ['RESERVING_FORUM_CHANNEL'])), "ReservingForum")
        self.ArchiveCategory = require(get(self.Guild.categories, id=int(os.environ['ARCHIVE_CATEGORY_ID'])), "ArchiveCategory")
        self.ModRole = require(get(self.Guild.roles, id=int(os.environ['DOOMSAYER_ROLE_ID'])), "ModRole")
        self.LogChannel = require(get(self.Guild.channels, id=int(os.environ['LOG_CHANNEL_ID'])), "LogChannel")
        if not isinstance(self.LogChannel, nextcord.abc.Messageable):
            raise EnvironmentError("Log channel must be messageable")
        try:
            self.SecondaryOutputChannel = get(self.Guild.channels, id=int(os.environ['SECONDARY_OUTPUT_CHANNEL']))
        except:
            self.SecondaryOutputChannel = None
            logging.warning("Count not load secondary output channel from enviroment, continuing with it")
        if self.SecondaryOutputChannel and not isinstance(self.SecondaryOutputChannel, nextcord.abc.Messageable):
            logging.warning("Secondary output channel not messageable, continuing without it")
        self.StorageLocation = os.environ['STORAGE_LOCATION']
        self.OwnerId = int(os.environ['OWNER_ID'])

    def get_game_channel(self, number: str) -> Optional[nextcord.TextChannel]:
        if number.isdigit():  # no letters in the number
            # ensure that number occurs without being preceded by b, r, x or another digit
            # (so "1" doesn't find the x1 or 11 channel)
            # or followed by another digit (so "1" doesn't find the 10 channel)
            pattern = fr"(?<![0-9brx]){re.escape(number)}(?![0-9])"
        else:
            # ensure that number occurs without being immediately followed by another digit
            # (so "x1" doesn't find the x10 channel)
            pattern = fr"{re.escape(number)}(?![0-9])"
        matching_channels = [channel for channel in self.TextGamesCategory.text_channels
                             if re.search(pattern, channel.name) is not None]
        if len(matching_channels) == 1:
            return matching_channels[0]
        if len(matching_channels) > 1:
            logging.warning(
                f"Multiple candidates for game channel {number} found - attempting to distinguish by ST role")
            st_role = self.get_st_role(number)
            if st_role is None:
                return None
            channel = next((c for c in matching_channels if c.permissions_for(st_role).manage_threads), None)
            if channel is not None:
                return channel
        logging.info(f"Game channel {number} not found")
        return None

    def get_kibitz_channel(self, number: str) -> Optional[nextcord.TextChannel]:
        if number[0] == "r":
            name = "rsvp-kibitz-" + number[1:]
        elif number[0] == "x":
            name = "experimental-kibitz-" + number[1:]
        else:
            # b-games also follow this format
            name = "kibitz-game-" + number
        channel = get(self.Guild.channels, name=name)
        if not isinstance(channel, nextcord.TextChannel):
            logging.warning(f"Kibitz channel is unexpected type - verify the guild is set up correctly")
            return None
        if channel is None:
            logging.warning(f"Could not find kibitz channel for game {number}")
        return channel

    def get_game_role(self, number: str) -> Optional[nextcord.Role]:
        name = "game" + number
        role = get(self.Guild.roles, name=name)
        if role is None:
            logging.warning(f"Could not find game role for game {number}")
        return role

    def get_st_role(self, number: str) -> Optional[nextcord.Role]:
        name = "st" + number
        role = get(self.Guild.roles, name=name)
        if role is None:
            logging.warning(f"Could not find ST role for game {number}")
        return role

    def get_kibitz_role(self, number: str) -> Optional[nextcord.Role]:
        name = "kibitz" + number
        role = get(self.Guild.roles, name=name)
        if role is None:
            logging.warning(f"Could not find kibitz role for game {number}")
        return role

    def authorize_st_command(self, author: Union[nextcord.Member, nextcord.User], game_number: str):
        if isinstance(author, nextcord.User):
            member = get(self.Guild.members, id=author.id)
            if member is None:
                logging.warning("Non guild member attempting to use ST command")
                return False
        else:
            member = author
        return (self.ModRole in member.roles) \
            or (self.get_st_role(game_number) in member.roles) \
            or (member.id == self.OwnerId)

    def authorize_mod_command(self, author: Union[nextcord.Member, nextcord.User]):
        if isinstance(author, nextcord.User):
            member = get(self.Guild.members, id=author.id)
            if member is None:
                logging.warning("Non guild member attempting to use mod command")
                return False
            return (self.ModRole in member.roles) or (author.id == self.OwnerId)
        return (self.ModRole in author.roles) or (author.id == self.OwnerId)

    async def log(self, log_string: str):
        await self.LogChannel.send(log_string)