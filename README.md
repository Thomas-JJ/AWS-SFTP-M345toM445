# AWS SFTP Scheduled Server

A Terraform-based solution that creates an AWS Transfer Family SFTP server with automated scheduling, multiple user support, and optional custom domain configuration.

## 🚀 Features

- **Scheduled Operations**: Automatically starts Monday at 3:45 AM and stops after 1 hours
- **Multiple Users**: Support for multiple SFTP users with individual home directories
- **S3 Integration**: Files stored securely in S3 with encryption and versioning
- **Custom Domain**: Optional Route 53 integration for custom SFTP hostnames
- **Automated Management**: Lambda functions handle server lifecycle and DNS updates
- **Cost Effective**: Server only runs when needed, reducing AWS Transfer Family costs

## 📋 Prerequisites

- AWS CLI configured with appropriate permissions
- Terraform >= 1.0
- Domain registered in Route 53 (optional, for custom hostnames)

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   EventBridge   │───▶│ Lambda Functions │───▶│ Transfer Family │
│   (Scheduler)   │    │  (Start/Stop)    │    │  SFTP Server    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │    Route 53     │    │   S3 Bucket     │
                       │ (Custom Domain) │    │ (File Storage)  │
                       └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/Thomas-JJ/AWS-SFTP-M345to445.git
cd AWS-SFTP-M345to445
```

### 2. Configure Variables

Create a `terraform.tfvars` file:

```hcl
aws_region     = "us-east-1"
server_name    = "weekly-sftp"
s3_bucket_name = "my-company-sftp-files-2025"

# Optional: Leave empty if you don't want a custom domain
domain_name     = "example.com"
sftp_subdomain  = "sftp"

# Configure your SFTP users
sftp_user_configs = [
  {
    username   = "alice"
    home_dir   = "/alice"
    public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAA... alice@company.com"
  },
  {
    username   = "bob"
    home_dir   = "/bob"
    public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAA... bob@company.com"
  }
]
```

### 3. Deploy Infrastructure

```bash
# Initialize Terraform
terraform init

# Review planned changes
terraform plan

# Deploy the infrastructure
terraform apply
```

### 4. Generate SSH Keys (if needed)

```bash
# Generate SSH key pair for a user
ssh-keygen -t rsa -b 4096 -C "username@company.com" -f ~/.ssh/sftp_key

# Copy the public key content for terraform.tfvars
cat ~/.ssh/sftp_key.pub
```

## 📅 Schedule Configuration

The server is configured to run:
- **Start**: Monday at 3:45 AM EST
- **Stop**: Monday at 4:45 AM EST (1 hour later)

To modify the schedule, update these cron expressions in `main.tf`:

```hcl
# Start time: Monday at 3:45 AM EST
schedule_expression = "cron(45 8 ? * MON *)"

