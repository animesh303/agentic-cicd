output "s3_bucket" {
  value = aws_s3_bucket.templates.bucket
}

output "dynamodb_table" {
  value = aws_dynamodb_table.task_tracking.name
}

# Lambda Functions
output "lambda_repo_scanner" {
  value = aws_lambda_function.repo_scanner.function_name
}

output "lambda_repo_ingestor" {
  value = aws_lambda_function.repo_ingestor.function_name
}

output "lambda_static_analyzer" {
  value = aws_lambda_function.static_analyzer.function_name
}

output "lambda_template_validator" {
  value = aws_lambda_function.template_validator.function_name
}

output "lambda_orchestrator" {
  value = aws_lambda_function.orchestrator.function_name
}

output "lambda_github_api" {
  value = aws_lambda_function.github_api.function_name
}

output "cloudwatch_dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

# Bedrock Agents
output "bedrock_agent_repo_scanner_id" {
  value = aws_bedrockagent_agent.repo_scanner_agent.id
}

output "bedrock_agent_pipeline_designer_id" {
  value = aws_bedrockagent_agent.pipeline_designer_agent.id
}

output "bedrock_agent_security_compliance_id" {
  value = aws_bedrockagent_agent.security_compliance_agent.id
}

output "bedrock_agent_yaml_generator_id" {
  value = aws_bedrockagent_agent.yaml_generator_agent.id
}

output "bedrock_agent_pr_manager_id" {
  value = aws_bedrockagent_agent.pr_manager_agent.id
}

output "bedrock_agent_feedback_id" {
  value = aws_bedrockagent_agent.feedback_agent.id
}

# Agent IDs map for orchestrator
output "agent_ids_map" {
  value = {
    repo_scanner        = aws_bedrockagent_agent.repo_scanner_agent.id
    pipeline_designer   = aws_bedrockagent_agent.pipeline_designer_agent.id
    security_compliance = aws_bedrockagent_agent.security_compliance_agent.id
    yaml_generator      = aws_bedrockagent_agent.yaml_generator_agent.id
    pr_manager          = aws_bedrockagent_agent.pr_manager_agent.id
    feedback            = aws_bedrockagent_agent.feedback_agent.id
  }
}
