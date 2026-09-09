from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
from math import ceil
from typing import List, Optional, Dict, Union, Callable, Literal

import nextcord
from nextcord.ext import commands
from nextcord.utils import get, utcnow, format_dt

import utility
from State.townsquare import Nomination, Player, TownSquare, TownSquareStore, Vote

not_voted_yet = "-"
confirmed_yes_vote = "confirmed_yes_vote"
confirmed_no_vote = "confirmed_no_vote"
voted_yes_emoji = '\U00002705'  # ✅
voted_no_emoji = '\U0000274C'  # ❌
clock_emoji = '\U0001f566'  # 🕦


def format_nom_message(game_role: nextcord.Role, town_square: TownSquare, nom: Nomination,
                       emoji: Dict[str, nextcord.PartialEmoji], include_game_role_mention: bool = True) -> (str, nextcord.Embed):
    if town_square.vote_threshold == 0:
        votes_needed = ceil(len([player for player in town_square.players if not player.dead]) / 2)
    else:
        votes_needed = town_square.vote_threshold
    players = reordered_players(nom, town_square)
    current_voter = next((player for player in players if player.can_vote and
                          nom.votes[player.id].vote not in [confirmed_yes_vote, confirmed_no_vote]), None)
    game_role_mention = f"{game_role.mention} " if include_game_role_mention else ""
    content = f"{game_role_mention}{nom.nominator.alias} has nominated {nom.nominee.alias}.\n" \
              f"Accusation: {nom.accusation}\n" \
              f"Defense: {nom.defense}\n" \
              f"Votes close {nom.deadline}. " \
              f"{votes_needed} votes required to put {nom.nominee.alias} on the block.\n"
    embed = nextcord.Embed(title="Votes",
                           color=0xff0000)
    counter = 0
    for player in players:
        name = player.alias + " (Nominator)" if player == nom.nominator else player.alias
        if player.dead:
            name = str(emoji["shroud"]) + " " + name
        if player == current_voter:
            name = clock_emoji + " " + name
        vote = nom.votes[player.id]
        if (not player.can_vote) and vote != confirmed_yes_vote:
            embed.add_field(name=f"~~{name}~~", value="", inline=True)
        else:
            if town_square.organ_grinder:
                embed.add_field(name=name,
                                value=str(emoji["organ_grinder"]),
                                inline=False)
            elif vote.vote == confirmed_yes_vote:
                value = 1
                if vote.thief:
                    value *= -1
                if vote.banshee:
                    value *= 2
                if vote.bureaucrat:
                    value *= 3
                counter += value
                embed.add_field(name=name,
                                value=f"{voted_yes_emoji} ({counter}/{votes_needed})",
                                inline=False)
            elif vote.vote == confirmed_no_vote:
                embed.add_field(name=name,
                                value=voted_no_emoji,
                                inline=False)
            else:
                embed.add_field(name=name,
                                value=nom.votes[player.id].vote,
                                inline=False)
    return content, embed


def reordered_players(nom: Nomination, town_square: TownSquare) -> List[Player]:
    if nom.nominee in town_square.players:
        last_vote_index = next(i for i, player in enumerate(town_square.players) if player == nom.nominee)
    elif nom.nominator in town_square.players:
        last_vote_index = next(i for i, player in enumerate(town_square.players) if player == nom.nominator)
    else:
        last_vote_index = len(town_square.players) - 1
    return town_square.players[last_vote_index + 1:] + town_square.players[:last_vote_index + 1]