# Stop time: Monday at 4:45 AM EST (1 hour later)
schedule_expression = "cron(45 9 ? * MON *)"
```

## 🔧 Configuration Options

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `aws_region` | AWS region for deployment | `us-east-1` |
| `server_name` | Name for the SFTP server | `weekly-sftp` |
| `s3_bucket_name` | S3 bucket name (must be globally unique) | `my-company-sftp-2025` |
| `sftp_user_configs` | List of user configurations | See example above |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `domain_name` | Custom domain for SFTP access | `""` (disabled) |
| `sftp_subdomain` | Subdomain for SFTP server | `server` |

## 👥 User Management

Each user in `sftp_user_configs` supports:

- **username**: SFTP login name
- **home_dir**: User's home directory path in S3
- **public_key**: SSH public key for authentication

Example user configuration:
```hcl
{
  username   = "john"
  home_dir   = "/john"
  public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAA..."
}
```

## 🌐 Custom Domain Setup

### With Domain (Recommended for production)

1. Register domain through Route 53 or point existing domain to Route 53
2. Set `domain_name` in `terraform.tfvars`
3. Users connect via: `sftp username@sftp.yourdomain.com`

### Without Domain (Testing/Development)

1. Leave `domain_name` empty in `terraform.tfvars`
2. Users connect via: `sftp username@s-xxxxxxxxx.server.transfer.region.amazonaws.com`

## 📁 File Structure

```
.
├── main.tf                 # Main Terraform configuration
├── lambda/
│   ├── start_sftp.py      # Lambda function to start server
│   └── stop_sftp.py       # Lambda function to stop server
├── terraform.tfvars       # Configuration variables
└── README.md              # This file
```

## 🔒 Security Features

- **S3 Encryption**: AES-256 encryption at rest
- **S3 Versioning**: File version control enabled
- **IAM Roles**: Least privilege access for users and services
- **SSH Key Authentication**: Public key authentication only
- **User Isolation**: Each user restricted to their home directory

## 💰 Cost Optimization

- **Scheduled Operation**: Server only runs 1 hour per week
- **No Data Transfer Costs**: Internal AWS data transfer
- **S3 Standard**: Cost-effective storage for regular access
- **Minimal Lambda Usage**: Functions only run during start/stop

Estimated monthly cost: ~$15-25 (depending on data transfer and storage)

## 🚀 Usage Examples

### Connect via SFTP

```bash
# With custom domain
sftp -i ~/.ssh/sftp_key username@sftp.yourdomain.com

# With AWS hostname
sftp -i ~/.ssh/sftp_key username@s-xxxxxxxxx.server.transfer.us-east-1.amazonaws.com
```

### Upload Files

```bash
# Interactive SFTP session
sftp -i ~/.ssh/sftp_key username@hostname
sftp> put localfile.txt
sftp> quit

# Command line upload
echo "put localfile.txt" | sftp -i ~/.ssh/sftp_key username@hostname
```

### Manual Server Control

```bash
# Start server manually
aws lambda invoke --function-name weekly-sftp-start response.json

# Stop server manually  
aws lambda invoke --function-name weekly-sftp-stop response.json
```

## 🔍 Monitoring and Logs

### CloudWatch Logs

- Lambda execution logs: `/aws/lambda/{function-name}`
- Transfer Family logs: CloudWatch Logs (if logging enabled)

### Check Server Status

```bash
# List Transfer Family servers
aws transfer list-servers

# Get server details
aws transfer describe-server --server-id s-xxxxxxxxx
```

## 🐛 Troubleshooting

### Common Issues

**Server hostname is None**
```bash
# Check server status
aws transfer describe-server --server-id s-xxxxxxxxx

# Look for Endpoint field in response
```

**DNS not resolving**
```bash
# Test DNS resolution
nslookup sftp.yourdomain.com

# Check Route 53 records
aws route53 list-resource-record-sets --hosted-zone-id Z1234567890
```

**Can't connect via SFTP**
```bash
# Test with verbose SSH
sftp -v -i ~/.ssh/sftp_key username@hostname

# Check security groups and NACLs
```

### Debug Lambda Functions

```bash
# View recent logs
aws logs describe-log-streams --log-group-name /aws/lambda/weekly-sftp-start

# Get specific log events
aws logs get-log-events --log-group-name /aws/lambda/weekly-sftp-start --log-stream-name STREAM_NAME
```

## 🔄 Updates and Maintenance

### Modify Schedule

1. Update cron expressions in `main.tf`
2. Run `terraform apply`

### Add/Remove Users

1. Update `sftp_user_configs` in `terraform.tfvars`
2. Run `terraform apply`

### Change S3 Bucket

⚠️ **Warning**: Changing bucket name will create a new bucket. Migrate data manually if needed.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Check the troubleshooting section above
- Review AWS Transfer Family documentation

---

**⚠️ Important Notes:**
- Server automatically stops after 1 hour to control costs
- Ensure S3 bucket names are globally unique
- Test with a small file before large transfers
- Monitor AWS costs, especially data transfer charges