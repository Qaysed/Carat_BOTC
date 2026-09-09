from collections.abc import AsyncIterator
from typing import List, Dict

import nextcord
from nextcord import InvalidArgument, HTTPException, Message
from nextcord.ext import tasks, commands
from nextcord.utils import get

import utility
from State.archive import ArchiveStore, ThreadList

ivy_id = 183474450237358081

async def copy_history(target: nextcord.abc.Messageable, history: AsyncIterator[Message]) -> int:
    errors = 0
    async for message in history:
        embed = nextcord.Embed(description=message.content)
        embed.set_author(name=str(message.author) + " at " + str(message.created_at),
                         icon_url=message.author.display_avatar.url)
        attachment_list = []
        for i in message.attachments:
            attachment_list.append(await i.to_file())
        for i in message.reactions:
            user_list = []
            async for user in i.users():
                user_list.append(str(user.name))
            reactors = ", ".join(user_list)
            if not embed.footer.text or len(embed.footer.text) == 0:
                embed.set_footer(text=f"{i.emoji} - {reactors}, ")
            else:
                embed.set_footer(text=embed.footer.text + f" {i.emoji} - {reactors}, ")
        try:
            await target.send(embed=embed, files=attachment_list)
        except InvalidArgument:
            embed.set_footer(text=f"{embed.footer.text}\nError: Attachment file was too large.")
            await target.send(embed=embed)
        except HTTPException as e:
            if e.status == 413:
                embed.set_footer(text=f"{embed.footer.text}\nError: Attachment file was too large.")
                await target.send(embed=embed)
            else:
                await target.send(f"Error: this message caused an unknown issue: {e.status} - {e.text}")
                errors += 1
    return errors


