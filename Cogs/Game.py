from time import strftime, gmtime
from typing import Optional

from nextcord.ext import commands
import nextcord

import utility
from State.townsquare import TownSquareStore


class Game(commands.Cog):
    def __init__(self, bot: commands.Bot, helper: utility.Helper, townsquares: TownSquareStore):
        self.bot = bot
        self.helper = helper
        self.townsquares = townsquares

    @nextcord.slash_command(name="open_kibitz", description="Manually opens the kibitz channel so anyone can view it.")
    async def open_kibitz(self, interaction: nextcord.Interaction, 
                         game_number: str = nextcord.SlashOption(required=True, name="game_number")):
        if await self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            townsfolk_role = self.helper.Guild.default_role
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=True)
            game_role = self.helper.get_game_role(game_number)
            await interaction.followup.send(
                f"{game_role.mention} Kibitz is now being opened (found [here]({kibitz_channel.jump_url})) - remove your game role to access it. " +
                f"Remember to give your ST(s) any feedback you may have!\n" +
                f"Feedback form: https://forms.gle/3PsSPs4TznRkMhY8A")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(f"{interaction.user.mention} has run the open kibitz command on game {game_number}")

    @nextcord.slash_command(name="close_kibitz", description="Manually closes the kibitz channel.")
    async def close_kibitz(self, interaction: nextcord.Interaction, 
                           game_number: str = nextcord.SlashOption(required=True, name="game_number")):
        if await self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            townsfolk_role = self.helper.Guild.default_role
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=False)
            await interaction.followup.send("Kibitz has been closed", ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(f"{interaction.user.mention} has run the close kibitz command on game {game_number}")

    @nextcord.slash_command(name="end_game", description="Opens kibitz and cleans up after the game. Use after the game is done.")
    async def end_game(self, interaction: nextcord.Interaction, 
                      game_number: str = nextcord.SlashOption(required=True, name="game_number")):
        if await self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            kibitz_role = self.helper.get_kibitz_role(game_number)
            game_role = self.helper.get_game_role(game_number)
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await interaction.followup.send(
                f"{game_role.mention} Kibitz is now being opened (found [here]({kibitz_channel.jump_url})). "
                f"Remember to give your ST(s) any feedback you may have!\n" +
                f"Feedback form: https://forms.gle/3PsSPs4TznRkMhY8A"
            )
            members = game_role.members
            members += kibitz_role.members
            for member in members:
                if not member.bot:
                    await member.remove_roles(kibitz_role)
                    await member.remove_roles(game_role)

            if game_number in self.townsquares.town_squares:
                self.townsquares.town_squares.pop(game_number)
                self.townsquares.save()

            townsfolk_role = self.helper.Guild.default_role
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

        await self.helper.log(f"{interaction.user.mention} has run the end game command on game {game_number}")

    @nextcord.slash_command(name="archive_game", description="Moves the game channel to the archive and creates a new empty channel.")
    async def archive_game(self, interaction: nextcord.Interaction, 
                           game_number: str = nextcord.SlashOption(required=True, name="game_number"),
                           archive_name: str = nextcord.SlashOption(required=True, name="archive_name")):
        if await self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer()
            townsfolk_role = self.helper.Guild.default_role
            st_role = self.helper.get_st_role(game_number)
            game_channel = self.helper.get_game_channel(game_number)
            if game_channel is None:
                await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
                return
            game_position = game_channel.position
            archive_category = self.helper.ArchiveCategory
            if len(archive_category.channels) == 50:
                await utility.deny_app_command(interaction, utility.DenialReason.ArchiveFull)
                await interaction.followup.send(f"{self.helper.ModRole.mention} The archive category is full, so this channel "
                                                f"cannot be archived")
                return
            if game_number[0] != "r":
                new_channel = await game_channel.clone(reason="New Game")
                await new_channel.edit(position=game_position, name=f"{game_number}-text-game", topic="")
            # remove manage threads permission so future STs for the game number can't see private threads
            st_permissions = game_channel.overwrites[st_role]
            st_permissions.update(manage_threads=None)
            await game_channel.set_permissions(st_role, overwrite=st_permissions)
            for st in st_role.members:
                if st in game_channel.overwrites:
                    member_permissions = game_channel.overwrites[st]
                    member_permissions.update(manage_threads=True)
                    await game_channel.set_permissions(st, overwrite=member_permissions)
                else:
                    await game_channel.set_permissions(st, manage_threads=True)
            await game_channel.edit(category=archive_category, name=archive_name, topic="")
            
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=False)
            await interaction.followup.send("Game successfully archived! Please drop the ST role at your soonest convenience.", ephemeral=True)
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)

        await self.helper.log(f"{interaction.user.mention} has run the archive game command for game {game_number}")


def setup(bot):
    bot.add_cog(Game(bot, utility.Helper(bot), bot.data.townsquare))
