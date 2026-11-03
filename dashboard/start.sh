#!/bin/bash
# Start ONE dashboard task with a public IP and print its URL.
#   bash start.sh       the newest task definition revision
#   bash start.sh 3     a given revision (to go back to an earlier image)
# Bills Fargate time until stop.sh. Refuses if a task is already running.
source "$(dirname "$0")/common.sh"
REV=${1:-}
[[ -z "$REV" || "$REV" =~ ^[0-9]+$ ]] || { echo "usage: start.sh [revision number]" >&2; exit 2; }
TD_REF=$FAMILY${REV:+:$REV}
guard
aws ecs describe-task-definition --task-definition "$TD_REF" \
  --query 'taskDefinition.[family,revision,containerDefinitions[0].image]' --output text | sed 's/^/task definition: /'
if [ -n "$(running_tasks)" ]; then echo "already running: $(running_tasks)"; exec bash "$HERE/url.sh"; fi
VPC=$(default_vpc); SG=$(sg_id)
SUBNET=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
          --query 'Subnets[0].SubnetId' --output text)
TASK=$(aws ecs run-task --cluster $CLUSTER --task-definition "$TD_REF" --launch-type FARGATE --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text)
mkdir -p "$(dirname "$STATE")"; echo "$TASK" >> "$STATE"
echo "started $TASK; waiting for RUNNING (about 1-2 minutes)"
aws ecs wait tasks-running --cluster $CLUSTER --tasks "$TASK"
exec bash "$HERE/url.sh"
