# Set Up Personal Access Token for Autonomous Git Operations

## Create Personal Access Token

1. Go to: https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Name it: `gmail-bot-deployment`
4. Select these permissions:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `workflow` (Update GitHub Action workflows)
5. Set expiration: 90 days (or longer)
6. Click "Generate token"
7. **COPY THE TOKEN** (you won't see it again)

## Configure Git to Use Token

Once you have the token, I'll run:

```bash
git config --global credential.helper store
echo "https://YOUR_USERNAME:YOUR_TOKEN@github.com" > ~/.git-credentials
```

## Test Autonomous Push

Then I can autonomously:
- Push code changes
- Create branches
- Make commits
- Deploy to Railway

**Just get the token and come back with it!**