from time import strftime, gmtime
from typing import Optional

from nextcord.ext import commands

import utility
from Cogs.Townsquare import Townsquare


class Game(commands.Cog):
    def __init__(self, bot: commands.Bot, helper: utility.Helper):
        self.bot = bot
        self.helper = helper

    @commands.command()
    async def OpenKibitz(self, ctx, game_number):
        if self.helper.authorize_st_command(ctx.author, game_number):
            # React on Approval
            await utility.start_processing(ctx)

            # Change permission of Kibitz to allow Townsfolk to view
            townsfolk_role = self.helper.Guild.default_role
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=True)
            game_role = self.helper.get_game_role(game_number)
            await ctx.channel.send(
                f"{game_role.mention} Kibitz is now being opened - remove your game role to access it. " +
                f"Remember to give your ST(s) any feedback you may have!\n" +
                f"Feedback form: https://forms.gle/HqNfMv1pte8vo5j59")

            # React for completion
            await self.helper.finish_processing(ctx)
        else:
            # React on Disapproval
            await utility.deny_command(ctx)
            await utility.dm_user(ctx.author, "You are not the current ST for game " + str(game_number))

        await self.helper.log(f"{ctx.author.mention} has run the OpenKibitz Command on Game {game_number}")

    @commands.command()
    async def CloseKibitz(self, ctx, game_number):
        if self.helper.authorize_st_command(ctx.author, game_number):
            # React on Approval
            await utility.start_processing(ctx)

            # Change permission of Kibitz to allow Townsfolk to view
            townsfolk_role = self.helper.Guild.default_role

            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=False)

            # React for completion
            await self.helper.finish_processing(ctx)
        else:
            await utility.deny_command(ctx)
            await utility.dm_user(ctx.author, "You are not the current ST for game " + game_number)

        await self.helper.log(f"{ctx.author.mention} has run the CloseKibitz Command on Game {game_number}")

    @commands.command()
    async def EndGame(self, ctx: commands.Context, game_number):
        if self.helper.authorize_st_command(ctx.author, game_number):
            # React on Approval
            await utility.start_processing(ctx)

            # Gather member list & role information
            kibitz_role = self.helper.get_kibitz_role(game_number)
            game_role = self.helper.get_game_role(game_number)

            await ctx.channel.send(
                f"{game_role.mention} Kibitz is now being opened. "
                f"Remember to give your ST(s) any feedback you may have!\n" +
                f"Feedback form: https://forms.gle/HqNfMv1pte8vo5j59"
            )
            members = game_role.members
            members += kibitz_role.members

            # Remove roles from non-bot players
            for member in members:
                if str(member.bot) == "False":
                    await member.remove_roles(kibitz_role)
                    await member.remove_roles(game_role)

            townsquare: Optional[Townsquare] = self.bot.get_cog("Townsquare")
            if townsquare and game_number in townsquare.town_squares:
                townsquare.town_squares.pop(game_number)
                townsquare.update_storage()

            # Change permission of Kibitz to allow Townsfolk to view
            townsfolk_role = self.helper.Guild.default_role
            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=True)

            # React for completion
            await self.helper.finish_processing(ctx)

        else:
            # React on Disapproval
            await utility.deny_command(ctx)
            await utility.dm_user(ctx.author, "You are not the current ST for game " + game_number)

        await self.helper.log(f"{ctx.author.mention} has run the EndGame Command on Game {game_number}")

    @commands.command()
    async def ArchiveGame(self, ctx, game_number):
        if self.helper.authorize_st_command(ctx.author, game_number):
            # React on Approval
            await utility.start_processing(ctx)

            townsfolk_role = self.helper.Guild.default_role
            game_channel = self.helper.get_game_channel(game_number)

            game_position = game_channel.position
            game_channel_name = game_channel.name
            new_channel = await game_channel.clone(reason="New Game")
            archive_category = self.helper.ArchiveCategory
            if len(archive_category.channels) == 50:
                await archive_category.channels[49].delete()
            await game_channel.edit(category=archive_category, name=str(game_channel_name) + " Archived on " + str(
                strftime("%a, %d %b %Y %H %M %S ", gmtime())), topic="")

            await new_channel.edit(position=game_position, name=f"text-game-{game_number}", topic="")

            kibitz_channel = self.helper.get_kibitz_channel(game_number)
            await kibitz_channel.set_permissions(townsfolk_role, view_channel=False)

            # React for completion
            await self.helper.finish_processing(ctx)

        else:
            await utility.deny_command(ctx)
            await utility.dm_user(ctx.author, "You are not the current ST for game " + game_number)

        await self.helper.log(f"{ctx.author.mention} has run the ArchiveGame Command for Game {game_number}")