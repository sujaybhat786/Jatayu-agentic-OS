import json
import logging
from typing import List, Optional

from jatayu.integrations.google.gmail import GmailService
from jatayu.integrations.google.calendar import CalendarService
from jatayu.integrations.google.drive import DriveService
from jatayu.integrations.google.docs import DocsService
from jatayu.integrations.google.sheets import SheetsService
from jatayu.integrations.google.account_manager import GoogleAccountManager
from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager

logger = logging.getLogger(__name__)

# Shared workspace manager — centralized account resolution
_workspace = GoogleWorkspaceManager()

# ==========================================
# Account Management Tool
# ==========================================

def google_list_accounts() -> str:
    """List all connected Google accounts.
    
    Returns account details including alias, email, services, and which is the default.
    Use this when the user asks about connected accounts or when you need to route
    a request to a specific account.
    """
    try:
        manager = GoogleAccountManager()
        accounts = manager.list_accounts()
        
        if not accounts:
            return "No Google accounts connected. The user can connect accounts from the Integrations page."
        
        result = [f"Connected Google Accounts ({len(accounts)}):"]
        for acct in accounts:
            default_marker = " ⭐ DEFAULT" if acct["is_default"] else ""
            services = acct.get("services", {})
            if isinstance(services, dict):
                active = [k.capitalize() for k, v in services.items() if v]
                svc_str = ", ".join(active) if active else "None"
            else:
                svc_str = str(services)
            
            status_note = ""
            if acct["status"] == "Needs Reauth":
                status_note = " ⚠️ Needs re-authentication for new Workspace features"
            
            result.append(
                f"• {acct['alias']} ({acct['email']}){default_marker}{status_note}\n"
                f"  Services: {svc_str}"
            )
        
        return "\n".join(result)
    except Exception as e:
        return f"Error listing accounts: {str(e)}"


def _resolve_account_or_error(account_email: str) -> str:
    """Centralized account resolution — returns resolved email or raises ValueError."""
    resolution = _workspace.resolve_account(account_email)
    if not resolution["resolved"]:
        raise ValueError(resolution["error"])
    return resolution["email"]


# ==========================================
# Gmail Tools
# ==========================================

def google_gmail_read(account_email: str = "default", query: str = "is:unread") -> str:
    """Read emails from Gmail.
    
    Args:
        account_email: Account alias, name, email, or "default".
        query: Gmail search query (e.g., 'is:unread', 'from:boss@company.com').
    """
    try:
        email = _resolve_account_or_error(account_email)
        service = GmailService(email)
        emails = service.search_emails(query, max_results=5)
        
        if not emails:
            return "No emails found matching the query."
            
        result = []
        for e in emails:
            result.append(f"ID: {e['id']}\nFrom: {e['from']}\nSubject: {e['subject']}\nDate: {e['date']}\nBody:\n{e['body']}\n---")
            
        return "\n".join(result)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error reading Gmail: {str(e)}"

def google_gmail_draft(to: str, subject: str, body: str, account_email: str = "default") -> str:
    """Draft an email in Gmail.
    
    Args:
        to: Recipient email address.
        subject: Email subject.
        body: Plain text email body.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        service = GmailService(email)
        result = service.create_draft(to, subject, body)
        if result.get("status") == "success":
            return f"Draft created successfully. Draft ID: {result['draft_id']}"
        return f"Failed to create draft: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error drafting email: {str(e)}"

def google_gmail_send(to: str, subject: str, body: str, account_email: str = "default") -> str:
    """Send an email immediately via Gmail.
    
    Args:
        to: Recipient email address.
        subject: Email subject.
        body: Plain text email body.
        account_email: Account alias, name, email, or "default" to send from.
    """
    try:
        email = _resolve_account_or_error(account_email)
        service = GmailService(email)
        result = service.send_email(to, subject, body)
        if result.get("status") == "success":
            return f"Email sent successfully. Message ID: {result['message_id']}"
        return f"Failed to send email: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error sending email: {str(e)}"

# ==========================================
# Calendar Tools
# ==========================================

def google_calendar_read(days: int = 1, account_email: str = "default") -> str:
    """Read upcoming events from Google Calendar.
    
    Args:
        days: Number of days to look ahead (default 1 for today).
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        service = CalendarService(email)
        events = service.get_upcoming_events(days=days)
        
        if not events:
            return f"No upcoming events found for the next {days} day(s)."
            
        result = [f"Upcoming events for the next {days} day(s):"]
        for e in events:
            result.append(f"- {e['summary']} | Start: {e['start']} | End: {e['end']} | Link: {e['htmlLink']}")
            
        return "\n".join(result)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error reading calendar: {str(e)}"

