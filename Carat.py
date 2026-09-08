import io
import logging
import os
import re
import sys
import tempfile
import traceback
from typing import Optional, List

import nextcord
import requests
from dotenv import load_dotenv
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
from nextcord.ext.commands import CommandError
from nextcord.utils import utcnow


import utility
from State import DataLayer

LogFile = "Carat.log"
repository_api_url = "https://api.github.com/repos/Qaysed/Carat_BOTC"

LogLevelMapping = {'DEBUG': logging.DEBUG,
                   'INFO': logging.INFO,
                   'WARNING': logging.WARNING,
                   'ERROR': logging.ERROR,
                   'CRITICAL': logging.CRITICAL}

LogHeaderPattern = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL): "
)

logging.basicConfig(filename=LogFile, filemode="w",
                    format="%(asctime)s - %(levelname)s: %(message)s",
                    level=logging.INFO)

try:
    load_dotenv()
    token = os.environ['TOKEN']
    guild_id = int(os.environ['GUILD_ID'])
    repository_api_url = "https://api.github.com/repos/" + os.environ['GITHUB_REPOSITORY']
    owner_id = int(os.environ['OWNER_ID'])
except Exception as e:
    message = "Encountered an issue loading environment variables. Ensure .env file exists and is properly formatted " \
              "with all necessary variables.\nException: " + str(e)
    print(message)
    logging.critical(message)
    sys.exit()


intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
allowedMentions = nextcord.AllowedMentions.all()
allowedMentions.everyone = False

# TDOD: remove prefix once all commands are gone
bot = commands.Bot(intents=intents,
                   allowed_mentions=allowedMentions,
                   owner_id=owner_id,
                   default_guild_ids=[guild_id])


# load cogs and print ready message
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('Loading cogs')
    if not hasattr(bot, "data"):
        bot.data = DataLayer(utility.Helper(bot).StorageLocation)
    cog_paths = ["Cogs." + os.path.splitext(file)[0] for file in os.listdir("Cogs") if file.endswith(".py")]
    load_extensions(cog_paths)
    await bot.sync_all_application_commands()
    print('Ready')
    print('------')
    logging.info("Carat online")


def load_extensions(paths: List[str]):
    for extension in paths:
        try:
            bot.load_extension(extension)
        except commands.ExtensionFailed as exception:
            logging.exception(f"Failed to load {extension}: {exception}")


@bot.event
async def on_application_command_error(interaction: Interaction, error: Exception):
    traceback_text = utility.traceback_text(error)
    logging.exception(f"Ignoring exception in command {interaction.application_command.name}:\n{traceback_text}")
    if isinstance(error, nextcord.HTTPException) and error.code == 429:
        user_warning = "Ran into a rate limit. Try again in a bit."
    else:
        user_warning = ("Ran into internal error. You can try again, "
                        "otherwise you may need to contact a developer")
    if interaction.response.is_done():
        await interaction.followup.send(user_warning, ephemeral=True)
    else:
        await interaction.send(user_warning, ephemeral=True)


def get_level(line: str) -> Optional[int]:
    match = LogHeaderPattern.match(line)
    if match is None:
        return None
    return LogLevelMapping[match["level"]]


@bot.slash_command(name="send_logs", description="Send Carat program logs. Developer only")
async def SendLogs(interaction: Interaction, 
                   limit: int = SlashOption(name="number_of_lines"), 
                   level: int = SlashOption(name="log_level", 
                                            choices={"ERROR": logging.ERROR, "WARNING": logging.WARN, "INFO": logging.INFO, "DEBUG": logging.DEBUG}, 
                                            required=False, 
                                            default=logging.ERROR), 
                   filter_string: str = SlashOption(name="filter", required=False)):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id == owner_id or \
            (utility.authorize_dev_command(interaction.user) and level > logging.DEBUG):
        with open(LogFile, "r") as logs:
            lines = logs.readlines()
        items = []
        include_current_entry = False
        for line in lines:
            item_level = get_level(line)
            if item_level is not None:
                include_current_entry = item_level >= level
                if include_current_entry:
                    items.append(line)
            elif include_current_entry:
                items[-1] += line
        if filter_string is not None:
            items = [item for item in items if filter_string.lower() in item.lower()]
        if limit < len(items):
            items = items[-limit:]
        bytes_data = io.BytesIO("".join(items).encode("utf-8"))
        await interaction.followup.send("Logs", file=nextcord.File(bytes_data, f"Carat_{level}_{limit}_{utcnow().isoformat()}.log"), ephemeral=True)
    else:
        await utility.deny_command(interaction, utility.DenialReason.NoPermission)
        logging.warning(f"{interaction.user.display_name} (id: {interaction.user.id}) attempted to access Carat's logs")


def get_repo_info(sub_path: str) -> Optional[List]:
    try:
        response = requests.get(repository_api_url + "/contents" + sub_path,
                            headers={"Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"})
    except Exception as error:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Exception during request to repository:\n{traceback_text}")
        return None
    if response.status_code != 200:
        logging.error(f"Initial request failed with status code {response.status_code} and message {response.text}.")
        return None
    return response.json()


def download_file(url, local_directory, local_filename):
    try:
        response = requests.get(url)
    except Exception as error:
        traceback_text = utility.traceback_text(error)
        logging.exception(f"Exception during request to repository:\n{traceback_text}")
        return False
    if response.status_code != 200:
        logging.error(f"File request failed with status code {response.status_code} and message {response.text}.")
        return False
    with open(os.path.join(local_directory, local_filename), "w", encoding="utf-8") as f:
        f.write(response.text)
    return True


