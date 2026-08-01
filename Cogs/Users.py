import logging

import nextcord
from nextcord.ext import commands

import utility

class Users(commands.Cog):
    def __init__(self, bot: commands.Bot, helper: utility.Helper):
        self.bot = bot
        self.helper = helper

    @nextcord.slash_command(name="player", description="Manage game players.")
    async def player(self, interaction: nextcord.Interaction):
        pass

    @player.subcommand(name="add", description="Add players to a game.")
    async def player_add(self, interaction: nextcord.Interaction,
                         game: str = nextcord.SlashOption(required=True, name="game_number"),
                         p1: nextcord.Member = nextcord.SlashOption(required=True, name="player"),
                         p2: nextcord.Member = nextcord.SlashOption(required=False),
                         p3: nextcord.Member = nextcord.SlashOption(required=False),
                         p4: nextcord.Member = nextcord.SlashOption(required=False),
                         p5: nextcord.Member = nextcord.SlashOption(required=False),
                         p6: nextcord.Member = nextcord.SlashOption(required=False),
                         p7: nextcord.Member = nextcord.SlashOption(required=False),
                         p8: nextcord.Member = nextcord.SlashOption(required=False),
                         p9: nextcord.Member = nextcord.SlashOption(required=False),
                         p10: nextcord.Member = nextcord.SlashOption(required=False),
                         p11: nextcord.Member = nextcord.SlashOption(required=False),
                         p12: nextcord.Member = nextcord.SlashOption(required=False)):
        if game not in utility.PotentialGames:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
            return
        if self.helper.authorize_st_command(interaction.user, game):
            await interaction.response.defer()
            player_role = self.helper.get_game_role(game)
            if not player_role:
                logging.warning(f"Failed to find player role for game {game}")
                await interaction.followup.send("Failed to find player role", ephemeral=True)
                return
            players = [player for player in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12]
                       if player and player_role not in player.roles]
            for player in players:
                try:
                    await player.add_roles(player_role)
                except Exception as error:
                    await interaction.followup.send(
                        f"Failed adding the player role to {player.mention}. Stopping", ephemeral=True)
                    logging.error(f"Exception adding player {player.id} to {game}: {utility.traceback_text(error)}")
                    return
            await interaction.followup.send(f"Added {len(players)} users to game {game}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @player.subcommand(name="remove", description="Remove players from a game.")
    async def player_remove(self, interaction: nextcord.Interaction,
                            game: str = nextcord.SlashOption(required=True, name="game_number"),
                            p1: nextcord.Member = nextcord.SlashOption(required=True, name="player"),
                            p2: nextcord.Member = nextcord.SlashOption(required=False),
                            p3: nextcord.Member = nextcord.SlashOption(required=False),
                            p4: nextcord.Member = nextcord.SlashOption(required=False),
                            p5: nextcord.Member = nextcord.SlashOption(required=False),
                            p6: nextcord.Member = nextcord.SlashOption(required=False),
                            p7: nextcord.Member = nextcord.SlashOption(required=False),
                            p8: nextcord.Member = nextcord.SlashOption(required=False),
                            p9: nextcord.Member = nextcord.SlashOption(required=False),
                            p10: nextcord.Member = nextcord.SlashOption(required=False),
                            p11: nextcord.Member = nextcord.SlashOption(required=False),
                            p12: nextcord.Member = nextcord.SlashOption(required=False)):
        if game not in utility.PotentialGames:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
            return
        if self.helper.authorize_st_command(interaction.user, game):
            await interaction.response.defer()
            player_role = self.helper.get_game_role(game)
            if not player_role:
                logging.warning(f"Failed to find player role for game {game}")
                await interaction.followup.send("Failed to find player role", ephemeral=True)
                return
            players = [player for player in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12]
                       if player and player_role in player.roles]
            for player in players:
                try:
                    await player.remove_roles(player_role)
                except Exception as error:
                    await interaction.followup.send(
                        f"Failed removing the player role from {player.mention}. Stopping", ephemeral=True)
                    logging.error(f"Exception removing player {player.id} from {game}: {utility.traceback_text(error)}")
                    return
            await interaction.followup.send(f"Removed {len(players)} users from game {game}")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @nextcord.slash_command(name="kibitz", description="Manage game kibitzers.")
    async def kibitz(self, interaction: nextcord.Interaction):
        pass

    @kibitz.subcommand(name="add", description="Add kibitzers to a game.")
    async def kibitz_add(self, interaction: nextcord.Interaction, 
                         game: str = nextcord.SlashOption(required=True, name="game_number"), 
                         k1: nextcord.Member = nextcord.SlashOption(required=True, name="kibitzer"),
                         k2: nextcord.Member = nextcord.SlashOption(required=False),
                         k3: nextcord.Member = nextcord.SlashOption(required=False),
                         k4: nextcord.Member = nextcord.SlashOption(required=False),
                         k5: nextcord.Member = nextcord.SlashOption(required=False),
                         k6: nextcord.Member = nextcord.SlashOption(required=False),
                         k7: nextcord.Member = nextcord.SlashOption(required=False),
                         k8: nextcord.Member = nextcord.SlashOption(required=False),
                         k9: nextcord.Member = nextcord.SlashOption(required=False),
                         k10: nextcord.Member = nextcord.SlashOption(required=False),
                         k11: nextcord.Member = nextcord.SlashOption(required=False),
                         k12: nextcord.Member = nextcord.SlashOption(required=False)):
        if game not in utility.PotentialGames:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
        if self.helper.authorize_st_command(interaction.user, game):
            await interaction.response.defer()
            kibitz_role = self.helper.get_kibitz_role(game)
            kibitzers = [k for k in [k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11, k12] if k and kibitz_role not in k.roles]
            if not kibitz_role:
                logging.warning(f"Failed to find kibitz role for game {game}")
                await interaction.followup.send("Failed to find kibitz role", ephemeral=True)
                return
            for kibitzer in kibitzers:
                try:
                    await kibitzer.add_roles(kibitz_role)
                except Exception as error:
                    await interaction.followup.send(f"Failed adding kibitz role to {kibitzer.mention}. Stopping", ephemeral=True)
                    logging.error(f"Exception adding kibitzer {kibitzer.id} to {game}: {utility.traceback_text(error)}")
                    return
            await interaction.followup.send(f"Added {len(kibitzers)} users to the {game} kibitz")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)

    @kibitz.subcommand(name="remove", description="Remove kibitzers from a game.")
    async def kibitz_remove(self, interaction: nextcord.Interaction,
                            game: str = nextcord.SlashOption(required=True, name="game_number"),
                            k1: nextcord.Member = nextcord.SlashOption(required=True, name="kibitzer"),
                            k2: nextcord.Member = nextcord.SlashOption(required=False),
                            k3: nextcord.Member = nextcord.SlashOption(required=False),
                            k4: nextcord.Member = nextcord.SlashOption(required=False),
                            k5: nextcord.Member = nextcord.SlashOption(required=False),
                            k6: nextcord.Member = nextcord.SlashOption(required=False),
                            k7: nextcord.Member = nextcord.SlashOption(required=False),
                            k8: nextcord.Member = nextcord.SlashOption(required=False),
                            k9: nextcord.Member = nextcord.SlashOption(required=False),
                            k10: nextcord.Member = nextcord.SlashOption(required=False),
                            k11: nextcord.Member = nextcord.SlashOption(required=False),
                            k12: nextcord.Member = nextcord.SlashOption(required=False)):
        if game not in utility.PotentialGames:
            await utility.deny_app_command(interaction, utility.DenialReason.InvalidGame)
            return
        if self.helper.authorize_st_command(interaction.user, game):
            await interaction.response.defer()
            kibitz_role = self.helper.get_kibitz_role(game)
            if not kibitz_role:
                logging.warning(f"Failed to find kibitz role for game {game}")
                await interaction.followup.send("Failed to find kibitz role", ephemeral=True)
                return
            kibitzers = [kibitzer for kibitzer in [k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11, k12]
                         if kibitzer and kibitz_role in kibitzer.roles]
            for kibitzer in kibitzers:
                try:
                    await kibitzer.remove_roles(kibitz_role)
                except Exception as error:
                    await interaction.followup.send(
                        f"Failed removing kibitz role from {kibitzer.mention}. Stopping", ephemeral=True)
                    logging.error(f"Exception removing kibitzer {kibitzer.id} from {game}: {utility.traceback_text(error)}")
                    return
            await interaction.followup.send(f"Removed {len(kibitzers)} users from the {game} kibitz")
        else:
            await utility.deny_app_command(interaction, utility.DenialReason.NoPermission)


def setup(bot: commands.Bot):
    bot.add_cog(Users(bot, utility.Helper(bot)))
