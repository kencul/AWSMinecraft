import os
import requests
import time
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# --- CONFIGURATION ---
# Get these from your .env file or set them directly
APP_ID = os.environ.get("DISCORD_APP_ID")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") 
# --- END CONFIGURATION ---

if not all([APP_ID, BOT_TOKEN]):
    print("Error: Please set DISCORD_APP_ID and DISCORD_BOT_TOKEN in your .env file.")
    exit()

url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"

# This is the definition of your slash commands
commands = [
    {
        "name": "start",
        "type": 1,
        "description": "Starts the AWS Minecraft server by modifying the existing fleet."
    },
    {
        "name": "start_fleet",
        "type": 1,
        "description": "Creates a new EC2 Fleet and starts the Minecraft server."
    },
    {
        "name": "stop_fleet",
        "type": 1,
        "description": "Deletes the EC2 Fleet and terminates the Minecraft server instances."
    },
    {
        "name": "status",
        "type": 1,
        "description": "Checks the status of the Minecraft server."
    },
    {
        "name": "help",
        "type": 1,
        "description": "Provides information about available commands."
    },
    {
        "name": "command",
        "type": 1,
        "description": "Sends a server command through RCON.",
        "options": [
            {
                "name": "command",
                "description": "The command to run (e.g., list).",
                "type": 3,
                "required": True
            }
        ]
    }
]

headers = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json"
}

print("Registering commands with Discord...")

for command in commands:
    print(f"  - Registering '/{command['name']}' command...")
    response = requests.post(url, headers=headers, json=command)

    if response.status_code == 200 or response.status_code == 201:
        print(f"  - Success! The '/{command['name']}' command has been registered.")
    else:
        print(f"  - Error registering '/{command['name']}' command: {response.status_code}")
        print(response.text)
    # Add a small delay to avoid rate limiting
    time.sleep(1)

print("\nAll commands registered. It may take up to an hour for them to appear in your server.")
