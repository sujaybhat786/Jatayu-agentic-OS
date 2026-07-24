"""
JATAYU Daily Context Aggregator Service
Aggregates situational awareness modules (Weather, future providers) into a single API contract.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from jatayu.context.weather import WeatherService

logger = logging.getLogger(__name__)

class DailyContextService:
    """Orchestrator for daily environmental context providers."""

    def __init__(self, weather_service: Optional[WeatherService] = None):
        self.weather_service = weather_service or WeatherService()

    def get_daily_context(self) -> Dict[str, Any]:
        """
        Aggregates situational context for today.
        Returns a clean dictionary consumed by the frontend.
        """
        now = datetime.now()
        date_formatted = now.strftime("%A, %d %B %Y")
        day_of_week = now.strftime("%A")

        weather_info = None
        try:
            weather_info = self.weather_service.get_weather()
        except Exception as e:
            logger.warning("DailyContextService: Weather provider error: %s", e)

        has_content = bool(weather_info is not None)

        return {
            "status": "ok",
            "date_formatted": date_formatted,
            "day_of_week": day_of_week,
            "weather": weather_info,
            "has_content": has_content
        }