class Townsquare(commands.Cog):
    bot: commands.Bot
    helper: utility.Helper
    store: TownSquareStore
    emoji: Dict[str, nextcord.PartialEmoji]

    def __init__(self, bot: commands.Bot, helper: utility.Helper, store: TownSquareStore):
        self.bot = bot
        self.helper = helper
        self.store = store
        self.emoji = {}
        self.town_squares = self.store.town_squares

    async def load_emoji(self):
        self.emoji = {}
        shroud_emoji = get(self.helper.Guild.emojis, name="shroud")
        if shroud_emoji is not None:
            self.emoji["shroud"] = nextcord.PartialEmoji.from_str('{emoji.name}:{emoji.id}'.format(emoji=shroud_emoji))
        else:
            self.emoji["shroud"] = nextcord.PartialEmoji.from_str('\U0001F480')  # 💀
            await self.helper.log("Shroud emoji not found, using default")
        thief_emoji = get(self.helper.Guild.emojis, name="thief")
        if thief_emoji is not None:
            self.emoji["thief"] = nextcord.PartialEmoji.from_str('{emoji.name}:{emoji.id}'.format(emoji=thief_emoji))
        else:
            self.emoji["thief"] = nextcord.PartialEmoji.from_str('\U0001F48E')  # 💎
            await self.helper.log("Thief emoji not found, using default")
        bureaucrat_emoji = get(self.helper.Guild.emojis, name="bureaucrat")
        if bureaucrat_emoji is not None:
            self.emoji["bureaucrat"] = nextcord.PartialEmoji.from_str(
                '{emoji.name}:{emoji.id}'.format(emoji=bureaucrat_emoji))
        else:
            self.emoji["bureaucrat"] = nextcord.PartialEmoji.from_str('\U0001f4ce')  # 📎
            await self.helper.log("Bureaucrat emoji not found, using default")
        banshee_emoji = get(self.helper.Guild.emojis, name="banshee")
        if banshee_emoji is not None:
            self.emoji["banshee"] = nextcord.PartialEmoji.from_str(
                '{emoji.name}:{emoji.id}'.format(emoji=banshee_emoji))
        else:
            self.emoji["banshee"] = nextcord.PartialEmoji.from_str('\U0001f47b')  # 👻
            await self.helper.log("Banshee emoji not found, using default")
        organ_grinder_emoji = get(self.helper.Guild.emojis, name="organ_grinder")
        if organ_grinder_emoji is not None:
            self.emoji["organ_grinder"] = nextcord.PartialEmoji.from_str(
                '{emoji.name}:{emoji.id}'.format(emoji=organ_grinder_emoji))
        else:
            self.emoji["organ_grinder"] = nextcord.PartialEmoji.from_str('\U0001f648')  # 🙈
            await self.helper.log("Organ grinder emoji not found, using default")

    async def log(self, game_number: str, message: str):
        kibitz = self.helper.get_kibitz_channel(game_number)
        log_thread = get(kibitz.threads, id=self.town_squares[game_number].log_thread)
        await log_thread.send((format_dt(utcnow()) + ": " + message)[:2000])

    def get_nomination_thread(self, game_number: str) -> nextcord.Thread:
        game_channel = self.helper.get_game_channel(game_number)
        return get(game_channel.threads, id=self.town_squares[game_number].nomination_thread)

    async def update_nom_message(self, game_number: str, nom: Nomination):
        """Keep the original nomination announcement immutable after it is posted."""
        logging.debug(f"Nomination state changed for game {game_number}: {nom}")

    async def announce_vote(self, game_number: str, voter: Player, nom: Nomination, vote: str) -> None:
        nom_thread = self.get_nomination_thread(game_number)
        await nom_thread.send(f"**{voter.alias}** voted `{vote}` on **{nom.nominee.alias}**.")

    async def announce_counted_vote(self, game_number: str, player: Player, nom: Nomination,
                                    vote: str) -> None:
        town_square = self.town_squares[game_number]
        threshold = town_square.vote_threshold or ceil(
            len([town_player for town_player in town_square.players if not town_player.dead]) / 2
        )
        count = 0
        for current_vote in nom.votes.values():
            if current_vote.vote != confirmed_yes_vote:
                continue
            value = 1
            if current_vote.thief:
                value *= -1
            if current_vote.banshee:
                value *= 2
            if current_vote.bureaucrat:
                value *= 3
            count += value
        vote_text = "yes" if vote == confirmed_yes_vote else "no"
        nom_thread = self.get_nomination_thread(game_number)
        await nom_thread.send(
            f"**{player.alias}**'s vote on **{nom.nominee.alias}** was counted as {vote_text}. ({count}/{threshold})"
        )

    def get_game_participant(self, game_number: str, identifier: str) -> Union[nextcord.Member, None]:
        participants = self.town_squares[game_number].players + self.town_squares[game_number].sts
        # handle explicit mentions
        if utility.is_mention(identifier):
            member = self.helper.Guild.get_member(int(identifier[2:-1]))
            if member is not None and member.id in [p.id for p in participants]:
                return member
            else:
                return None
        # check alternatives for identifying the player
        alias_matches = self.try_get_matching_player(participants, identifier, lambda p: p.alias)
        display_names = {p.id: (self.helper.Guild.get_member(p.id)).display_name for p in participants}
        display_name_matches = self.try_get_matching_player(participants, identifier, lambda p: display_names[p.id])
        usernames = {p.id: (self.helper.Guild.get_member(p.id)).name for p in participants}
        username_matches = self.try_get_matching_player(participants, identifier, lambda p: usernames[p.id])
        if len(alias_matches) == 1:
            target_id = alias_matches[0]
        elif len(alias_matches) > 1:
            if len(set(alias_matches).intersection(set(display_name_matches))) == 1:
                target_id = list(set(alias_matches).intersection(set(display_name_matches)))[0]
            elif len(set(alias_matches).intersection(set(username_matches))) == 1:
                target_id = list(set(alias_matches).intersection(set(username_matches)))[0]
            elif len(set(display_name_matches).intersection(set(display_name_matches)).intersection(
                    set(username_matches))) == 1:
                target_id = list(set(display_name_matches).intersection(set(display_name_matches)).intersection(
                    set(username_matches)))[0]
            else:
                return None
        elif len(display_name_matches) == 1:
            target_id = display_name_matches[0]
        elif len(display_name_matches) > 1:
            if len(set(display_name_matches).intersection(set(username_matches))) == 1:
                target_id = list(set(display_name_matches).intersection(set(username_matches)))[0]
            else:
                return None
        elif len(username_matches) == 1:
            target_id = username_matches[0]
        else:
            return None
        return self.helper.Guild.get_member(target_id)

    @staticmethod
    def try_get_matching_player(player_list: List[Player], identifier: str, attribute: Callable[[Player], str]) \
            -> List[int]:
        matches = [p.id for p in player_list if identifier.lower() in attribute(p).lower()]
        if len(matches) > 1:
            matches = [p.id for p in player_list if attribute(p).lower().startswith(identifier.lower())]
            if len(matches) < 1:
                matches = [p.id for p in player_list if identifier in attribute(p)]
            elif len(matches) > 1:
                matches = [p.id for p in player_list if attribute(p).startswith(identifier)]
                if len(matches) < 1:
                    matches = [p.id for p in player_list if attribute(p).lower() == identifier.lower()]
                elif len(matches) > 1:
                    matches = [p.id for p in player_list if attribute(p) == identifier]
        return matches

    @nextcord.slash_command(name="setup_town_square")
    async def SetupTownSquare(self, interaction: nextcord.Interaction, game_number: str,
                              player1: nextcord.Member, player2: Optional[nextcord.Member] = None,
                              player3: Optional[nextcord.Member] = None, player4: Optional[nextcord.Member] = None,
                              player5: Optional[nextcord.Member] = None, player6: Optional[nextcord.Member] = None,
                              player7: Optional[nextcord.Member] = None, player8: Optional[nextcord.Member] = None,
                              player9: Optional[nextcord.Member] = None, player10: Optional[nextcord.Member] = None,
                              player11: Optional[nextcord.Member] = None, player12: Optional[nextcord.Member] = None,
                              player13: Optional[nextcord.Member] = None, player14: Optional[nextcord.Member] = None,
                              player15: Optional[nextcord.Member] = None, player16: Optional[nextcord.Member] = None,
                              player17: Optional[nextcord.Member] = None, player18: Optional[nextcord.Member] = None,
                              player19: Optional[nextcord.Member] = None, player20: Optional[nextcord.Member] = None):
        players = [player for player in (player1, player2, player3, player4, player5, player6, player7,
                                          player8, player9, player10, player11, player12, player13, player14,
                                          player15, player16, player17, player18, player19, player20)
                   if player is not None]
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            player_list = [Player(player.id, player.display_name) for player in players]
            st_list = [Player(st.id, st.display_name) for st in self.helper.get_st_role(game_number).members]
            self.town_squares[game_number] = TownSquare(player_list, st_list)
            kibitz = self.helper.get_kibitz_channel(game_number)
            try:
                log_thread = await kibitz.create_thread(
                    name="Nomination & Vote Logging Thread",
                    auto_archive_duration=4320,
                    type=nextcord.ChannelType.private_thread)
            except nextcord.HTTPException:
                old_logging_threads = [thread for thread in kibitz.threads if thread.name == "Nomination & Vote Logging Thread"]
                old_logging_threads.sort(key=lambda thread: thread.create_timestamp)
                try:
                    await old_logging_threads[0].delete()
                    log_thread = await kibitz.create_thread(
                        name="Nomination & Vote Logging Thread",
                        auto_archive_duration=4320,
                        type=nextcord.ChannelType.private_thread)
                except nextcord.HTTPException:
                    self.town_squares.pop(game_number)
                    await utility.deny_command(interaction, "Failed to create logging thread.")
                    return
            for st in self.helper.get_st_role(game_number).members:
                await log_thread.add_user(st)
            self.town_squares[game_number].log_thread = log_thread.id
            await self.log(game_number, f"Town square created: {self.town_squares[game_number]}")
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    @nextcord.slash_command(name="update_town_square")
    async def UpdateTownSquare(self, interaction: nextcord.Interaction, game_number: str,
                               player1: nextcord.Member, player2: Optional[nextcord.Member] = None,
                               player3: Optional[nextcord.Member] = None, player4: Optional[nextcord.Member] = None,
                               player5: Optional[nextcord.Member] = None, player6: Optional[nextcord.Member] = None,
                               player7: Optional[nextcord.Member] = None, player8: Optional[nextcord.Member] = None,
                               player9: Optional[nextcord.Member] = None, player10: Optional[nextcord.Member] = None,
                               player11: Optional[nextcord.Member] = None, player12: Optional[nextcord.Member] = None,
                               player13: Optional[nextcord.Member] = None, player14: Optional[nextcord.Member] = None,
                               player15: Optional[nextcord.Member] = None, player16: Optional[nextcord.Member] = None,
                               player17: Optional[nextcord.Member] = None, player18: Optional[nextcord.Member] = None,
                               player19: Optional[nextcord.Member] = None, player20: Optional[nextcord.Member] = None):
        players = [player for player in (player1, player2, player3, player4, player5, player6, player7,
                                          player8, player9, player10, player11, player12, player13, player14,
                                          player15, player16, player17, player18, player19, player20)
                   if player is not None]
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            new_player_list = [self.reuse_or_convert_player(player, game_number) for player in players]
            removed_players = [player for player in self.town_squares[game_number].players if player not in new_player_list]
            added_players = [player for player in new_player_list if player not in self.town_squares[game_number].players]
            self.town_squares[game_number].players = new_player_list
            for nom in [nomination for nomination in self.town_squares[game_number].nominations if not nomination.finished]:
                if nom.nominator in removed_players or nom.nominee in removed_players:
                    nom.finished = True
                for player in removed_players:
                    nom.votes.pop(player.id)
                for player in added_players:
                    nom.votes[player.id] = Vote(not_voted_yet)
                await self.update_nom_message(game_number, nom)
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user.mention} has updated the town square: {new_player_list}")
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    def reuse_or_convert_player(self, player: nextcord.Member, game_number: str) -> Player:
        existing_player = next((p for p in self.town_squares[game_number].players if p.id == player.id), None)
        if existing_player:
            return existing_player
        else:
            return Player(player.id, player.display_name)

    @nextcord.slash_command(name="substitute_player")
    async def SubstitutePlayer(self, interaction: nextcord.Interaction, game_number: str, player: nextcord.Member,
                               substitute: nextcord.Member):
        """Exchanges a player in the town square with a substitute.
        Transfers the position, status, nominations and votes of the exchanged player to the substitute, adds the
        substitute to all threads the exchanged player was in, and adds/removes the game role.
        Can be used without the town square."""
        if game_number not in self.town_squares:
            await self.SubstitutePlayerNoTownsquare(interaction, game_number, player, substitute)
            return
        player_left_server = False
        if not type(player) == nextcord.Member:
            player = next((p for p in self.town_squares[game_number].players if str(p.id) == player or 
                           p.alias == player), None)
            if player is None:
                await utility.deny_command(interaction,
                "Player could not be determined. Please mention the player or input their user ID or alias.")
                return
            current_player = await self.helper.fetch_member(player.id)
            if current_player == None:
                player_left_server = True
            else:
                player = current_player
        if player_left_server:
            await self.SubstitutePlayerLeftServer(interaction, game_number, player, substitute)
            return
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            player_list = self.town_squares[game_number].players
            current_player = next((p for p in player_list if p.id == player.id), None)
            substitute_existing_player = next((p for p in player_list if p.id == substitute.id), None)
            if substitute_existing_player is not None:
                await utility.deny_command(interaction, f"{substitute.display_name} is already a player.")
                return
            if current_player is None:
                st_list = self.town_squares[game_number].sts
                current_st = next((st for st in st_list if st.id == player.id), None)
                if not current_st:
                    await utility.deny_command(interaction, f"{player.display_name} is not a participant.")
                    return
                current_st.id = substitute.id
                current_st.alias = substitute.display_name
            else:
                game_role = self.helper.get_game_role(game_number)
                await player.remove_roles(game_role, reason="substituted out")
                await substitute.add_roles(game_role, reason="substituted in")
                current_player.id = substitute.id
                current_player.alias = substitute.display_name
                game_channel = self.helper.get_game_channel(game_number)
                for thread in game_channel.threads:
                    thread_members = await thread.fetch_members()
                    if player in [tm.member for tm in thread_members]:
                        await thread.add_user(substitute)
                        await asyncio.sleep(10)
                for nom in [n for n in self.town_squares[game_number].nominations if not n.finished]:
                    nom.votes[substitute.id] = nom.votes.pop(player.id)
                    await self.update_nom_message(game_number, nom)
            await self.log(game_number, f"{interaction.user.mention} has substituted {player.display_name} with "
                                        f"{substitute.display_name}")
            logging.debug(f"Substituted {player} with {substitute} in game {game_number} - "
                          f"current town square: {self.town_squares[game_number]}")
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You are not the storyteller for this game")

    async def SubstitutePlayerNoTownsquare(self, interaction: nextcord.Interaction, game_number: str, player: nextcord.Member,
                                           substitute: nextcord.Member):
        game_role = self.helper.get_game_role(game_number)
        if game_role not in player.roles:
            await utility.deny_command(interaction, f"{player.display_name} is not a player.")
            return
        elif game_role in substitute.roles:
            await utility.deny_command(interaction, f"{substitute.display_name} is already a player.")
            return
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            await player.remove_roles(game_role, reason="substituted out")
            await substitute.add_roles(game_role, reason="substituted in")
            game_channel = self.helper.get_game_channel(game_number)
            for thread in game_channel.threads:
                thread_members = await thread.fetch_members()
                if player in [tm.member for tm in thread_members]:
                    await thread.add_user(substitute)
                    await asyncio.sleep(10)
            logging.debug(f"Substituted {player} with {substitute} in game {game_number}")
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You are not the storyteller for this game")

    async def SubstitutePlayerLeftServer(self, interaction: nextcord.Interaction, game_number: str, player: Player,
                                         substitute: nextcord.Member):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            player_list = self.town_squares[game_number].players
            substitute_existing_player = next((p for p in player_list if p.id == substitute.id), None)
            if substitute_existing_player is not None:
                await utility.deny_command(interaction, f"{substitute.display_name} is already a player.")
                return
            else:
                game_role = self.helper.get_game_role(game_number)
                await substitute.add_roles(game_role, reason="substituted in")
                old_player_id = player.id
                old_player_alias = player.alias
                player.id = substitute.id
                player.alias = substitute.display_name
                for nom in [n for n in self.town_squares[game_number].nominations if not n.finished]:
                    nom.votes[substitute.id] = nom.votes.pop(old_player_id)
                    await self.update_nom_message(game_number, nom)
            await self.log(game_number, f"{interaction.user.mention} has substituted {old_player_alias} with "
                                        f"{substitute.display_name}")
            logging.debug(f"Substituted {old_player_alias} with {substitute.display_name} in game {game_number} - "
                          f"current town square: {self.town_squares[game_number]}")
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You are not the storyteller for this game")

    @nextcord.slash_command(name="create_nomination_thread")
    async def CreateNominationThread(self, interaction: nextcord.Interaction, game_number: str, name: Optional[str]):
        """Creates a thread for nominations to be run in.
        The name of the thread is optional, with `Nominations` as default."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            if name is not None and len(name) > 100:
                await utility.dm_user(interaction.user, "Thread name is too long, will be shortened")
            game_channel = self.helper.get_game_channel(game_number)
            thread = await game_channel.create_thread(name=name[:100] if name is not None else "Nominations",
                                                      auto_archive_duration=4320,
                                                      type=nextcord.ChannelType.public_thread)
            for st in self.helper.get_st_role(game_number).members:
                await thread.add_user(st)
            self.town_squares[game_number].nomination_thread = thread.id
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You are not the storyteller for this game")

    @nextcord.slash_command(name="nominate")
    async def Nominate(self, interaction: nextcord.Interaction, game_number: str,
                       nominee_identifier: str, nominator_identifier: Optional[str]):
        """Create a nomination for the given nominee.
        If you are an ST, provide the nominator. If you are a player, leave the nominator out or give yourself.
        In either case, you don't need to ping, a name should work."""
        await interaction.response.defer()
        game_role = self.helper.get_game_role(game_number)
        # check permission
        can_nominate = self.helper.authorize_st_command(interaction.user, game_number) or game_role in interaction.user.roles
        nominee = self.get_game_participant(game_number, nominee_identifier)
        nominator = self.get_game_participant(game_number, nominator_identifier) if nominator_identifier else None
        game_channel = self.helper.get_game_channel(game_number)
        nom_thread = game_channel.get_thread(self.town_squares[game_number].nomination_thread)
        if not can_nominate:
            await utility.deny_command(interaction, "You must participate in the game to nominate!")
        elif not self.helper.authorize_st_command(interaction.user,
                                                  game_number) and nominator and nominator.id != interaction.user.id:
            await utility.deny_command(interaction, "You may not nominate in the name of others")
        elif nominator_identifier and not nominator:
            await utility.deny_command(interaction, "The nominator must be a game participant")
        elif not nominee:  # Atheist allows ST to be nominated
            await utility.deny_command(interaction, "The nominee must be a game participant")
        elif not nom_thread:
            await utility.deny_command(interaction, "The nomination thread has not been created. Ask an ST to fix this.")
        elif any([nominee.id == nom.nominee.id and not nom.finished for nom in
                  self.town_squares[game_number].nominations]):
            await utility.deny_command(interaction, "That player has already been nominated")
        else:
            participants = self.town_squares[game_number].players + self.town_squares[game_number].sts
            converted_nominee = next((p for p in participants if p.id == nominee.id), None)
            if not converted_nominee:
                await utility.deny_command(interaction,
                                           "The Nominee is not included in the town square. Ask an ST to fix this.")
            if not nominator_identifier:
                converted_nominator = next((p for p in participants if p.id == interaction.user.id), None)
            else:
                converted_nominator = next((p for p in participants if p.id == nominator.id), None)
            if not converted_nominator:
                await utility.deny_command(interaction,
                                           "The Nominator is not included in the town square. Ask an ST to fix this.")
            votes = {}
            for player in self.town_squares[game_number].players:
                votes[player.id] = Vote(not_voted_yet)
            deadline = utcnow() + datetime.timedelta(seconds=self.town_squares[game_number].default_nomination_duration)
            nom = Nomination(converted_nominator, converted_nominee, votes, format_dt(deadline, "R"))

            content, embed = format_nom_message(game_role, self.town_squares[game_number], nom, self.emoji)
            nom_message = await nom_thread.send(content=content, embed=embed)
            nom.message = nom_message.id
            self.town_squares[game_number].nominations.append(nom)
            logging.debug(f"Nomination created: in game {game_number}: {nom}")
            await interaction.followup.send("Done", ephemeral=True)
            self.store.save()
            await self.log(game_number, f"{converted_nominator.alias} has nominated {converted_nominee.alias}")

    @nextcord.slash_command(name="add_accusation")
    async def AddAccusation(self, interaction: nextcord.Interaction, game_number: str, accusation: str,
                            nominee_identifier: Optional[str]):
        """Add an accusation to the nomination of the given nominee.
        You don't need to ping, a name should work. You must be the nominator or a storyteller for this."""
        if len(accusation) > 900:
            await utility.deny_command(interaction, "Your accusation is too long. Consider posting it in public and "
                                            "setting a link to the message as your accusation.")
            return
        await interaction.response.defer()
        if nominee_identifier:
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
        else:
            nom = next((n for n in self.town_squares[game_number].nominations
                        if n.nominator.id == interaction.user.id and not n.finished), None)
        if not nom:
            await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
            return
        if interaction.user.id == nom.nominator.id or self.helper.authorize_st_command(interaction.user, game_number):
            nom.accusation = accusation
            self.store.save()
            nom_thread = self.get_nomination_thread(game_number)
            await nom_thread.send(f"{nom.nominator.alias} provided an accusation against {nom.nominee.alias}:\n"
                                  f"{accusation}")
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user} has added this accusation to the nomination of "
                                        f"{nom.nominee.alias}: {accusation}")
        else:
            await utility.deny_command(interaction, "You must be the ST or nominator to use this command")

    @nextcord.slash_command(name="add_defense")
    async def AddDefense(self, interaction: nextcord.Interaction, game_number: str, defense: str,
                         nominee_identifier: Optional[str]):
        """Add a defense to your nomination or that of the given nominee.
        You must be a storyteller for the latter."""
        if len(defense) > 900:
            await utility.deny_command(interaction, "Your defense is too long. Consider posting it in public and "
                                            "setting a link to the message as your defense.")
            return
        await interaction.response.defer()
        if nominee_identifier:
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
        else:
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == interaction.user.id and not n.finished), None)
        if not nom:
            await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
            return
        if interaction.user.id == nom.nominee.id or self.helper.authorize_st_command(interaction.user, game_number):
            nom.defense = defense
            self.store.save()
            nom_thread = self.get_nomination_thread(game_number)
            await nom_thread.send(f"{nom.nominee.alias} provided a defense statement:\n"
                                  f"{defense}")
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number,
                           f"{interaction.user} has added this defense to the nomination of {nom.nominee.alias}: {defense}")
        else:
            await utility.deny_command(interaction, "You must be the ST or nominee to use this command")

    @nextcord.slash_command(name="set_vote_threshold")
    async def SetVoteThreshold(self, interaction: nextcord.Interaction, game_number: str, target: int):
        """Set the vote threshold to put a player on the block to the given number.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            if target < 0:
                await utility.deny_command(interaction, "Vote threshold cannot be negative")
                return
            self.town_squares[game_number].vote_threshold = target
            for nom in [nom for nom in self.town_squares[game_number].nominations if not nom.finished]:
                await self.update_nom_message(game_number, nom)
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user} has set the vote threshold to {target}")

    @nextcord.slash_command(name="set_deadline")
    async def SetDeadline(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str, time_in_h: float):
        """Set the deadline for the nomination of a given nominee to the given number of hours from now.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            time = datetime.timedelta(hours=time_in_h)
            if utcnow() + time < utcnow():
                await utility.deny_command(interaction, "Deadline must be in the future")
                return
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
            if not nom:
                await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                return
            nom.deadline = format_dt(utcnow() + time, "R")
            self.store.save()
            await self.update_nom_message(game_number, nom)
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user} has set the deadline for the nomination of {nom.nominee.alias} "
                                        f"to {format_dt(utcnow() + time)}")
        else:
            await utility.deny_command(interaction, "You must be the ST to use this command")

    @nextcord.slash_command(name="set_default_deadline")
    async def SetDefaultDeadline(self, interaction: nextcord.Interaction, game_number: str, hours: int):
        """Set the default nomination duration for the game to the given number of hours.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            if hours < 0:
                await utility.deny_command(interaction, "Deadline must be in the future")
                return
            self.town_squares[game_number].default_nomination_duration = hours * 3600
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You must be the ST to use this command")

    @nextcord.slash_command(name="vote")
    async def Vote(self, interaction: nextcord.Interaction, game_number: str, nominee_identifiers: str, vote: str):
        """Set your vote for the given nominee or nominees.
        You don't need to ping, name(s) should work.
        Your vote can be anything, but should be something the ST can unambiguously interpret as yes or no when they
        count it. You can change your vote until it is counted by the storyteller."""
        nominee_identifiers = [identifier.strip() for identifier in nominee_identifiers.split(",") if identifier.strip()]
        if not nominee_identifiers:
            await utility.deny_command(interaction, "You must provide at least one nominee")
            return
        game_role = self.helper.get_game_role(game_number)
        if not game_role:
            await utility.deny_command(interaction, f"Game '{game_number}' does not exist")
            return
        if len(vote) > 400:
            await utility.deny_command(interaction, "Your vote is too long. Consider simplifying your condition. If that is "
                                            "somehow impossible, just let the ST know.")
            return
        voter = next((p for p in self.town_squares[game_number].players if p.id == interaction.user.id), None)
        if not voter:
            await utility.deny_command(interaction, "You are not included in the town square. Ask the ST to correct this.")
            return
        if not voter.can_vote:
            await utility.deny_command(interaction, "You seem to have spent your vote already.")
            return
        if vote in [confirmed_yes_vote, confirmed_no_vote, not_voted_yet]:
            await utility.deny_command(interaction, "Nice try. That's a reserved string for internal handling, "
                                            "you cannot set your vote to it.")
            return
        if game_role in interaction.user.roles:
            await interaction.response.defer(ephemeral=True)
            for nominee_identifier in nominee_identifiers:
                nominee = self.get_game_participant(game_number, nominee_identifier)
                if not nominee:
                    await utility.deny_command(interaction,
                                          f"Could not clearly identify any player from {nominee_identifier}")
                    continue
                nom = next((n for n in self.town_squares[game_number].nominations if
                            n.nominee.id == nominee.id and not n.finished), None)
                if not nom:
                    await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                    continue
                if nom.votes[voter.id].vote in [confirmed_yes_vote, confirmed_no_vote]:
                    await utility.deny_command(interaction, f"Your vote on {nominee_identifier} is already locked in and "
                                                      f"cannot be changed.")
                    continue
                nom.votes[voter.id] = Vote(vote)
                if not self.town_squares[game_number].organ_grinder:
                    await self.announce_vote(game_number, voter, nom, vote)
                await self.log(game_number,
                               f"{interaction.user} has set their vote on the nomination of {nom.nominee.alias} to {vote}")
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
        else:
            await utility.deny_command(interaction, "You must be a player to vote. "
                                            "If you are, the ST may have to add you to the town square.")

    @nextcord.slash_command(name="private_vote")
    async def PrivateVote(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str, vote: str):
        """Same as >Vote, but your vote will be hidden from other players.
        They will still see whether you voted yes or no after your vote is counted. A private vote will always override
        any public vote, even later ones. If you want your public vote to be counted instead,
        you can change your private vote accordingly or use >RemovePrivateVote."""
        game_role = self.helper.get_game_role(game_number)
        if game_role in interaction.user.roles:
            await interaction.response.defer()
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
            voter = next((p for p in self.town_squares[game_number].players if p.id == interaction.user.id), None)
            if not nom:
                await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                return
            if not voter:
                await utility.deny_command(interaction,
                                           "You are not included in the town square. Ask the ST to correct this.")
                return
            if nom.votes[voter.id].vote in [confirmed_yes_vote, confirmed_no_vote]:
                await utility.deny_command(interaction, "Your vote is already locked in and cannot be changed.")
                return
            if not voter.can_vote:
                await utility.deny_command(interaction, "You seem to have spent your vote already.")
                return
            if vote in [confirmed_yes_vote, confirmed_no_vote, not_voted_yet]:
                await utility.deny_command(interaction, "Nice try. That's a reserved string for internal handling, "
                                                "you cannot set your vote to it.")
                return
            nom.private_votes[voter.id] = vote
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number,
                           f"{interaction.user} has set a private vote on the nomination of {nom.nominee.alias} as {vote}")
        else:
            await utility.deny_command(interaction, "You must be a player to vote. "
                                            "If you are, the ST may have to add you to the town square.")

    @nextcord.slash_command(name="remove_private_vote")
    async def RemovePrivateVote(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str):
        """Removes your private vote for the given nominee, so that your public vote is counted instead."""
        game_role = self.helper.get_game_role(game_number)
        if game_role in interaction.user.roles:
            await interaction.response.defer()
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
            voter = next((p for p in self.town_squares[game_number].players if p.id == interaction.user.id), None)
            if not nom:
                await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                return
            if not voter:
                await utility.deny_command(interaction,
                                           "You are not included in the town square. Ask the ST to correct this.")
                return
            private_vote = nom.private_votes.pop(voter.id, None)
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            if private_vote:
                await utility.dm_user(interaction.user, f"Your private vote on the nomination of {nom.nominee.alias} "
                                                  f"has been removed.")
            else:
                await utility.dm_user(interaction.user, f"You have no private vote on the nomination of {nom.nominee.alias}.")
            await self.log(game_number,
                           f'{interaction.user} has removed their private vote, "{private_vote}", '
                           f'on the nomination of {nom.nominee.alias}')
        else:
            await utility.deny_command(interaction, "You must be a player to vote. "
                                            "If you are, the ST may have to add you to the town square.")

    @nextcord.slash_command(name="count_votes")
    async def CountVotes(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str):
        """Start a private, per-player modal flow for counting an active nomination."""
        if not self.helper.authorize_st_command(interaction.user, game_number):
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)
            return
        nominee = self.get_game_participant(game_number, nominee_identifier)
        if not nominee:
            await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
            return
        nom = next((nomination for nomination in self.town_squares[game_number].nominations
                    if nomination.nominee.id == nominee.id and not nomination.finished), None)
        if not nom:
            await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
            return
        session = CountVoteSession(self, nom, interaction.user, game_number)
        await interaction.response.send_modal(CountVoteModal(session))

    @nextcord.slash_command(name="set_vote")
    async def SetVote(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str, voter_identifier: str,
                      vote: Optional[str]):
        """Sets the vote on the given nominee for the given voter to the given vote. If no vote is given, it is simply
        reset. You must be a storyteller for this. Note that you cannot lock a vote in this way."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            voter = self.get_game_participant(game_number, voter_identifier)
            if not voter:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {voter_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
            if not nom:
                await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                return
            if not vote:
                vote = not_voted_yet
            nom.votes[voter.id] = Vote(vote)
            await self.update_nom_message(game_number, nom)
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user} has set the vote of {voter.name} on the nomination of "
                                        f"{nom.nominee.alias}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to reset a vote")

    @nextcord.slash_command(name="close_nomination")
    async def CloseNomination(self, interaction: nextcord.Interaction, game_number: str, nominee_identifier: str):
        """Marks the nomination for the given nominee as closed.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            nominee = self.get_game_participant(game_number, nominee_identifier)
            if not nominee:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
                return
            nom = next((n for n in self.town_squares[game_number].nominations if
                        n.nominee.id == nominee.id and not n.finished), None)
            if not nom:
                await utility.deny_command(interaction, f"No relevant nomination found for nominee {nominee_identifier}")
                return
            else:
                nom.finished = True
                self.store.save()
                await interaction.followup.send("Done", ephemeral=True)
                await self.log(game_number, f"{interaction.user} has closed the nomination of {nom.nominee.alias}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to close a nomination")

    @nextcord.slash_command(name="set_alias")
    async def SetAlias(self, interaction: nextcord.Interaction, game_number: str, alias: str):
        """Set your preferred alias for the given game.
        This will be used anytime the bot refers to you. The default is your username.
        Can be used by players and storytellers."""
        game_role = self.helper.get_game_role(game_number)
        st_role = self.helper.get_st_role(game_number)
        if len(alias) > 100 or utility.is_mention(alias):
            await utility.deny_command(interaction, f"not an allowed alias: {alias}"[:2000])
            return
        if game_role in interaction.user.roles:
            await interaction.response.defer()
            player = next((p for p in self.town_squares[game_number].players if p.id == interaction.user.id), None)
            if not player:
                await utility.deny_command(interaction,
                                           "You are not included in the town square. Ask the ST to correct this.")
                return
            player.alias = alias
            self.store.save()
            await self.log(game_number, f"{interaction.user.name} has set their alias to {alias}")
            await interaction.followup.send("Done", ephemeral=True)
        elif st_role in interaction.user.roles:
            await interaction.response.defer()
            st = next((st for st in self.town_squares[game_number].sts if st.id == interaction.user.id), None)
            if not st:
                await utility.deny_command(interaction, "Something went wrong and you are not included in the townsquare. "
                                                "Try dropping and re-adding the grimoire")
                return
            st.alias = alias
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await self.log(game_number, f"{interaction.user.name} has set their alias to {alias}")
        else:
            await utility.deny_command(interaction, "You must be a player to set your alias. "
                                            "If you are, the ST may have to add you to the town square.")

    @nextcord.slash_command(name="toggle_organ_grinder")
    async def ToggleOrganGrinder(self, interaction: nextcord.Interaction, game_number: str):
        """Activates or deactivates Organ Grinder for the display of nominations in the game.
        Finished nominations are not updated.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            self.town_squares[game_number].organ_grinder = not self.town_squares[game_number].organ_grinder
            self.store.save()
            for nom in self.town_squares[game_number].nominations:
                if not nom.finished:
                    await self.update_nom_message(game_number, nom)
            await interaction.followup.send("Done", ephemeral=True)
            await utility.dm_user(interaction.user,
                                  f"Organ Grinder is now "
                                  f"{'enabled' if self.town_squares[game_number].organ_grinder else 'disabled'}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to toggle the Organ Grinder")

    @nextcord.slash_command(name="toggle_player_noms")
    async def TogglePlayerNoms(self, interaction: nextcord.Interaction, game_number: str):
        """Activates or deactivates the ability of players to nominate directly.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            if game_number not in self.town_squares:
                await utility.deny_command(interaction, "Town square not set up yet.")
                return
            self.town_squares[game_number].player_noms_allowed = not self.town_squares[game_number].player_noms_allowed
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await utility.dm_user(interaction.user,
                                  f"Player nominations are now "
                                  f"{'enabled' if self.town_squares[game_number].player_noms_allowed else 'disabled'}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to toggle player nominations")

    @nextcord.slash_command(name="toggle_marked_dead")
    async def ToggleMarkedDead(self, interaction: nextcord.Interaction, game_number: str, player_identifier: str):
        """Marks the given player as dead or alive for display on nominations.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            player_user = self.get_game_participant(game_number, player_identifier)
            if not player_user:
                await utility.deny_command(interaction, f"Could not find player with identifier {player_identifier}")
                return
            player = next((p for p in self.town_squares[game_number].players if p.id == player_user.id), None)
            if not player:
                await utility.deny_command(interaction, f"{player_user.display_name} is not included in the town square.")
                return
            player.dead = not player.dead
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await utility.dm_user(interaction.user, f"{player.alias} is now "
                                              f"{'marked as dead' if player.dead else 'marked as living'}")
            await self.log(game_number, f"{interaction.user} has marked {player.alias} as "
                                        f"{'dead' if player.dead else 'living'}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to mark a player as dead")

    @nextcord.slash_command(name="toggle_can_vote")
    async def ToggleCanVote(self, interaction: nextcord.Interaction, game_number: str, player_identifier: str):
        """Allows or disallows the given player to vote.
        You must be a storyteller for this."""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            player_user = self.get_game_participant(game_number, player_identifier)
            if not player_user:
                await utility.deny_command(interaction, f"Could not clearly identify any player from {player_identifier}")
                return
            player = next((p for p in self.town_squares[game_number].players if p.id == player_user.id), None)
            if not player:
                await utility.deny_command(interaction, f"{player_user.display_name} is not included in the town square.")
                return
            player.can_vote = not player.can_vote
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await utility.dm_user(interaction.user, f"{player.alias} can now "
                                              f"{'vote' if player.can_vote else 'not vote'}")
            await self.log(game_number, f"{interaction.user} has set {player.alias} as "
                                        f"{'able to vote' if player.can_vote else 'unable to vote'}")
        else:
            await utility.deny_command(interaction, "You must be the Storyteller to toggle a player's voting ability")

    @nextcord.slash_command(name="recreate_noms")
    async def RecreateNoms(self,interaction: nextcord.Interaction, game_number: str):
        """creates new messages for each nom"""
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            # add new carat to logging thread
            kibitz = self.helper.get_kibitz_channel(game_number)
            log_thread = kibitz.get_thread(self.town_squares[game_number].log_thread)
            try:
                if self.bot.user.id not in [m.id for m in log_thread.members]:
                    await log_thread.join()
            except:
                await utility.dm_user(interaction.user, "Could not join the Noms & Votes logging thread in Kibitz. Please add me.")
            game_role = self.helper.get_game_role(game_number)
            nom_thread = get(self.helper.Guild.threads, id=self.town_squares[game_number].nomination_thread)
            for nom in [n for n in self.town_squares[game_number].nominations if not n.finished]:
                content, embed = format_nom_message(game_role, self.town_squares[game_number], nom, self.emoji)
                nom_message = await nom_thread.send(content=content, embed=embed)
                nom.message = nom_message.id
            self.store.save()
            await interaction.followup.send("Done", ephemeral=True)
            await utility.dm_user(interaction.user, f"Recreated nominations for {game_number}")
            await self.log(game_number, f"Recreated nominations")
        else:
            await utility.deny_command(interaction, "Not permitted")

    @nextcord.slash_command(name="show_nomination")
    async def ShowNomination(self, interaction: nextcord.Interaction, game_number: str,
                             nominee_identifier: str, public: bool = True):
        """Show the current state of an active nomination without pinging the game role."""
        if game_number not in self.town_squares:
            await utility.deny_command(interaction, utility.DenialReason.NoTownSquare)
            return
        await interaction.response.defer()
        nominee = self.get_game_participant(game_number, nominee_identifier)
        if not nominee:
            await utility.deny_command(interaction, f"Could not clearly identify any player from {nominee_identifier}")
            return
        nom = next((nomination for nomination in self.town_squares[game_number].nominations
                    if nomination.nominee.id == nominee.id and not nomination.finished), None)
        if not nom:
            await utility.deny_command(interaction, f"No active nomination found for nominee {nominee_identifier}")
            return
        game_role = self.helper.get_game_role(game_number)
        content, embed = format_nom_message(game_role, self.town_squares[game_number], nom, self.emoji,
                                            include_game_role_mention=False)
        await interaction.followup.send(content=content, embed=embed, ephemeral=not public)

    @nextcord.slash_command(name="get_ts_status")
    async def GetTSStatus(self, interaction: nextcord.Interaction, game_number: str):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer(ephemeral=True)
            json_data = self.town_squares[game_number].to_dict()
            for nom in json_data.get("nominations", []):
                nom.pop("private_votes", None)
            json_str = json.dumps(json_data, indent=2)
            bytes_data = io.BytesIO(json_str.encode("utf-8"))
            await interaction.followup.send(f"Townsquare {game_number} json (private votes not shown)",
                                            file=nextcord.File(bytes_data, f"Townsquare_{game_number}.json"),
                                            ephemeral=True)
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)


