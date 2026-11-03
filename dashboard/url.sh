#!/bin/bash
# Print the URL of the running dashboard task (read only).
source "$(dirname "$0")/common.sh"
guard >/dev/null
for t in $(running_tasks); do
  ENI=$(aws ecs describe-tasks --cluster $CLUSTER --tasks "$t" \
        --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text)
  IP=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --query 'NetworkInterfaces[0].Association.PublicIp' --output text)
  echo "http://$IP:$PORT/   ($t)"
done
