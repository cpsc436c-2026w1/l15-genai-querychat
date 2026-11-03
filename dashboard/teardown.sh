#!/bin/bash
# Remove everything deploy.sh made: tasks, task definition revisions (deregistered), cluster, security group,
# log group, ECR repo with its images. Leaves the two roles and the secret (the account owner's; see README).
source "$(dirname "$0")/common.sh"
guard
bash "$HERE/stop.sh" || true
for td in $(aws ecs list-task-definitions --family-prefix $FAMILY --status ACTIVE --query 'taskDefinitionArns[]' --output text); do
  aws ecs deregister-task-definition --task-definition "$td" >/dev/null && echo "deregistered $td"
done
aws ecs delete-cluster --cluster $CLUSTER >/dev/null 2>&1 && echo "deleted cluster $CLUSTER" || true
SG=$(sg_id); if [ "$SG" != "None" ] && [ -n "$SG" ]; then
  for i in 1 2 3 4 5 6; do aws ec2 delete-security-group --group-id "$SG" 2>/dev/null && { echo "deleted $SG"; break; }; sleep 20; done
fi
aws logs delete-log-group --log-group-name $LOG_GROUP 2>/dev/null && echo "deleted $LOG_GROUP" || true
aws ecr delete-repository --repository-name $REPO --force >/dev/null 2>&1 && echo "deleted ECR $REPO" || true
echo "--- left:"
echo "ecr:      $(aws ecr describe-repositories --repository-names $REPO --query 'repositories[].repositoryName' --output text 2>/dev/null)"
echo "cluster:  $(aws ecs describe-clusters --clusters $CLUSTER --query 'clusters[?status==`ACTIVE`].clusterName' --output text)"
echo "taskdefs: $(aws ecs list-task-definitions --family-prefix $FAMILY --status ACTIVE --query 'taskDefinitionArns[]' --output text) (INACTIVE revisions stay listed by AWS, at no cost)"
echo "sg:       $(sg_id)"
echo "logs:     $(aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP --query 'logGroups[].logGroupName' --output text)"
echo "roles (account owner's, kept): $(for r in $EXEC_ROLE_NAME $TASK_ROLE_NAME; do aws iam get-role --role-name $r --query Role.RoleName --output text 2>/dev/null; done | tr '\n' ' ')"
