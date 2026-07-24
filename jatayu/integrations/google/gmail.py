import base64
from email.message import EmailMessage
import logging
from typing import List, Dict

from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager

logger = logging.getLogger(__name__)

class GmailService:
    """Business logic wrapper for Gmail API."""

    def __init__(self, account_email: str = "default"):
        self.workspace = GoogleWorkspaceManager()
        self.service, self.account_email = self.workspace.get_service('gmail', 'v1', account_email)

    def get_unread_emails(self, max_results: int = 10) -> List[Dict]:
        """Fetch unread emails from the inbox."""
        return self.search_emails("is:unread in:inbox", max_results)

    def search_emails(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search for emails matching a query."""
        try:
            results = self.service.users().messages().list(
                userId='me', q=query, maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            parsed_messages = []
            
            for msg in messages:
                parsed = self.read_email(msg['id'])
                if parsed:
                    parsed_messages.append(parsed)
                    
            return parsed_messages
        except Exception as e:
            logger.error(f"Failed to search emails: {e}")
            return []

    def read_email(self, message_id: str) -> Dict:
        """Fetch and parse a specific email."""
        try:
            msg = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}
            
            # Extract plain text body
            body = self._extract_text_body(msg['payload'])
            
            return {
                "id": message_id,
                "threadId": msg['threadId'],
                "subject": headers.get("Subject", "(No Subject)"),
                "from": headers.get("From", "Unknown"),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "body": body,
                "snippet": msg.get("snippet", "")
            }
        except Exception as e:
            logger.error(f"Failed to read email {message_id}: {e}")
            return None

    def _extract_text_body(self, payload: dict) -> str:
        """Recursively extract plain text body from the payload."""
        if payload.get("mimeType") == "text/plain":
            if "data" in payload.get("body", {}):
                return base64.urlsafe_b64decode(payload["body"]["data"]).decode('utf-8')
        
        if "parts" in payload:
            for part in payload["parts"]:
                text = self._extract_text_body(part)
                if text:
                    return text
                    
        return ""

    def create_draft(self, to: str, subject: str, body: str) -> Dict:
        """Create an email draft."""
        try:
            message = EmailMessage()
            message.set_content(body) # Uses plain text for V1
            message['To'] = to
            message['From'] = self.account_email
            message['Subject'] = subject

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'message': {'raw': encoded_message}}
            
            draft = self.service.users().drafts().create(
                userId='me', body=create_message
            ).execute()
            
            return {"status": "success", "draft_id": draft['id']}
        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return {"status": "error", "message": str(e)}

    def send_email(self, to: str, subject: str, body: str) -> Dict:
        """Send an email immediately."""
        try:
            message = EmailMessage()
            message.set_content(body) # Uses plain text for V1
            message['To'] = to
            message['From'] = self.account_email
            message['Subject'] = subject

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            send_message = {'raw': encoded_message}
            
            sent = self.service.users().messages().send(
                userId='me', body=send_message
            ).execute()
            
            return {"status": "success", "message_id": sent['id']}
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return {"status": "error", "message": str(e)}
