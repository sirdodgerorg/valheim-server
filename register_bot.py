"""
https://discord.com/developers/docs/interactions/slash-commands#registering-a-command
"""

import argparse

import requests


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--name", choices=["moria", "valheim"])
    parser.add_argument("-a", "--application-id")
    parser.add_argument("-g", "--guild-id")
    parser.add_argument("-t", "--token")
    args = parser.parse_args()

    url = f"https://discord.com/api/v10/applications/{args.application_id}/guilds/{args.guild_id}/commands"
    headers = {"Authorization": f"Bot {args.token}"}
    json = {
        "name": args.name,
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
