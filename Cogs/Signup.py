import io
import logging
import traceback

import nextcord
from nextcord.ext import commands

import utility

green_square_emoji = '\U0001F7E9'
red_square_emoji = '\U0001F7E5'
refresh_emoji = '\U0001F504'


class Signup(commands.Cog):
    def __init__(self, bot: commands.Bot, helper: utility.Helper):
        self.bot = bot
        self.bot.add_view(SignupView(helper))  # so it knows to listen for buttons on pre-existing signup forms
        self.helper = helper

    @nextcord.slash_command(name="signups", description="Manages game signups.")
    async def signups(self, interaction: nextcord.Interaction):
        pass

    @signups.subcommand(name="send_list", description="Sends you a list of all player, kibitzers and sts for a given game.")
    async def send_list(self, interaction: nextcord.Interaction, 
                          game_number: str = nextcord.SlashOption(required=True)):
        await interaction.response.defer(ephemeral=True)
        st_role = self.helper.get_st_role(game_number)
        if st_role is None:
            await utility.deny_command(interaction, utility.DenialReason.NoSTRole)
            return
        st_names = [st.display_name for st in st_role.members]
        player_role = self.helper.get_game_role(game_number)
        if player_role is None:
            await utility.deny_command(interaction, utility.DenialReason.NoPlayerRole)
            return
        player_names = [player.display_name for player in player_role.members]
        kibitz_role = self.helper.get_kibitz_role(game_number)
        if player_role is None:
            await utility.deny_command(interaction, utility.DenialReason.NoKibitzRole)
            return
        kibitz_names = [kibitzer.display_name for kibitzer in kibitz_role.members]

        output_string = f"Game {game_number} Players\n" \
                        f"Storyteller:\n"
        output_string += "\n".join(st_names)

        output_string += "\nPlayers:\n"
        output_string += "\n".join(player_names)

        output_string += "\nKibitz members:\n"
        output_string += "\n".join(kibitz_names)

        interaction.followup.send(output_string)

    @signups.subcommand(name="show", description="Posts a message listing the signed up players in the game channel with buttons to sign up with.")
    async def show_signups(self, interaction: nextcord.Interaction, 
                     game_number: str = nextcord.SlashOption(required=True), 
                     signup_limit: int = nextcord.SlashOption(required=True), 
                     script: str = nextcord.SlashOption(required=True)):
        if self.helper.authorize_st_command(interaction.user, game_number):
            await interaction.response.defer(ephemeral=True)
            st_names = [st.display_name for st in self.helper.get_st_role(game_number).members]
            player_list = self.helper.get_game_role(game_number).members
            embed = nextcord.Embed(title=str(script),
                                   description="Ran by " + ", ".join(st_names) +
                                               f"\nPress {green_square_emoji} to sign up for the game"
                                               f"\nPress {red_square_emoji} to remove yourself from the game"
                                               f"\nPress {refresh_emoji} if the list needs updating "
                                               "(if a command is used to assign roles)",
                                   color=0xff0000)
            for i in range(signup_limit):
                if i < len(player_list):
                    name = player_list[i].display_name
                    embed.add_field(name=str(i + 1) + ". " + str(name),
                                    value=f"{player_list[i].mention} has signed up",
                                    inline=False)
                else:
                    embed.add_field(name=str(i + 1) + ". ", value=" Awaiting Player", inline=False)
            embed.set_footer(text=game_number)
            await self.helper.get_game_channel(game_number).send(embed=embed, view=SignupView(self.helper))
            await interaction.followup.send("Sign up list sent!")
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)


class SignupView(nextcord.ui.View):
    def __init__(self, helper: utility.Helper):
        super().__init__(timeout=None)  # for persistence
        self.helper = helper

    async def on_error(self, error: Exception, item: nextcord.ui.Item, interaction: nextcord.Interaction) -> None:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Ignoring exception in SignupView:\n{traceback_text}")

    @nextcord.ui.button(label="Sign Up", custom_id="Sign_Up_Command", style=nextcord.ButtonStyle.green)
    async def signup_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        signup_message = interaction.message
        number_of_fields = signup_message.embeds[0].to_dict()
        game_number = str(number_of_fields["footer"]["text"])
        game_role = self.helper.get_game_role(game_number)
        st_role = self.helper.get_st_role(game_number)
        kibitz_role = self.helper.get_kibitz_role(game_number)
        signup_limit = len(number_of_fields["fields"])
        no_of_signups = len(game_role.members)

        if game_role in interaction.user.roles:
            await interaction.send("You are already signed up", ephemeral=True)
        elif st_role in interaction.user.roles:
            await interaction.send("You are the Storyteller for this game and so cannot sign up for it", ephemeral=True)
        elif interaction.user.bot:
            pass
        elif no_of_signups >= signup_limit:
            await interaction.send("The game is currently full, please contact the Storyteller", ephemeral=True)
        else:
            await interaction.user.add_roles(game_role)
            await interaction.user.remove_roles(kibitz_role)
            await self.update_signup_sheet(interaction.message)
            await interaction.send("You have signed up for the game", ephemeral=True)
            for st in st_role.members:
                await utility.dm_user(st,
                                      f"{interaction.user.display_name} ({interaction.user.name}) "
                                      f"has signed up for Game {game_number}")
            await self.helper.log(
                f"{interaction.user.display_name} ({interaction.user.name}) has signed up for Game {game_number}")

    @nextcord.ui.button(label="Leave Game", custom_id="Leave_Game_Command", style=nextcord.ButtonStyle.red)
    async def leave_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        signup_message = interaction.message
        number_of_fields = signup_message.embeds[0].to_dict()
        game_number = str(number_of_fields["footer"]["text"])
        game_role = self.helper.get_game_role(game_number)
        st_role = self.helper.get_st_role(game_number)

        if game_role not in interaction.user.roles:
            await interaction.send("You haven't signed up", ephemeral=True)
        elif interaction.user.bot:
            pass
        else:
            await interaction.user.remove_roles(game_role)
            await self.update_signup_sheet(interaction.message)
            await interaction.send("You have left the game", ephemeral=True)
            for st in st_role.members:
                await utility.dm_user(st,
                                      f"{interaction.user.display_name} ({interaction.user.name}) "
                                      f"has removed themself from Game {game_number}")
            await self.helper.log(
                f"{interaction.user.display_name} ({interaction.user.name}) "
                f"has removed themself from Game {game_number}")

    @nextcord.ui.button(label="Refresh List", custom_id="Refresh_Command", style=nextcord.ButtonStyle.gray,
                        emoji=refresh_emoji)
    async def refresh_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.send(f"{refresh_emoji}Refreshing...", ephemeral=True)
        await self.update_signup_sheet(interaction.message)

    async def update_signup_sheet(self, signup_message: nextcord.Message):
        number_of_fields = signup_message.embeds[0].to_dict()
        game_number = str(number_of_fields["footer"]["text"])
        signup_limit = len(number_of_fields["fields"])
        ran_by = str(number_of_fields["description"])
        script = str(number_of_fields["title"])
        
        embed = nextcord.Embed(title=script, description=ran_by, color=0xff0000)
        player_list = self.helper.get_game_role(game_number).members
        for i in range(signup_limit):
            if i < len(player_list):
                name = player_list[i].display_name
                embed.add_field(name=str(i + 1) + ". " + str(name),
                                value=f"{player_list[i].mention} has signed up",
                                inline=False)
            else:
                embed.add_field(name=str(i + 1) + ". ", value=" Awaiting Player", inline=False)
        embed.set_footer(text=game_number)
        await signup_message.edit(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Signup(bot, utility.Helper(bot)))
