#!/bin/bash
# Prepare the dashboard on Fargate in your account. Starts NOTHING (no RunTask): start.sh does that.
# Safe to rerun; each step skips what exists.
#   ECR repo $NAME (keeps the last 3 images), image build (arm64) and push, log group /ecs/$NAME (7 days),
#   cluster $NAME, security group $NAME (tag project=$NAME, port 8000 open), task definition $NAME
#   (0.5 vCPU, 1 GB, ARM64).
# Needs BUCKET (common.sh) and DASH_PASSWORD in the shell. With TRACES_TABLE set (common.sh), the task writes one
# trace per question to that table: create it first with traces.sh create. The password goes into the task definition as a plain
# environment variable, so anyone who can describe task definitions in the account can read it.
# The two roles and the secret are made by the account owner (README); this script only checks they exist.
source "$(dirname "$0")/common.sh"
: "${DASH_PASSWORD:?set DASH_PASSWORD in your shell first (read -rs DASH_PASSWORD; export DASH_PASSWORD)}"
: "${BUCKET:?set BUCKET to the S3 bucket that holds $KEY (see README)}"
QUESTION_CAP=${QUESTION_CAP:-15}
TOTAL_CALLS=${TOTAL_CALLS:-2000}
guard

for r in "$EXEC_ROLE" "$TASK_ROLE"; do
  aws iam get-role --role-name "${r##*/}" --query Role.Arn --output text >/dev/null || { echo "missing role $r (the account owner makes it, see README)"; exit 1; }
done
SECRET_ARN=$(aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --query ARN --output text)
echo "roles present; secret $SECRET_ARN"

# 1. ECR repository and image
aws ecr describe-repositories --repository-names $REPO >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name $REPO --image-scanning-configuration scanOnPush=false >/dev/null
aws ecr put-lifecycle-policy --repository-name $REPO --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"description":"keep last 3","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":3},"action":{"type":"expire"}}]}' >/dev/null
# the taxi table is not in the image: the app reads s3://$BUCKET/$KEY at start with the task role
$DOCKER build --platform linux/arm64 -t $REPO:local "$HERE"
aws ecr get-login-password | $DOCKER login --username AWS --password-stdin $REGISTRY >/dev/null
$DOCKER tag $REPO:local $IMAGE
$DOCKER push $IMAGE | tail -1

# 2. logs, cluster, network
aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP --query 'logGroups[].logGroupName' --output text | grep -qx "$LOG_GROUP" || \
  aws logs create-log-group --log-group-name $LOG_GROUP
aws logs put-retention-policy --log-group-name $LOG_GROUP --retention-in-days 7
aws ecs describe-clusters --clusters $CLUSTER --query 'clusters[?status==`ACTIVE`].clusterName' --output text | grep -qx $CLUSTER || \
  aws ecs create-cluster --cluster-name $CLUSTER >/dev/null
VPC=$(default_vpc)
SG=$(sg_id)
if [ "$SG" = "None" ] || [ -z "$SG" ]; then
  SG=$(aws ec2 create-security-group --group-name $SG_NAME --vpc-id "$VPC" \
        --description "CPSC 436C genai demo dashboard, port $PORT" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=project,Value=$NAME}]" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port $PORT --cidr 0.0.0.0/0 >/dev/null
fi
echo "cluster $CLUSTER, security group $SG in $VPC, log group $LOG_GROUP"

# 3. task definition
TD=$(mktemp); trap 'rm -f "$TD"' EXIT
TAXI_S3=s3://$BUCKET/$KEY TAXI_REGION=${TAXI_REGION:-$REGION}
export FAMILY EXEC_ROLE TASK_ROLE IMAGE PORT SECRET_ARN LOG_GROUP DASH_PASSWORD QUESTION_CAP TOTAL_CALLS TAXI_S3 TAXI_REGION REGION TRACES_TABLE TRACE_TTL_DAYS TRACES_REGION
python3 - "$TD" <<'PY'
import json, os, sys
e = os.environ
env = {k: e[k] for k in ("DASH_PASSWORD", "QUESTION_CAP", "TOTAL_CALLS", "TAXI_S3", "TAXI_REGION", "TRACES_TABLE", "TRACE_TTL_DAYS", "TRACES_REGION", "GROQ_MODEL", "OPENAI_NANO_MODEL", "OPENAI_MINI_MODEL") if e.get(k)}
td = {
    "family": e["FAMILY"], "networkMode": "awsvpc", "requiresCompatibilities": ["FARGATE"],
    "cpu": "512", "memory": "1024",
    "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
    "executionRoleArn": e["EXEC_ROLE"], "taskRoleArn": e["TASK_ROLE"],
    "containerDefinitions": [{
        "name": "dashboard", "image": e["IMAGE"], "essential": True,
        "portMappings": [{"containerPort": int(e["PORT"]), "protocol": "tcp"}],
        "environment": [{"name": k, "value": v} for k, v in env.items()],
        "secrets": [{"name": k, "valueFrom": f"{e['SECRET_ARN']}:{k}::"} for k in ("GROQ_API_KEY", "OPENAI_API_KEY")],
        "logConfiguration": {"logDriver": "awslogs", "options": {
            "awslogs-group": e["LOG_GROUP"], "awslogs-region": e["REGION"], "awslogs-stream-prefix": "dashboard"}},
    }],
}
open(sys.argv[1], "w").write(json.dumps(td))
PY
REV=$(aws ecs register-task-definition --cli-input-json "file://$TD" --query taskDefinition.revision --output text)
echo "task definition $FAMILY:$REV registered"
echo "prepared; nothing is running. Start it with: bash $HERE/start.sh"
