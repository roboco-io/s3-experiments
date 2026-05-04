REGION ?= us-east-1
STACK_PREFIX = S3FilesBenchmark
CDK_DIR = cdk

export AWS_REGION = $(REGION)
export CDK_DEFAULT_REGION = $(REGION)

.PHONY: help install bootstrap deploy run-sm run-ec2 collect analyze docs destroy verify-clean cost

help:
	@echo "S3 Files Benchmark — targets"
	@echo "  install        Install CDK deps"
	@echo "  bootstrap      cdk bootstrap (idempotent)"
	@echo "  deploy         Deploy all CDK stacks (cleanup-stack first)"
	@echo "  run-sm         Launch SageMaker T1-T4 PoC"
	@echo "  run-ec2        Trigger EC2 fio runner via SSM (UserData usually auto-fires)"
	@echo "  collect        Pull output/ artifacts from EFS to local"
	@echo "  analyze        Parse fio JSON + render charts"
	@echo "  docs           Update docs/research/s3-files.md and file-io.md"
	@echo "  destroy        cdk destroy --all (use after experiment)"
	@echo "  verify-clean   Grep for any leftover AWS resources"
	@echo "  cost           Show today's UnblendedCost in $(REGION)"

install:
	cd $(CDK_DIR) && npm install

bootstrap: install
	cd $(CDK_DIR) && npx cdk bootstrap aws://$$(aws sts get-caller-identity --query Account --output text)/$(REGION)

deploy: bootstrap
	cd $(CDK_DIR) && npx cdk deploy --all --require-approval never --region $(REGION)

run-sm:
	cd sagemaker && python launch_t1_t4.py

run-ec2:
	@INSTANCE_ID=$$(aws ec2 describe-instances --region $(REGION) --filters Name=tag:Project,Values=s3-files-benchmark Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text); \
	echo "Triggering on $$INSTANCE_ID"; \
	aws ssm send-command --region $(REGION) --instance-ids $$INSTANCE_ID --document-name AWS-RunShellScript --parameters 'commands=["bash /home/ec2-user/scripts/50_run_all.sh"]'

collect:
	bash scripts/collect_results.sh

analyze:
	cd analysis && python parse_fio.py && python plots.py

destroy:
	cd $(CDK_DIR) && npx cdk destroy --all --force --region $(REGION) || true
	@echo "Sleeping 30s for EFS mount target cleanup..." && sleep 30
	cd $(CDK_DIR) && npx cdk destroy --all --force --region $(REGION) || true

verify-clean:
	bash scripts/99_verify_clean.sh

cost:
	aws ce get-cost-and-usage \
	  --time-period Start=$$(date -v-1d +%Y-%m-%d),End=$$(date +%Y-%m-%d) \
	  --granularity DAILY --metrics UnblendedCost \
	  --region $(REGION) \
	  --query 'ResultsByTime[0].Total.UnblendedCost' --output text
