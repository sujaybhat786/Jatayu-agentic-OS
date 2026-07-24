import logging
from typing import Dict, List, Optional

from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager
from jatayu.integrations.google.drive import DriveService

logger = logging.getLogger(__name__)

SHEETS_MIME = 'application/vnd.google-apps.spreadsheet'


class SheetsService:
    """Business logic wrapper for Google Sheets API v4.
    
    Supports title-based resolution — pass a spreadsheet title instead of an ID
    and it will be resolved via Drive search.
    """

    def __init__(self, account_email: str = "default"):
        self.workspace = GoogleWorkspaceManager()
        self.service, self.account_email = self.workspace.get_service('sheets', 'v4', account_email)
        self._drive = DriveService(self.account_email)

    def _resolve_id(self, spreadsheet_id_or_title: str) -> Optional[str]:
        """Resolve a spreadsheet ID or title to an actual spreadsheet ID."""
        if len(spreadsheet_id_or_title) > 30 and '/' not in spreadsheet_id_or_title and ' ' not in spreadsheet_id_or_title:
            return spreadsheet_id_or_title
        
        file = self._drive.find_file_by_name(spreadsheet_id_or_title, mime_type=SHEETS_MIME)
        if file:
            return file['id']
        return None

    def create_spreadsheet(self, title: str) -> Dict:
        """Create a new Google Spreadsheet."""
        try:
            spreadsheet = self.service.spreadsheets().create(
                body={'properties': {'title': title}},
                fields='spreadsheetId,properties,spreadsheetUrl'
            ).execute()
            
            return {
                "status": "success",
                "spreadsheet_id": spreadsheet['spreadsheetId'],
                "title": spreadsheet['properties']['title'],
                "link": spreadsheet['spreadsheetUrl']
            }
        except Exception as e:
            logger.error(f"Sheets create failed: {e}")
            return {"status": "error", "message": str(e)}

    def read_spreadsheet(self, spreadsheet_id_or_title: str, range: str = "Sheet1") -> Dict:
        """Read data from a Google Spreadsheet.
        
        Args:
            spreadsheet_id_or_title: Spreadsheet ID or title.
            range: A1 notation range (e.g. 'Sheet1', 'Sheet1!A1:D10', 'A1:C5').
                   Defaults to 'Sheet1' (entire first sheet).
        """
        try:
            sid = self._resolve_id(spreadsheet_id_or_title)
            if not sid:
                return {"status": "error", "message": f"Could not find spreadsheet: '{spreadsheet_id_or_title}'"}
            
            result = self.service.spreadsheets().values().get(
                spreadsheetId=sid, range=range
            ).execute()
            
            values = result.get('values', [])
            
            # Get spreadsheet metadata for title
            meta = self.service.spreadsheets().get(
                spreadsheetId=sid, fields='properties.title,spreadsheetUrl'
            ).execute()
            
            return {
                "status": "success",
                "title": meta['properties']['title'],
                "spreadsheet_id": sid,
                "range": result.get('range', range),
                "rows": len(values),
                "data": values,
                "link": meta['spreadsheetUrl']
            }
        except Exception as e:
            logger.error(f"Sheets read failed: {e}")
            return {"status": "error", "message": str(e)}

    def update_cells(self, spreadsheet_id_or_title: str, range: str, values: List[List]) -> Dict:
        """Write data to a specific range in a spreadsheet.
        
        Args:
            spreadsheet_id_or_title: Spreadsheet ID or title.
            range: A1 notation range (e.g. 'Sheet1!A1:C3').
            values: 2D list of values — [[row1col1, row1col2], [row2col1, row2col2]].
        """
        try:
            sid = self._resolve_id(spreadsheet_id_or_title)
            if not sid:
                return {"status": "error", "message": f"Could not find spreadsheet: '{spreadsheet_id_or_title}'"}
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=sid,
                range=range,
                valueInputOption='USER_ENTERED',
                body={'values': values}
            ).execute()
            
            return {
                "status": "success",
                "updated_cells": result.get('updatedCells', 0),
                "updated_range": result.get('updatedRange', ''),
                "spreadsheet_id": sid
            }
        except Exception as e:
            logger.error(f"Sheets update failed: {e}")
            return {"status": "error", "message": str(e)}

    def append_rows(self, spreadsheet_id_or_title: str, range: str, rows: List[List]) -> Dict:
        """Append rows to the bottom of a spreadsheet range.
        
        Args:
            spreadsheet_id_or_title: Spreadsheet ID or title.
            range: A1 notation (e.g. 'Sheet1' or 'Sheet1!A:E'). Rows are appended
                   after the last row with data in this range.
            rows: 2D list of row data — [[col1, col2], [col1, col2]].
        """
        try:
            sid = self._resolve_id(spreadsheet_id_or_title)
            if not sid:
                return {"status": "error", "message": f"Could not find spreadsheet: '{spreadsheet_id_or_title}'"}
            
            result = self.service.spreadsheets().values().append(
                spreadsheetId=sid,
                range=range,
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body={'values': rows}
            ).execute()
            
            updates = result.get('updates', {})
            return {
                "status": "success",
                "updated_rows": updates.get('updatedRows', 0),
                "updated_range": updates.get('updatedRange', ''),
                "spreadsheet_id": sid
            }
        except Exception as e:
            logger.error(f"Sheets append failed: {e}")
            return {"status": "error", "message": str(e)}

    def delete_rows(self, spreadsheet_id_or_title: str, sheet_id: int, start_row: int, end_row: int) -> Dict:
        """Delete a range of rows from a sheet.
        
        Args:
            spreadsheet_id_or_title: Spreadsheet ID or title.
            sheet_id: The sheet's numeric ID (0 for the first sheet).
            start_row: Start row index (0-based, inclusive).
            end_row: End row index (0-based, exclusive).
        """
        try:
            sid = self._resolve_id(spreadsheet_id_or_title)
            if not sid:
                return {"status": "error", "message": f"Could not find spreadsheet: '{spreadsheet_id_or_title}'"}
            
            requests = [{
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': start_row,
                        'endIndex': end_row
                    }
                }
            }]
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=sid, body={'requests': requests}
            ).execute()
            
            return {
                "status": "success",
                "message": f"Deleted rows {start_row + 1} to {end_row}.",
                "spreadsheet_id": sid
            }
        except Exception as e:
            logger.error(f"Sheets delete rows failed: {e}")
            return {"status": "error", "message": str(e)}

    def rename_spreadsheet(self, spreadsheet_id_or_title: str, new_title: str) -> Dict:
        """Rename a spreadsheet (via Drive API)."""
        try:
            sid = self._resolve_id(spreadsheet_id_or_title)
            if not sid:
                return {"status": "error", "message": f"Could not find spreadsheet: '{spreadsheet_id_or_title}'"}
            return self._drive.rename_file(sid, new_title)
        except Exception as e:
            logger.error(f"Sheets rename failed: {e}")
            return {"status": "error", "message": str(e)}
