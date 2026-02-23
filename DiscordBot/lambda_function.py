import os
import json
import socket
import boto3
import time
import re
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from botocore.exceptions import ClientError

# Load environment variables
AWS_REGION = os.environ.get('MY_AWS_REGION', 'us-east-1') # Default to us-east-1 if not set

ec2_client = boto3.client('ec2', region_name=AWS_REGION)
ssm_client = boto3.client('ssm', region_name=AWS_REGION)

server_port = 25565

ssmResponse = ssm_client.get_parameter(
    Name='/minecraft/discord_public_key'
)
PUBLIC_KEY = ssmResponse['Parameter']['Value']
verify_key = VerifyKey(bytes.fromhex(PUBLIC_KEY))

# Hardcoded list of authorized user IDs (Discord user IDs as strings)
# Find your ID in Discord: Settings > Advanced > Enable Developer Mode, then right-click your name > Copy User ID
AUTHORIZED_USERS = [
    "YOUR_DISCORD_USER_ID"
]

def is_authorized(user_id):
    """
    Checks if a user is authorized to run a command.
    Note: A more advanced implementation might check for user roles instead, so permissions can be given in Discord instead of changing the lambda code
    """
    return user_id in AUTHORIZED_USERS

def get_fleet_id():
    """Retrieves the fleet ID from SSM Parameter Store."""
    try:
        ssm_response = ssm_client.get_parameter(Name='/minecraft/fleet_id')
        return ssm_response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return None
        raise e

def get_eip_id():
    """Retrieves the EIP Allocation ID from SSM Parameter Store."""
    try:
        ssm_response = ssm_client.get_parameter(Name='/minecraft/eip_allocation_id')
        return ssm_response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return None
        raise e
        
def get_rcon_password():
    """Retrives the encrypted RCON password from SSM Parameter Store."""
    try:
        ssm_response = ssm_client.get_parameter(Name='/minecraft/rcon_password', WithDecryption=True)
        return ssm_response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return None
        raise e

