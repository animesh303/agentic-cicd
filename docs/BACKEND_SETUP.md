# Terraform S3 Backend Setup

This project uses an S3 backend for storing Terraform state files remotely. This enables:
- **State sharing** across team members
- **State locking** to prevent concurrent modifications (with DynamoDB)
- **State versioning** via S3 versioning
- **Encryption** for security

## Prerequisites

1. **S3 Bucket** for storing state files
2. **DynamoDB Table** (optional but recommended) for state locking
3. **IAM Permissions** to access S3 and DynamoDB

## Setup Steps

### 1. Create S3 Bucket for State

```bash
aws s3 mb s3://your-terraform-state-bucket --region us-east-1

# Enable versioning (recommended)
aws s3api put-bucket-versioning \
  --bucket your-terraform-state-bucket \
  --versioning-configuration Status=Enabled

# Enable encryption (recommended)
aws s3api put-bucket-encryption \
  --bucket your-terraform-state-bucket \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### 2. Create DynamoDB Table for State Locking (Optional but Recommended)

```bash
aws dynamodb create-table \
  --table-name terraform-state-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### 3. Configure Backend

**Option A: Using backend.tfvars (Recommended)**

1. Copy the example file:
   ```bash
   cp backend.tfvars.example backend.tfvars
   ```

2. Edit `backend.tfvars` with your values:
   ```hcl
   bucket         = "your-terraform-state-bucket"
   key            = "agentic-cicd/terraform.tfstate"
   region         = "us-east-1"
   encrypt        = true
   dynamodb_table = "terraform-state-lock"
   ```

3. Initialize Terraform with backend config:
   ```bash
   terraform init -backend-config=backend.tfvars
   ```

**Option B: Using Command-Line Flags**

```bash
terraform init \
  -backend-config="bucket=your-terraform-state-bucket" \
  -backend-config="key=agentic-cicd/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="encrypt=true" \
  -backend-config="dynamodb_table=terraform-state-lock"
```

**Option C: Direct Configuration in backend.tf**

Edit `backend.tf` and uncomment the backend block, then fill in your values:

```hcl
terraform {
  backend "s3" {
    bucket         = "your-terraform-state-bucket"
    key            = "agentic-cicd/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
```

Then run:
```bash
terraform init
```

## Backend Configuration Options

| Option | Required | Description |
|--------|----------|-------------|
| `bucket` | Yes | S3 bucket name for state storage |
| `key` | Yes | Path to state file in bucket |
| `region` | Yes | AWS region of the S3 bucket |
| `encrypt` | No | Enable server-side encryption (default: true) |
| `dynamodb_table` | No | DynamoDB table for state locking |
| `kms_key_id` | No | KMS key ID for encryption (if using KMS) |
| `profile` | No | AWS profile to use |
| `role_arn` | No | IAM role ARN for backend access |

## IAM Permissions Required

The user/role running Terraform needs:

**S3 Permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-terraform-state-bucket",
        "arn:aws:s3:::your-terraform-state-bucket/*"
      ]
    }
  ]
}
```

**DynamoDB Permissions (if using locking):**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/terraform-state-lock"
    }
  ]
}
```

## Migrating Existing State

If you already have a local state file and want to migrate to S3:

1. Initialize with backend:
   ```bash
   terraform init -backend-config=backend.tfvars
   ```

2. Terraform will prompt to migrate state:
   ```
   Do you want to copy existing state to the new backend?
   ```
   Answer: `yes`

## Troubleshooting

### Error: "Backend configuration changed"
If you see this error, you may need to migrate state:
```bash
terraform init -migrate-state
```

### Error: "Access Denied"
- Check IAM permissions
- Verify bucket exists and is accessible
- Check bucket policy if using bucket policies

### Error: "State locking failed"
- Verify DynamoDB table exists
- Check DynamoDB permissions
- Ensure table has `LockID` as primary key

## Best Practices

1. **Use separate state buckets** for different environments (dev, staging, prod)
2. **Enable versioning** on state bucket for recovery
3. **Use DynamoDB locking** to prevent concurrent modifications
4. **Use encryption** for sensitive state data
5. **Never commit** `backend.tfvars` to version control (already in .gitignore)
6. **Use different state keys** for different projects/environments

## Example: Multi-Environment Setup

For multiple environments, use different state keys:

**Development:**
```hcl
key = "agentic-cicd/dev/terraform.tfstate"
```

**Production:**
```hcl
key = "agentic-cicd/prod/terraform.tfstate"
```

This allows you to use the same bucket but keep states separate.