class Archive(commands.Cog):
    bot: commands.Bot
    helper: utility.Helper
    store: ArchiveStore

    def __init__(self, bot: commands.Bot, helper: utility.Helper, store: ArchiveStore):
        self.bot = bot
        self.helper = helper
        self.store = store
        self.threads_by_channel = self.store.threads_by_channel

    @nextcord.slash_command(name="archive", description="Manages off server archive and commands related to that.")
    async def archive(self, interaction: nextcord.Interaction):
        pass

    @archive.subcommand(name="include", description="Marks a thread as to be included in the archive. Use in the thread you want to include.")
    async def include(self, interaction: nextcord.Interaction):
        thread = interaction.channel
        if thread.type == nextcord.ChannelType.private_thread:
            await interaction.response.defer()
            if thread.parent.id not in self.threads_by_channel:
                self.threads_by_channel[thread.parent.id] = ThreadList()
            if thread.id not in self.threads_by_channel[thread.parent.id].private_to_archive:
                self.threads_by_channel[thread.parent.id].private_to_archive.append(thread.id)
                await interaction.followup.send("This thread is now set to be included in the archive")
            else:
                await interaction.followup.send("This thread is already included in the archive")
            await self.helper.log(f"{interaction.user.display_name} has run the 'archive include' command in {thread.mention}")
            self.store.save()
        elif thread.type == nextcord.ChannelType.public_thread:
            await interaction.response.defer()
            if thread.parent.id not in self.threads_by_channel:
                self.threads_by_channel[thread.parent.id] = ThreadList()
            if thread.id in self.threads_by_channel[thread.parent.id].public_to_not_archive:
                self.threads_by_channel[thread.parent.id].public_to_not_archive.remove(thread.id)
                await interaction.followup.send("This thread is now set to be included in the archive")
            else:
                await interaction.followup.send("This thread is already included in the archive")
            await self.helper.log(f"{interaction.user.display_name} has run the 'archive include' command in {thread.mention}")
            self.store.save()
        else:
            await utility.deny_command(interaction, utility.DenialReason.NotAThread)

    @archive.subcommand(name="exclude", description="Marks a thread as to be excluded from the archive. Use in the thread you want to exclude.")
    async def exclude(self, interaction: nextcord.Interaction):
        thread = interaction.channel
        if thread.type == nextcord.ChannelType.private_thread:
            await interaction.response.defer()
            if thread.parent.id not in self.threads_by_channel:
                self.threads_by_channel[thread.parent.id] = ThreadList()
            if thread.id in self.threads_by_channel[thread.parent.id].private_to_archive:
                self.threads_by_channel[thread.parent.id].private_to_archive.remove(thread.id)
                await interaction.followup.send("This thread is now set to be excluded from the archive")
            else:
                await interaction.followup.send("This thread is already excluded from the archive")
            await self.helper.log(f"{interaction.user.display_name} has run the 'archive exclude' command in {thread.mention}")
            self.store.save()
        elif thread.type == nextcord.ChannelType.public_thread:
            await interaction.response.defer()
            if thread.parent.id not in self.threads_by_channel:
                self.threads_by_channel[thread.parent.id] = ThreadList()
            if thread.id not in self.threads_by_channel[thread.parent.id].public_to_not_archive:
                self.threads_by_channel[thread.parent.id].public_to_not_archive.append(thread.id)
                await interaction.followup.send("This thread is now set to be excluded from the archive")
            else:
                await interaction.followup.send("This thread is already excluded from the archive")
            await self.helper.log(f"{interaction.user.display_name} has run the 'archive exclude' command in {thread.mention}")
            self.store.save()
        else:
            await utility.deny_command(interaction, utility.DenialReason.NotAThread)

    # TODO: enable command in archive servers, load archive servers from .env
    @archive.subcommand(name="claim_role", description="Claims your unique role for this server, this allows you to view threads of games you STed.")
    async def claim_role(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # TODO: Remove hard coded archive server ids - probably via a set up command or .env-dist
        if interaction.guild_id is None or interaction.guild_id not in [959219314014163036, 1203126128693354516, 1317487976309329920, 1447544308675907656]:
            await utility.deny_command(interaction, utility.DenialReason.NotArchiveServer)
            return
        archive_server = interaction.guild
        unique_role_name = str(interaction.user.id)
        unique_role = nextcord.utils.get(archive_server.roles, name=unique_role_name)
        if unique_role is None:
            unique_role = await archive_server.create_role(name=unique_role_name)
        await interaction.user.add_roles(unique_role)
        await interaction.followup.send("You have claimed your unique role")

    @archive.subcommand(name="off_server_archive", description="Copies the channel the message was sent in to the provided server and channel, message by message.")
    async def off_server_archive(self, interaction: nextcord.Interaction, 
                                 archive_server_id: str = nextcord.SlashOption(required=True), # discord has a build in max int cap so str is used instead
                                 st: nextcord.Member = nextcord.SlashOption(required=True), 
                                 archive_channel_id: str = nextcord.SlashOption(required=False, default=None)):
        if interaction.channel is None or interaction.channel.type != nextcord.ChannelType.text:
            await utility.deny_command(interaction, utility.DenialReason.NotATextChannel)
            return 
        # Ivy Access
        if self.helper.authorize_mod_command(interaction.user) or interaction.user.id == ivy_id:
            await interaction.response.defer()

            channel_to_archive = interaction.channel

            archive_server = None
            if archive_server_id.isdigit():
                archive_server = self.helper.bot.get_guild(int(archive_server_id))
            if archive_server is None:
                await interaction.followup.send(f"Was unable to find server with ID {archive_server_id}")
                return

            if archive_channel_id is not None:
                archive_channel = None
                if archive_channel_id.isdigit():
                    archive_channel = get(archive_server.channels, id=int(archive_channel_id))
                if archive_channel is None or archive_channel.type != nextcord.ChannelType.text:
                    await interaction.followup.send(f"Was unable to find a text channel with ID {archive_channel_id}")
                    return
            else:
                channel_name = str(channel_to_archive.name) + "-" + str(st.display_name)
                archive_channel = await archive_server.create_text_channel(name=channel_name)

            unique_role_name = str(st.id)
            unique_role = nextcord.utils.get(archive_server.roles, name=unique_role_name)
            if unique_role is None:
                unique_role = await archive_server.create_role(name=unique_role_name)

            # the after parameter might seem weird here. nextcord's pagination for this is broken if after isn't set
            # and after can be basically any discord object - the ID serves as a timestamp of the creation time
            # so this should get all messages in the channel
            channel_history = channel_to_archive.history(limit=None, oldest_first=True, after=channel_to_archive)

            errors = await copy_history(archive_channel, channel_history)

            for thread in channel_to_archive.threads:
                if thread.is_private() and (thread.parent.id not in self.threads_by_channel or
                                            thread.id not in self.threads_by_channel[
                                                channel_to_archive.id].private_to_archive):
                    try:
                        archive_thread = await archive_channel.create_thread(
                            name=str(thread.name),
                            auto_archive_duration=4320,  # 3 days
                            type=nextcord.ChannelType.private_thread,
                            invitable=True,
                            reason="Private Thread"
                            )
                        thread_history = thread.history(limit=None, oldest_first=True, after=channel_to_archive)
                        errors += await copy_history(archive_thread, thread_history)
                        continue
                    except HTTPException:
                        await archive_channel.send(f"Failed to create thread '{thread.name}'")
                        continue

                elif (not thread.is_private()) and thread.parent.id in self.threads_by_channel and \
                        thread.id in self.threads_by_channel[channel_to_archive.id].public_to_not_archive:
                    continue

                try:
                    archive_thread = await archive_channel.create_thread(name=thread.name,
                                                                         type=nextcord.ChannelType.public_thread)
                    thread_history = thread.history(limit=None, oldest_first=True, after=channel_to_archive)
                    errors += await copy_history(archive_thread, thread_history)
                except HTTPException:
                    await archive_channel.send(f"Failed to create thread '{thread.name}'")
                    continue

            await archive_channel.create_thread(name="Chat about the game", type=nextcord.ChannelType.public_thread)

            await archive_channel.set_permissions(unique_role, manage_threads=True)

            self.threads_by_channel.pop(channel_to_archive.id, None)
            self.store.save()

            await interaction.followup.send(f"Your archive for {interaction.channel.name} is done.")
            await self.helper.log(f"{interaction.user.display_name} has run the OffServerArchive Command")
            if errors > 0:
                message += f" {errors} messages caused unknown errors and were not archived."
                await interaction.followup.send(message, ephemeral=True)
        else:
            await utility.deny_command(interaction, utility.DenialReason.NoPermission)

    @tasks.loop(hours=24)
    async def adjust_thread_archive_time():

        guild = bot.get_guild(569683781800296501)
        EXCLUDED_CHANNELS = [1218704547585724537, 1218706422297137272, 777660207424733204, 1173738081036283924]
        ACTIVE_THREAD_CATEGORIES = [569683781846433930]

        for current_thread_ID in ACTIVE_THREAD_CATEGORIES:
            category = nextcord.utils.get(guild.categories, id=current_thread_ID)

            for channel in category.channels:
                if channel.id in EXCLUDED_CHANNELS:
                    continue
            
                threads = await channel.threads()
                for thread in threads:
                    try:
                        await thread.edit(auto_archive_duration=10080)  # 10080 minutes = 7 days
                        await thread.edit(auto_archive_duration=4320)  # 4,320 minutes = 3 days
                    except Exception as e:
                        print(f"Failed to update thread: {thread.name} in channel: {channel.name}. Error: {e}")

def setup(bot: commands.Bot):
    bot.add_cog(Archive(bot, utility.Helper(bot), bot.data.archive))
