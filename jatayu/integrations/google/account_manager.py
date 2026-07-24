import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow

from jatayu.config import get_config

logger = logging.getLogger(__name__)

class GoogleAccountManager:
    """Manages multi-account Google OAuth tokens and credentials."""

    def __init__(self):
        config = get_config()
        self.data_dir = Path(config["data_dir"])
        self.accounts_file = self.data_dir / "google_accounts.json"
        self.credentials_file = Path(config["project_root"]) / "credentials.json"
        
        # All Google Workspace scopes
        self.scopes = [
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile',
            'https://www.googleapis.com/auth/gmail.modify',
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/documents',
            'https://www.googleapis.com/auth/spreadsheets',
        ]

        # Scope → capability mapping for detecting missing scopes
        self.SCOPE_CAPABILITIES = {
            'https://www.googleapis.com/auth/gmail.modify': 'gmail',
            'https://www.googleapis.com/auth/calendar': 'calendar',
            'https://www.googleapis.com/auth/drive': 'drive',
            'https://www.googleapis.com/auth/documents': 'docs',
            'https://www.googleapis.com/auth/spreadsheets': 'sheets',
        }

        if not self.accounts_file.exists():
            with open(self.accounts_file, "w") as f:
                json.dump({"accounts": {}, "default": None}, f)

    def _load(self) -> dict:
        try:
            with open(self.accounts_file, "r") as f:
                data = json.load(f)
                if "accounts" not in data:
                    data = {"accounts": data, "default": None}
                # Backwards-compat migration: add alias, connected_date, last_used, capability flags
                for email, acct in data["accounts"].items():
                    if "alias" not in acct:
                        acct["alias"] = acct.get("name", email.split("@")[0])
                    if "connected_date" not in acct:
                        acct["connected_date"] = None
                    if "last_used" not in acct:
                        acct["last_used"] = None
                    # Migrate old list-based services to capability flags
                    if isinstance(acct.get("services"), list):
                        old_list = acct["services"]
                        acct["services"] = {
                            "gmail": "Gmail" in old_list,
                            "calendar": "Calendar" in old_list,
                            "drive": "Drive" in old_list,
                            "docs": "Docs" in old_list,
                            "sheets": "Sheets" in old_list,
                        }
                    elif not isinstance(acct.get("services"), dict):
                        acct["services"] = {"gmail": True, "calendar": True, "drive": False, "docs": False, "sheets": False}
                return data
        except Exception as e:
            logger.error(f"Failed to load google accounts: {e}")
            return {"accounts": {}, "default": None}

    def _save(self, data: dict):
        with open(self.accounts_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_flow(self, redirect_uri: str) -> Flow:
        """Create an OAuth flow for generating authorization URLs."""
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                "credentials.json not found in project root. "
                "Please download it from Google Cloud Console."
            )
            
        flow = Flow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=self.scopes,
            redirect_uri=redirect_uri
        )
        return flow

    def save_credentials(self, email: str, credentials: Credentials, profile: dict):
        """Save a new Google account's credentials."""
        data = self._load()
        
        # Determine if this should be the default
        is_first_account = len(data["accounts"]) == 0
        
        # Preserve existing alias if account already exists
        existing = data["accounts"].get(email, {})
        alias = existing.get("alias", profile.get("name", email.split("@")[0]))
        connected_date = existing.get("connected_date", datetime.now().isoformat(timespec="seconds"))
        
        # Detect granted capabilities from the credential scopes
        granted_scopes = set(credentials.scopes or [])
        services = {}
        for scope_url, capability in self.SCOPE_CAPABILITIES.items():
            services[capability] = scope_url in granted_scopes
        
        data["accounts"][email] = {
            "email": email,
            "name": profile.get("name", email),
            "picture": profile.get("picture", ""),
            "alias": alias,
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": list(credentials.scopes) if credentials.scopes else list(self.scopes),
            "services": services,
            "connected_date": connected_date,
            "last_used": existing.get("last_used"),
        }
        
        if is_first_account or data["default"] is None:
            data["default"] = email
            
        self._save(data)
        logger.info(f"Saved Google credentials for {email}")

    def get_credentials(self, email: Optional[str] = None) -> Optional[Credentials]:
        """Retrieve valid credentials for an email, refreshing if necessary."""
        data = self._load()
        
        if not email:
            email = data.get("default")
            
        if not email or email not in data["accounts"]:
            return None
            
        acct = data["accounts"][email]
        
        creds = Credentials(
            token=acct.get("token"),
            refresh_token=acct.get("refresh_token"),
            token_uri=acct.get("token_uri"),
            client_id=acct.get("client_id"),
            client_secret=acct.get("client_secret"),
            scopes=acct.get("scopes", self.scopes)
        )
        
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save the new access token
                self.save_credentials(email, creds, {"name": acct["name"], "picture": acct["picture"]})
            except Exception as e:
                logger.error(f"Failed to refresh token for {email}: {e}")
                return None
        
        # Touch last_used timestamp
        self.touch_last_used(email)
                
        return creds

    def list_accounts(self) -> list[dict]:
        """Return a list of all connected accounts for the UI."""
        data = self._load()
        default = data.get("default")
        
        accounts = []
        for email, acct in data["accounts"].items():
            services = acct.get("services", {})
            # Detect if account needs re-auth for new scopes
            granted_scopes = set(acct.get("scopes", []))
            needs_reauth = not all(
                scope in granted_scopes
                for scope in self.SCOPE_CAPABILITIES.keys()
            )
            
            accounts.append({
                "email": email,
                "name": acct.get("name", email),
                "alias": acct.get("alias", acct.get("name", "")),
                "picture": acct.get("picture", ""),
                "services": services,
                "is_default": email == default,
                "status": "Needs Reauth" if needs_reauth else ("Connected" if acct.get("refresh_token") else "Needs Auth"),
                "connected_date": acct.get("connected_date"),
                "last_used": acct.get("last_used"),
            })
            
        return sorted(accounts, key=lambda x: (not x["is_default"], x["email"]))

    def set_default(self, email: str) -> bool:
        """Change the default account."""
        data = self._load()
        if email in data["accounts"]:
            data["default"] = email
            self._save(data)
            return True
        return False

    def remove_account(self, email: str) -> bool:
        """Remove a connected Google account and reassign default if needed."""
        data = self._load()
        if email not in data["accounts"]:
            return False
        
        del data["accounts"][email]
        
        # Smart default reassignment
        if data["default"] == email:
            remaining = list(data["accounts"].keys())
            if len(remaining) == 1:
                # Only one account left → auto-default
                data["default"] = remaining[0]
            elif len(remaining) > 1:
                # Multiple remain → pick the first alphabetically
                data["default"] = sorted(remaining)[0]
            else:
                # No accounts remain
                data["default"] = None
        
        self._save(data)
        logger.info(f"Removed Google account: {email}")
        return True

    def update_alias(self, email: str, alias: str) -> bool:
        """Update the user-facing alias for an account."""
        data = self._load()
        if email not in data["accounts"]:
            return False
        data["accounts"][email]["alias"] = alias.strip()
        self._save(data)
        return True

    def touch_last_used(self, email: str):
        """Update the last_used timestamp for an account."""
        data = self._load()
        if email in data["accounts"]:
            data["accounts"][email]["last_used"] = datetime.now().isoformat(timespec="seconds")
            self._save(data)

    def find_account(self, query: str) -> dict:
        """Find account(s) matching a query string.
        
        Priority: alias → display name → email prefix.
        
        Returns:
            {
                "match": "exact" | "multiple" | "none",
                "email": str | None,           # set when match == "exact"
                "candidates": list[dict] | []   # set when match == "multiple"
            }
        """
        if not query:
            return {"match": "none", "email": None, "candidates": []}
        
        data = self._load()
        query_lower = query.strip().lower()
        
        # If it's already an email address, use it directly
        if "@" in query:
            if query in data["accounts"]:
                return {"match": "exact", "email": query, "candidates": []}
            return {"match": "none", "email": None, "candidates": []}
        
        candidates = []
        
        for email, acct in data["accounts"].items():
            alias = acct.get("alias", "").lower()
            name = acct.get("name", "").lower()
            email_prefix = email.split("@")[0].lower()
            
            # Exact alias match → immediate return
            if alias == query_lower:
                return {"match": "exact", "email": email, "candidates": []}
            
            # Exact name match → immediate return
            if name == query_lower:
                return {"match": "exact", "email": email, "candidates": []}
            
            # Substring match (alias, name, or email prefix)
            if (query_lower in alias or 
                query_lower in name or 
                query_lower in email_prefix):
                candidates.append({
                    "email": email,
                    "alias": acct.get("alias", ""),
                    "name": acct.get("name", ""),
                })
        
        if len(candidates) == 1:
            return {"match": "exact", "email": candidates[0]["email"], "candidates": []}
        elif len(candidates) > 1:
            return {"match": "multiple", "email": None, "candidates": candidates}
        
        return {"match": "none", "email": None, "candidates": []}