class CountVoteSession:
    """Tracks a Storyteller's sequential modal-based vote count."""

    def __init__(self, cog: Townsquare, nom: Nomination, author: nextcord.Member, game_number: str):
        self.cog = cog
        self.nom = nom
        self.author = author
        self.game_number = game_number
        self.players = reordered_players(nom, cog.town_squares[game_number])
        self.player_index = 0

    @property
    def current_player(self) -> Player:
        return self.players[self.player_index]

    def state_summary(self) -> str:
        lines = [f"Nominator: {self.nom.nominator.alias}", f"Nominee: {self.nom.nominee.alias}"]
        for player in self.players:
            public_vote = self.nom.votes[player.id].vote
            private_vote = self.nom.private_votes.get(player.id)
            details = f"public: {public_vote}"
            if private_vote is not None:
                details += f", private: {private_vote}"
            if player.dead:
                details += ", dead"
            if not player.can_vote:
                details += ", no ghost vote"
            prefix = "→ " if player == self.current_player else ""
            lines.append(f"{prefix}{player.alias}: {details}")
        return "\n".join(lines)[:4000]

    @staticmethod
    def parse_boolean(value: str, field_name: str) -> bool:
        normalized = value.strip().lower()
        if normalized in {"yes", "y", "true", "1"}:
            return True
        if normalized in {"no", "n", "false", "0", ""}:
            return False
        raise ValueError(f"{field_name} must be yes or no.")

    @staticmethod
    def apply_multiplier(vote_state: Vote, multiplier: int) -> None:
        if multiplier not in {-6, -3, -2, -1, 1, 2, 3, 6}:
            raise ValueError("Multiplier must be one of -6, -3, -2, -1, 1, 2, 3, or 6.")
        vote_state.thief = multiplier < 0
        magnitude = abs(multiplier)
        vote_state.banshee = magnitude in {2, 6}
        vote_state.bureaucrat = magnitude in {3, 6}

    async def submit(self, interaction: nextcord.Interaction, vote_input: str, multiplier_input: str,
                     mark_dead_input: str, remove_ghost_vote_input: str) -> None:
        if interaction.user != self.author:
            await utility.deny_command(interaction, "Only the Storyteller who started this count may continue it.")
            return
        normalized_vote = vote_input.strip().lower()
        if normalized_vote not in {"yes", "no"}:
            await utility.deny_command(interaction, "Count as must be yes or no.")
            return
        try:
            multiplier = int(multiplier_input.strip())
            mark_dead = self.parse_boolean(mark_dead_input, "Mark dead")
            remove_ghost_vote = self.parse_boolean(remove_ghost_vote_input, "Remove ghost vote")
            self.apply_multiplier(self.nom.votes[self.current_player.id], multiplier)
        except ValueError as error:
            await utility.deny_command(interaction, str(error))
            return

        player = self.current_player
        vote = confirmed_yes_vote if normalized_vote == "yes" else confirmed_no_vote
        vote_state = self.nom.votes[player.id]
        self.nom.private_votes.pop(player.id, None)
        vote_state.vote = vote
        if mark_dead:
            player.dead = True
        if remove_ghost_vote:
            player.can_vote = False

        first_counted_vote = self.player_index == 0
        self.player_index += 1
        if self.player_index >= len(self.players):
            self.nom.finished = True
        self.cog.store.save()

        if first_counted_vote:
            game_role = self.cog.helper.get_game_role(self.game_number)
            content, embed = format_nom_message(game_role, self.cog.town_squares[self.game_number], self.nom,
                                                self.cog.emoji, include_game_role_mention=False)
            await self.cog.get_nomination_thread(self.game_number).send(content=content, embed=embed)
        await self.cog.announce_counted_vote(self.game_number, player, self.nom, vote)
        await self.cog.log(self.game_number,
                           f"{self.author} locked vote of {player.alias} on the nomination of "
                           f"{self.nom.nominee.alias} as {normalized_vote}")

        if self.nom.finished:
            await interaction.response.send_message("Vote counting is complete.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Counted {player.alias}. Continue with {self.current_player.alias}.",
                view=CountVoteContinueView(self), ephemeral=True
            )


