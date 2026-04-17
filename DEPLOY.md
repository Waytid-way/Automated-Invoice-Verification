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

## Alternative: Railway

```bash
npm install -g @railway/cli
railway login
railway init
railway add
railway env set TYHOON_API_KEY=sk-xxx
railway env set LINE_CHANNEL_ACCESS_TOKEN=xxx
railway env set LINE_GROUP_ID=C68080abc2a2d63f1ae8a797c961cfd51
railway up
```
