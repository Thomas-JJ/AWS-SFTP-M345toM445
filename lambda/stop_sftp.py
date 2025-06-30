# lambda/stop_sftp.py
import boto3
import os
import json
import time
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """
    Lambda function to stop and delete SFTP server
    """
    transfer = boto3.client('transfer')
    server_name = os.environ['SERVER_NAME']
    
    try:
        print(f"Starting SFTP server deletion process for: {server_name}")
        
        # Find server by name tag
        server_id = find_server_by_name(transfer, server_name)
        
        if not server_id:
            print(f"No server found with name: {server_name}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'No server found with name {server_name}',
                    'action': 'none_required'
                })
            }
        
        # Get server details
        server_info = transfer.describe_server(ServerId=server_id)
        current_state = server_info['Server']['State']
        
        print(f"Found server {server_id} in state: {current_state}")
        
        # Delete all users first
        try:
            users_response = transfer.list_users(ServerId=server_id)
            for user in users_response.get('Users', []):
                username = user['UserName']
                print(f"Deleting user: {username}")
                transfer.delete_user(ServerId=server_id, UserName=username)
                print(f"Deleted user: {username}")
        except ClientError as e:
            print(f"Error deleting users: {e}")
            # Continue with server deletion even if user deletion fails
        
        # Stop server if it's running
        if current_state == 'ONLINE':
            print(f"Stopping server {server_id}")
            transfer.stop_server(ServerId=server_id)
            
            # Wait for server to stop
            wait_for_server_stopped(transfer, server_id)
        elif current_state in ['STOPPING', 'OFFLINE']:
            print(f"Server {server_id} is already stopping or offline")
            if current_state == 'STOPPING':
                wait_for_server_stopped(transfer, server_id)
        else:
            print(f"Server {server_id} is in state {current_state}")
        
        # Delete the server
        print(f"Deleting server {server_id}")
        transfer.delete_server(ServerId=server_id)
        
        # Verify deletion
        try:
            # Wait a moment for deletion to process
            time.sleep(5)
            transfer.describe_server(ServerId=server_id)
            # If we get here, server still exists
            print(f"Server {server_id} deletion initiated but may still be processing")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Server {server_id} successfully deleted")
            else:
                print(f"Unexpected error checking server deletion: {e}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Successfully deleted SFTP server {server_id}',
                'server_id': server_id,
                'previous_state': current_state,
                'action': 'deleted'
            })
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

def find_server_by_name(transfer, server_name):
    """Find server by name tag"""
    try:
        servers = transfer.list_servers()
        
        for server in servers['Servers']:
            try:
                tags_response = transfer.list_tags_for_resource(Arn=server['Arn'])
                for tag in tags_response.get('Tags', []):
                    if tag['Key'] == 'Name' and tag['Value'] == server_name:
                        return server['ServerId']
            except ClientError:
                # Skip servers we can't get tags for
                continue
                
        return None
        
    except Exception as e:
        print(f"Error finding server: {str(e)}")
        return None

def wait_for_server_stopped(transfer, server_id, max_wait_time=300):
    """Wait for server to stop"""
    print(f"Waiting for server {server_id} to stop...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            server_info = transfer.describe_server(ServerId=server_id)
            state = server_info['Server']['State']
            
            if state == 'OFFLINE':
                print(f"Server {server_id} is now offline")
                return True
            elif state == 'STOP_FAILED':
                print(f"Server {server_id} failed to stop. Proceeding with deletion anyway.")
                return True
            
            print(f"Server {server_id} state: {state}. Waiting...")
            time.sleep(10)
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Server {server_id} no longer exists")
                return True
            raise
    
    print(f"Server {server_id} did not stop within {max_wait_time} seconds. Proceeding with deletion anyway.")
    return False