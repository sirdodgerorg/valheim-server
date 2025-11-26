# AWS CDK for game servers

Run dedicated game servers and set up Discord slash-command handlers to start and stop them.

Borrows heavily from:
* Brian Caffey's [valheim-cdk-discord-interactions](https://gitlab.com/briancaffey/valheim-cdk-discord-interactions)
* Neil Kuan's [cdk-valheim](https://github.com/gotodeploy/cdk-valheim)
* Andrew Sav's [moria-docker](https://github.com/AndrewSav/moria-docker)

# Maintenance

See the (Maintenance Guide)[MAINTENANCE.md]


# Setup instructions for a new game server

## Create a steam user

```
useradd steam -m -s /bin/bash
```

## Mount EFS volume

Create a mount point and set permissions.

```
sudo apt install nfs-common
sudo mkdir /mnt/efs
sudo chown steam:steam /mnt/efs
```

Look up the filesystem id on the (EFS AWS Console)[https://us-west-2.console.aws.amazon.com/efs/home?region=us-west-2#/file-systems]

Modify /etc/fstab and add line
```
{filesystem id}.efs.us-west-2.amazonaws.com:/ /mnt/efs nfs4 nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport,_netdev 0 0
```

And mount it now:
```
sudo mount -a
```

## Install game

| Game | Application ID |
|-|-|
| Return to Moria | 3349480 |
| Valheim | 896660 |

### Return to Moria

Return to Moria is a Windows application and does not have a Linux build. There is a community Docker image that uses Wine to run it.

Install (Docker)[https://docs.docker.com/engine/install/ubuntu/]
```
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Make sure Docker is running and run it on startup.
```
sudo systemctl status docker
sudo systemctl enable docker
```

Clone the community Docker image for Return to Moria. Symlink the server directory it wants to create to the existing EFS volume.
```
mkdir /mnt/efs/moria
ln -s /mnt/efs/moria /home/steam/moria
cd /home/steam/moria
git clone https://github.com/AndrewSav/moria-docker
cd moria-docker
docker compose up -u steam:steam -d --force-recreate
```


### Valheim

#### Install steam

Follow the (instructions for installing SteamCMD)[https://developer.valvesoftware.com/wiki/SteamCMD#Ubuntu]
```
sudo add-apt-repository multiverse; sudo dpkg --add-architecture i386; sudo apt update
sudo apt install steamcmd
```

TBD


## Set up CloudWatch log exporter

Follow instructions on installing the (Amazon Cloudwatch Agent)[https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/QuickStartEC2Instance.html]

```
cd /root
wget https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i -E ./amazon-cloudwatch-agent.deb
```

1. Shut down the agent 

```
amazon-cloudwatch-agent-ctl -a stop
```

1. Modify `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.toml` and change `run_as_user` to `root`.
1. Modify `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.d/default` and change `run_as_user` to `root`.

```
amazon-cloudwatch-agent-ctl -a append-config /mnt/efs/moria/cloudwatch.conf
```
