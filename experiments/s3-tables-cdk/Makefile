.PHONY: all synth deploy benchmark destroy clean

all: benchmark

synth:
	npx cdk synth --context runId=$(RUN_ID)

deploy:
	@echo "Deploying S3 Tables + Regular Iceberg benchmark stack..."
	@echo "  Region: us-east-1"
	@echo "  Resources: S3 Table Bucket, Regular S3 Bucket, Glue DB, Athena Workgroup"
	@echo "  Estimated cost: < \$$0.50"
	@echo ""
	mkdir -p output
	bash benchmark.sh

benchmark: deploy

destroy:
	npx cdk destroy --force --context runId=$(RUN_ID)

clean:
	rm -rf dist output cdk.out
