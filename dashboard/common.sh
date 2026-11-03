# Shared by deploy.sh, start.sh, stop.sh, url.sh, teardown.sh. Sourced, not run.
# Set the variables below in your shell (or a gitignored .env next to this file) to override the defaults.
# Every AWS call runs only after guard() has printed the account and checked the region.
set -euo pipefail
export AWS_PAGER=""
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/.env" ] && . "$HERE/.env"

REGION=${REGION:-ca-central-1}                       # where everything runs
export AWS_REGION=$REGION AWS_DEFAULT_REGION=$REGION
ACCOUNT=${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text)}   # the account you are signed in to
NAME=${NAME:-genai-querychat}                        # ECR repo, cluster, task family, security group, log group
BUCKET=${BUCKET:-}                                   # S3 bucket that holds the trips Parquet file (you set it)
KEY=${KEY:-genai/taxi_2024-01.parquet}               # its key in that bucket
SECRET_NAME=${SECRET_NAME:-$NAME/keys}               # Secrets Manager secret: JSON with GROQ_API_KEY, OPENAI_API_KEY
EXEC_ROLE_NAME=${EXEC_ROLE_NAME:-$NAME-exec}         # execution role (made by the account owner, see README)
TASK_ROLE_NAME=${TASK_ROLE_NAME:-$NAME-task}         # task role (made by the account owner, see README)
IMAGE_TAG=${IMAGE_TAG:-$(date +%Y%m%d-%H%M)}         # tag of a new build (deploy.sh never pushes :latest)

REPO=$NAME; CLUSTER=$NAME; FAMILY=$NAME; SG_NAME=$NAME; LOG_GROUP=/ecs/$NAME; PORT=8000
EXEC_ROLE=arn:aws:iam::$ACCOUNT:role/$EXEC_ROLE_NAME
TASK_ROLE=arn:aws:iam::$ACCOUNT:role/$TASK_ROLE_NAME
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
IMAGE=$REGISTRY/$REPO:$IMAGE_TAG
STATE=$HERE/.task-arns                               # tasks start.sh started (gitignored)
DOCKER=docker; docker info >/dev/null 2>&1 || DOCKER="sudo docker"

guard() {
  local acct region
  acct=$(aws sts get-caller-identity --query Account --output text)
  region=$(aws configure get region 2>/dev/null || true); region=${AWS_REGION:-$region}
  if [ "$acct" != "$ACCOUNT" ] || [ "$region" != "$REGION" ]; then
    echo "refusing: account $acct region $region (want $ACCOUNT $REGION)" >&2; exit 1
  fi
  echo "account $acct, region $region, identity $(aws sts get-caller-identity --query Arn --output text)"
}

default_vpc() { aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text; }
sg_id() {
  aws ec2 describe-security-groups --filters Name=group-name,Values=$SG_NAME Name=vpc-id,Values="$(default_vpc)" \
    --query 'SecurityGroups[0].GroupId' --output text
}
# Tasks not yet stopped. Uses ListTasks when the caller may; otherwise the ARNs start.sh recorded, checked
# with DescribeTasks. Fails loudly rather than report "none" when neither works.
running_tasks() {
  local arns
  if arns=$(aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING --query 'taskArns[]' --output text 2>/dev/null); then
    echo "$arns" | tr '\t' '\n' | grep -v '^None$' | grep . || true; return 0
  fi
  echo "(ecs:ListTasks denied; using $STATE)" >&2
  [ -s "$STATE" ] || return 0
  aws ecs describe-tasks --cluster $CLUSTER --tasks $(cat "$STATE") \
    --query 'tasks[?lastStatus!=`STOPPED`].taskArn' --output text | tr '\t' '\n' | grep -v '^None$' | grep . || true
}
