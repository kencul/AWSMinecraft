# AWS Minecraft Spot-Server: Discord-Controlled Infrastructure

A cost-optimized, automated Minecraft server solution hosted on **AWS EC2 Spot Instances**. This project reduces monthly hosting costs while maintaining accessibility by leveraging Spot Fleets and a serverless Discord bot control plane.

## Overview

Traditional 24/7 cloud hosting is expensive. This system treats infrastructure as "Cattle, not Pets":

* **Discord Control**: Anyone with permission can wake the server using `/start`.
* **Spot Pricing**: Uses AWS Spot Instances for up to 90% cost savings.
* **Auto-Shutdown**: Automatically sets Spot Fleet capacity to 0 after configurable amount of inactivity.
* **Data Persistence**: World data is stored on a persistent EBS volume that automatically re-attaches to new instances on boot.

---

## Infrastructure Architecture

### Core Components

* **EC2 Spot Fleet**: Manages a pool of varied instance types (T4g family) to ensure high availability at low cost.
* **Lambda & API Gateway**: A serverless entry point that handles Discord slash commands.
* **Systems Manager (SSM)**: Securely stores secrets like RCON passwords and Fleet IDs.
* **User Data Script**: A master bash script that orchestrates the "Cold Start" (mounting disks, associating IPs, starting services).

---

## Setup

**Before you begin:** See [config.md](config.md) for a full reference of every placeholder value (`YOUR_ACCOUNT_ID`, `YOUR_AWS_REGION`, etc.) you will need to substitute throughout the setup steps below.

### Step 1: Data Persistence (EBS Volume)

The EBS volume acts as the persistent storage for your world. Because Spot instances are ephemeral "cattle," this volume must be prepared manually once so the automation script can find and attach it on every boot.

1. **Create Volume**: Go to **EC2 > Volumes > Create volume**.
* **Size**: 8 GiB (minimum).
* **Availability Zone**: Select a specific zone (e.g., `us-east-1a`). Your server must always run in this zone to attach the disk.

2. **Tagging**: Add a tag with Key: `minecraft-server` and Value: `server-files`.

3. **File Structure & Initial Setup**:
* Launch a temporary Amazon Linux instance in the same AZ.
* Attach the volume to the instance.
* Format the volume: `sudo mkfs -t xfs /dev/sdb`.
* Mount it and set up the following directory structure:
```text
/minecraft/
└── server/
    ├── server.jar        # Your Minecraft server executable
    ├── eula.txt          # Must set eula=true
    ├── server.properties # Configure RCON here
    └── world/            # Your world data
```

4. **RCON Setup**: In `server.properties`, ensure the following are set:
* `enable-rcon=true`
* `rcon.port=25575`
* `rcon.password=YOUR_SECURE_PASSWORD` (This must match the password you later put in SSM).  

5. **Finalize**: Detach the volume and terminate the temporary instance.

---

### Step 2: Custom AMI

To ensure the server boots in under a minute, we use a custom AMI with dependencies pre-installed.

1. **Launch Instance**: Launch a temporary instance using **Amazon Linux 2023** with **ARM (64-bit)** architecture.
2. **Install Base Packages**: SSH in and run:
```bash
sudo dnf install -y java-21-amazon-corretto-devel git make gcc cronie
```

3. **Compile mcrcon**: Build the RCON tool from source to match the ARM architecture:
```bash
git clone https://github.com/Tiiffi/mcrcon.git
cd mcrcon && make && sudo make install
```

4. **Create Image**: In the EC2 Console, select the instance, go to **Actions > Image and templates > Create image**. Name it `MC-Server-AMI-With-Java`.

---

### Step 3: Networking & Security

#### 1. Elastic IP (EIP)

1. Go to **EC2 > Network & Security > Elastic IPs**.
2. Click **Allocate Elastic IP address** and click **Allocate**.
3. Note the **Allocation ID** (e.g., `eipalloc-0a1b2c3d`). You will need this for SSM.

#### 2. Security Groups

Create a Security Group and attach it to your Launch Template. See [`awsInfra/EC2-security-groups.md`](awsInfra/EC2-security-groups.md) for the full inbound rule table.

* **Port 25565 (TCP)**: Source `0.0.0.0/0` (Game traffic).
* **Port 22 (SSH)**: Source `My IP`.

#### 3. IAM Roles

Create the two roles listed in [`awsInfra/IAM-roles.md`](awsInfra/IAM-roles.md). The custom policy JSON files are in `awsInfra/iamPolicies/`. Before attaching them, replace `YOUR_ACCOUNT_ID` and `YOUR_AWS_REGION` in each JSON (see [config.md](config.md)).

