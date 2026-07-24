import logging
import os
from typing import List, Dict, Optional
from io import BytesIO

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager

logger = logging.getLogger(__name__)


class DriveService:
    """Business logic wrapper for Google Drive API v3."""

    def __init__(self, account_email: str = "default"):
        self.workspace = GoogleWorkspaceManager()
        self.service, self.account_email = self.workspace.get_service('drive', 'v3', account_email)

    # ── Search & List ──────────────────────────────────

    def search_files(self, query: str, file_type: Optional[str] = None, max_results: int = 10) -> List[Dict]:
        """Search Drive files by name, keyword, or type.
        
        Args:
            query: Search text (matched against file name and content).
            file_type: Optional filter — 'document', 'spreadsheet', 'presentation',
                       'pdf', 'image', 'folder', or a MIME type.
            max_results: Maximum results to return.
        """
        try:
            q_parts = [f"name contains '{query}' or fullText contains '{query}'"]
            q_parts.append("trashed = false")
            
            type_map = {
                'document': "mimeType = 'application/vnd.google-apps.document'",
                'doc': "mimeType = 'application/vnd.google-apps.document'",
                'spreadsheet': "mimeType = 'application/vnd.google-apps.spreadsheet'",
                'sheet': "mimeType = 'application/vnd.google-apps.spreadsheet'",
                'presentation': "mimeType = 'application/vnd.google-apps.presentation'",
                'slides': "mimeType = 'application/vnd.google-apps.presentation'",
                'pdf': "mimeType = 'application/pdf'",
                'image': "mimeType contains 'image/'",
                'folder': "mimeType = 'application/vnd.google-apps.folder'",
            }
            if file_type and file_type.lower() in type_map:
                q_parts.append(type_map[file_type.lower()])
            
            results = self.service.files().list(
                q=" and ".join(q_parts),
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink, owners)",
                orderBy="modifiedTime desc"
            ).execute()
            
            return self._format_files(results.get('files', []))
        except Exception as e:
            logger.error(f"Drive search failed: {e}")
            return []

    def list_recent(self, max_results: int = 10) -> List[Dict]:
        """List recently modified files."""
        try:
            results = self.service.files().list(
                q="trashed = false",
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink, owners)",
                orderBy="modifiedTime desc"
            ).execute()
            return self._format_files(results.get('files', []))
        except Exception as e:
            logger.error(f"Drive list recent failed: {e}")
            return []

    def list_shared(self, max_results: int = 10) -> List[Dict]:
        """List files shared with the user."""
        try:
            results = self.service.files().list(
                q="sharedWithMe = true and trashed = false",
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink, owners)",
                orderBy="modifiedTime desc"
            ).execute()
            return self._format_files(results.get('files', []))
        except Exception as e:
            logger.error(f"Drive list shared failed: {e}")
            return []

    def find_file_by_name(self, name: str, mime_type: Optional[str] = None) -> Optional[Dict]:
        """Find a single file by exact or close name match.
        
        Used internally by Docs/Sheets to resolve titles → IDs.
        Returns the most recently modified match, or None.
        """
        try:
            q_parts = [f"name contains '{name}'", "trashed = false"]
            if mime_type:
                q_parts.append(f"mimeType = '{mime_type}'")
            
            results = self.service.files().list(
                q=" and ".join(q_parts),
                pageSize=5,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                orderBy="modifiedTime desc"
            ).execute()
            
            files = results.get('files', [])
            if not files:
                return None
            
            # Prefer exact name match
            for f in files:
                if f['name'].lower() == name.lower():
                    return f
            
            # Fall back to first (most recent) result
            return files[0]
        except Exception as e:
            logger.error(f"Drive find_file_by_name failed: {e}")
            return None

    # ── File Operations ────────────────────────────────

    def upload_file(self, file_path: str, folder_id: Optional[str] = None) -> Dict:
        """Upload a local file to Google Drive."""
        try:
            if not os.path.exists(file_path):
                return {"status": "error", "message": f"File not found: {file_path}"}
            
            file_name = os.path.basename(file_path)
            file_metadata = {'name': file_name}
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            media = MediaFileUpload(file_path, resumable=True)
            file = self.service.files().create(
                body=file_metadata, media_body=media, fields='id, name, webViewLink'
            ).execute()
            
            return {
                "status": "success",
                "file_id": file['id'],
                "name": file['name'],
                "link": file.get('webViewLink', '')
            }
        except Exception as e:
            logger.error(f"Drive upload failed: {e}")
            return {"status": "error", "message": str(e)}

    def download_file(self, file_id: str, destination: str) -> Dict:
        """Download a file from Google Drive to a local path."""
        try:
            # Get file metadata for the name
            file_meta = self.service.files().get(fileId=file_id, fields='name, mimeType').execute()
            
            # Google Workspace files need to be exported
            mime = file_meta.get('mimeType', '')
            if mime.startswith('application/vnd.google-apps.'):
                export_map = {
                    'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
                    'application/vnd.google-apps.spreadsheet': ('text/csv', '.csv'),
                    'application/vnd.google-apps.presentation': ('application/pdf', '.pdf'),
                }
                export_mime, ext = export_map.get(mime, ('application/pdf', '.pdf'))
                request = self.service.files().export_media(fileId=file_id, mimeType=export_mime)
                dest_path = destination if destination.endswith(ext) else destination + ext
            else:
                request = self.service.files().get_media(fileId=file_id)
                dest_path = destination
            
            fh = BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            
            with open(dest_path, 'wb') as f:
                f.write(fh.getvalue())
            
            return {"status": "success", "path": dest_path, "name": file_meta['name']}
        except Exception as e:
            logger.error(f"Drive download failed: {e}")
            return {"status": "error", "message": str(e)}

    def move_file(self, file_id: str, destination_folder_id: str) -> Dict:
        """Move a file to a different folder."""
        try:
            # Get current parents
            file = self.service.files().get(fileId=file_id, fields='parents, name').execute()
            previous_parents = ",".join(file.get('parents', []))
            
            updated = self.service.files().update(
                fileId=file_id,
                addParents=destination_folder_id,
                removeParents=previous_parents,
                fields='id, name, webViewLink'
            ).execute()
            
            return {"status": "success", "name": updated['name'], "link": updated.get('webViewLink', '')}
        except Exception as e:
            logger.error(f"Drive move failed: {e}")
            return {"status": "error", "message": str(e)}

    def rename_file(self, file_id: str, new_name: str) -> Dict:
        """Rename a file."""
        try:
            updated = self.service.files().update(
                fileId=file_id, body={'name': new_name}, fields='id, name, webViewLink'
            ).execute()
            return {"status": "success", "name": updated['name'], "link": updated.get('webViewLink', '')}
        except Exception as e:
            logger.error(f"Drive rename failed: {e}")
            return {"status": "error", "message": str(e)}

    def delete_file(self, file_id: str) -> Dict:
        """Move a file to trash."""
        try:
            self.service.files().update(fileId=file_id, body={'trashed': True}).execute()
            return {"status": "success", "message": "File moved to trash."}
        except Exception as e:
            logger.error(f"Drive delete failed: {e}")
            return {"status": "error", "message": str(e)}

    def copy_file(self, file_id: str, new_name: Optional[str] = None) -> Dict:
        """Copy a file."""
        try:
            body = {}
            if new_name:
                body['name'] = new_name
            copied = self.service.files().copy(
                fileId=file_id, body=body, fields='id, name, webViewLink'
            ).execute()
            return {"status": "success", "file_id": copied['id'], "name": copied['name'], "link": copied.get('webViewLink', '')}
        except Exception as e:
            logger.error(f"Drive copy failed: {e}")
            return {"status": "error", "message": str(e)}

    def share_file(self, file_id: str, email: str, role: str = "reader") -> Dict:
        """Share a file with another user.
        
        Args:
            file_id: The file to share.
            email: Email address of the person to share with.
            role: Permission role — 'reader', 'writer', or 'commenter'.
        """
        try:
            permission = {'type': 'user', 'role': role, 'emailAddress': email}
            self.service.permissions().create(
                fileId=file_id, body=permission, sendNotificationEmail=True
            ).execute()
            return {"status": "success", "message": f"Shared with {email} as {role}."}
        except Exception as e:
            logger.error(f"Drive share failed: {e}")
            return {"status": "error", "message": str(e)}

    def get_shareable_link(self, file_id: str) -> Dict:
        """Generate a shareable link for a file."""
        try:
            # Set anyone with link can view
            permission = {'type': 'anyone', 'role': 'reader'}
            self.service.permissions().create(fileId=file_id, body=permission).execute()
            
            file = self.service.files().get(fileId=file_id, fields='webViewLink').execute()
            return {"status": "success", "link": file['webViewLink']}
        except Exception as e:
            logger.error(f"Drive get link failed: {e}")
            return {"status": "error", "message": str(e)}

    # ── Helpers ────────────────────────────────────────

    def _format_files(self, files: list) -> List[Dict]:
        """Format raw Drive API file objects for display."""
        formatted = []
        mime_labels = {
            'application/vnd.google-apps.document': 'Google Doc',
            'application/vnd.google-apps.spreadsheet': 'Google Sheet',
            'application/vnd.google-apps.presentation': 'Google Slides',
            'application/vnd.google-apps.folder': 'Folder',
            'application/pdf': 'PDF',
        }
        for f in files:
            mime = f.get('mimeType', '')
            formatted.append({
                'id': f['id'],
                'name': f['name'],
                'type': mime_labels.get(mime, mime.split('/')[-1] if '/' in mime else 'File'),
                'modified': f.get('modifiedTime', ''),
                'size': f.get('size', ''),
                'link': f.get('webViewLink', ''),
                'owner': f.get('owners', [{}])[0].get('displayName', '') if f.get('owners') else '',
            })
        return formatted
