# Configuration Reference

This file lists every placeholder value in the project that you must replace before deploying. Search for the placeholder name in the referenced file(s) and substitute your own value.

---

## AWS Account

| Placeholder | Description | Where to Find |
|---|---|---|
| `YOUR_ACCOUNT_ID` | Your 12-digit AWS account ID | AWS Console → top-right account menu |

**Used in:** `awsInfra/iamPolicies/DiscordBotMinecraftPolicy.json`, `awsInfra/iamPolicies/MinecraftGetSSMParameter.json`, `awsInfra/iamPolicies/MinecraftSSMParameterReadAccess.json`

---

## AWS Region

| Placeholder | Description | Example Values |
|---|---|---|
| `YOUR_AWS_REGION` | The AWS region you are deploying to | `us-east-1`, `ap-northeast-1`, `eu-west-1` |

> Your EBS volume, Subnet, Launch Template, and SSM parameters must **all be in the same region**.

**Used in:** `awsInfra/iamPolicies/MinecraftGetSSMParameter.json`, `awsInfra/iamPolicies/MinecraftSSMParameterReadAccess.json`

Also set this as the `MY_AWS_REGION` **environment variable** in your Lambda function configuration.

---

## EC2 Fleet (`createFleet.json`)

| Placeholder | Description | Where to Find |
|---|---|---|
| `YOUR_LAUNCH_TEMPLATE_ID` | The ID of your EC2 Launch Template | EC2 → Launch Templates → your template → *Template ID* column |
| `YOUR_SUBNET_ID` | The subnet to launch instances in | VPC → Subnets → the subnet in your chosen Availability Zone |

> The subnet must be in the **same Availability Zone** as your EBS volume.

---

## Discord Bot (`DiscordBot/lambdaFunction.py`)

| Placeholder | Description | Where to Find |
|---|---|---|
| `YOUR_DISCORD_USER_ID` | Your Discord user ID (18-digit number) | Discord: Settings → Advanced → Enable Developer Mode, then right-click your username → *Copy User ID* |

This value is added to the `AUTHORIZED_USERS` list, which controls who can run admin-only commands (`/start_fleet`, `/stop_fleet`, `/command`).

---

## Discord App Registration (`DiscordBot/commandRegistration.py`)

This script is run **locally once** to register slash commands with Discord. It reads from a `.env` file in the project root.

Create a `.env` file with:
```
DISCORD_APP_ID=your_application_id
DISCORD_BOT_TOKEN=your_bot_token
```

| Value | Where to Find |
|---|---|
| `DISCORD_APP_ID` | Discord Developer Portal → your app → *Application ID* |
| `DISCORD_BOT_TOKEN` | Discord Developer Portal → your app → Bot → *Token* |
