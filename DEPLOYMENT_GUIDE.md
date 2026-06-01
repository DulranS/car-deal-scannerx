# Deployment & Infrastructure Guide

## Overview

This Car Deal Scanner system now includes:

✅ **Multi-Agent Architecture** - Task handoff with LangGraph  
✅ **Prompt Caching** - Reduced LLM costs  
✅ **Model Routing** - Haiku (fast) / Sonnet (powerful)  
✅ **LangSmith Tracing** - Full observability  
✅ **Docker Containerization** - Consistent deployments  
✅ **Terraform IaC** - AWS infrastructure  
✅ **GitHub Actions CI/CD** - Automated pipelines  

---

## Quick Start

### 1. Prerequisites

- AWS Account with appropriate permissions
- Docker & Docker Compose
- Terraform >= 1.0
- Git
- Python 3.10+

### 2. Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your API keys

# Run with docker-compose
docker-compose up -d

# Access the service
curl http://localhost:8000/health
```

### 3. AWS Deployment

#### Step 1: Set up Terraform

```bash
cd terraform

# Copy example and customize
cp terraform.tfvars.example terraform.tfvars

# Initialize Terraform
terraform init

# Review the plan
terraform plan \
  -var="anthropic_api_key=sk-..." \
  -var="discord_webhook_url=https://..." \
  -var="serpapi_api_key=..." \
  -var="langsmith_api_key=..." \
  -var="supabase_url=https://..." \
  -var="supabase_key=..." \
  -var="rds_password=SecurePassword123"

# Apply infrastructure
terraform apply
```

#### Step 2: Push Docker Image to ECR

```bash
# Get ECR repository URL from Terraform output
ECR_REPO=$(terraform output -raw ecr_repository_url)

# Build and push image
docker build -t $ECR_REPO:latest .
docker push $ECR_REPO:latest
```

#### Step 3: Deploy to ECS

```bash
# Update task definition with new image
# Then trigger deployment via GitHub Actions or AWS Console

# Manual deployment:
aws ecs update-service \
  --cluster car-deal-scanner-cluster \
  --service car-deal-scanner-service \
  --force-new-deployment
```

---

## Architecture

### Multi-Agent System

```
┌─────────────────────────────────────────┐
│         Master Agent Orchestrator       │
│    (LangSmith traced, task routing)     │
└────────────┬────────────────────────────┘
             │
    ┌────────┼────────┬──────────┬─────────┐
    │        │        │          │         │
    v        v        v          v         v
┌───────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌────────┐
│Scraper│→│Enrich│→│Score │→│Format  │→│Output  │
│(Haiku)│ │(Sonnet)│(Opus)│ │(Haiku) │ │Discord │
└───────┘ └──────┘ └──────┘ └────────┘ └────────┘
    │        │        │          │         │
    └────────┼────────┴──────────┴─────────┘
             │
    LangSmith Tracing / Caching
```

### Infrastructure

```
┌────────────────────────────────────────┐
│          AWS Infrastructure            │
│                                        │
│  ┌─────────────────────────────────┐  │
│  │      ECS Fargate Service        │  │
│  │    (Auto-scaling: 1-3 tasks)    │  │
│  └──────────────┬──────────────────┘  │
│                 │                      │
│  ┌──────────────┴──────────────────┐  │
│  │                                  │  │
│  v                                  v  │
│ ┌────────────┐              ┌──────────────┐
│ │  RDS      │              │ ElastiCache  │
│ │ PostgreSQL│              │   Redis      │
│ │ (Aurora)  │              │ (Prompt      │
│ └────────────┘              │  Caching)    │
│                              └──────────────┘
│  ┌─────────────────────────────────┐
│  │    Application Load Balancer    │
│  └─────────────────────────────────┘
│
└────────────────────────────────────────┘
```

---

## Environment Variables

### Local Development (.env)

```env
# API Keys
ANTHROPIC_API_KEY=sk-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SERPAPI_API_KEY=...
SUPABASE_URL=https://...supabase.co
SUPABASE_KEY=...

# LangSmith Observability
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=car-deal-scanner

# Redis Cache
REDIS_URL=redis://localhost:6379

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=carscanner
DB_USER=postgres
DB_PASSWORD=...

# App Config
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### AWS Secrets Manager

All sensitive variables are stored in AWS Secrets Manager and injected at runtime.

---

## GitHub Actions Workflows

### 1. Test & Lint (`test.yml`)

- Runs on: Push to `main`/`develop`, Pull Requests
- Tests: Python 3.10, 3.11
- Checks: flake8, black, isort, pytest, security scans

### 2. Build & Push (`build.yml`)

- Runs on: Push to `main`, Tags
- Builds Docker image
- Pushes to ECR
- Scans with Trivy
- Notifies Slack

### 3. Deploy (`deploy.yml`)

