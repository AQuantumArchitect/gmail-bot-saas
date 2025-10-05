# Gmail Bot SaaS - Railway Deployment Guide

## 🚀 Ready to Deploy!

Your app_v2 is clean and functional. Here's how to get it online:

### 1. Push to Git

```bash
git add .
git commit -m "Ready for deployment: Fixed nixpacks.toml and cleaned environment"
git push origin main
```

### 2. Railway Environment Variables

In Railway dashboard, set these environment variables from `railway-env-production.txt`:

**Core (Required):**
- `ENVIRONMENT=production`
- `DEBUG_MODE=false`
- `WEBAPP_URL=https://your-app.railway.app`

**Supabase (Required):**
- `SUPABASE_URL=https://cppgpznezalpsxivrcva.supabase.co`
- `SUPABASE_KEY=[your-anon-key]`
- `SUPABASE_SERVICE_KEY=[your-service-key]`
- `SUPABASE_JWT_SECRET=[your-jwt-secret]`

**Google OAuth (Required):**
- `GOOGLE_CLIENT_ID=[your-client-id]`
- `GOOGLE_CLIENT_SECRET=[your-client-secret]`
- `REDIRECT_URI=https://your-app.railway.app/auth/gmail/callback`

**AI & Security:**
- `ANTHROPIC_API_KEY=[your-key]`
- `STATE_SECRET_KEY=[generate-new]`
- `VAULT_PASSPHRASE=[your-passphrase]`

### 3. Railway Configuration

✅ `nixpacks.toml` - Fixed to use `main_v2:app`
✅ `requirements.txt` - All dependencies listed
✅ Build will run tests automatically

### 4. Domain Setup

1. Railway will provide: `https://your-app.railway.app`
2. Update `WEBAPP_URL` and `REDIRECT_URI` with actual domain
3. Update Google OAuth redirect URIs in Google Console

### 5. Supabase Setup

Your Supabase instance should have:
- Authentication enabled
- Google OAuth provider configured
- User profiles table
- RLS policies for security

### 6. Test the Deployment

After deployment, test:
- `https://your-app.railway.app/` - Root endpoint
- `https://your-app.railway.app/health` - Health check
- `https://your-app.railway.app/docs` - API docs (disabled in prod)

## Architecture Overview

```
local code → git push → Railway fetches → deploys to website
         ↓
website ←→ Supabase ←→ Google Auth ←→ Vault ←→ User Services
```

✅ This pathway is implemented and ready to work!

## Next Steps After Deployment

1. Test authentication flow
2. Enable Stripe if needed (`ENABLE_STRIPE=true`)
3. Set up custom domain
4. Configure monitoring/logs
5. Set up Gmail webhook processing

Your app_v2 architecture is clean and deployment-ready! 🎉