# app/api/routes/frontend.py
"""
Frontend HTML routes for serving the beautiful UI templates.
Serves index.html and dashboard.html with proper authentication.
"""

import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import (
    get_optional_user_context,
    get_user_context,
    UserContext
)

logger = logging.getLogger(__name__)

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="templates")

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def homepage(
    request: Request,
    user_context: UserContext = Depends(get_optional_user_context)
):
    """Serve the beautiful landing page"""
    logger.info("Serving homepage")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user_context.user if user_context else None,
            "authenticated": user_context is not None
        }
    )

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user_context: UserContext = Depends(get_user_context)
):
    """Serve the beautiful dashboard - requires authentication"""
    logger.info(f"Serving dashboard for user {user_context.user.id}")

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user_context.user,
            "user_email": user_context.user.email,
            "authenticated": True
        }
    )

@router.get("/auth/login")
async def auth_login_redirect(request: Request):
    """OAuth login endpoint - redirect to Supabase auth"""
    # This will be handled by our Supabase integration
    # For now, return the OAuth URL like our current system

    # Import the working OAuth logic from our current system
    import urllib.parse

    client_id = "497990580830-hjhq4nfcud7mh1ll0d4f6l5ihlq2977a.apps.googleusercontent.com"
    # TODO: Update redirect_uri to point to this system when deployed
    redirect_uri = "https://quantum-email-website-production.up.railway.app/auth/callback"
    scopes = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/userinfo.email"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent"
    }

    oauth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    return {"oauth_url": oauth_url, "status": "ready"}

@router.get("/auth/callback")
async def auth_callback(code: str = None, error: str = None):
    """Handle OAuth callback and redirect to dashboard"""
    if error:
        logger.error(f"OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {error}")

    if not code:
        logger.error("No authorization code received")
        raise HTTPException(status_code=400, detail="No authorization code received")

    # TODO: Integrate with Supabase auth to exchange code for tokens
    # For now, redirect to dashboard with success message
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard?auth=success", status_code=302)