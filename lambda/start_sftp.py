# lambda/start_sftp.py
import boto3
import os
import json
import time
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """
    Lambda function to create new SFTP server and update DNS alias
    """
    transfer = boto3.client('transfer')
    route53 = boto3.client('route53')
    
    server_name = os.environ['SERVER_NAME']
    sftp_role_arn = os.environ['SFTP_ROLE_ARN']
    user_role_arn = os.environ['USER_ROLE_ARN']
    s3_bucket = os.environ['S3_BUCKET']
    
    # Parse the user configs from JSON string
    try:
        sftp_user_configs = json.loads(os.environ['SFTP_USER_CONFIGS'])
    except json.JSONDecodeError as e:
        print(f"Error parsing SFTP_USER_CONFIGS: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid SFTP_USER_CONFIGS format. Must be valid JSON.'})
        }
    
    # DNS configuration
    domain_name = os.environ.get('DOMAIN_NAME', '')
    sftp_subdomain = os.environ.get('SFTP_SUBDOMAIN', 'server')
    hosted_zone_id = os.environ.get('HOSTED_ZONE_ID', '')
    
    try:
        print(f"Starting SFTP server creation process for: {server_name}")
        print(f"DNS Config - Domain: {domain_name}, Subdomain: {sftp_subdomain}, Zone ID: {hosted_zone_id}")
        print(f"Creating {len(sftp_user_configs)} users")
        
        # Always create a new server (as requested)
        print("Creating new SFTP server...")
        create_response = transfer.create_server(
            IdentityProviderType='SERVICE_MANAGED',
            Protocols=['SFTP'],
            EndpointType='PUBLIC',
            LoggingRole=sftp_role_arn,
            Tags=[
                {'Key': 'Name', 'Value': server_name},
                {'Key': 'Schedule', 'Value': 'Monday-345am-EST'},
                {'Key': 'AutoManaged', 'Value': 'true'},
                {'Key': 'CreatedAt', 'Value': str(int(time.time()))}
            ]
        )
        
        server_id = create_response['ServerId']
        print(f"✓ Created SFTP server: {server_id}")
        
        # Wait for server to be online
        print("Waiting for server to come online...")
        wait_for_server_online(transfer, server_id)
        
        # Get server details with retry for endpoint
        print("Getting server hostname...")
        server_hostname = None
        max_hostname_attempts = 5
        
        for attempt in range(max_hostname_attempts):
            server_info = transfer.describe_server(ServerId=server_id)
            server_hostname = get_server_hostname(server_info)
            
            if server_hostname and server_hostname != "None":
                print(f"✓ Server hostname obtained: {server_hostname}")
                break
            else:
                print(f"Attempt {attempt + 1}: Hostname not yet available, waiting 30 seconds...")
                if attempt < max_hostname_attempts - 1:
                    time.sleep(30)
        
        if server_hostname == "None":
            print("❌ Failed to get server hostname after multiple attempts")
            # Fallback: construct hostname manually
            region = boto3.Session().region_name
            server_hostname = f"{server_id}.server.transfer.{region}.amazonaws.com"
            print(f"Using constructed hostname: {server_hostname}")
        
        print(f"✓ Server is online with hostname: {server_hostname}")
        
        # Update Route 53 CNAME if configured
        alias_hostname = None
        if domain_name and hosted_zone_id and server_hostname:
            alias_hostname = f"{sftp_subdomain}.{domain_name}"
            print(f"Updating DNS record: {alias_hostname} -> {server_hostname}")
            
            try:
                update_dns_record(route53, hosted_zone_id, alias_hostname, server_hostname)
                print(f"✓ Successfully updated DNS: {alias_hostname} -> {server_hostname}")
                
                # Verify DNS update
                verify_dns_update(route53, hosted_zone_id, alias_hostname, server_hostname)
                
            except Exception as dns_error:
                print(f"❌ Failed to update DNS: {str(dns_error)}")
                # Continue with user creation even if DNS fails
        else:
            print("⚠️ DNS update skipped - missing domain configuration")
            if not domain_name:
                print("  - DOMAIN_NAME not set")
            if not hosted_zone_id:
                print("  - HOSTED_ZONE_ID not set")
            if not server_hostname:
                print("  - server_hostname not available")
        
        # Create SFTP users
        print(f"Creating users on server {server_id}")
        created_users = []
        
        for sftp_user_config in sftp_user_configs:
            try:
                username = sftp_user_config['username']
                home_dir = sftp_user_config['home_dir']
                public_key = sftp_user_config.get('public_key', '')
                
                print(f"Creating user: {username}")
                
                create_user_response = transfer.create_user(
                    ServerId=server_id,
                    UserName=username,
                    Role=user_role_arn,
                    HomeDirectory=f'/{s3_bucket}{home_dir}',
                    HomeDirectoryType='PATH',
                    SshPublicKeyBody=public_key,
                    Tags=[
                        {'Key': 'Name', 'Value': username},
                        {'Key': 'ServerName', 'Value': server_name}
                    ]
                )
                
                user_info = {
                    'username': username,
                    'home_directory': f'/{s3_bucket}{home_dir}',
                    'user_arn': create_user_response.get('UserName', username)
                }
                created_users.append(user_info)
                
                print(f"✓ Created user {username}")
                
            except KeyError as e:
                print(f"❌ Missing required field for user: {e}")
                continue
            except Exception as e:
                print(f"❌ Failed to create user {sftp_user_config.get('username', 'unknown')}: {e}")
                continue
        
        # Prepare response
        connection_hostname = alias_hostname if alias_hostname else server_hostname
        
        response_body = {
            'message': f'Successfully created SFTP server with {len(created_users)} users',
            'server_id': server_id,
            'aws_hostname': server_hostname,
            'connection_hostname': connection_hostname,
            'users': created_users,
            's3_bucket': s3_bucket,
            'created_at': str(int(time.time())),
            'dns_updated': bool(alias_hostname)
        }
        
        if alias_hostname:
            response_body['alias_hostname'] = alias_hostname
        
        # Add connection examples for each user
        response_body['connection_examples'] = [
            f"sftp {user['username']}@{connection_hostname}" 
            for user in created_users
        ]
        
        print(f"✓ SFTP server setup complete!")
        print(f"✓ Created {len(created_users)} users")
        if alias_hostname:
            print(f"Connect using: sftp <username>@{alias_hostname}")
        else:
            print(f"Connect using: sftp <username>@{server_hostname}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body, indent=2)
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"AWS Error [{error_code}]: {error_message}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'AWS Error: {error_message}',
                'error_code': error_code
            })
        }
        
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Unexpected error: {str(e)}'
            })
        }

