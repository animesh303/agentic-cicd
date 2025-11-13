aws_region = "us-east-1"
project_prefix = "bedrock-ci-agent"
bucket_name = "bedrock-ci-agent-templates-12345" # change to globally unique
github_pat_secret_name = "bedrock/github/pat"
lambda_s3_key = "lambda/repo_scanner.zip"
lambda_handler = "repo_scanner.lambda_handler"
lambda_runtime = "python3.11"