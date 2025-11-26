"""
https://discord.com/developers/docs/interactions/slash-commands#registering-a-command

https://discord.com/developers/applications

Get the application id from General Information -> Application ID
Get the token from Bot -> Token
Get the guild id by enabling developer options User Settings -> Advanced -> Developer Mode,
    then right click on a server and copy Server ID

"""

import argparse

import requests


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--name", required=True, choices=["moria", "valheim"])
    parser.add_argument(
        "-a",
        "--application-id",
        required=True,
        help="The bot public key (not actually application id!)",
    )
    parser.add_argument("-g", "--guild-id", required=True)
    parser.add_argument("-t", "--token", required=True)
    args = parser.parse_args()

    url = f"https://discord.com/api/v10/applications/{args.application_id}/guilds/{args.guild_id}/commands"
    headers = {"Authorization": f"Bot {args.token}"}
    json = {
        "name": args.name,
        "type": 1,
        "description": f"Start, stop or get the status of the {args.name.capitalize()} server",
        "options": [
            {
                "name": f"{args.name}_server_controls",
                "description": f"Control the {args.name.capitalize()} server",
                "type": 3,
                "required": True,
                "choices": [
                    {"name": "status", "value": "status"},
                    {"name": "start", "value": "start"},
                    {"name": "stop", "value": "stop"},
                ],
            },
        ],
    }
    r = requests.post(url, headers=headers, json=json)
    print(r.content)
