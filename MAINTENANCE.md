
# Return to Moria

## Console access
```
docker compose attach moria
```

To exit: ctrl-p ctrl-q

## Upgrade world (ONE WAY DOOR!)

The world can be upgraded to take advantage of DLC features, but players without the DLC will no longer be able to join.

The configuration for what DLCs will be enabled on new worlds, and what worlds should be upgraded on next launch are stored in `/home/steam/moria/moria-docker/server/MoriaServerConfig.ini`


# On instance termination

## Update the instance id for the new server

* Add the instance id to lambda/functions/discord/discord.py in the SERVER_INSTANCES variable. This tells the Discord interaction handler which instance to start when it receives a message from an application.

* Add the instance id to lambda/functions/updatedns/updatedns.py in the SERVER_DOMAIN variable. When the instance with that id starts, the lambda will update the DNS entry from this dictionary to the newly running server's public IP address.