class CountVoteModal(nextcord.ui.Modal):
    def __init__(self, session: CountVoteSession):
        player = session.current_player
        public_vote = session.nom.votes[player.id].vote
        private_vote = session.nom.private_votes.get(player.id, "none")
        super().__init__(f"Count vote: {player.alias}"[:45])
        self.session = session
        self.state = nextcord.ui.TextInput(
            label="Nomination state (reference only)", style=nextcord.TextInputStyle.paragraph,
            default_value=session.state_summary(), required=False, max_length=4000,
        )
        self.vote = nextcord.ui.TextInput(
            label="Count as (yes/no)", placeholder=f"Public: {public_vote}; private: {private_vote}",
            default_value="yes" if public_vote == confirmed_yes_vote else "no" if public_vote == confirmed_no_vote else "",
            required=True, max_length=3,
        )
        self.multiplier = nextcord.ui.TextInput(
            label="Combined multiplier", placeholder="-6, -3, -2, -1, 1, 2, 3, or 6",
            default_value="1", required=True, max_length=2,
        )
        self.mark_dead = nextcord.ui.TextInput(
            label="Mark player dead? (yes/no)", default_value="no", required=True, max_length=3,
        )
        self.remove_ghost_vote = nextcord.ui.TextInput(
            label="Remove ghost vote? (yes/no)", default_value="no", required=True, max_length=3,
        )
        for item in (self.state, self.vote, self.multiplier, self.mark_dead, self.remove_ghost_vote):
            self.add_item(item)

    async def callback(self, interaction: nextcord.Interaction) -> None:
        await self.session.submit(interaction, self.vote.value, self.multiplier.value,
                                  self.mark_dead.value, self.remove_ghost_vote.value)


class CountVoteContinueView(nextcord.ui.View):
    def __init__(self, session: CountVoteSession):
        super().__init__(timeout=86400)
        self.session = session

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user != self.session.author:
            await interaction.response.send_message("Only the Storyteller who started this count may continue it.",
                                                    ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Continue counting", style=nextcord.ButtonStyle.primary)
    async def continue_counting(self, button: nextcord.ui.Button, interaction: nextcord.Interaction) -> None:
        await interaction.response.send_modal(CountVoteModal(self.session))



async def setup(bot: commands.Bot):
    cog = Townsquare(bot, utility.Helper(bot), bot.data.townsquare)
    await cog.load_emoji()
    bot.add_cog(cog)
