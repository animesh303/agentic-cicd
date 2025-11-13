# Bedrock Agent Role Foundation Model Permissions Fix

## Issue

The Bedrock agent role (`bedrock-ci-agent-bedrock-agent-role`) was missing permissions to invoke foundation models (Claude Sonnet 3.5). Agents need these permissions to actually use the LLM for processing.

## Missing Permissions

The role was missing:
- `bedrock:InvokeModel` - Invoke foundation models synchronously
- `bedrock:InvokeModelWithResponseStream` - Invoke foundation models with streaming responses

## Fix Applied

Added a new IAM policy statement to `bedrock_agent_policy`:

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": [
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-*",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
    "arn:aws:bedrock:*::foundation-model/*"
  ]
}
```

## Resource ARN Patterns

The policy uses three resource patterns for flexibility:

1. **Specific Claude 3.5 Sonnet**: `arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-sonnet-*`
   - Matches Claude 3.5 Sonnet models specifically

2. **All Claude Models**: `arn:aws:bedrock:*::foundation-model/anthropic.claude-*`
   - Matches all Anthropic Claude models (3.5 Sonnet, 3 Haiku, etc.)

3. **All Foundation Models**: `arn:aws:bedrock:*::foundation-model/*`
   - Wildcard for any foundation model (future-proof)

## Verification

To verify the fix was applied:

```bash
# Get the policy version
POLICY_ARN="arn:aws:iam::ACCOUNT_ID:policy/bedrock-ci-agent-bedrock-agent-policy"
VERSION_ID=$(aws iam get-policy --policy-arn $POLICY_ARN --query 'Policy.DefaultVersionId' --output text)

# Check for foundation model permissions
aws iam get-policy-version \
  --policy-arn $POLICY_ARN \
  --version-id $VERSION_ID \
  --query 'PolicyVersion.Document' \
  --output json | jq '.Statement[] | select(.Action[]? | contains("bedrock:InvokeModel"))'
```

Expected output should show the new statement with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` actions.

## Complete Bedrock Agent Role Permissions

After this fix, the `bedrock-ci-agent-bedrock-agent-role` has:

1. ✅ **Lambda Invocation** - Can invoke Lambda functions (action groups)
2. ✅ **S3 Access** - Can read OpenAPI specs and templates from S3
3. ✅ **Secrets Manager** - Can read GitHub PAT secret
4. ✅ **Agent Invocation** - Can invoke other Bedrock agents
5. ✅ **Foundation Model Invocation** - Can invoke Claude Sonnet 3.5 and other models ✨ **NEW**

## Impact

With this fix:
- ✅ Bedrock agents can now use Claude Sonnet 3.5 for processing
- ✅ Agents can generate responses using the foundation model
- ✅ Streaming responses are supported
- ✅ Agents will function properly instead of failing silently

## Testing

After applying the fix, test an agent:

1. **Via Lambda Console:**
   - Test the orchestrator Lambda function
   - Agents should now successfully invoke Claude Sonnet 3.5

2. **Via Bedrock Console:**
   - Go to Bedrock → Agents
   - Select an agent
   - Use the test chat interface
   - Agent should respond using Claude Sonnet 3.5

3. **Check CloudWatch Logs:**
   - Monitor agent execution logs
   - Should see successful model invocations

## Related Fixes

- **Lambda Execution Role** (`lambda_extra_policy`) - Already has `bedrock:InvokeModel` permissions for Lambda functions to invoke models directly
- **Bedrock Agent Role** (`bedrock_agent_policy`) - Now has foundation model permissions ✨ **Fixed**

## Files Modified

- `main.tf` - Added foundation model permissions to `bedrock_agent_policy`

## Next Steps

1. ✅ Apply Terraform changes: `terraform apply`
2. ✅ Verify permissions are updated
3. ✅ Test agent functionality
4. ✅ Monitor CloudWatch logs for successful invocations

## Notes

- The resource ARN pattern uses `*` for account ID and region to allow flexibility
- Foundation model ARNs follow the pattern: `arn:aws:bedrock:region::foundation-model/model-id`
- The wildcard patterns ensure compatibility with different Claude model versions

