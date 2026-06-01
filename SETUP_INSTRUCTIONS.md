# 🎯 Setup Instructions - Complete Enterprise System

## Overview

Your Car Deal Scanner has been fully upgraded to an enterprise-grade system with:

✅ Multi-Agent AI with LangGraph  
✅ Prompt Caching with Redis  
✅ Model Routing (Haiku/Sonnet/Opus)  
✅ LangSmith Tracing  
✅ Docker Containerization  
✅ Terraform AWS Infrastructure  
✅ GitHub Actions CI/CD  

**Total Setup Time**: 1-2 hours (dev) to 3-4 hours (production)

---

## Step 1: Review Documentation (15 min)

### Essential Reading
1. **README_ENTERPRISE.md** - Overview of entire system
2. **SYSTEM_UPGRADE_SUMMARY.md** - What was implemented
3. **DELIVERABLES.md** - Checklist of all features

### Reference Docs
- **DEPLOYMENT_GUIDE.md** - Full deployment walkthrough
- **INTEGRATION_GUIDE.md** - Architecture & integration
- **SYSTEM_ARCHITECTURE.md** - Quick reference & commands

---

## Step 2: Local Development Setup (30 min)

### Prerequisites
```bash
# Check Python version
python --version  # Should be 3.10+

# Install Docker
# Download from: https://www.docker.com/products/docker-desktop

# Install Terraform (for later)
# Download from: https://www.terraform.io/downloads
```

### Setup

```bash
# 1. Navigate to project
cd car-deal-scanner

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env

# 5. Edit .env with your API keys
# - ANTHROPIC_API_KEY=sk-...
# - LANGSMITH_API_KEY=...
# - DISCORD_WEBHOOK_URL=...
# - SUPABASE_URL=...
# - SUPABASE_KEY=...
```

### Test Agents Locally

```bash
# Run the multi-agent system
python agents.py

# You should see output like:
# ============================================================
# MULTI-AGENT PROCESSING COMPLETE
# ============================================================
#
# Listing: L001
# Status: ✓ Success
# 🚗 **Sample Car** (2015)
# ...
```

### Run Full Stack with Docker

```bash
# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f app

# Test API
curl http://localhost:8000/health

# Stop services
docker-compose down
```

---

## Step 3: AWS Preparation (15 min)

### Create AWS Account
1. Go to https://aws.amazon.com
2. Create account if you don't have one
3. Create an IAM user (not root) with programmatic access
4. Save access key & secret access key

### Configure AWS Credentials

```bash
# Install AWS CLI
pip install awscli

# Configure credentials
aws configure
# Enter:
# - Access Key ID
# - Secret Access Key
# - Region: us-east-1
# - Output format: json

# Verify
aws sts get-caller-identity
```

### Enable Required AWS Services
```bash
# The services we use are all enabled by default:
# - ECS Fargate
# - RDS Aurora
# - ElastiCache
# - ECR
# - Load Balancing
# - Secrets Manager
# - CloudWatch
```

---

## Step 4: LangSmith Setup (10 min)

### Create LangSmith Project

1. Go to https://smith.langchain.com
2. Sign up for account
3. Create new project: "car-deal-scanner"
4. Get API key from settings
5. Add to `.env`:
   ```env
   LANGSMITH_API_KEY=<your-key>
   LANGSMITH_PROJECT=car-deal-scanner
   ```

### Test Tracing

```python
from observability import setup_langsmith, tracer

setup_langsmith()

# Run your agents
from agents import master_agent
results = master_agent([{"url": "...", "id": "L001"}])

# Get metrics
tracer.print_trace_report()

# View at: https://smith.langchain.com
```

---

## Step 5: GitHub Setup (20 min)

### Create GitHub Repository

1. Go to https://github.com
2. Create new repository (private recommended)
3. Clone your existing repo or initialize new one:

```bash
git init
git add .
git commit -m "Initial commit: Enterprise system upgrade"
git branch -M main
git remote add origin https://github.com/your-username/car-deal-scanner.git
git push -u origin main
```

### Configure GitHub Secrets

1. Go to **Settings → Secrets and variables → Actions**
2. Add these secrets (click "New repository secret"):

```
AWS_REGION
us-east-1

AWS_ROLE_TO_ASSUME
arn:aws:iam::YOUR-ACCOUNT-ID:role/github-actions-role

ANTHROPIC_API_KEY
sk-...

LANGSMITH_API_KEY
...

DISCORD_WEBHOOK_URL
https://discord.com/api/webhooks/...

SERPAPI_API_KEY
...

SUPABASE_URL
https://...supabase.co

SUPABASE_KEY
...

SLACK_WEBHOOK_URL (optional, for notifications)
https://hooks.slack.com/services/...
```

### Enable GitHub Actions

1. Go to **Actions** tab
2. You should see the workflows:
   - test.yml ✅
   - build.yml ✅
   - deploy.yml ✅
   - terraform.yml ✅