def google_calendar_create(summary: str, start_time: str, end_time: str, attendees: Optional[List[str]] = None, account_email: str = "default") -> str:
    """Create a new event in Google Calendar.
    
    Args:
        summary: Event title.
        start_time: ISO-8601 formatted start time (e.g., '2026-07-18T10:00:00-07:00').
        end_time: ISO-8601 formatted end time.
        attendees: Optional list of email addresses to invite.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        service = CalendarService(email)
        result = service.create_event(summary, start_time, end_time, attendees)
        if result.get("status") == "success":
            return f"Event created successfully. Link: {result['link']}"
        return f"Failed to create event: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error creating event: {str(e)}"

# ==========================================
# Drive Tools
# ==========================================

def google_drive_search(query: str, file_type: Optional[str] = None, account_email: str = "default") -> str:
    """Search for files in Google Drive by name, keyword, or type.
    
    Args:
        query: Search text (e.g. 'resume', 'Marketing', 'Q3 report').
        file_type: Optional filter — 'document', 'spreadsheet', 'presentation', 'pdf', 'image', 'folder'.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        if query.lower() in ('recent', 'recents', 'latest'):
            files = drive.list_recent(max_results=10)
        elif query.lower() in ('shared', 'shared with me'):
            files = drive.list_shared(max_results=10)
        else:
            files = drive.search_files(query, file_type=file_type, max_results=10)
        
        if not files:
            return f"No files found matching '{query}'."
        
        result = [f"Found {len(files)} file(s):"]
        for f in files:
            modified = f['modified'][:10] if f.get('modified') else ''
            result.append(f"• {f['name']} ({f['type']}) — Modified: {modified}\n  Link: {f['link']}")
        
        return "\n".join(result)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error searching Drive: {str(e)}"

def google_drive_upload(file_path: str, folder_name: Optional[str] = None, account_email: str = "default") -> str:
    """Upload a local file to Google Drive.
    
    Args:
        file_path: Absolute path to the local file to upload.
        folder_name: Optional destination folder name (will search for folder in Drive).
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        folder_id = None
        if folder_name:
            folder = drive.find_file_by_name(folder_name, mime_type='application/vnd.google-apps.folder')
            if folder:
                folder_id = folder['id']
            else:
                return f"Could not find folder '{folder_name}' in Drive."
        
        result = drive.upload_file(file_path, folder_id=folder_id)
        if result.get("status") == "success":
            return f"Uploaded '{result['name']}' to Drive.\nLink: {result['link']}"
        return f"Upload failed: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error uploading to Drive: {str(e)}"

def google_drive_download(file_name: str, destination: str = "/tmp", account_email: str = "default") -> str:
    """Download a file from Google Drive.
    
    Args:
        file_name: Name of the file to download (resolved via Drive search).
        destination: Local directory to save the file to.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        file = drive.find_file_by_name(file_name)
        if not file:
            return f"Could not find file '{file_name}' in Drive."
        
        import os
        dest_path = os.path.join(destination, file['name'])
        result = drive.download_file(file['id'], dest_path)
        
        if result.get("status") == "success":
            return f"Downloaded '{result['name']}' to {result['path']}"
        return f"Download failed: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error downloading from Drive: {str(e)}"

