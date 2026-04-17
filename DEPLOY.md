# Deploy to Render

## Prerequisites
- [Render account](https://render.com) (free)
- GitHub repo (push this code to GitHub first)

## Steps

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "feat: invoice verification system"
git remote add origin https://github.com/YOUR_USERNAME/Automated-Invoice-Verification.git
git push -u origin main
```

### 2. Deploy on Render
1. Go to [render.com](https://render.com) → Login
2. Click **"New Blueprint"**
3. Connect your GitHub repo
4. Upload `render.yaml` or select the repo directly
5. Add environment variables:
   - `TYHOON_API_KEY` = your Typhoon API key
   - `LINE_CHANNEL_ACCESS_TOKEN` = your LINE channel token
   - `LINE_GROUP_ID` = C68080abc2a2d63f1ae8a797c961cfd51
6. Click **"Create Blueprint"**

### 3. Configure LINE Webhook
1. After deploy, get your URL: `https://invoice-webhook.onrender.com`
2. Go to [LINE Developers Console](https://developers.line.me/)
3. Select your channel → Webhook settings
4. Set webhook URL: `https://invoice-webhook.onrender.com/webhook`
5. Click **"Verify"**

## Notes

- Free tier: 750 hours/month (enough for dev)
- Sleeps after 15 min inactivity (cold start ~30s)
- For production: upgrade to paid tier or use Railway

## Railway Deployment

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Initialize (in project dir)
cd /home/com-way/hermes-agent/Automated-Invoice-Verification
railway init
# Select: Yes to create new project
# Select: Python app

# 4. Set environment variables
railway env set TYHOON_API_KEY=sk-pthdPtLlSjoB9nncrDh8kAjAVowQWU3bYLY09UjBgg7dXeAd
railway env set LINE_CHANNEL_ACCESS_TOKEN=YOUR_LINE_TOKEN
railway env set LINE_GROUP_ID=C68080abc2a2d63f1ae8a797c961cfd51

# 5. Deploy
railway up

# 6. Get URL
railway domain
```

### Or via UI:
1. Go to [railway.app](https://railway.app) → Login with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select `Automated-Invoice-Verification`
4. Add env vars in Variables tab
5. Deploy

## Configure LINE Webhook

After Railway deploy, get your domain:
```bash
railway domain
```

Set webhook URL in LINE Developers Console:
```
https://YOUR-RAILWAY-DOMAIN/webhook
```

## Notes

- Free tier: $5/month credit (enough for dev/staging)
- Sleeps after 1 hour inactivity
- Prorated billing

