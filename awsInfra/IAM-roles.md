# IAM Roles

Two IAM roles are required. The custom policy JSON files referenced below are in `awsInfra/iamPolicies/`. Before attaching them, open each JSON file and replace `YOUR_ACCOUNT_ID` and `YOUR_AWS_REGION` with your values (see [config.md](../config.md)).

---

## 1. `EC2-Minecraft-Server-Role`

Attached to the EC2 instance via the Launch Template.

| Field | Value |
|---|---|
| **Trusted Entity** | AWS Service: `ec2.amazonaws.com` |

**Attached Policies:**
| Policy | Type |
|---|---|
| `AmazonEC2FullAccess` | AWS Managed |
| `AmazonSSMManagedInstanceCore` | AWS Managed |
| `CancelSpotFleet` | Custom — `iamPolicies/CancelSpotFleet.json` |
| `MinecraftSSMParameterReadAccess` | Custom — `iamPolicies/MinecraftSSMParameterReadAccess.json` |

---

## 2. `DiscordBotMinecraftRole`

Attached to the Lambda function.

| Field | Value |
|---|---|
| **Trusted Entity** | AWS Service: `lambda.amazonaws.com` |

**Attached Policies:**
| Policy | Type |
|---|---|
| `DiscordBotMinecraftPolicy` | Custom — `iamPolicies/DiscordBotMinecraftPolicy.json` |
| `MinecraftGetSSMParameter` | Custom — `iamPolicies/MinecraftGetSSMParameter.json` |