def google_drive_move(file_name: str, destination_folder: str, account_email: str = "default") -> str:
    """Move a file to a different folder in Google Drive.
    
    Args:
        file_name: Name of the file to move (resolved via Drive search).
        destination_folder: Name of the destination folder.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        file = drive.find_file_by_name(file_name)
        if not file:
            return f"Could not find file '{file_name}' in Drive."
        
        folder = drive.find_file_by_name(destination_folder, mime_type='application/vnd.google-apps.folder')
        if not folder:
            return f"Could not find folder '{destination_folder}' in Drive."
        
        result = drive.move_file(file['id'], folder['id'])
        if result.get("status") == "success":
            return f"Moved '{result['name']}' to '{destination_folder}'."
        return f"Move failed: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error moving file: {str(e)}"

def google_drive_share(file_name: str, share_with_email: str, role: str = "reader", account_email: str = "default") -> str:
    """Share a Google Drive file with someone or generate a shareable link.
    
    Args:
        file_name: Name of the file to share (resolved via Drive search).
        share_with_email: Email address to share with, or 'link' to generate a shareable link.
        role: Permission role — 'reader', 'writer', or 'commenter'. Defaults to 'reader'.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        file = drive.find_file_by_name(file_name)
        if not file:
            return f"Could not find file '{file_name}' in Drive."
        
        if share_with_email.lower() == 'link':
            result = drive.get_shareable_link(file['id'])
            if result.get("status") == "success":
                return f"Shareable link for '{file['name']}':\n{result['link']}"
            return f"Failed to generate link: {result.get('message')}"
        else:
            result = drive.share_file(file['id'], share_with_email, role)
            if result.get("status") == "success":
                return f"Shared '{file['name']}' with {share_with_email} as {role}."
            return f"Share failed: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error sharing file: {str(e)}"

def google_drive_delete(file_name: str, account_email: str = "default") -> str:
    """Delete (trash) a file from Google Drive.
    
    Args:
        file_name: Name of the file to delete (resolved via Drive search).
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        drive = DriveService(email)
        
        file = drive.find_file_by_name(file_name)
        if not file:
            return f"Could not find file '{file_name}' in Drive."
        
        result = drive.delete_file(file['id'])
        if result.get("status") == "success":
            return f"'{file['name']}' moved to trash."
        return f"Delete failed: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error deleting file: {str(e)}"

# ==========================================
# Google Docs Tools
# ==========================================

def google_docs_create(title: str, account_email: str = "default") -> str:
    """Create a new Google Document.
    
    Args:
        title: Document title.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        docs = DocsService(email)
        result = docs.create_document(title)
        if result.get("status") == "success":
            return f"Created Google Doc: '{result['title']}'\nLink: {result['link']}"
        return f"Failed to create document: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error creating document: {str(e)}"

def google_docs_read(document: str, account_email: str = "default") -> str:
    """Read the contents of a Google Document.
    
    Args:
        document: Document title or ID (title will be resolved via Drive search).
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        docs = DocsService(email)
        result = docs.read_document(document)
        if result.get("status") == "success":
            text = result['text']
            if len(text) > 3000:
                text = text[:3000] + "\n\n... [truncated — document is long]"
            return f"📄 {result['title']}\nLink: {result['link']}\n\n{text}"
        return f"Failed to read document: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error reading document: {str(e)}"

def google_docs_edit(document: str, text: str, mode: str = "append", find: Optional[str] = None, account_email: str = "default") -> str:
    """Edit a Google Document by appending text or replacing text.
    
    Args:
        document: Document title or ID (title will be resolved via Drive search).
        text: The text to add or the replacement text.
        mode: 'append' to add text at the end, 'replace' to find and replace.
        find: The text to find (required when mode is 'replace').
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        docs = DocsService(email)
        
        if mode == "replace":
            if not find:
                return "When mode is 'replace', you must provide the 'find' parameter."
            result = docs.replace_text(document, find, text)
        else:
            result = docs.append_text(document, text)
        
        if result.get("status") == "success":
            return result.get("message", "Document updated successfully.")
        return f"Failed to edit document: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error editing document: {str(e)}"

