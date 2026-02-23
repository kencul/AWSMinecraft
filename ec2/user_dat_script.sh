#!/bin/bash -xe
# This script runs on instance boot to automate Minecraft server setup.
# It attaches an EBS volume, configures the server as a systemd service,
# sets up a scheduled restart, and adds an idle auto-shutdown service.

# --- CONFIGURATION ---
# Static Configuration
VOLUME_TAG_KEY="minecraft-server"
MOUNT_POINT="/minecraft"
DEVICE_NAME="/dev/sdb"
MINECRAFT_START_COMMAND="java -Xmx1300M -Xms1300M -jar server.jar nogui"
SERVER_DIR="${MOUNT_POINT}/server"
IDLE_TIMEOUT_MINUTES=10
DEBUG_LOG="/tmp/minecraft_auto_shutdown.log"

# Dynamic Configuration fetched from SSM Parameter Store
echo "Fetching configuration from AWS Parameter Store..."
RCON_PASSWORD=$(aws ssm get-parameter --name "/minecraft/rcon_password" --with-decryption --query "Parameter.Value" --output text)
EIP_ALLOCATION_ID=$(aws ssm get-parameter --name "/minecraft/eip_allocation_id" --query "Parameter.Value" --output text)
VOLUME_TAG_VALUE=$(aws ssm get-parameter --name "/minecraft/volume_tag_value" --query "Parameter.Value" --output text)

# Check if secrets were fetched successfully
if [ -z "$RCON_PASSWORD" ] || [ -z "$EIP_ALLOCATION_ID" ]; then
    echo "FATAL: Could not fetch secrets from Parameter Store. Check IAM permissions." >&2
    exit 1
fi


# --- AUTOMATION LOGIC ---

