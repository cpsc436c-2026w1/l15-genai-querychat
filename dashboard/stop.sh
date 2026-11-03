#!/bin/bash
# Stop every running dashboard task. Keeps the image, task definition, cluster, log group and security group.
source "$(dirname "$0")/common.sh"
guard
TASKS=$(running_tasks)
for t in $TASKS; do aws ecs stop-task --cluster $CLUSTER --task "$t" --reason "stop.sh" --query 'task.lastStatus' --output text; done
[ -z "$TASKS" ] || aws ecs wait tasks-stopped --cluster $CLUSTER --tasks $TASKS
LEFT=$(running_tasks); echo "tasks not stopped: $(echo $LEFT | wc -w)"; [ -z "$LEFT" ] && : > "$STATE" 2>/dev/null || true
