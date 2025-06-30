# main.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "server_name" {
  description = "Name for the SFTP server"
  type        = string
}

variable "sftp_user_configs" {
  description = "List of SFTP user configurations"
  type = list(object({
    username   = string
    home_dir   = string
    public_key = string
  }))
  
  validation {
    condition = alltrue([
      for user in var.sftp_user_configs : 
      length(user.username) > 0 && length(user.home_dir) > 0
    ])
    error_message = "Username and home_dir cannot be empty for any user."
  }
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for SFTP storage (must be globally unique)"
  type        = string
  
  validation {
    condition = can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.s3_bucket_name)) && length(var.s3_bucket_name) >= 3 && length(var.s3_bucket_name) <= 63
    error_message = "S3 bucket name must be 3-63 characters, start/end with alphanumeric, and contain only lowercase letters, numbers, dots, and hyphens."
  }
}

# Route 53 hosted zone creation
variable "domain_name" {
  description = "Domain name for SFTP alias (e.g., company.com)"
  type        = string
  default     = ""
}

variable "sftp_subdomain" {
  description = "Subdomain for SFTP server (e.g., server)"
  type        = string
  default     = "server"
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Try to get existing hosted zone, ignore errors if not found
data "aws_route53_zone" "existing" {
  count = var.domain_name != "" ? 1 : 0
  name  = var.domain_name
}

locals {
  zone_exists = var.domain_name != "" ? length(data.aws_route53_zone.existing) > 0 : false
}

# Create hosted zone only if domain is specified AND zone doesn't exist
resource "aws_route53_zone" "sftp_domain" {
  count = var.domain_name != "" && !local.zone_exists ? 1 : 0
  name  = var.domain_name

  tags = {
    Name    = var.domain_name
    Purpose = "SFTP Server DNS"
  }
}

# Reference the hosted zone (existing or new)
locals {
  hosted_zone_id = var.domain_name != "" ? (
    local.zone_exists ? 
    data.aws_route53_zone.existing[0].zone_id : 
    aws_route53_zone.sftp_domain[0].zone_id
  ) : ""
}

# S3 Bucket for SFTP files
resource "aws_s3_bucket" "sftp_bucket" {
  bucket = var.s3_bucket_name
  
  tags = {
    Name    = var.s3_bucket_name
    Purpose = "SFTP Server Storage"
  }
}

resource "aws_s3_bucket_versioning" "sftp_bucket_versioning" {
  bucket = aws_s3_bucket.sftp_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sftp_bucket_encryption" {
  bucket = aws_s3_bucket.sftp_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Route 53 CNAME record for consistent hostname
resource "aws_route53_record" "sftp_cname" {
  count   = var.domain_name != "" ? 1 : 0
  zone_id = local.hosted_zone_id
  name    = var.sftp_subdomain
  type    = "CNAME"
  ttl     = 60

  # Placeholder that will be updated by Lambda
  records = ["placeholder.example.com"]

  lifecycle {
    ignore_changes = [records]
  }
}

# IAM Role for SFTP Server
resource "aws_iam_role" "sftp_server_role" {
  name = "${var.server_name}-server-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "transfer.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.server_name}-server-role"
  }
}

resource "aws_iam_role_policy_attachment" "sftp_logging" {
  role       = aws_iam_role.sftp_server_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSTransferLoggingAccess"
}

# IAM Role for SFTP Users
resource "aws_iam_role" "sftp_user_role" {
  name = "${var.server_name}-user-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "transfer.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.server_name}-user-role"
  }
}

# IAM Policy for SFTP Users S3 Access - allows access to all user directories
resource "aws_iam_role_policy" "sftp_user_policy" {
  name = "${var.server_name}-user-s3-policy"
  role = aws_iam_role.sftp_user_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = aws_s3_bucket.sftp_bucket.arn
        Condition = {
          StringLike = {
            "s3:prefix" = [
              for user in var.sftp_user_configs : 
              "${trimprefix(user.home_dir, "/")}/*"
            ]
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion"
        ]
        Resource = [
          for user in var.sftp_user_configs : 
          "${aws_s3_bucket.sftp_bucket.arn}${user.home_dir}/*"
        ]
      }
    ]
  })
}