def google_docs_delete(document: str, account_email: str = "default") -> str:
    """Delete (trash) a Google Document.
    
    Args:
        document: Document title or ID.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        docs = DocsService(email)
        result = docs.delete_document(document)
        if result.get("status") == "success":
            return "Document moved to trash."
        return f"Failed to delete document: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error deleting document: {str(e)}"

# ==========================================
# Google Sheets Tools
# ==========================================

def google_sheets_create(title: str, account_email: str = "default") -> str:
    """Create a new Google Spreadsheet.
    
    Args:
        title: Spreadsheet title.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        sheets = SheetsService(email)
        result = sheets.create_spreadsheet(title)
        if result.get("status") == "success":
            return f"Created Google Sheet: '{result['title']}'\nLink: {result['link']}"
        return f"Failed to create spreadsheet: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error creating spreadsheet: {str(e)}"

def google_sheets_read(spreadsheet: str, range: str = "Sheet1", account_email: str = "default") -> str:
    """Read data from a Google Spreadsheet.
    
    Args:
        spreadsheet: Spreadsheet title or ID (title resolved via Drive search).
        range: A1 notation (e.g. 'Sheet1', 'Sheet1!A1:D10'). Defaults to first sheet.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        sheets = SheetsService(email)
        result = sheets.read_spreadsheet(spreadsheet, range)
        
        if result.get("status") == "success":
            data = result['data']
            if not data:
                return f"📊 {result['title']} — No data found in range '{range}'.\nLink: {result['link']}"
            
            # Format as a readable table
            lines = [f"📊 {result['title']} ({result['rows']} rows)"]
            lines.append(f"Range: {result['range']}")
            lines.append(f"Link: {result['link']}\n")
            
            # Simple text table
            for i, row in enumerate(data[:50]):  # Cap at 50 rows
                lines.append(" | ".join(str(cell) for cell in row))
                if i == 0 and len(data) > 1:
                    lines.append("-" * 40)
            
            if len(data) > 50:
                lines.append(f"\n... and {len(data) - 50} more rows")
            
            return "\n".join(lines)
        return f"Failed to read spreadsheet: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error reading spreadsheet: {str(e)}"

def google_sheets_update(spreadsheet: str, range: str, values: str, account_email: str = "default") -> str:
    """Update cells in a Google Spreadsheet.
    
    Args:
        spreadsheet: Spreadsheet title or ID.
        range: A1 notation target (e.g. 'Sheet1!A1:C3').
        values: JSON-encoded 2D array of values, e.g. '[["Name","Age"],["Ram","25"]]'.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        sheets = SheetsService(email)
        
        parsed_values = json.loads(values) if isinstance(values, str) else values
        result = sheets.update_cells(spreadsheet, range, parsed_values)
        
        if result.get("status") == "success":
            return f"Updated {result['updated_cells']} cell(s) in range {result['updated_range']}."
        return f"Failed to update spreadsheet: {result.get('message')}"
    except json.JSONDecodeError:
        return "Invalid values format. Please provide a JSON 2D array like [[\"a\",\"b\"],[\"c\",\"d\"]]."
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error updating spreadsheet: {str(e)}"