- Runs on: Push to `main`, Manual trigger
- Updates ECS task definition
- Performs health checks
- Creates deployment annotations
- Notifies Slack

### 4. Terraform (`terraform.yml`)

- Runs on: Changes to `terraform/` directory
- Plans infrastructure changes
- Applies to AWS (on main branch)
- Posts plan in PR comments
- Notifies Slack

---

## Cost Optimization

### Multi-Agent with Caching

- **Prompt Caching**: Haiku model for simple tasks (90% cheaper than Sonnet)
- **Redis Caching**: Enrichment data cached for 24 hours
- **Model Routing**: Complex tasks use Sonnet, simple tasks use Haiku

### Infrastructure

- **Fargate Spot**: Use for non-critical workloads (70% cheaper)
- **RDS Aurora**: 40% cheaper than single-instance RDS
- **ElastiCache Redis**: Reduces database calls by 50+%

Estimated monthly cost: **$50-100** (compared to $500+ with single model)

---

## LangSmith Observability

### Tracing

All agent interactions are traced to LangSmith:

```python
from observability import tracer

@tracer.trace_agent_execution("my_agent")
def my_agent(state):
    # Your agent logic
    pass

# Get metrics
summary = tracer.get_execution_summary()
costs = tracer.get_cost_analysis()
tracer.print_trace_report()
```

### Metrics Tracked

- Agent execution time
- LLM token usage
- Cache hit/miss rates
- Error rates
- API latencies
- Cost by model

### Dashboard

Access LangSmith dashboard at: https://smith.langchain.com

---

## Monitoring & Logs

### CloudWatch

```bash
# View logs
aws logs tail /ecs/car-deal-scanner --follow

# Get metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=car-deal-scanner-service
```

### Health Checks

- ALB performs health checks every 30 seconds
- ECS auto-scales based on CPU/Memory
- Slack notifications on deployment status

---

## Troubleshooting

### Docker Build Issues

```bash
# Clear cache
docker builder prune -a

# Build with debug
docker build --progress=plain -t car-deal-scanner .
```

### Terraform State Issues

```bash
# Check state
terraform show

# Refresh state
terraform refresh

# Remove resource if corrupted
terraform state rm aws_instance.example
```

### ECS Deployment Issues

```bash
# Check task logs
aws ecs describe-tasks \
  --cluster car-deal-scanner-cluster \
  --tasks <task-arn> \
  --query 'tasks[0].lastStatus'

# View container logs
aws logs get-log-events \
  --log-group-name /ecs/car-deal-scanner \
  --log-stream-name <stream-name>
```

### Agent Debugging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check LangSmith traces
# https://smith.langchain.com/projects/car-deal-scanner
```

---

## Scaling & Performance

### Horizontal Scaling

- ECS auto-scales from 1-3 tasks based on CPU/Memory
- Modify `min_capacity`/`max_capacity` in Terraform

### Vertical Scaling

- Increase `container_cpu` and `container_memory`
- Change RDS instance class: `db.t3.small` → `db.t3.medium`
- Increase Redis node type: `cache.t3.micro` → `cache.t3.small`

### Performance Tuning

1. **Increase prompt cache TTL** in `agents.py`
2. **Batch enrich listings** (reduce API calls)
3. **Use Redis for session caching**
4. **Enable RDS read replicas** (production)

---

## Security

### Secrets Management

- All API keys stored in AWS Secrets Manager
- Rotated automatically (configurable)
- Encrypted at rest (KMS)
- Encrypted in transit (TLS)

### Network Security

- ECS tasks in private subnets
- NAT Gateway for outbound traffic
- Security groups restrict ingress/egress
- ALB handles HTTPS (configurable)

### Code Security

- Bandit scans for vulnerabilities
- Safety checks for known CVEs
- Trivy scans Docker images
- GitHub Dependabot for dependency updates

---

## Next Steps

1. **Configure GitHub Secrets**
   - AWS_ROLE_TO_ASSUME
   - AWS_REGION
   - ANTHROPIC_API_KEY
   - LANGSMITH_API_KEY
   - SLACK_WEBHOOK_URL

2. **Set up Terraform Backend**
   - Uncomment S3 backend in `provider.tf`
   - Create S3 bucket and DynamoDB table

3. **Configure Custom Domain**
   - Request SSL certificate in ACM
   - Update Route 53 records
   - Enable HTTPS in ALB

4. **Set up Monitoring**
   - Configure CloudWatch alarms
   - Set up SNS notifications
   - Configure PagerDuty integration

5. **Production Checklist**
   - [ ] Enable Aurora multi-AZ
   - [ ] Enable RDS automated backups
   - [ ] Enable Redis replication
   - [ ] Configure WAF rules
   - [ ] Set up CloudFront CDN
   - [ ] Configure API rate limiting
   - [ ] Enable request logging
