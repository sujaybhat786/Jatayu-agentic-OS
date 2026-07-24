import logging
from typing import Dict, Optional

from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager
from jatayu.integrations.google.drive import DriveService

logger = logging.getLogger(__name__)

DOCS_MIME = 'application/vnd.google-apps.document'


class DocsService:
    """Business logic wrapper for Google Docs API v1.
    
    Supports title-based resolution — pass a document title instead of an ID
    and it will be resolved via Drive search.
    """

    def __init__(self, account_email: str = "default"):
        self.workspace = GoogleWorkspaceManager()
        self.service, self.account_email = self.workspace.get_service('docs', 'v1', account_email)
        self._drive = DriveService(self.account_email)

    def _resolve_id(self, doc_id_or_title: str) -> Optional[str]:
        """Resolve a document ID or title to an actual document ID.
        
        If the input contains no slashes and doesn't look like a Google ID
        (44+ char alphanumeric), treat it as a title and search Drive.
        """
        # If it looks like a Google resource ID, use directly
        if len(doc_id_or_title) > 30 and '/' not in doc_id_or_title and ' ' not in doc_id_or_title:
            return doc_id_or_title
        
        # Otherwise search by title
        file = self._drive.find_file_by_name(doc_id_or_title, mime_type=DOCS_MIME)
        if file:
            return file['id']
        return None

    def create_document(self, title: str) -> Dict:
        """Create a new Google Doc."""
        try:
            doc = self.service.documents().create(body={'title': title}).execute()
            doc_id = doc['documentId']
            link = f"https://docs.google.com/document/d/{doc_id}/edit"
            return {"status": "success", "document_id": doc_id, "title": title, "link": link}
        except Exception as e:
            logger.error(f"Docs create failed: {e}")
            return {"status": "error", "message": str(e)}

    def read_document(self, doc_id_or_title: str) -> Dict:
        """Read the full text content of a Google Doc.
        
        Args:
            doc_id_or_title: Document ID or title (title will be resolved via Drive).
        """
        try:
            doc_id = self._resolve_id(doc_id_or_title)
            if not doc_id:
                return {"status": "error", "message": f"Could not find document: '{doc_id_or_title}'"}
            
            doc = self.service.documents().get(documentId=doc_id).execute()
            title = doc.get('title', '')
            
            # Extract text from the document body
            text = self._extract_text(doc.get('body', {}).get('content', []))
            
            return {
                "status": "success",
                "title": title,
                "document_id": doc_id,
                "text": text,
                "link": f"https://docs.google.com/document/d/{doc_id}/edit"
            }
        except Exception as e:
            logger.error(f"Docs read failed: {e}")
            return {"status": "error", "message": str(e)}

    def append_text(self, doc_id_or_title: str, text: str) -> Dict:
        """Append text to the end of a Google Doc.
        
        Args:
            doc_id_or_title: Document ID or title.
            text: Text to append (will be preceded by a newline).
        """
        try:
            doc_id = self._resolve_id(doc_id_or_title)
            if not doc_id:
                return {"status": "error", "message": f"Could not find document: '{doc_id_or_title}'"}
            
            # Get current document to find the end index
            doc = self.service.documents().get(documentId=doc_id).execute()
            end_index = doc['body']['content'][-1]['endIndex'] - 1
            
            requests = [{
                'insertText': {
                    'location': {'index': end_index},
                    'text': '\n' + text
                }
            }]
            
            self.service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
            
            return {"status": "success", "message": f"Text appended to document.", "document_id": doc_id}
        except Exception as e:
            logger.error(f"Docs append failed: {e}")
            return {"status": "error", "message": str(e)}

    def replace_text(self, doc_id_or_title: str, find: str, replace: str) -> Dict:
        """Find and replace text in a Google Doc.
        
        Args:
            doc_id_or_title: Document ID or title.
            find: Text to find.
            replace: Replacement text.
        """
        try:
            doc_id = self._resolve_id(doc_id_or_title)
            if not doc_id:
                return {"status": "error", "message": f"Could not find document: '{doc_id_or_title}'"}
            
            requests = [{
                'replaceAllText': {
                    'containsText': {'text': find, 'matchCase': True},
                    'replaceText': replace
                }
            }]
            
            result = self.service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
            
            count = result.get('replies', [{}])[0].get('replaceAllText', {}).get('occurrencesChanged', 0)
            return {"status": "success", "message": f"Replaced {count} occurrence(s).", "document_id": doc_id}
        except Exception as e:
            logger.error(f"Docs replace failed: {e}")
            return {"status": "error", "message": str(e)}

    def rename_document(self, doc_id_or_title: str, new_title: str) -> Dict:
        """Rename a Google Doc (via Drive API)."""
        try:
            doc_id = self._resolve_id(doc_id_or_title)
            if not doc_id:
                return {"status": "error", "message": f"Could not find document: '{doc_id_or_title}'"}
            return self._drive.rename_file(doc_id, new_title)
        except Exception as e:
            logger.error(f"Docs rename failed: {e}")
            return {"status": "error", "message": str(e)}

    def delete_document(self, doc_id_or_title: str) -> Dict:
        """Move a Google Doc to trash (via Drive API)."""
        try:
            doc_id = self._resolve_id(doc_id_or_title)
            if not doc_id:
                return {"status": "error", "message": f"Could not find document: '{doc_id_or_title}'"}
            return self._drive.delete_file(doc_id)
        except Exception as e:
            logger.error(f"Docs delete failed: {e}")
            return {"status": "error", "message": str(e)}

    # ── Helpers ──

    def _extract_text(self, content: list) -> str:
        """Extract plain text from Docs API structural elements."""
        text_parts = []
        for element in content:
            if 'paragraph' in element:
                for pe in element['paragraph'].get('elements', []):
                    if 'textRun' in pe:
                        text_parts.append(pe['textRun'].get('content', ''))
            elif 'table' in element:
                for row in element['table'].get('tableRows', []):
                    for cell in row.get('tableCells', []):
                        text_parts.append(self._extract_text(cell.get('content', [])))
        return ''.join(text_parts)
