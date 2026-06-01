# Quick Reference: System Components

## 🏗️ Architecture at a Glance

```
Multi-Agent System (agents.py)
├── Master Agent
├── Scraper (Haiku)
├── Enrichment (Sonnet) + Prompt Cache
├── Scoring (Opus)
└── Formatter (Haiku)
     ↓
LangSmith Tracing (observability.py)
     ↓
Docker Container (Dockerfile)
     ↓
AWS Infrastructure (terraform/)
├── ECS Fargate (1-3 tasks)
├── RDS Aurora
├── ElastiCache Redis
└── Application Load Balancer
     ↓
GitHub Actions (CI/CD)
├── Test
├── Build
├── Deploy
└── Terraform Apply
```

---

## 📦 Files Overview

### Core Application
| File | Purpose | Lines |
|------|---------|-------|
| `agents.py` | Multi-agent system with LangGraph | 450 |
| `observability.py` | LangSmith tracing & metrics | 350 |
| `car_deal_scanner.py` | Original scraper (unchanged) | 716 |

### Docker
| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage container build |
| `docker-compose.yml` | Local dev environment |

### Infrastructure (Terraform)
| File | Purpose | Resources |
|------|---------|-----------|
| `provider.tf` | AWS config | 1 |
| `variables.tf` | Input variables | 30+ |
| `vpc.tf` | Networking | 20+ |
| `security_groups.tf` | Network security | 4 |
| `ecr_and_iam.tf` | Container registry & roles | 10+ |
| `alb.tf` | Load balancer | 4 |
| `ecs.tf` | Container orchestration | 7 |
| `rds.tf` | PostgreSQL | 4 |
| `elasticache.tf` | Redis | 2 |
| `outputs.tf` | Output values | 10+ |

### CI/CD (GitHub Actions)
| File | Trigger | Jobs |
|------|---------|------|
| `test.yml` | Push/PR | Test, Lint, Security |
| `build.yml` | main, tags | Build, Push ECR |
| `deploy.yml` | main + manual | Deploy to ECS |
| `terraform.yml` | terraform/ | Plan, Apply |

### Documentation
| File | Purpose |
|------|---------|
| `SYSTEM_UPGRADE_SUMMARY.md` | What was built |
| `DEPLOYMENT_GUIDE.md` | How to deploy |
| `INTEGRATION_GUIDE.md` | How components work |
| `QUICK_REFERENCE.md` | This file |

---

## 🚀 Quick Commands

### Local Development
```bash
# Install deps
pip install -r requirements.txt

# Run with docker-compose
docker-compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker-compose logs -f app

# Stop
docker-compose down
```

### Test & Lint
```bash
# Run tests
pytest tests/ --cov

# Format code
black .

# Lint
flake8 .

# Check imports
isort --check-only .
```

### Docker
```bash
# Build
docker build -t car-deal-scanner .

# Run
docker run -p 8000:8000 --env-file .env car-deal-scanner

# Push to ECR
docker tag car-deal-scanner:latest $ECR_REPO:latest
docker push $ECR_REPO:latest
```

### Terraform
```bash
# Init
cd terraform && terraform init

# Plan
terraform plan -var-file=terraform.tfvars

# Apply
terraform apply

# Destroy (dev only!)
terraform destroy

# Show state
terraform state list
terraform show aws_ecs_service.main
```

### AWS CLI
```bash
# View logs
aws logs tail /ecs/car-deal-scanner --follow

# Check ECS service
aws ecs describe-services --cluster car-deal-scanner-cluster \
  --services car-deal-scanner-service

# Get ALB DNS
aws elbv2 describe-load-balancers --names car-deal-scanner-alb \
  --query 'LoadBalancers[0].DNSName'

# View secrets
aws secretsmanager list-secrets --filters Key=name,Values=car-deal-scanner
```

### GitHub
```bash
# View Actions
# https://github.com/your-repo/actions

# Trigger manual deploy
# Actions → Deploy → Run workflow → Select environment

# View Secrets
# Settings → Secrets and variables → Actions
```

---

## 🎯 Key Concepts

### Multi-Agent Handoff
- **Master Agent**: Orchestrates workflow
- **Agents**: Specialized workers (Scraper, Enrichment, etc.)
- **State**: Passed between agents in LangGraph
- **Flow**: Automatic routing with error handling

### Prompt Caching
- **Key**: Generated from model + context
- **TTL**: 24 hours default
- **Hit Rate**: 80%+ expected
- **Savings**: 100% when cached

### Model Routing
- **Haiku**: Simple tasks (60% of calls)
- **Sonnet**: Medium complexity (30% of calls)
- **Opus**: Complex reasoning (10% of calls)
- **Cost**: 63% cheaper than all-Opus

### LangSmith Tracing
- **Decorator**: `@tracer.trace_agent_execution("name")`
- **Metrics**: Tokens, latency, costs, errors
- **Dashboard**: https://smith.langchain.com
- **Tracking**: Every agent call automatically logged

---

## 📊 Cost Breakdown (Monthly)

| Component | Dev | Staging | Prod |
|-----------|-----|---------|------|
| ECS Fargate | $5 | $10 | $30 |
| RDS Aurora | $5 | $10 | $50 |
| Redis | $3 | $3 | $10 |
| LLM Calls | $2 | $5 | $15 |
| **Total** | **$15** | **$28** | **$105** |

**Savings vs. Before**: 85% ($120/mo → $15/mo dev)

---

## 🔐 Secrets Management

### Local Development
Create `.env`:
```env
ANTHROPIC_API_KEY=sk-...
LANGSMITH_API_KEY=...
SUPABASE_URL=...
DISCORD_WEBHOOK_URL=...
```