---

## Step 6: Terraform Setup (1 hour)

### Prerequisites

```bash
# Install Terraform
# Download from: https://www.terraform.io/downloads
terraform --version  # Should be 1.0+

# Navigate to terraform directory
cd terraform
```

### Configure Variables

```bash
# Copy example
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars
# Set these values:
environment = "development"  # or staging/production
aws_region = "us-east-1"
container_image = "ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/car-deal-scanner:latest"
container_cpu = "256"
container_memory = "512"
desired_count = 1
```

### Initialize Terraform

```bash
# Initialize
terraform init

# Validate configuration
terraform validate

# Check formatting
terraform fmt -check -recursive
```

### Plan Infrastructure

```bash
# Create a plan
terraform plan \
  -var="anthropic_api_key=sk-..." \
  -var="discord_webhook_url=https://..." \
  -var="serpapi_api_key=..." \
  -var="langsmith_api_key=..." \
  -var="supabase_url=https://..." \
  -var="supabase_key=..." \
  -var="rds_password=YourSecurePassword123!" \
  -out=tfplan

# Review the output - look for resources being created
# It should show something like:
# Plan: 50 to add, 0 to change, 0 to destroy
```

### Apply Infrastructure

```bash
# Apply the plan
terraform apply tfplan

# Wait for completion (10-15 minutes)
# You should see output like:

# Outputs:
#
# alb_hostname = "car-deal-scanner-alb-1234567890.us-east-1.elb.amazonaws.com"
# api_endpoint = "http://car-deal-scanner-alb-..."
# ecr_repository_url = "123456789.dkr.ecr.us-east-1.amazonaws.com/car-deal-scanner"
# ecs_cluster_name = "car-deal-scanner-cluster"
# ...
```

### Save Output

```bash
# Save outputs for later
terraform output -json > outputs.json

# Get specific values
ECR_REPO=$(terraform output -raw ecr_repository_url)
ALB_DNS=$(terraform output -raw alb_hostname)

echo "ECR_REPO=$ECR_REPO"
echo "ALB_DNS=$ALB_DNS"
```

---

## Step 7: Docker Image Build & Push (20 min)

### Build Docker Image

```bash
# Build the image
docker build -t car-deal-scanner:latest .

# Test it locally
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-... \
  -e LANGSMITH_API_KEY=... \
  car-deal-scanner:latest

# Test health endpoint
curl http://localhost:8000/health
```

### Push to ECR

```bash
# Get ECR repo from Terraform output
ECR_REPO=$(terraform output -raw ecr_repository_url)

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REPO

# Tag image
docker tag car-deal-scanner:latest $ECR_REPO:latest

# Push to ECR
docker push $ECR_REPO:latest

# Verify
aws ecr describe-images --repository-name car-deal-scanner
```

---

## Step 8: Deploy to ECS (Automatic)

### Option A: Automatic via GitHub Actions (Recommended)

```bash
# Push to GitHub
git add .
git commit -m "Deploy to production"
git push origin main

# GitHub Actions automatically:
# 1. Runs tests
# 2. Builds Docker image
# 3. Pushes to ECR
# 4. Deploys to ECS
# 5. Runs health checks
# 6. Sends Slack notification

# Monitor at: https://github.com/your-repo/actions
```

### Option B: Manual Deployment

```bash
# Update task definition with new image
aws ecs update-service \
  --cluster car-deal-scanner-cluster \
  --service car-deal-scanner-service \
  --force-new-deployment

# Check deployment status
aws ecs describe-services \
  --cluster car-deal-scanner-cluster \
  --services car-deal-scanner-service \
  --query 'services[0].status'

# Get health check status
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups \
    --names car-deal-scanner-tg \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)
```

---

## Step 9: Verify Deployment (10 min)

### Check ECS Service

```bash
# Get service status
aws ecs describe-services \
  --cluster car-deal-scanner-cluster \
  --services car-deal-scanner-service

# Get running tasks
aws ecs list-tasks \
  --cluster car-deal-scanner-cluster \
  --service-name car-deal-scanner-service

# View task logs
aws logs tail /ecs/car-deal-scanner --follow
```

### Test API Endpoint

```bash
# Get ALB DNS name
ALB_DNS=$(terraform output -raw alb_hostname)

# Test health endpoint
curl http://$ALB_DNS/health

# Test API
curl http://$ALB_DNS/api/health
```

### Monitor Metrics

```bash
# View CloudWatch logs
aws logs tail /ecs/car-deal-scanner --follow

# Get CPU metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=car-deal-scanner-service \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average
```

### Check LangSmith Traces

1. Go to https://smith.langchain.com
2. Select "car-deal-scanner" project
3. View traces from your deployment
4. Check costs and metrics

---

## Step 10: Monitor & Optimize (Ongoing)

