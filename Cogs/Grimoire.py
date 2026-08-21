import logging
from typing import Optional

import nextcord
from nextcord.ext import commands

import utility
from Cogs.TextQueue import TextQueue
from Cogs.Townsquare import Townsquare, Player


class Grimoire(commands.Cog):
    def __init__(self, bot: commands.Bot, helper: utility.Helper):
        self.bot = bot
        self.helper = helper

    @nextcord.slash_command(name="grimoire", description="Manages grimoire ownerships.")
    async def grimoire(self, interaction: nextcord.Interaction):
        pass

    @grimoire.subcommand(name="claim", description="Grants you the ST role of the given game.")
    async def grimoire_claim(self, interaction: nextcord.Interaction, 
                            game_number: str = nextcord.SlashOption(required=True, name="game_number")):
        st_role = self.helper.get_st_role(game_number)
        if st_role is None:
            await utility.deny_app_command(interaction, utility.DenialReason.NoSTRole)
            return
        game_channel = self.helper.get_game_channel(game_number)
        if game_channel is None:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
            return
        
        if len(st_role.members) == 0 or self.helper.authorize_mod_command(interaction.user):
            await interaction.response.defer()
            await interaction.user.add_roles(st_role)
            await interaction.followup.send("You are now the current ST for game " + game_number, ephemeral=True)
            queue: Optional[TextQueue] = self.bot.get_cog('TextQueue')
            if queue is not None:
                if game_number[0] == "b":
                    channel_type = "Base"
                elif game_number[0] == "x":
                    channel_type = "Experimental"
                else:
                    channel_type = "Regular"
                users_in_queue = [entry.st for entry in queue.queues[channel_type].entries]
                if interaction.user.id not in users_in_queue:
                    await interaction.followup.send(f"{interaction.user.mention} Warning - you are taking a channel without having "
                                            f"been in the appropriate text ST queue. If that's how it's supposed to "
                                            f"be, carry on - otherwise you can drop the grimoire with `/grimoire drop {game_number}` "
                                            f"and join the text game queue (see `/HelpMe` for details)")
                await queue.user_leave_queue(interaction.user)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.AlreadySTS)

        await self.helper.log(f"{interaction.user.mention} has run the ClaimGrimoire Command for game {game_number}")
        minions_channel_id = 1199438203627773952
        Secondary_output_channel = self.bot.get_channel(minions_channel_id)
        await Secondary_output_channel.send(f"{interaction.user.mention} has run the ClaimGrimoire Command for game {game_number}")

    @grimoire.subcommand(name="give", description="Removes the ST role from you and gives it to another member.")
    async def grimoire_give(self, interaction: nextcord.Interaction, 
                           game_number: str = nextcord.SlashOption(required=True, name="game_number"), 
                           member: nextcord.Member = nextcord.SlashOption(required=True, name="member")):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            st_role = self.helper.get_st_role(game_number)
            await member.add_roles(st_role)
            await interaction.user.remove_roles(st_role)
            await interaction.followup.send("You have assigned the current ST role for game " + str(game_number) +
                                            " to " + member.display_name, ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(
            f"{interaction.user.mention} has run the GiveGrimoire Command on {member.display_name} for game {game_number}")

    @grimoire.subcommand(name="drop", description="Removes the ST role for the game from you.")
    async def grimoire_drop(self, interaction: nextcord.Interaction, 
                           game_number: str = nextcord.SlashOption(required=True, name="game_number")):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            st_role = self.helper.get_st_role(game_number)
            await interaction.user.remove_roles(st_role)
            await interaction.followup.send("You have removed the current ST role from yourself for game " + str(game_number), ephemeral=True)
            queue: Optional[TextQueue] = self.bot.get_cog('TextQueue')
            if queue is not None and len(st_role.members) == 0 and game_number[0] != "r":
                await queue.announce_free_channel(game_number, 0)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(f"{interaction.user.mention} has run the DropGrimoire Command for game {game_number}")

    @grimoire.subcommand(name="share", description="Gives another member the ST role without taking it away from you")
    async def grimoire_share(self, interaction: nextcord.Interaction, 
                             game_number: str = nextcord.SlashOption(required=True, name="game_number"), 
                             member: nextcord.Member = nextcord.SlashOption(required=True, name="member")):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            await member.add_roles(self.helper.get_st_role(game_number))
            townsquare: Optional[Townsquare] = self.bot.get_cog('Townsquare')
            if townsquare and game_number in townsquare.town_squares:
                townsquare.town_squares[game_number].sts.append(Player(member.id, member.display_name))
            await interaction.followup.send(f"You have added {member.display_name} as a ST.", ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(
            f"{interaction.user.mention} has run the ShareGrimoire Command on {member.display_name} for game {game_number}")

    @grimoire.subcommand(name="find", description="Sends you a list all games and their ST if applicable")
    async def grimoire_find(self, interaction: nextcord.Interaction):
        # find existing games by getting all channel names in the text games category
        # and checking which of 1 to [MaxGameNumber] and x1 to x[MaxGameNumber] appear in them
        await interaction.response.defer()
        channel_names_string = " ".join([channel.name for channel in self.helper.TextGamesCategory.channels])
        games = [x for x in utility.PotentialGames if x in channel_names_string]
        message = ""
        for j in games:
            st_role = self.helper.get_st_role(j)
            if not st_role:
                logging.warning(f"ST role for game {j} not found")
            elif not st_role.members:
                if j[0] != "r":
                    message += "There is currently no assigned ST for game " + str(j) + "\n"
            else:
                message += f"Game {j}'s STs are: " + ", ".join([st.display_name for st in st_role.members]) + "\n"
        await interaction.followup.send(message, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Grimoire(bot, utility.Helper(bot)))
