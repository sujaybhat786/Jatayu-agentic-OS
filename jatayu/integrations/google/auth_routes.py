import logging
import os
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from jatayu.integrations.google.account_manager import GoogleAccountManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/google", tags=["google"])
manager = GoogleAccountManager()

# Allow HTTP transport for local development OAuth flow
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# This should match the redirect URI added in Google Cloud Console
# It will run on the FastAPI server port 8000
REDIRECT_URI = "http://localhost:8000/api/integrations/google/callback"

# Store flows in memory for local single-user app to persist PKCE code_verifier
oauth_flows = {}

@router.get("/auth")
async def google_auth():
    """Start the OAuth flow by redirecting the user to Google."""
    try:
        flow = manager.get_flow(redirect_uri=REDIRECT_URI)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Force consent to ensure we get a refresh token
        )
        oauth_flows[state] = flow
        return RedirectResponse(url=authorization_url)
    except Exception as e:
        logger.error(f"Failed to generate auth url: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def google_auth_callback(request: Request):
    """Handle the OAuth callback from Google."""
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    
    if error:
        return {"error": f"Google OAuth error: {error}"}
        
    if not code:
        return {"error": "No authorization code provided by Google."}
        
    try:
        flow = oauth_flows.get(state)
        if not flow:
            return {"error": "OAuth session expired or invalid state. Please try connecting again."}
            
        # Fetch the token
        # request.url contains the full URL with query params
        flow.fetch_token(authorization_response=str(request.url))
        creds = flow.credentials
        
        # Clean up memory
        del oauth_flows[state]
        
        # Get user profile info using the access token
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"}
            )
            profile = resp.json()
            
        email = profile.get("email")
        if not email:
            raise ValueError("Could not retrieve email from Google profile.")
            
        # Save credentials
        manager.save_credentials(email, creds, profile)
        
        # Redirect back to the integrations UI
        return RedirectResponse(url="/#integrations")
        
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return {"error": f"Failed to complete authentication: {str(e)}"}

@router.get("/accounts")
async def get_accounts():
    """List all connected Google accounts."""
    try:
        accounts = manager.list_accounts()
        return {"accounts": accounts}
    except Exception as e:
        logger.error(f"Failed to list accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accounts/{email}/default")
async def set_default_account(email: str):
    """Set the specified account as the default."""
    success = manager.set_default(email)
    if success:
        return {"status": "success", "default": email}
    raise HTTPException(status_code=404, detail="Account not found.")

@router.delete("/accounts/{email}")
async def remove_account(email: str):
    """Disconnect and remove a Google account."""
    success = manager.remove_account(email)
    if success:
        return {"status": "success", "message": f"Account {email} disconnected."}
    raise HTTPException(status_code=404, detail="Account not found.")

@router.put("/accounts/{email}/alias")
async def update_alias(email: str, request: Request):
    """Update the user-facing alias for an account."""
    body = await request.json()
    alias = body.get("alias", "").strip()
    if not alias:
        raise HTTPException(status_code=400, detail="Alias cannot be empty.")
    success = manager.update_alias(email, alias)
    if success:
        return {"status": "success", "alias": alias}
    raise HTTPException(status_code=404, detail="Account not found.")