### Daily Monitoring

```bash
# Check service health
aws ecs describe-services \
  --cluster car-deal-scanner-cluster \
  --services car-deal-scanner-service

# View recent logs
aws logs tail /ecs/car-deal-scanner --follow --since 1h

# Check LangSmith metrics
# https://smith.langchain.com/projects/car-deal-scanner
```

### Weekly Optimization

```python
# Get cost analysis
from observability import tracer
costs = tracer.get_cost_analysis()
print(costs)

# Adjust prompt cache TTL if needed
# Adjust model routing based on metrics
# Review bottlenecks from traces
```

### Monthly Scaling

```bash
# Check auto-scaling metrics
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs

# Adjust min/max capacity if needed
terraform apply -var="max_capacity=5"
```

---

## 🆘 Troubleshooting

### Docker Build Fails

```bash
# Clear Docker cache
docker builder prune -a

# Try rebuilding
docker build --no-cache -t car-deal-scanner:latest .

# Check Docker logs
docker logs $(docker ps -a -q)
```

### Terraform Apply Fails

```bash
# Refresh state
terraform refresh

# Check for conflicts
terraform show

# Destroy and rebuild (dev only!)
terraform destroy
terraform apply
```

### ECS Deployment Issues

```bash
# Check task logs
aws logs tail /ecs/car-deal-scanner --follow

# Describe task
aws ecs describe-tasks \
  --cluster car-deal-scanner-cluster \
  --tasks $(aws ecs list-tasks --cluster car-deal-scanner-cluster --query 'taskArns[0]' --output text)

# Restart service
aws ecs update-service \
  --cluster car-deal-scanner-cluster \
  --service car-deal-scanner-service \
  --force-new-deployment
```

### High Costs

```python
# Check token usage
from observability import tracer
summary = tracer.get_execution_summary()

# Analyze by model
haiku_tokens = summary.get('llm_haiku', {}).get('input_tokens', {}).get('total', 0)
sonnet_tokens = summary.get('llm_sonnet', {}).get('input_tokens', {}).get('total', 0)

# Increase cache TTL
# Review model routing
# Optimize prompts
```

---

## ✅ Completion Checklist

### Setup Complete When:
- [ ] Python environment working (agents.py runs)
- [ ] Docker stack runs locally (docker-compose up works)
- [ ] AWS credentials configured
- [ ] LangSmith project created and API key saved
- [ ] GitHub repository created with secrets configured
- [ ] Terraform initialized and validated
- [ ] Docker image pushed to ECR
- [ ] ECS service deployed and healthy
- [ ] LangSmith shows traces
- [ ] API responding to requests

### Production Ready When:
- [ ] 24-hour uptime test passed
- [ ] Cost analysis shows savings
- [ ] LangSmith shows 80%+ cache hit rate
- [ ] All GitHub Actions passing
- [ ] CloudWatch alarms configured
- [ ] Backup tested
- [ ] Disaster recovery plan documented

---

## 📞 Getting Help

1. **Review Documentation**
   - SYSTEM_UPGRADE_SUMMARY.md
   - DEPLOYMENT_GUIDE.md
   - INTEGRATION_GUIDE.md

2. **Check Logs**
   - Local: `docker-compose logs -f`
   - AWS: `aws logs tail /ecs/car-deal-scanner --follow`
   - GitHub: Actions tab

3. **Monitor Metrics**
   - LangSmith: https://smith.langchain.com
   - CloudWatch: AWS Console
   - Local: `tracer.print_trace_report()`

4. **Test Components**
   ```bash
   # Test agents
   python agents.py
   
   # Test observability
   python -c "from observability import tracer; tracer.print_trace_report()"
   
   # Test Docker
   docker-compose up -d && docker-compose logs -f
   ```

---

## 🚀 Next Steps After Setup

1. ✅ Set up monitoring dashboards
2. ✅ Configure CloudWatch alarms
3. ✅ Set up automated backups
4. ✅ Test disaster recovery
5. ✅ Optimize based on metrics
6. ✅ Scale infrastructure as needed
7. ✅ Plan capacity for growth

---

## 📝 Important Notes

### Environment Variables
- **Never commit `.env` or `terraform.tfvars`** - they contain secrets
- Always use GitHub Secrets for CI/CD
- Always use AWS Secrets Manager for production

### Cost Control
- Monitor LangSmith daily for token usage
- Review AWS billing weekly
- Adjust auto-scaling thresholds based on traffic

### Security
- Rotate secrets regularly
- Enable MFA on AWS account
- Review IAM permissions monthly
- Monitor CloudTrail logs

### Performance
- Use Redis for caching (enabled by default)
- Enable CloudFront CDN (optional)
- Monitor ECS metrics for bottlenecks
- Adjust model routing based on performance

---

**You're all set! Deploy with confidence. 🚀**

See DEPLOYMENT_GUIDE.md for more details.