def get_server_hostname(server_info):
    """Extract the actual hostname from server info"""
    server = server_info['Server']
    
    # Debug: Print server info to understand the structure
    print(f"Server endpoint type: {server.get('EndpointType')}")
    print(f"Server endpoint: {server.get('Endpoint')}")
    print(f"Server ID: {server.get('ServerId')}")
    
    # For PUBLIC endpoint type (most common)
    endpoint = server.get('Endpoint')
    if endpoint:
        print(f"Found endpoint: {endpoint}")
        return endpoint
    
    # If no endpoint yet, construct hostname from server ID and region
    server_id = server.get('ServerId')
    if server_id:
        # Get region from the server ARN or use current session region
        region = None
        if 'Arn' in server:
            # ARN format: arn:aws:transfer:region:account:server/server-id
            arn_parts = server['Arn'].split(':')
            if len(arn_parts) >= 4:
                region = arn_parts[3]
        
        if not region:
            region = boto3.Session().region_name or 'us-east-1'
        
        constructed_hostname = f"{server_id}.server.transfer.{region}.amazonaws.com"
        print(f"Constructed hostname: {constructed_hostname}")
        return constructed_hostname
    
    print("ERROR: Could not determine server hostname")
    return None

def update_dns_record(route53, hosted_zone_id, record_name, target_hostname):
    """Update Route 53 CNAME record to point to new server"""
    try:
        print(f"Updating DNS record in zone {hosted_zone_id}")
        print(f"Record: {record_name} -> {target_hostname}")
        
        response = route53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Comment': f'Updated by Lambda for SFTP server - {int(time.time())}',
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': record_name,
                        'Type': 'CNAME',
                        'TTL': 60,
                        'ResourceRecords': [{'Value': target_hostname}]
                    }
                }]
            }
        )
        
        change_id = response['ChangeInfo']['Id']
        print(f"DNS change submitted with ID: {change_id}")
        
        # Wait for change to propagate (optional, but good for verification)
        waiter = route53.get_waiter('resource_record_sets_changed')
        print("Waiting for DNS change to propagate...")
        waiter.wait(Id=change_id, WaiterConfig={'Delay': 5, 'MaxAttempts': 12})
        
        print(f"✓ DNS change completed successfully")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"❌ Route53 ClientError [{error_code}]: {error_message}")
        raise Exception(f"Route53 Error: {error_message}")
    except Exception as e:
        print(f"❌ Unexpected DNS error: {str(e)}")
        raise

def verify_dns_update(route53, hosted_zone_id, record_name, expected_value):
    """Verify that the DNS record was updated correctly"""
    try:
        print(f"Verifying DNS record: {record_name}")
        
        response = route53.list_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            StartRecordName=record_name,
            StartRecordType='CNAME',
            MaxItems='1'
        )
        
        for record_set in response.get('ResourceRecordSets', []):
            if record_set['Name'].rstrip('.') == record_name and record_set['Type'] == 'CNAME':
                current_value = record_set['ResourceRecords'][0]['Value']
                if current_value == expected_value:
                    print(f"✓ DNS verification successful: {record_name} = {current_value}")
                    return True
                else:
                    print(f"⚠️ DNS value mismatch: expected {expected_value}, got {current_value}")
                    return False
        
        print(f"⚠️ CNAME record not found: {record_name}")
        return False
        
    except Exception as e:
        print(f"⚠️ DNS verification failed: {str(e)}")
        return False

def wait_for_server_online(transfer, server_id, max_wait_time=300):
    """Wait for server to come online"""
    print(f"Waiting for server {server_id} to come online...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            server_info = transfer.describe_server(ServerId=server_id)
            state = server_info['Server']['State']
            
            if state == 'ONLINE':
                print(f"Server {server_id} is now online")
                return True
            elif state in ['STOP_FAILED', 'START_FAILED']:
                raise Exception(f"Server {server_id} failed to start. State: {state}")
            
            print(f"Server {server_id} state: {state}. Waiting...")
            time.sleep(10)
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Server {server_id} not found")
                return False
            raise
    
    raise Exception(f"Server {server_id} did not come online within {max_wait_time} seconds")