def check_server_port(ip, port, timeout=3):
    """
    Checks if a given port is open on an IP address.
    Returns 'ONLINE' if the port is open, 'OFFLINE' otherwise.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            return 'ONLINE'
    except (socket.timeout, ConnectionRefusedError):
        return 'OFFLINE'
    except Exception as e:
        print(f"Error checking port: {e}")
        return 'UNKNOWN'

def strip_ansi_codes(text):
    """
    Strips ANSI escape codes from a string.
    """
    ansi_regex = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_regex.sub('', text)

def start_fleet():
    """Creates a new EC2 Fleet and stores its ID in SSM Parameter Store."""
    try:
        FLEET_ID = get_fleet_id()
        if FLEET_ID:
            try:
                # Check current state of existing fleet ID
                response = ec2_client.describe_fleets(FleetIds=[FLEET_ID])
                print(response)
                config = response['Fleets'][0]
                status = config['FleetState']
                print("Fetched fleet status")
                print(f"Fleet status: {status}")

                if status in ['submitted', 'active', 'modifying']:
                    return f"Cannot create a new fleet: the current fleet is active! Current fleet status: {status}."

            except botocore.exceptions.ClientError as e:
                # If the error is 'InvalidFleetId.NotFound', the fleet is so old it isn't showing up in describe_fleets
                # We can safely ignore this and move on to creating a new fleet.
                if e.response['Error']['Code'] == 'InvalidFleetId.NotFound':
                    print(f"Fleet {FLEET_ID} no longer exists in AWS records. Proceeding...")
                else:
                    # If it's a different error, re-raise it
                    raise e

        # Read the fleet configuration from a JSON file
        print("Reading fleet configuration from createFleet.json...")
        with open('createFleet.json', 'r') as f:
            fleet_config = json.load(f)
        
        print("Creating new EC2 Fleet...")
        create_fleet_response = ec2_client.create_fleet(**fleet_config)
        
        fleet_id = create_fleet_response.get('FleetId')
        
        if not fleet_id:
            return "ERROR: FleetId was not returned from the create-fleet call."

        print(f"Successfully created Fleet with ID: {fleet_id}")
        
        # Save the Fleet ID to SSM Parameter Store
        print(f"Saving Fleet ID to Parameter Store at /minecraft/fleet_id...")
        ssm_client.put_parameter(
            Name='/minecraft/fleet_id',
            Value=fleet_id,
            Type='String',
            Overwrite=True
        )
        
        return f"Successfully created new fleet: `{fleet_id}`."
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return f"An error occurred: {e}"

def stop_fleet():
    """Deletes the existing fleet based on the ID in SSM Parameter Store."""
    try:
        FLEET_ID = get_fleet_id()

        if not FLEET_ID:
            return f"Cannot delete fleet: no fleet ID in SSM store!"

        # Check current state of existing fleet ID
        response = ec2_client.describe_fleets(FleetIds=[FLEET_ID])
        print(response)
        config = response['Fleets'][0]
        status = config['FleetState']
        print("Fetched fleet status")
        print(f"Fleet status: {status}")

        if status not in ['submitted', 'active', 'modifying']:
            return f"Cannot delete fleet: the current fleet is not active! Current fleet status: {status}."
        
        print("Deleting EC2 Fleet...")
        
        # Delete fleet and terminate instances
        ec2_client.delete_fleets(
            FleetIds=[FLEET_ID],
            TerminateInstances=True
        )

        return f"Successfully deleted fleet: `{FLEET_ID}`."
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return f"An error occurred: {e}"

def start_minecraft_server():
    """Starts the Minecraft server by setting Fleet target capacity to 1."""
    try:
        # Get fleet ID
        FLEET_ID = get_fleet_id()

        if not FLEET_ID:
            return "Cannot start Minecraft server: no fleet registered in SSM! Run /start_fleet to start a fleet"

        # Retrieve data and parse
        response = ec2_client.describe_fleets(FleetIds=[FLEET_ID])
        print(response)
        config = response['Fleets'][0]
        status = config['FleetState']
        print("Fetched fleet status")
        print(f"Fleet status: {status}")
        
        if status in ['cancelled', 'cancelled_running', 'cancelled_terminating', 'deleted', 'deleted_terminating']:
            return "Cannot start the server: the Fleet request has been cancelled. Create a new fleet with /start_fleet"

        if config['TargetCapacitySpecification']['TotalTargetCapacity'] > 0:
            return "The Minecraft server is already running or in the process of starting."
            
        ec2_client.modify_fleet(
            FleetId=FLEET_ID,
            TargetCapacitySpecification={
                'TotalTargetCapacity': 1
            }
            #ExcessCapacityTerminationPolicy='noTermination' # Important to prevent immediate shutdown
        )
        return "Server startup initiated! Please allow a few minutes for the instance to boot."
    except Exception as e:
        print(f"Error starting server: {e}")
        return "An error occurred while trying to start the server. Check the Lambda logs."

def status_fleet():
    """Retrieves and returns the status of the EC2 fleet, instances, and Elastic IP."""
    try:
        # Check if a fleet ID exists in SSM Parameter Store
        fleet_id = get_fleet_id()
        if not fleet_id:
            return "The Minecraft server is currently offline. No active fleet ID found."
        
        eip_id = get_eip_id()
        eip_response = ec2_client.describe_addresses(AllocationIds=[eip_id])
        eip_info = eip_response['Addresses'][0]
        eip_public_ip = eip_info['PublicIp']
        
        fleet_response = ec2_client.describe_fleets(FleetIds=[fleet_id])
        fleet_info = fleet_response['Fleets'][0]
        
        fleet_state = fleet_info['FleetState']
        
        fleet_instance_response = ec2_client.describe_fleet_instances(FleetId=fleet_id)

        instance_id = "N/A"
        instance_public_ip = "N/A"
        instance_state = "N/A"
        instance_type = "N/A"
        instance_launch_time = "N/A"
        server_status = "N/A"
        instance_lifecycle = "N/A"
        
        # Get instance ID and IP if the fleet has instances
        if 'ActiveInstances' in fleet_instance_response and len(fleet_instance_response['ActiveInstances']) > 0:
            
            instance_id = fleet_instance_response['ActiveInstances'][0]['InstanceId']
            
            # Fetch instance details to get the public IP and launch time
            instance_response = ec2_client.describe_instances(InstanceIds=[instance_id])
            instance_details = instance_response['Reservations'][0]['Instances'][0]
            instance_state = instance_details['State']['Name']
            instance_public_ip = instance_details.get('PublicIpAddress', 'N/A')
            instance_launch_time = instance_details.get('LaunchTime', 'N/A')
            instance_type = instance_details.get('InstanceType', 'N/A')
            instance_lifecycle = instance_details.get('InstanceLifecycle', 'N/A')

            # Check Minecraft server port only if instance is running and has a public IP
            if instance_state == 'running' and instance_public_ip != 'N/A':
                server_status = check_server_port(instance_public_ip, server_port)
            
        status_message = (
            "**Minecraft Server Status:**\n\n"
            f"**Fleet ID:** `{fleet_id}`\n"
            f"**Fleet State:** `{fleet_state}`\n"
            f"**Instance ID:** `{instance_id}`\n"
            f"**Instance State:** `{instance_state}`\n"
            f"**Instance Lifecycle:** `{instance_lifecycle}`\n"
            f"**Instance Type:** `{instance_type}`\n"
            f"**Server Status:** `{server_status}`\n"
            f"**Launch Time:** `{instance_launch_time}`\n"
            f"**Instance Public IP:** `{instance_public_ip}`\n"
            f"**Assigned Elastic IP:** `{eip_public_ip}`"
        )
        
        # Handle Fleets that are shutting down or gone
        if fleet_state in ["deleted_terminating", "deleted", "failed"]:
            status_message += f"\n\n**Fleet is shutting down or unavailable!** Please run `/start_fleet` to create a new one."
        # Handle cases where the Instance is running, but the Minecraft Server itself is failing
        elif instance_state == 'running' and server_status == "OFFLINE":
            status_message += (
                f"\n\n**Warning:** The EC2 instance is running, but the **Minecraft server is OFFLINE**.\n"
                f"Something went wrong during startup. Check logs or run `/start` to try and kickstart the service."
            )
        # Everything is actually ready
        elif instance_state == 'running' and server_status == "ONLINE" and eip_public_ip:
            status_message += f"\n\n**Server ready!** Connect with: `{eip_public_ip}`"
        # Handle transition states
        elif fleet_state == "active" and instance_state != 'running':
            status_message += f"\n\n**Fleet is active but no instance is running yet.** Run `/start` to start the server."
        elif fleet_state in ["modifying", "submitted"]:
            status_message += f"\n\n**Fleet loading!** Wait a moment and run `/status` again!"
        else:
            status_message += f"\n\n**Status unclear.** Run `/start_fleet` or contact the admin."
        
        print(status_message)
        return status_message

    except Exception as e:
        print(f"An error occurred: {e}")
        return f"An error occurred while getting the server status: {e}"

def run_command(mc_command):
    """
    Runs a Minecraft server command on the active EC2 instance.
    The command is executed via SSM Run Command.
    """
    try:
        # Get fleet ID
        fleet_id = get_fleet_id()

        if not fleet_id:
            return "Server is offline. No fleet ID found."
        print("Fleed ID found!")

        # Get instance ID from the fleet
        fleet_instance_response = ec2_client.describe_fleet_instances(FleetId=fleet_id)
        if 'ActiveInstances' not in fleet_instance_response or len(fleet_instance_response['ActiveInstances']) == 0:
            return "No instances found in the fleet. Server might be starting or has stopped. Run `/status` for more information!"
        print("Fleet has active instance!")

        # Get instance ID and fetch IP and state
        # Fetch instance details to get the public IP and launch time
        instance_id = fleet_instance_response['ActiveInstances'][0]['InstanceId']
        print(f"Instance ID: {instance_id}")
        instance_response = ec2_client.describe_instances(InstanceIds=[instance_id])
        instance_details = instance_response['Reservations'][0]['Instances'][0]
        instance_public_ip = instance_details.get('PublicIpAddress', 'N/A')
        instance_state = instance_details['State']['Name']

        print(f"Instance IP: {instance_public_ip}, Instance state: {instance_state}")

        if instance_public_ip == 'N/A':
            return "Failed to get instance public IP!"
        
        if instance_state != 'running':
            return "Failed to run command: Instance not running."
            
        # Check Minecraft server port only if instance is running and has a public IP
        server_status = check_server_port(instance_public_ip, server_port)

        print(f"Server status: {server_status}")

        if server_status != 'ONLINE':
            return "Failed to run command: Minecraft server not available!"

        # Get RCON password
        rcon_password = get_rcon_password()

        print(f"RCON password: {rcon_password}")

        # Command to be executed on the instance
        ssm_command = [f"/usr/local/bin/mcrcon -H 127.0.0.1 -p \"{rcon_password}\" \"{mc_command}\""]

        # Send the command via SSM
        print(f"Sending command to instance {instance_id}: {mc_command}")
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': ssm_command},
            CloudWatchOutputConfig={
                'CloudWatchOutputEnabled': True
            }
        )
        
        command_id = response['Command']['CommandId']
        print(f"Command ID: {command_id}")

        # Poll for command status to avoid long wait times
        time.sleep(0.5)
        status = "Pending"
        retries = 0
        max_retries = 4
        while status in ['Pending', 'InProgress'] and retries < max_retries:
            output_response = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            status = output_response['Status']
            if status in ['Pending', 'InProgress']:
                time.sleep(0.5)
                retries += 1
        print(f"Polled response {retries} time(s)")
        if status in ['Pending', 'InProgress']:
            return "Command timed out. Please check the SSM logs for more details."

        # Retrieve command status and output
        status = output_response['Status']
        stdout = output_response['StandardOutputContent']
        stripped_stdout = strip_ansi_codes(stdout)
        print(f"Command output: {stripped_stdout}")
        
        return f"Command `{mc_command}` executed. Status: `{status}`\nOutput:```{stripped_stdout}```"

    except ClientError as e:
        print(f"SSM command failed: {e}")
        return f"Failed to run command. Check IAM permissions and SSM Agent status. Error: {e}"
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {e}"

def help():
    """Returns a formatted list of all available commands."""
    return (
        "**Minecraft Bot Commands**\n\n"
        "**`/start`**: Starts the Minecraft server instance in the existing fleet.\n"
        "**`/start_fleet`**: Creates a new EC2 Fleet and starts a new server.\n"
        "**`/stop_fleet`**: Stops and deletes the entire EC2 Fleet.\n"
        "**`/status`**: Shows the current status of the fleet and server.\n"
        "**`/run_command`**: Runs a Minecraft server command (e.g., `say Hello World!`).\n"
        "**`/help`**: Shows this help message."
    )


def lambda_handler(event, context):
    """Main handler for the Lambda function."""
    try:
        # Discord security handshake
        signature = event['headers']['x-signature-ed25519']
        timestamp = event['headers']['x-signature-timestamp']
        body = event['body']

        verify_key.verify(f'{timestamp}{body}'.encode(), bytes.fromhex(signature))
        print("Request verified!")
        
        body_json = json.loads(body)

        # Handle Discord's PING request
        if body_json['type'] == 1:
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'type': 1})
            }
        
        # Handle slash command
        if body_json['type'] == 2:
            command = body_json['data']['name']
            user_id = body_json['member']['user']['id'] if 'member' in body_json else None
            # The structure for a command with arguments is slightly different
            command_options = body_json['data'].get('options', [])

            message_content = "Unknown command. Use `/help` for list of available commands."

            # Commands restricted only to me
            restricted_commands = ['start_fleet', 'stop_fleet', 'command']

            
            # Parse command
            if command in restricted_commands and not is_authorized(user_id):
                message_content = "You are not authorized to run this command."
            else:
                if command == 'start':
                    message_content = start_minecraft_server()

                elif command == 'start_fleet':
                    message_content = start_fleet()

                elif command == 'stop_fleet':
                    message_content = stop_fleet()

                elif command == 'status':
                    message_content = status_fleet()

                elif command == 'command':
                    # Pass the command option value to the function
                    mc_command = command_options[0]['value'] if command_options else ""
                    if mc_command == "":
                        message_content = "Missing Minecraft command! Usage: `/command [minecraft_command]`"
                    else:    
                        message_content = run_command(mc_command)
                    
                elif command == 'help':
                    message_content = help()
            
            return {
                    'statusCode': 200,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'type': 4,
                        'data': {
                            'content': message_content,
                        }
                    })
                }

    except (BadSignatureError, KeyError) as e:
        print(f"Signature verification failed or header missing: {e}")
        return {'statusCode': 401, 
                'headers': {'Content-Type': 'application/json'},
                'body': 'invalid request signature'}
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return {'statusCode': 500, 
                'headers': {'Content-Type': 'application/json'},
                'body': 'An internal error occurred.'}

    return {'statusCode': 404, 
            'headers': {'Content-Type': 'application/json'},
            'body': 'unhandled command'}
