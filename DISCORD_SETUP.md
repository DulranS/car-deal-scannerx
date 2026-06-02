# Discord Webhook Setup Guide

## Quick Setup

### 1. Create Discord Server & Channel
1. Go to [Discord](https://discord.com)
2. Create a new server (or use existing)
3. Create a channel named `#car-deals`

### 2. Create Webhook
1. Right-click channel → "Edit Channel"
2. Go to "Integrations" → "Webhooks"
3. Click "New Webhook"
4. Name it: `Car Deal Scanner`
5. Click "Copy Webhook URL"

Your URL will look like:
```
https://discord.com/api/webhooks/1234567890/abcdefghijklmnop
```

### 3. Set Environment Variable
```bash
# Local development
echo 'DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN' >> .env

# AWS Secrets Manager
aws secretsmanager create-secret \
  --name car-deal-scanner/discord-webhook \
  --secret-string 'https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN'

# GitHub Actions
# Go to Settings → Secrets and variables → Actions
# Add secret: DISCORD_WEBHOOK_URL
```

### 4. Deploy with Terraform
```bash
terraform apply \
  -var="discord_webhook_url=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
```

## Testing

### Test Locally
```bash
python -c "
import requests
import os
from dotenv import load_dotenv

load_dotenv()
webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

payload = {
    'embeds': [{
        'title': 'Test Message',
        'description': 'Car Deal Scanner is connected!',
        'color': 16096779
    }]
}

response = requests.post(webhook_url, json=payload)
print('Status:', response.status_code)
"
```

### Test in Docker
```bash
docker-compose up
# Should post test message to Discord
```

## Message Format

### Single Deal
```json
{
  "embeds": [
    {
      "title": "#1 | 2015 Suzuki Alto",
      "color": 16096779,
      "fields": [
        {"name": "Asking Price", "value": "LKR 3,500,000", "inline": true},
        {"name": "Market Value", "value": "LKR 4,100,000", "inline": true},
        {"name": "ROI Score", "value": "17/100", "inline": true},
        {"name": "Est. Profit", "value": "LKR 600,000", "inline": true},
        {"name": "Mileage", "value": "125,000 km", "inline": true},
        {"name": "Transmission", "value": "Manual", "inline": true},
        {"name": "Location", "value": "Colombo - Private", "inline": true},
        {"name": "Why Buy", "value": "Private seller improves negotiation...", "inline": false},
        {"name": "Risks", "value": "High mileage may require additional...", "inline": false},
        {"name": "Listing URL", "value": "[View on RiyaSewana](https://...)", "inline": false}
      ]
    }
  ]
}
```

### Multiple Deals (Auto-Chunked)
```
Post 1: Deals #1-10 (max Discord limit)
Post 2: Deals #11-20
Post 3: Header with summary
```

## Cost & Rate Limits

### Discord Limits
- **Messages**: Unlimited
- **Embeds per message**: 10 max
- **Characters per embed**: 6000 max (we use ~500)
- **Rate limit**: 10 posts/second (we use 0.5s spacing)

### No Cost
✅ Webhook posts are completely free
✅ No Discord Nitro required
✅ No API key needed

## Troubleshooting

### 401 Unauthorized
- Webhook URL is incorrect or expired
- Regenerate webhook in Discord settings
- Update environment variable

### 404 Not Found
- Webhook URL format is wrong
- Check: `https://discord.com/api/webhooks/{ID}/{TOKEN}`

### 429 Too Many Requests
- Reduce posting frequency
- Increase delay: `time.sleep(1)` in `DiscordPoster.post()`
- Group messages into fewer posts

### Posts Not Appearing
1. Check channel permissions (webhook might not have access)
2. Verify webhook hasn't been deleted
3. Check Discord #car-deals channel exists
4. Look for error in application logs

## Migration from Slack

### Differences
| Feature | Slack | Discord |
|---------|-------|---------|
| Setup | More complex | 1-click webhook |
| Cost | Free tier limited | Completely free |
| Embeds | Custom format | Rich embeds native |
| Rate limits | Lower | 10 posts/sec |
| Threading | Supported | Not supported |
| Reactions | Supported | Supported |

### Migration Steps
1. Remove all Slack references from code
2. Create Discord server & channel
3. Set `DISCORD_WEBHOOK_URL` in environment
4. Remove `SLACK_WEBHOOK_URL` from Secrets Manager
5. Deploy and test

## Example .env
```bash
# Car Deal Scanner
SUPABASE_URL=https://xyzabc.supabase.co
SUPABASE_KEY=eyJhbGc...
ANTHROPIC_API_KEY=sk-ant-...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123456/abcdef
SERPAPI_API_KEY=...
LANGSMITH_API_KEY=...

# Optional
DEBUG=true
DRY_RUN=false
```

## Example Docker Compose
```yaml
version: '3'
services:
  car-scanner:
    build: .
    environment:
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
    restart: always
    schedule: "0 */2 * * *"  # Every 2 hours
```

## Support

Need help?
1. Check webhook URL in Discord settings
2. Verify channel permissions
3. Test with curl:
   ```bash
   curl -X POST "YOUR_WEBHOOK_URL" \
     -H "Content-Type: application/json" \
     -d '{"content":"Test message"}'
   ```
4. Check application logs for error details
