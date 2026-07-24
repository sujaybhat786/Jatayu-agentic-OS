import datetime
import logging
from typing import List, Dict, Optional

from jatayu.integrations.google.workspace_manager import GoogleWorkspaceManager

logger = logging.getLogger(__name__)

class CalendarService:
    """Business logic wrapper for Google Calendar API."""

    def __init__(self, account_email: str = "default"):
        self.workspace = GoogleWorkspaceManager()
        self.service, self.account_email = self.workspace.get_service('calendar', 'v3', account_email)

    def get_upcoming_events(self, days: int = 1, max_results: int = 20) -> List[Dict]:
        """Fetch upcoming events for the specified number of days."""
        try:
            now = datetime.datetime.utcnow()
            time_min = now.isoformat() + 'Z'  # 'Z' indicates UTC time
            time_max = (now + datetime.timedelta(days=days)).isoformat() + 'Z'

            events_result = self.service.events().list(
                calendarId='primary', 
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            parsed_events = []
            
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                parsed_events.append({
                    "id": event['id'],
                    "summary": event.get('summary', '(No title)'),
                    "start": start,
                    "end": end,
                    "location": event.get('location', ''),
                    "description": event.get('description', ''),
                    "htmlLink": event.get('htmlLink', '')
                })
                
            return parsed_events
        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return []

    def create_event(self, summary: str, start_time: str, end_time: str, attendees: Optional[List[str]] = None) -> Dict:
        """
        Create a new calendar event.
        start_time and end_time should be ISO formatted strings (e.g., '2026-07-18T10:00:00-07:00').
        """
        try:
            event_body = {
                'summary': summary,
                'start': {
                    'dateTime': start_time,
                    # Fallback timezone if offset isn't provided in dateTime
                    'timeZone': 'UTC', 
                },
                'end': {
                    'dateTime': end_time,
                    'timeZone': 'UTC',
                },
            }
            
            if attendees:
                event_body['attendees'] = [{'email': email} for email in attendees]

            event = self.service.events().insert(
                calendarId='primary', 
                body=event_body
            ).execute()
            
            return {
                "status": "success", 
                "event_id": event['id'], 
                "link": event.get('htmlLink')
            }
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return {"status": "error", "message": str(e)}

    def delete_event(self, event_id: str) -> Dict:
        """Delete an event by ID."""
        try:
            self.service.events().delete(
                calendarId='primary', 
                eventId=event_id
            ).execute()
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            return {"status": "error", "message": str(e)}
