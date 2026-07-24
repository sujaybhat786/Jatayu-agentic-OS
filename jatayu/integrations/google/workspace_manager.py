import logging
from typing import Optional

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from jatayu.integrations.google.account_manager import GoogleAccountManager

logger = logging.getLogger(__name__)

class GoogleWorkspaceManager:
    """Centralized routing layer for Google Workspace services.
    
    All Google integrations (Gmail, Calendar, Drive, Docs, Sheets, etc.)
    communicate through this manager. It handles:
    - Account resolution (alias, name, email, or "default")
    - Credential retrieval and refresh
    - Service client creation for any Google API
    - Last-used tracking
    
    Future Google services plug into get_service() without redesign.
    """
    
    def __init__(self):
        self.account_manager = GoogleAccountManager()

    def resolve_account(self, account_query: str = "default") -> dict:
        """Resolve an account query to an email address.
        
        Supports: "default", exact email, alias, display name, or partial match.
        
        Returns:
            {
                "resolved": True/False,
                "email": str | None,
                "error": str | None,
                "candidates": list | []   # populated when ambiguous
            }
        """
        if not account_query or account_query.lower() == "default":
            data = self.account_manager._load()
            default = data.get("default")
            if default:
                return {"resolved": True, "email": default, "error": None, "candidates": []}
            return {"resolved": False, "email": None, "error": "No default Google account set. Please connect an account first.", "candidates": []}
        
        # Try direct email match first
        if "@" in account_query:
            data = self.account_manager._load()
            if account_query in data["accounts"]:
                return {"resolved": True, "email": account_query, "error": None, "candidates": []}
            return {"resolved": False, "email": None, "error": f"No Google account found with email '{account_query}'.", "candidates": []}
        
        # Use the confidence-based name/alias matching
        result = self.account_manager.find_account(account_query)
        
        if result["match"] == "exact":
            return {"resolved": True, "email": result["email"], "error": None, "candidates": []}
        elif result["match"] == "multiple":
            names = [f"• {c['alias']} ({c['email']})" for c in result["candidates"]]
            return {
                "resolved": False,
                "email": None,
                "error": f"I found multiple matching accounts:\n" + "\n".join(names) + "\nWhich account would you like to use?",
                "candidates": result["candidates"]
            }
        else:
            return {"resolved": False, "email": None, "error": f"No Google account matching '{account_query}'. Use google_list_accounts to see connected accounts.", "candidates": []}

    def get_service(self, service_name: str, version: str, account_email: str = "default"):
        """Get an authenticated Google API service client.
        
        This is the single entry point for ALL Google services.
        Future integrations (Drive, Docs, Sheets, Meet, etc.) call this
        same method — no redesign needed.
        
        Args:
            service_name: Google API service (e.g. 'gmail', 'calendar', 'drive', 'docs')
            version: API version (e.g. 'v1', 'v3')
            account_email: Account identifier — email, alias, name, or "default"
        """
        resolution = self.resolve_account(account_email)
        
        if not resolution["resolved"]:
            raise ValueError(resolution["error"])
        
        email = resolution["email"]
        creds = self.account_manager.get_credentials(email)
        if not creds:
            raise ValueError(f"No valid credentials found for account '{email}'. Please re-authenticate.")
            
        try:
            return build(service_name, version, credentials=creds), email
        except Exception as e:
            logger.error(f"Failed to build Google {service_name} service: {e}")
            raise