* **`EC2-Minecraft-Server-Role`**: Attached to the EC2 instance. Needs EC2, SSM, and Fleet management permissions.
* **`DiscordBotMinecraftRole`**: Attached to the Lambda function. Needs Fleet and SSM read/write permissions.

#### 4. SSM Parameter Store

Store the following variables in **AWS Systems Manager > Parameter Store**:

* `/minecraft/rcon_password` (SecureString): Your RCON password.
* `/minecraft/eip_allocation_id` (String): Your EIP Allocation ID.
* `/minecraft/volume_tag_value` (String): `server-files`.
* `/minecraft/discord_public_key` (String): From the Discord Dev Portal.

---

### Step 4: The Launch Template

1. **Create Template**: Go to **EC2 > Launch Templates > Create launch template**.
2. **AMI**: Select your `MC-Server-AMI-With-Java`.
3. **Key Pair**: Select an existing key pair or create one. Required for SSH access.
4. **Advanced Hardware Controls**: Set **vCPUs** to 2 and **Memory** to 2048–5000 MiB.
5. **Advanced Details**:
* **IAM Instance Profile**: Select your EC2 Instance Role.
* **User Data**: Paste the contents of `ec2/user_dat_script.sh`.

---

### Step 5: Lambda & API Gateway Setup

#### 1. The PyNaCl Layer (Docker Required)

1. Ensure **Docker** is running. From the project root, run:
```bash
bash layer/build_layer.sh
```
This produces `layer/pynacl-layer.zip`.

2. Go to **Lambda > Layers > Create layer**. Upload `layer/pynacl-layer.zip`, select **Python 3.13** as the compatible runtime, and click **Create**.

#### 2. Creating the Function

1. **Create Function**: Select **Author from scratch**, Runtime **Python 3.13**, Architecture **x86_64**, and use your `DiscordBotMinecraftRole`.
2. **Add Files**:
* Copy paste `DiscordBot/lambda_function.py` into `lambda_function.py` in your lambda function in the management console.
* **Crucial**: Upload `awsInfra/createFleet.json` into the **same directory** as the Lambda code. The function reads this file to create the fleet. Make sure you have filled in `YOUR_LAUNCH_TEMPLATE_ID` and `YOUR_SUBNET_ID` first.
3. **Add Layer**: Scroll to the bottom of the function page, click **Add a layer > Custom layers**, and select your `PyNaCl` layer.
4. **Set Environment Variable**: Go to **Configuration > Environment variables**, add `MY_AWS_REGION` set to your AWS region (e.g., `us-east-1`). Without this, the function defaults to `us-east-1`.
5. **Update Config**: In the code, update `AUTHORIZED_USERS` with your Discord user ID.

#### 3. API Gateway Trigger

1. In the Lambda Console, click **Add trigger > API Gateway**.
2. Select **Create an API**, Type **HTTP API**, and Security **Open**.
* *Security Note*: Set this to "Open" because the Python code uses the `PyNaCl` layer to verify the `x-signature-ed25519` header from Discord on every request.
3. Copy the **Invoke URL**.

---

### Step 6: Discord Bot Integration

1. **Developer Portal**: Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. **Interactions Endpoint**: Paste your API Gateway Invoke URL here.
3. **Invite Bot**: Under **OAuth2 > URL Generator**, select `applications.commands` and use the link to add it to your server.
4. **Command Registration**:
* Create a `.env` file in the project root with `DISCORD_APP_ID` and `DISCORD_BOT_TOKEN`.
* Install dependencies: `pip install requests python-dotenv`
* Run `python DiscordBot/commandRegistration.py` to register the commands with Discord.

---

## Usage

Once setup is complete, **start here for the first launch:**
1. Run `/start_fleet` in your Discord server to create the initial EC2 Fleet and store its ID in SSM. This must be done by an authorized user.
2. Run `/start` to set the fleet capacity to 1 and boot the server. It will be ready in less than a minute.

Subsequent uses only need `/start`. `/start_fleet` is only needed again if the fleet is fully deleted.

**Available commands:**

* **`/help`**: Shows all available commands.
* **`/start`**: Scales the existing Spot Fleet from 0 to 1. The server will be ready in a minute.
* **`/status`**: Checks the live status of the server, including the player count and current IP.
* **`/command [minecraft_command]`**: (Admin Only) Sends a command directly to the Minecraft console via SSM (e.g., `/command say Hello World`).
* **`/start_fleet`**: (Admin Only) Re-initializes a new Spot Fleet request if the previous one was deleted.
* **`/stop_fleet`**: (Admin Only) Fully terminates the Spot Fleet request and the instance.
* **Auto-Shutdown**: The server automatically polls player counts every minute. If 0 players are detected for 10 consecutive minutes, the instance triggers a self-shutdown by setting the Fleet capacity back to 0.
