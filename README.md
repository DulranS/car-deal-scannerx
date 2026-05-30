# Car Deal Scanner

A Python implementation of the car deal scanner flow using Supabase for seen-ID storage and a modern agentic LLM workflow.

## What it does
- searches for targeted used car listings on `ikman.lk` and `riyasewana.com`
- scrapes and normalizes listing details
- applies the same ROI and market-value scoring logic from the original Make flow
- stores seen listing IDs in Supabase
- sends formatted Discord embeds for the top deals

## Environment variables
Create a `.env` file with:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-role-key
OPENAI_API_KEY=your-openai-key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SERPAPI_API_KEY=your-serpapi-key
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python car_deal_scanner.py
```

## Notes
- `seen_ids` must exist in Supabase with at least columns `listing_id` and `seen_at`
- the script uses a modern LangChain agent for final formatting and summary generation
- scoring is computed client-side to preserve the original decision rules and output stability