@bot.slash_command(name="reload_cogs", description="Gets current versions of the extension files and reloads them")
async def ReloadCogs(interaction: Interaction):
    if not await bot.is_owner(interaction.user):
        await utility.deny_command(interaction, utility.DenialReason.NoPermission)
        return
    await interaction.response.defer(ephemeral=True)
    logging.warning("Starting the ReloadCogs process")
    logging.info("Current cogs: " + ", ".join(bot.cogs.keys()))
    logging.info("Downloading cogs list from repository")
    cogs_contents = get_repo_info("/Cogs")
    if cogs_contents is None:
        await interaction.followup.send("Could not download cogs from GitHub; no changes were made.", ephemeral=True)
        return
    logging.info("Downloading data-layer modules from repository")
    data_contents = get_repo_info("/State")
    if data_contents is None:
        await interaction.followup.send("Could not download the data layer; no changes were made.", ephemeral=True)
        return
    with tempfile.TemporaryDirectory(prefix=".carat-cogs-", dir=".") as staging_directory:
        staged_directories = (("Cogs", cogs_contents), ("State", data_contents))
        download_failed = False
        for directory, contents in staged_directories:
            staged_directory = os.path.join(staging_directory, directory)
            os.makedirs(staged_directory)
            for file in contents:
                if file["name"].endswith(".py"):
                    logging.info(f"Downloading {directory}/{file['name']} from repository")
                    if not download_file(file["download_url"], staged_directory, file["name"]):
                        download_failed = True
                        break
            if download_failed:
                break

        if download_failed:
            logging.warning("A download failed; keeping existing cogs and data-layer files")
            await interaction.followup.send("Could not download all files from GitHub; no changes were made.", ephemeral=True)
            return

        cog_paths = ["Cogs." + os.path.splitext(file)[0] for file in os.listdir("Cogs") if file.endswith(".py")]
        for cog in cog_paths:
            logging.info(f"Unloading {cog}")
            if cog[5:] in bot.cogs:
                bot.unload_extension(cog)
        logging.info("Unloaded all cogs in cog directory. Remaining cogs: " + ", ".join(bot.cogs.keys()))
        await interaction.followup.send("Unloaded cogs: " + ", ".join([c[5:] for c in cog_paths]), ephemeral=True)

        for directory, _ in staged_directories:
            os.makedirs(directory, exist_ok=True)
            staged_directory = os.path.join(staging_directory, directory)
            staged_filenames = set(os.listdir(staged_directory))
            for filename in os.listdir(directory):
                local_file = os.path.join(directory, filename)
                if filename.endswith(".py") and filename not in staged_filenames and os.path.isfile(local_file):
                    logging.info(f"Removing {directory}/{filename}; it is no longer in the repository")
                    os.remove(local_file)
            for filename in staged_filenames:
                os.replace(os.path.join(staged_directory, filename), os.path.join(directory, filename))

    new_cog_paths = ["Cogs." + os.path.splitext(file)[0] for file in os.listdir("Cogs") if file.endswith(".py")]
    logging.info("Now loading new cogs from files: " + ", ".join(new_cog_paths))
    load_extensions(new_cog_paths)
    await bot.sync_all_application_commands()
    logging.warning("Cogs successfully loaded. Currently loaded cogs: " + ", ".join(bot.cogs.keys()))
    await interaction.followup.send("Loaded new cogs: " + ", ".join([c[5:] for c in new_cog_paths]), ephemeral=True)


@bot.slash_command(name="reload_main_files", description="Downloads updated Carat.py and utility.py from GitHub.")
async def ReloadMainFiles(interaction: Interaction):
    if not await bot.is_owner(interaction.user):
        await utility.deny_command(interaction, utility.DenialReason.NoPermission)
        return
    await interaction.response.defer(ephemeral=True)
    logging.warning("Attempting to update Carat.py and utility.py")
    repo_contents = get_repo_info("/")
    if repo_contents is None:
        await interaction.followup.send("Could not connect to GitHub", ephemeral=True)
        return
    carat_file_url = next((file['download_url'] for file in repo_contents if file['name'] == "Carat.py"), None)
    utility_file_url = next((file['download_url'] for file in repo_contents if file['name'] == "utility.py"), None)
    if carat_file_url is None or utility_file_url is None:
        logging.error("Could not find files in repository")
        await interaction.followup.send("Could not find files in repository", ephemeral=True)
        return
    if download_file(carat_file_url, ".", "Carat_UPDATE.py"):
        if download_file(utility_file_url, ".", "utility_UPDATE.py"):
            await interaction.followup.send("New files downloaded. Restarting...", ephemeral=True)
            logging.warning("New files downloaded.Stopping Carat to restart new version")
            await bot.close()
        else:
            os.remove("Carat_UPDATE.py")  # Clean up
            await interaction.followup.send("Could not connect to GitHub", ephemeral=True)
    else:
        await interaction.followup.send("Could not connect to GitHub", ephemeral=True)


@bot.slash_command(name="restart")
async def Restart(interaction: Interaction):
    if utility.authorize_dev_command(interaction.user):
        await interaction.send("Restarting...", ephemeral=True)
        logging.warning("Trying to restart Carat...")
        # bot.close() finishes execution of bot.run(), so Carat terminates and is restarted by the loop in AutoRestart
        await bot.close()
    else:
        await utility.deny_command(interaction, utility.DenialReason.NoPermission)
        logging.warning(f"{interaction.user.display_name} (id: {interaction.user.id}) attempted to restart Carat")


bot.run(token)