# GET INSTANCE METADATA
TOKEN=$(/usr/bin/curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(/usr/bin/curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/instance-id)
AWS_REGION=$(/usr/bin/curl -H "X-aws-ec2-metadata-token: $TOKEN" -s http://169.254.169.254/latest/meta-data/placement/availability-zone | /usr/bin/sed 's/\(.*\)[a-z]/\1/')

# ATTACH AND MOUNT EBS VOLUME
VOLUME_ID=$(/usr/bin/aws ec2 describe-volumes --region $AWS_REGION --filters "Name=tag:${VOLUME_TAG_KEY},Values=${VOLUME_TAG_VALUE}" --query "Volumes[0].VolumeId" --output text)
if [ -z "$VOLUME_ID" ] || [ "$VOLUME_ID" == "None" ]; then
    /usr/bin/echo "FATAL: Could not find EBS volume. Exiting." >&2
    exit 1
fi

# Add a retry loop to check the volume's state
/usr/bin/echo "Found EBS volume with ID: $VOLUME_ID. Checking its state."
MAX_WAIT_TIME=120
CURRENT_WAIT_TIME=0
VOLUME_STATE=$(/usr/bin/aws ec2 describe-volumes --region $AWS_REGION --volume-ids $VOLUME_ID --query "Volumes[0].State" --output text)

while [ "$VOLUME_STATE" != "available" ] && [ "$CURRENT_WAIT_TIME" -lt "$MAX_WAIT_TIME" ]; do
    /usr/bin/echo "Volume state is '$VOLUME_STATE'. Waiting..."
    /usr/bin/sleep 5
    CURRENT_WAIT_TIME=$((CURRENT_WAIT_TIME + 5))
    VOLUME_STATE=$(/usr/bin/aws ec2 describe-volumes --region $AWS_REGION --volume-ids $VOLUME_ID --query "Volumes[0].State" --output text)
done

if [ "$VOLUME_STATE" != "available" ]; then
    /usr/bin/echo "FATAL: EBS volume did not become available in time. Exiting." >&2
    exit 1
fi

/usr/bin/echo "EBS volume is available. Attaching..."

/usr/bin/aws ec2 attach-volume --region $AWS_REGION --volume-id $VOLUME_ID --instance-id $INSTANCE_ID --device $DEVICE_NAME
while [ ! -e $DEVICE_NAME ]; do /usr/bin/sleep 5; done
/usr/bin/mkdir -p $MOUNT_POINT
/usr/bin/mount $DEVICE_NAME $MOUNT_POINT
/usr/bin/chown -R ec2-user:ec2-user $MOUNT_POINT

# ASSOCIATE ELASTIC IP
/usr/bin/aws ec2 associate-address --region $AWS_REGION --instance-id $INSTANCE_ID --allocation-id $EIP_ALLOCATION_ID

# MINECRAFT SYSTEMD SERVICE
/usr/bin/cat << EOF > /etc/systemd/system/minecraft.service
[Unit]
Description=Minecraft Server
After=network.target
# This ensures the service only starts after the volume is mounted
RequiresMountsFor=${MOUNT_POINT}

[Service]
User=ec2-user
Type=simple # Change type to simple
WorkingDirectory=${SERVER_DIR}
# Execute the java command directly. Systemd handles the process.
ExecStart=${MINECRAFT_START_COMMAND}
ExecStop=/usr/local/bin/mcrcon -H 127.0.0.1 -P 25575 -p "${RCON_PASSWORD}" "stop"
# Automatically restart the service if it fails
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# SCRIPTS DIRECTORY AND RESTART WRAPPER
/usr/bin/mkdir -p /opt/minecraft
/usr/bin/cat << EOF > /opt/minecraft/restart_wrapper.sh
#!/bin/bash
/usr/local/bin/mcrcon -H 127.0.0.1 -P 25575 -p "${RCON_PASSWORD}" "say Server is restarting in 1 minute!"
/usr/bin/sleep 60
/usr/bin/systemctl restart minecraft.service
EOF
/usr/bin/chmod +x /opt/minecraft/restart_wrapper.sh

# CRON JOB FOR SCHEDULED RESTART
/usr/bin/mkdir -p /etc/cron.d
/usr/bin/echo "0 */6 * * * root /opt/minecraft/restart_wrapper.sh" > /etc/cron.d/minecraft-restart
/usr/bin/systemctl enable --now crond

# AUTO-SHUTDOWN SCRIPT
/usr/bin/cat << EOF > /opt/minecraft/auto_shutdown.sh
#!/bin/bash
# Add a log file path at the top
echo "--- Script started at $(date) ---" >> $DEBUG_LOG

RCON_PASSWORD="${RCON_PASSWORD}"
IDLE_TIMEOUT_MINUTES=${IDLE_TIMEOUT_MINUTES}
idle_minutes=0

echo "Entering RCON wait loop..." >> $DEBUG_LOG
while ! /usr/local/bin/mcrcon -H 127.0.0.1 -P 25575 -p "\$RCON_PASSWORD" "list" > /dev/null 2>&1; do
    /usr/bin/echo "Waiting for Minecraft RCON to be available..."
    echo "RCON not available. Sleeping for 10s..." >> $DEBUG_LOG
    /usr/bin/sleep 10
done
echo "RCON is available. Exited wait loop." >> $DEBUG_LOG
echo "Entering main player check loop..." >> $DEBUG_LOG
while true; do
    player_list=\$(/usr/local/bin/mcrcon -H 127.0.0.1 -P 25575 -p "\$RCON_PASSWORD" "list")
    player_count=\$(/usr/bin/echo "\$player_list" | /usr/bin/awk 'BEGIN{FS="[ /]"} /players online/{print \$3}')

    if ! [[ "\$player_count" =~ ^[0-9]+$ ]]; then
        player_count=1
    fi

    /usr/bin/echo "Current player count: \$player_count"

    if [ "\$player_count" -eq 0 ]; then
        idle_minutes=\$((idle_minutes + 1))
        /usr/bin/echo "Server idle. Shutdown counter: \$idle_minutes / \$IDLE_TIMEOUT_MINUTES"
    else
        idle_minutes=0
        /usr/bin/echo "Players are online. Resetting shutdown counter."
    fi

    if [ "\$idle_minutes" -ge "\$IDLE_TIMEOUT_MINUTES" ]; then
        /usr/bin/echo "Server has been idle for \$IDLE_TIMEOUT_MINUTES minutes. Shutting down."
        TOKEN=\$(/usr/bin/curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
        INSTANCE_ID=\$(/usr/bin/curl -H "X-aws-ec2-metadata-token: \$TOKEN" -s http://169.254.169.254/latest/meta-data/instance-id)
        AWS_REGION=\$(/usr/bin/curl -H "X-aws-ec2-metadata-token: \$TOKEN" -s http://169.254.169.254/latest/meta-data/placement/availability-zone | /usr/bin/sed 's/\(.*\)[a-z]/\1/')
        echo "Debugging: INSTANCE_ID is \$INSTANCE_ID"
        echo "Debugging: AWS_REGION is \$AWS_REGION"
        FLEET_ID=\$(/usr/bin/aws ec2 describe-instances --region "\$AWS_REGION" --instance-ids "\$INSTANCE_ID" --query "Reservations[].Instances[].Tags[?Key=='aws:ec2:fleet-id'].Value" --output text)
        echo "Debugging: FLEET_ID is \$FLEET_ID"
        if [ -n "\$FLEET_ID" ]; then
            /usr/bin/echo "Found EC2 Fleet ID: \$FLEET_ID. Canceling request..."
            /usr/bin/aws ec2 modify-fleet --region "\$AWS_REGION" --fleet-id "\$FLEET_ID" --target-capacity-specification TotalTargetCapacity=0
            exit 0
        else
            /usr/bin/echo "ERROR: Could not find EC2 Fleet ID."
            exit 1
        fi
    fi
    /usr/bin/sleep 60
done
EOF
/usr/bin/chmod +x /opt/minecraft/auto_shutdown.sh

# AUTO-SHUTDOWN SYSTEMD SERVICE
/usr/bin/cat << EOF > /etc/systemd/system/minecraft-shutdown.service
[Unit]
Description=Minecraft Auto-Shutdown Service
After=minecraft.service

[Service]
User=ec2-user
ExecStartPre=/bin/sleep 30
ExecStart=/opt/minecraft/auto_shutdown.sh
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# ENABLE AND START ALL SERVICES
/usr/bin/systemctl daemon-reload
/usr/bin/systemctl enable minecraft.service
/usr/bin/systemctl start minecraft.service
/usr/bin/systemctl enable minecraft-shutdown.service
/usr/bin/systemctl start minecraft-shutdown.service