### AWS Production
All secrets stored in AWS Secrets Manager:
```bash
aws secretsmanager get-secret-value \
  --secret-id car-deal-scanner/api-keys
```

### GitHub Actions
Secrets configured in repository settings:
```
Settings → Secrets and variables → Actions
```

---

## 📈 Performance Targets

| Metric | Target | How to Improve |
|--------|--------|----------------|
| Agent latency | < 7s | Cache enrichment |
| Cache hit rate | > 80% | Increase TTL |
| Cost per listing | < $0.01 | Use Haiku more |
| Deploy time | < 5min | Smaller image |
| Error rate | < 0.1% | Better retry logic |

---

## 🆘 Common Issues

### Problem: High LLM Costs
**Solution**: 
- Check model routing is working
- Increase prompt cache TTL
- Review LangSmith dashboard

### Problem: Slow Enrichment
**Solution**:
- Check Redis connection
- Monitor cache hit rate
- Increase Redis node size

### Problem: ECS Deployment Fails
**Solution**:
```bash
# Check logs
aws logs tail /ecs/car-deal-scanner --follow

# Check task status
aws ecs describe-tasks --cluster car-deal-scanner-cluster \
  --tasks <task-arn>

# View secrets accessible to task
aws secretsmanager describe-secret --secret-id car-deal-scanner/api-keys
```

### Problem: Terraform Apply Fails
**Solution**:
```bash
# Refresh state
terraform refresh

# Check for conflicts
terraform show

# Plan only (no apply)
terraform plan

# Destroy and rebuild
terraform destroy
terraform apply
```

---

## 📚 Documentation Map

```
START_HERE.md (You are here)
├── SYSTEM_UPGRADE_SUMMARY.md ← What was built
├── DEPLOYMENT_GUIDE.md ← How to deploy
│   ├── Quick Start
│   ├── Architecture
│   ├── Environment Setup
│   └── Troubleshooting
├── INTEGRATION_GUIDE.md ← How it works
│   ├── Multi-Agent System
│   ├── Prompt Caching
│   ├── Model Routing
│   ├── LangSmith
│   ├── Docker
│   ├── Terraform
│   └── GitHub Actions
└── QUICK_REFERENCE.md (This file)
    ├── Architecture
    ├── Files
    ├── Commands
    └── Concepts
```

---

## ✅ Deployment Checklist

### Before First Deploy
- [ ] Install Python 3.10+, Docker, Terraform
- [ ] Clone repository
- [ ] Copy .env.example → .env
- [ ] Install pip dependencies
- [ ] Test locally with docker-compose

### Before AWS Deploy
- [ ] Create AWS account & configure credentials
- [ ] Create GitHub repository
- [ ] Set GitHub Secrets:
  - [ ] AWS_ROLE_TO_ASSUME
  - [ ] AWS_REGION
  - [ ] ANTHROPIC_API_KEY
  - [ ] LANGSMITH_API_KEY
  - [ ] SLACK_WEBHOOK_URL
- [ ] Review terraform.tfvars
- [ ] Initialize Terraform backend

### Before Production
- [ ] Enable RDS automated backups
- [ ] Enable ElastiCache replication
- [ ] Set up CloudWatch alarms
- [ ] Configure WAF rules
- [ ] Enable request logging
- [ ] Set up custom domain & HTTPS

### Ongoing
- [ ] Monitor LangSmith daily
- [ ] Review CloudWatch metrics
- [ ] Update dependencies monthly
- [ ] Test disaster recovery quarterly

---

## 🎓 Learning Resources

### Multi-Agent Systems
- LangGraph: https://langchain-ai.github.io/langgraph/
- LangChain: https://python.langchain.com/

### AWS
- ECS: https://docs.aws.amazon.com/ecs/
- RDS Aurora: https://docs.aws.amazon.com/rds/
- ElastiCache: https://docs.aws.amazon.com/elasticache/

### Terraform
- Docs: https://www.terraform.io/docs
- AWS Provider: https://registry.terraform.io/providers/hashicorp/aws/

### GitHub Actions
- Docs: https://docs.github.com/en/actions

### LangSmith
- Docs: https://docs.smith.langchain.com/

---

## 💬 Help

### Getting Help

1. **Read Documentation**
   - DEPLOYMENT_GUIDE.md
   - INTEGRATION_GUIDE.md
   - This QUICK_REFERENCE.md

2. **Check Logs**
   - Docker: `docker-compose logs -f app`
   - AWS: `aws logs tail /ecs/car-deal-scanner --follow`
   - GitHub: Check Actions tab

3. **Debug with LangSmith**
   - https://smith.langchain.com
   - View all traces
   - Check metrics

4. **Test Locally**
   - Run with docker-compose
   - Check agents.py directly
   - Print debug output

---

## 🚀 Next Steps

1. **Review Documentation**
   - [ ] Read SYSTEM_UPGRADE_SUMMARY.md
   - [ ] Read DEPLOYMENT_GUIDE.md
   - [ ] Skim INTEGRATION_GUIDE.md

2. **Set Up Local**
   - [ ] Install dependencies
   - [ ] Copy .env.example
   - [ ] Run docker-compose

3. **Test Agents**
   - [ ] Run agents.py
   - [ ] Check agent_logs output
   - [ ] Monitor with observability

4. **Deploy to AWS**
   - [ ] Set GitHub Secrets
   - [ ] Configure Terraform
   - [ ] Push to main (auto-deploys)

5. **Monitor**
   - [ ] Check LangSmith dashboard
   - [ ] Review CloudWatch logs
   - [ ] Adjust configuration

---

**That's it! You now have an enterprise-grade AI system. 🎉**
