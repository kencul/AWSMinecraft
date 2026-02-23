# EC2 Security Groups

Create a Security Group (e.g., `MC-SecurityGroup`) and attach it to your Launch Template.

## Inbound Rules

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 25565 | TCP | `0.0.0.0/0` | Minecraft game traffic |
| 22 | TCP | Your IP | SSH access |
| 22 | TCP | [EC2 Instance Connect IP range for your region](https://ip-ranges.amazonaws.com/ip-ranges.json) | Browser-based SSH via AWS console |

> **Note on RCON (Port 25575):** RCON is called from within the instance itself by the auto-shutdown script. It does not need an inbound security group rule as AWS security groups only filter external traffic.

## Outbound Rules

Leave the default outbound rule in place: allow all traffic on all ports.
