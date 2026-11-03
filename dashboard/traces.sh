#!/bin/bash
# The dashboard's optional per-question trace table in DynamoDB. Set TRACES_TABLE first (common.sh or the shell).
#   bash traces.sh create      on demand, pk session_id (S), sk ts (S), TTL on expires_at (items go about
#                              TRACE_TTL_DAYS days after they are written), tag project=$NAME
#   bash traces.sh describe    status, item count (DynamoDB updates it about every 6 hours), TTL state
#   bash traces.sh session ID  every item of one browser session (one Query)
#   bash traces.sh delete      deletes the table and its items (teardown.sh calls this)
# The task writes with PutItem only: the task role's permission on this one table (README, setup list).
source "$(dirname "$0")/common.sh"
: "${TRACES_TABLE:?set TRACES_TABLE to the name of the trace table, in common.sh}"
TABLE=$TRACES_TABLE
export AWS_REGION=$TRACES_REGION AWS_DEFAULT_REGION=$TRACES_REGION
guard
case "${1:-describe}" in
  create)
    if aws dynamodb describe-table --table-name "$TABLE" >/dev/null 2>&1; then
      echo "table $TABLE exists"
    else
      aws dynamodb create-table --table-name "$TABLE" --billing-mode PAY_PER_REQUEST \
        --attribute-definitions AttributeName=session_id,AttributeType=S AttributeName=ts,AttributeType=S \
        --key-schema AttributeName=session_id,KeyType=HASH AttributeName=ts,KeyType=RANGE \
        --tags Key=project,Value=$NAME --query TableDescription.TableStatus --output text
      aws dynamodb wait table-exists --table-name "$TABLE"
    fi
    aws dynamodb describe-time-to-live --table-name "$TABLE" --query TimeToLiveDescription.TimeToLiveStatus --output text | grep -q ENABLED || \
      aws dynamodb update-time-to-live --table-name "$TABLE" \
        --time-to-live-specification Enabled=true,AttributeName=expires_at --query TimeToLiveSpecification --output text
    exec bash "$0" describe ;;
  describe)
    aws dynamodb describe-table --table-name "$TABLE" \
      --query 'Table.{table:TableName,status:TableStatus,billing:BillingModeSummary.BillingMode,items:ItemCount,bytes:TableSizeBytes}' --output text
    aws dynamodb describe-time-to-live --table-name "$TABLE" --query 'TimeToLiveDescription.[TimeToLiveStatus,AttributeName]' --output text ;;
  session)
    : "${2:?usage: traces.sh session <session_id>}"
    aws dynamodb query --table-name "$TABLE" --key-condition-expression 'session_id = :s' \
      --expression-attribute-values "{\":s\":{\"S\":\"$2\"}}" --output json ;;
  delete)
    aws dynamodb delete-table --table-name "$TABLE" --query TableDescription.TableStatus --output text 2>/dev/null \
      && echo "deleting $TABLE" || echo "no table $TABLE" ;;
  *) echo "usage: traces.sh create|describe|session ID|delete" >&2; exit 2 ;;
esac