# IAM Role for Lambda Functions
resource "aws_iam_role" "lambda_execution_role" {
  name = "${var.server_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.server_name}-lambda-role"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# IAM Policy for Lambda to manage Transfer Family and Route 53
resource "aws_iam_role_policy" "lambda_transfer_policy" {
  name = "${var.server_name}-lambda-transfer-policy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "transfer:CreateServer",
          "transfer:DeleteServer",
          "transfer:DescribeServer",
          "transfer:StartServer",
          "transfer:StopServer",
          "transfer:ListServers",
          "transfer:CreateUser",
          "transfer:DeleteUser",
          "transfer:DescribeUser",
          "transfer:ListUsers",
          "transfer:ListTagsForResource",
          "transfer:TagResource"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.sftp_server_role.arn,
          aws_iam_role.sftp_user_role.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "route53:ChangeResourceRecordSets",
          "route53:GetChange",
          "route53:ListResourceRecordSets"
        ]
        Resource = local.hosted_zone_id != "" ? [
          "arn:aws:route53:::hostedzone/${local.hosted_zone_id}",
          "arn:aws:route53:::change/*"
        ] : ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# Lambda function to start SFTP server and create users
resource "aws_lambda_function" "start_sftp" {
  filename         = "start_sftp.zip"
  function_name    = "${var.server_name}-start"
  role            = aws_iam_role.lambda_execution_role.arn
  handler         = "index.lambda_handler"
  runtime         = "python3.9"
  timeout         = 300

  environment {
    variables = {
      SERVER_NAME       = var.server_name
      SFTP_ROLE_ARN    = aws_iam_role.sftp_server_role.arn
      USER_ROLE_ARN    = aws_iam_role.sftp_user_role.arn
      S3_BUCKET        = aws_s3_bucket.sftp_bucket.bucket
      SFTP_USER_CONFIGS = jsonencode(var.sftp_user_configs)  # Fixed: Convert to JSON string
      DOMAIN_NAME      = var.domain_name
      SFTP_SUBDOMAIN   = var.sftp_subdomain
      HOSTED_ZONE_ID   = local.hosted_zone_id  # Fixed: Use local instead of direct reference
    } 
  }

  depends_on = [data.archive_file.start_sftp_zip]

  tags = {
    Name = "${var.server_name}-start-function"
  }
}

# Lambda function to stop and destroy SFTP server
resource "aws_lambda_function" "stop_sftp" {
  filename         = "stop_sftp.zip"
  function_name    = "${var.server_name}-stop"
  role            = aws_iam_role.lambda_execution_role.arn
  handler         = "index.lambda_handler"
  runtime         = "python3.9"
  timeout         = 300

  environment {
    variables = {
      SERVER_NAME = var.server_name
    }
  }

  depends_on = [data.archive_file.stop_sftp_zip]

  tags = {
    Name = "${var.server_name}-stop-function"
  }
}

# Create Lambda deployment packages
data "archive_file" "start_sftp_zip" {
  type        = "zip"
  output_path = "start_sftp.zip"
  
  source {
    content = templatefile("${path.module}/lambda/start_sftp.py", {
      server_name = var.server_name
    })
    filename = "index.py"
  }
}

data "archive_file" "stop_sftp_zip" {
  type        = "zip"
  output_path = "stop_sftp.zip"
  
  source {
    content = templatefile("${path.module}/lambda/stop_sftp.py", {
      server_name = var.server_name
    })
    filename = "index.py"
  }
}

# EventBridge rules for scheduling - Monday at 3:45am EST
resource "aws_cloudwatch_event_rule" "start_server_rule" {
  name                = "${var.server_name}-start-rule"
  description         = "Start SFTP server on Mondays at 3:45am EST"
  schedule_expression = "cron(45 8 ? * MON *)"  # 8:45 AM UTC = 3:45 AM EST
  
  tags = {
    Name = "${var.server_name}-start-rule"
  }
}

resource "aws_cloudwatch_event_rule" "stop_server_rule" {
  name                = "${var.server_name}-stop-rule"
  description         = "Start SFTP server on Mondays at 4:45am EST (1 hour later)"
  schedule_expression = "cron(45 9 ? * MON *)"  # 9:45 AM UTC = 4:45 AM EST
  
  tags = {
    Name = "${var.server_name}-stop-rule"
  }
}

# EventBridge targets
resource "aws_cloudwatch_event_target" "start_server_target" {
  rule      = aws_cloudwatch_event_rule.start_server_rule.name
  target_id = "StartSFTPTarget"
  arn       = aws_lambda_function.start_sftp.arn
}

resource "aws_cloudwatch_event_target" "stop_server_target" {
  rule      = aws_cloudwatch_event_rule.stop_server_rule.name
  target_id = "StopSFTPTarget"
  arn       = aws_lambda_function.stop_sftp.arn
}

# Lambda permissions for EventBridge
resource "aws_lambda_permission" "allow_eventbridge_start" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start_sftp.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.start_server_rule.arn
}

resource "aws_lambda_permission" "allow_eventbridge_stop" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.stop_sftp.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.stop_server_rule.arn
}

# CloudWatch Log Groups for Lambda functions
resource "aws_cloudwatch_log_group" "start_sftp_logs" {
  name              = "/aws/lambda/${aws_lambda_function.start_sftp.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "stop_sftp_logs" {
  name              = "/aws/lambda/${aws_lambda_function.stop_sftp.function_name}"
  retention_in_days = 14
}

# Outputs
output "s3_bucket_name" {
  description = "Name of the S3 bucket for SFTP files"
  value       = aws_s3_bucket.sftp_bucket.bucket
}

output "sftp_alias_hostname" {
  description = "Consistent SFTP hostname alias"
  value       = var.domain_name != "" ? "${var.sftp_subdomain}.${var.domain_name}" : "No domain configured"
}

output "start_lambda_function_name" {
  description = "Name of the Lambda function that starts the SFTP server"
  value       = aws_lambda_function.start_sftp.function_name
}

output "stop_lambda_function_name" {
  description = "Name of the Lambda function that stops the SFTP server"
  value       = aws_lambda_function.stop_sftp.function_name
}

output "sftp_server_role_arn" {
  description = "ARN of the SFTP server IAM role"
  value       = aws_iam_role.sftp_server_role.arn
}

output "sftp_user_role_arn" {
  description = "ARN of the SFTP user IAM role"
  value       = aws_iam_role.sftp_user_role.arn
}

output "user_configs" {
  description = "User configurations for reference"
  value = {
    for user in var.sftp_user_configs : user.username => {
      home_directory = user.home_dir
      s3_path       = "${aws_s3_bucket.sftp_bucket.bucket}${user.home_dir}"
    }
  }
  sensitive = true  # Hide public keys from output
}