def google_sheets_append(spreadsheet: str, range: str, rows: str, account_email: str = "default") -> str:
    """Append rows to the bottom of a Google Spreadsheet.
    
    Args:
        spreadsheet: Spreadsheet title or ID.
        range: A1 notation (e.g. 'Sheet1' or 'Sheet1!A:E').
        rows: JSON-encoded 2D array of rows to append, e.g. '[["Ram","Lead","2026-07-18"]]'.
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        sheets = SheetsService(email)
        
        parsed_rows = json.loads(rows) if isinstance(rows, str) else rows
        result = sheets.append_rows(spreadsheet, range, parsed_rows)
        
        if result.get("status") == "success":
            return f"Appended {result['updated_rows']} row(s) to {result['updated_range']}."
        return f"Failed to append rows: {result.get('message')}"
    except json.JSONDecodeError:
        return "Invalid rows format. Please provide a JSON 2D array like [[\"a\",\"b\"],[\"c\",\"d\"]]."
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error appending to spreadsheet: {str(e)}"

def google_sheets_delete_rows(spreadsheet: str, start_row: int, end_row: int, sheet_id: int = 0, account_email: str = "default") -> str:
    """Delete rows from a Google Spreadsheet.
    
    Args:
        spreadsheet: Spreadsheet title or ID.
        start_row: First row to delete (1-based, inclusive).
        end_row: Last row to delete (1-based, inclusive).
        sheet_id: Sheet tab ID (0 for first sheet).
        account_email: Account alias, name, email, or "default".
    """
    try:
        email = _resolve_account_or_error(account_email)
        sheets = SheetsService(email)
        
        # Convert 1-based user input to 0-based API input
        result = sheets.delete_rows(spreadsheet, sheet_id, start_row - 1, end_row)
        
        if result.get("status") == "success":
            return result['message']
        return f"Failed to delete rows: {result.get('message')}"
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error deleting rows: {str(e)}"

# ==========================================
# Tool Registration
# ==========================================

from jatayu.tools import Tool, ToolParam, ToolRegistry

def register(registry: ToolRegistry) -> None:
    """Register all Google Workspace tools."""
    
    # ── Account ──
    registry.register(Tool(
        name="google_list_accounts",
        description="List all connected Google accounts with aliases, emails, services, and default indicator.",
        handler=google_list_accounts,
        params=[]
    ))
    
    # ── Gmail ──
    registry.register(Tool(
        name="google_gmail_read",
        description="Read emails from Gmail (inbox, unread, or search).",
        handler=google_gmail_read,
        params=[
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False),
            ToolParam("query", "string", "Gmail search query (e.g. 'is:unread', 'from:person@example.com')", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_gmail_draft",
        description="Draft an email in Gmail.",
        handler=google_gmail_draft,
        params=[
            ToolParam("to", "string", "Recipient email address."),
            ToolParam("subject", "string", "Email subject."),
            ToolParam("body", "string", "Plain text email body."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_gmail_send",
        description="Send an email immediately via Gmail.",
        handler=google_gmail_send,
        params=[
            ToolParam("to", "string", "Recipient email address."),
            ToolParam("subject", "string", "Email subject."),
            ToolParam("body", "string", "Plain text email body."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    # ── Calendar ──
    registry.register(Tool(
        name="google_calendar_read",
        description="Read upcoming events from Google Calendar.",
        handler=google_calendar_read,
        params=[
            ToolParam("days", "integer", "Number of days to look ahead (default 1).", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_calendar_create",
        description="Create a new event in Google Calendar.",
        handler=google_calendar_create,
        params=[
            ToolParam("summary", "string", "Event title."),
            ToolParam("start_time", "string", "ISO-8601 formatted start time."),
            ToolParam("end_time", "string", "ISO-8601 formatted end time."),
            ToolParam("attendees", "array", "Optional list of email addresses to invite.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    # ── Drive ──
    registry.register(Tool(
        name="google_drive_search",
        description="Search for files in Google Drive by name, keyword, or type. Also supports 'recent' and 'shared'.",
        handler=google_drive_search,
        params=[
            ToolParam("query", "string", "Search text, or 'recent' for recent files, or 'shared' for shared files."),
            ToolParam("file_type", "string", "Filter by type: 'document', 'spreadsheet', 'presentation', 'pdf', 'image', 'folder'.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_drive_upload",
        description="Upload a local file to Google Drive.",
        handler=google_drive_upload,
        params=[
            ToolParam("file_path", "string", "Absolute path to the local file."),
            ToolParam("folder_name", "string", "Destination folder name in Drive.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_drive_download",
        description="Download a file from Google Drive to the local machine.",
        handler=google_drive_download,
        params=[
            ToolParam("file_name", "string", "Name of the file to download."),
            ToolParam("destination", "string", "Local directory to save the file to.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_drive_move",
        description="Move a file to a different folder in Google Drive.",
        handler=google_drive_move,
        params=[
            ToolParam("file_name", "string", "Name of the file to move."),
            ToolParam("destination_folder", "string", "Name of the destination folder."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_drive_share",
        description="Share a Google Drive file with someone or generate a shareable link.",
        handler=google_drive_share,
        params=[
            ToolParam("file_name", "string", "Name of the file to share."),
            ToolParam("share_with_email", "string", "Email to share with, or 'link' for a shareable link."),
            ToolParam("role", "string", "Permission: 'reader', 'writer', or 'commenter'.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_drive_delete",
        description="Delete (trash) a file from Google Drive.",
        handler=google_drive_delete,
        params=[
            ToolParam("file_name", "string", "Name of the file to delete."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    # ── Docs ──
    registry.register(Tool(
        name="google_docs_create",
        description="Create a new Google Document.",
        handler=google_docs_create,
        params=[
            ToolParam("title", "string", "Document title."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_docs_read",
        description="Read the contents of a Google Document. Accepts a title (resolved via Drive search).",
        handler=google_docs_read,
        params=[
            ToolParam("document", "string", "Document title or ID."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_docs_edit",
        description="Edit a Google Document. Use mode='append' to add text at the end, or mode='replace' to find and replace.",
        handler=google_docs_edit,
        params=[
            ToolParam("document", "string", "Document title or ID."),
            ToolParam("text", "string", "Text to add (append mode) or replacement text (replace mode)."),
            ToolParam("mode", "string", "'append' or 'replace'. Defaults to 'append'.", required=False),
            ToolParam("find", "string", "Text to find (required for replace mode).", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_docs_delete",
        description="Delete (trash) a Google Document.",
        handler=google_docs_delete,
        params=[
            ToolParam("document", "string", "Document title or ID."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    # ── Sheets ──
    registry.register(Tool(
        name="google_sheets_create",
        description="Create a new Google Spreadsheet.",
        handler=google_sheets_create,
        params=[
            ToolParam("title", "string", "Spreadsheet title."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_sheets_read",
        description="Read data from a Google Spreadsheet. Accepts a title (resolved via Drive search).",
        handler=google_sheets_read,
        params=[
            ToolParam("spreadsheet", "string", "Spreadsheet title or ID."),
            ToolParam("range", "string", "A1 notation range (e.g. 'Sheet1', 'Sheet1!A1:D10'). Defaults to 'Sheet1'.", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_sheets_update",
        description="Update cells in a Google Spreadsheet.",
        handler=google_sheets_update,
        params=[
            ToolParam("spreadsheet", "string", "Spreadsheet title or ID."),
            ToolParam("range", "string", "A1 notation target (e.g. 'Sheet1!A1:C3')."),
            ToolParam("values", "string", "JSON 2D array of values, e.g. '[[\"Name\",\"Age\"],[\"Ram\",\"25\"]]'."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_sheets_append",
        description="Append rows to the bottom of a Google Spreadsheet.",
        handler=google_sheets_append,
        params=[
            ToolParam("spreadsheet", "string", "Spreadsheet title or ID."),
            ToolParam("range", "string", "A1 notation (e.g. 'Sheet1' or 'Sheet1!A:E')."),
            ToolParam("rows", "string", "JSON 2D array of rows, e.g. '[[\"Ram\",\"Lead\",\"2026-07-18\"]]'."),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
    
    registry.register(Tool(
        name="google_sheets_delete_rows",
        description="Delete rows from a Google Spreadsheet.",
        handler=google_sheets_delete_rows,
        params=[
            ToolParam("spreadsheet", "string", "Spreadsheet title or ID."),
            ToolParam("start_row", "integer", "First row to delete (1-based)."),
            ToolParam("end_row", "integer", "Last row to delete (1-based)."),
            ToolParam("sheet_id", "integer", "Sheet tab ID (0 for first sheet).", required=False),
            ToolParam("account_email", "string", "Account alias, name, or email (omit for default).", required=False)
        ]
    ))
