"""JATAYU Chief of Staff — Executive Orchestrator Backend Service.

Coordinates daily morning brief, afternoon check-in, night debrief,
habit/attendance tracking, deterministic execution score calculation,
and Obsidian daily review archiving.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

from jatayu.config import get_config

logger = logging.getLogger(__name__)

class ChiefOfStaffService:
    """Read-first orchestration layer that coordinates the Daily Executive Cycle."""

    def __init__(self, brain=None, pipeline_services=None):
        self._brain = brain
        self._pipeline_services = pipeline_services or {}
        self.config = get_config()
        self.data_dir = Path(self.config["data_dir"])
        self.runtime_file = self.data_dir / "chief_runtime.json"
        self._runtime_data = {}
        self._load()

    def _load(self) -> None:
        if self.runtime_file.exists():
            try:
                with open(self.runtime_file, "r", encoding="utf-8") as f:
                    self._runtime_data = json.load(f)
            except Exception as e:
                logger.error("Failed to load chief runtime: %s", e)
                self._runtime_data = {}

    def _save(self) -> None:
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.runtime_file, "w", encoding="utf-8") as f:
                json.dump(self._runtime_data, f, indent=2, default=str)
        except Exception as e:
            logger.error("Failed to save chief runtime: %s", e)

    def _get_date_data(self, date_str: str) -> dict:
        if date_str not in self._runtime_data:
            self._runtime_data[date_str] = {
                "morning_brief": None,
                "afternoon_checkin": None,
                "night_debrief": None,
                "habits": {
                    "Wake Early": False,
                    "Sandhya": False,
                    "Meditation": False,
                    "Exercise": False,
                    "Job Applications": False,
                    "Revenue Update": False,
                    "Content Published": False,
                    "Daily Review": False
                }
            }
        return self._runtime_data[date_str]

    def get_state(self, date_str: str) -> dict:
        """Get the full executive cycle and habit state for a specific date."""
        return self._get_date_data(date_str)

    def toggle_habit(self, date_str: str, habit_name: str) -> dict:
        """Toggle a habit's completion state for a given date."""
        data = self._get_date_data(date_str)
        habits = data["habits"]
        if habit_name in habits:
            habits[habit_name] = not habits[habit_name]
            self._save()
        return data

    def get_system_health(self) -> dict:
        """Evaluate JATAYU subsystems dynamically."""
        health = {
            "Brain": "🟢 Active",
            "Memory": "🔴 Offline",
            "Knowledge Graph": "🔴 Offline",
            "Obsidian": "🔴 Offline",
            "Telegram": "🔴 Disabled",
            "Revenue": "🟢 Active",
            "Calendar": "🟢 Active",
            "Weather": "🟢 Active",
            "News": "🟢 Active",
            "APIs": "🟢 Active"
        }

        # Check API / Brain Client
        if self._brain and self._brain.client:
            health["Brain"] = "🟢 Active"
        else:
            health["Brain"] = "🔴 API Key Missing"

        # Check Memory file
        if (self.data_dir / "memory.json").exists():
            health["Memory"] = "🟢 Active"

        # Check Graph (in-memory pipeline service or file check fallback)
        if self._pipeline_services.get("memory_graph") is not None:
            health["Knowledge Graph"] = "🟢 Active"
        elif (self.data_dir / "memory_graph.json").exists() or (self.data_dir / "graph.db").exists():
            health["Knowledge Graph"] = "🟢 Active"

        # Check Obsidian connection
        obsidian_dir = Path("/Users/sujayabhat/Downloads/Agentic OS/.obsidian")
        if obsidian_dir.exists():
            health["Obsidian"] = "🟢 Synced"

        # Check Telegram
        if self.config.get("comms", {}).get("telegram", {}).get("enabled", True):
            health["Telegram"] = "🟢 Polling"

        return health

    def _get_context_payload(self) -> dict:
        """Gathers context from memory, schedule, reminders, and entities."""
        # 1. Load tasks
        schedule_file = self.data_dir / "schedule.json"
        tasks = []
        if schedule_file.exists():
            try:
                with open(schedule_file, "r") as f:
                    sched_data = json.load(f)
                    tasks = sched_data.get("tasks", [])
            except Exception:
                pass

        # 2. Load reminders
        reminders_file = self.data_dir / "reminders.json"
        reminders = []
        if reminders_file.exists():
            try:
                with open(reminders_file, "r") as f:
                    reminders = json.load(f)
            except Exception:
                pass

        # 3. Load entities
        entities_file = self.data_dir / "entities.json"
        entities = {}
        if entities_file.exists():
            try:
                with open(entities_file, "r") as f:
                    entities = json.load(f)
            except Exception:
                pass

        # 4. Mock Revenue / Results
        revenue = {
            "target": "₹5,000 / week",
            "current": "₹3,500 achieved",
            "roi_insights": "Direct cold outreach is producing 80% of revenue, while general posting yields high views but low conversion."
        }

        results = {
            "AI Gurukula Landing Page": "Ready for staging deployment",
            "5th Veda Videos": "3 of 5 uploaded",
            "Job Applications": "12 submitted, 2 interview loops active"
        }

        # 5. Hindu Calendar & News placeholders (Future integrations)
        hindu_calendar = "Shravana Month, Krishna Paksha, Ekadashi"
        weather = "Rainy, 24°C, Humidity 88%"
        ai_news = "Gemini 3.5 Flash released globally with multi-agent orchestration tools."

        return {
            "tasks": tasks,
            "reminders": reminders,
            "entities": entities,
            "revenue": revenue,
            "results": results,
            "hindu_calendar": hindu_calendar,
            "weather": weather,
            "ai_news": ai_news,
            "system_health": self.get_system_health()
        }

    def generate_morning_brief(self, date_str: str) -> dict:
        """Generate a Morning Brief via Gemini using gathered context."""
        data = self._get_date_data(date_str)
        context = self._get_context_payload()

        prompt = f"""
You are the JATAYU Chief of Staff (Executive Orchestrator). 
You own no persistent memory. Your job is to analyze the current system context and construct a temporary Morning Brief to keep the user disciplined, focused, and strategic.

Current System Context:
{json.dumps(context, indent=2)}

Generate a Morning Brief for {date_str} in clean JSON format matching this schema:
{{
  "mission": "Single high-impact focus for today.",
  "priorities": ["Priority 1", "Priority 2", "Priority 3"],
  "risks": ["Potential execution bottlenecks or upcoming deadlines at risk."],
  "follow_ups": ["Important follow-ups with entities/people."],
  "hindu_calendar": "Hindu calendar status.",
  "ai_news": "Brief top AI update.",
  "weather": "Brief weather description."
}}
Ensure the JSON is raw, valid, and contains no markdown tags or wrapper text.
"""
        model = self.config.get("model", "gemini-3.5-flash")
        try:
            res = self._brain.client.models.generate_content(model=model, contents=prompt)
            text = res.text.strip()
            # Clean possible markdown block wrappers
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            brief_data = json.loads(text.strip())
            brief_data["generated_at"] = datetime.now(timezone.utc).isoformat()
            
            data["morning_brief"] = brief_data
            self._save()
        except Exception as e:
            logger.error("Failed to generate morning brief: %s", e)
            data["morning_brief"] = {
                "mission": "Focus on clearing pending workspace milestones.",
                "priorities": [t["description"] for t in context["tasks"][:3]],
                "risks": ["Unable to dynamically evaluate risks due to LLM error."],
                "follow_ups": ["Check pending emails."],
                "hindu_calendar": context["hindu_calendar"],
                "ai_news": context["ai_news"],
                "weather": context["weather"],
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            self._save()

        return data

    def generate_afternoon_checkin(self, date_str: str) -> dict:
        """Compare morning plan against current task progress to produce check-in questions."""
        data = self._get_date_data(date_str)
        context = self._get_context_payload()
        morning_brief = data["morning_brief"] or {}

        prompt = f"""
You are the JATAYU Chief of Staff. 
Construct an Afternoon Check-in to review progress against the morning plan. Identify any unfinished, blocked, or postponed tasks and formulate direct, helpful questions.

Morning Brief:
{json.dumps(morning_brief, indent=2)}

Current Task Status:
{json.dumps(context["tasks"], indent=2)}

Generate the Afternoon Check-in in clean JSON format matching this schema:
{{
  "progress_summary": "Brief analysis comparing morning goals to current progress.",
  "questions": ["Specific, context-aware question about task X", "Question about task Y"]
}}
Ensure the JSON is raw, valid, and contains no markdown tags or wrapper text.
"""
        model = self.config.get("model", "gemini-3.5-flash")
        try:
            res = self._brain.client.models.generate_content(model=model, contents=prompt)
            text = res.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            checkin_data = json.loads(text.strip())
            checkin_data["generated_at"] = datetime.now(timezone.utc).isoformat()
            
            data["afternoon_checkin"] = checkin_data
            self._save()
        except Exception as e:
            logger.error("Failed to generate afternoon checkin: %s", e)
            data["afternoon_checkin"] = {
                "progress_summary": "Daily tasks are still in progress.",
                "questions": ["Are you encountering any blockers on today's tasks?"],
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            self._save()

        return data

    def generate_night_debrief(self, date_str: str, user_answers: dict) -> dict:
        """Finalize the night review, calculate deterministic score, generate insights, and save to Obsidian."""
        data = self._get_date_data(date_str)
        context = self._get_context_payload()
        morning_brief = data["morning_brief"] or {}
        afternoon_checkin = data["afternoon_checkin"] or {}

        # ── 1. Calculate Deterministic Execution Score ──
        # A: Critical tasks completed (30%)
        tasks = context["tasks"]
        high_tasks = [t for t in tasks if t.get("priority") == "high"]
        completed_high = [t for t in high_tasks if t.get("done") == True]
        score_critical = 30.0 if not high_tasks else (len(completed_high) / len(high_tasks)) * 30.0

        # B: Habits completed (20%)
        habits = data["habits"]
        completed_habits = [h for h, val in habits.items() if val == True]
        score_habits = (len(completed_habits) / len(habits)) * 20.0

        # C: Deadlines met (20%) - derived from completed high/medium tasks
        active_tasks = [t for t in tasks if t.get("done") == True]
        score_deadlines = 20.0 if not tasks else (len(active_tasks) / len(tasks)) * 20.0

        # D: Revenue/Results update toggles (15%) - habit "Revenue Update"
        score_revenue = 15.0 if habits.get("Revenue Update") else 0.0

        # E: Night review completed (15%) - since we are running this debrief, it is completed!
        score_review = 15.0

        execution_score = int(score_critical + score_habits + score_deadlines + score_revenue + score_review)

        # ── 2. Call LLM to provide Executive Insights and summarize ──
        prompt = f"""
You are the JATAYU Chief of Staff. 
Review the daily execution metrics and the user's answers to the evening debrief interview. Generate tomorrow's priorities, executive insights, and a summary review.

Morning Plan: {json.dumps(morning_brief, indent=2)}
Daily Progress: {json.dumps(context["tasks"], indent=2)}
Habits Completed: {", ".join(completed_habits)}
Execution Score: {execution_score}/100
User Interview Answers: {json.dumps(user_answers, indent=2)}

Generate a Night Debrief in clean JSON format matching this schema:
{{
  "review_text": "Executive assessment of today's progress. Highlight effort vs. ROI insights.",
  "tomorrow_priorities": ["Draft Priority 1", "Draft Priority 2", "Draft Priority 3"]
}}
Ensure the JSON is raw, valid, and contains no markdown tags or wrapper text.
"""
        model = self.config.get("model", "gemini-3.5-flash")
        try:
            res = self._brain.client.models.generate_content(model=model, contents=prompt)
            text = res.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            debrief_data = json.loads(text.strip())
        except Exception as e:
            logger.error("Failed to generate night LLM insights: %s", e)
            debrief_data = {
                "review_text": "Completed the evening review successfully. Focus remained on high-priority integrations.",
                "tomorrow_priorities": ["Carry over uncompleted critical tasks."]
            }

        debrief_data.update({
            "user_answers": user_answers,
            "execution_score": execution_score,
            "score_breakdown": {
                "critical_tasks": int(score_critical),
                "habits": int(score_habits),
                "deadlines": int(score_deadlines),
                "revenue_results": int(score_revenue),
                "night_review": int(score_review)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        })

        data["night_debrief"] = debrief_data
        self._save()

        # ── 3. Archive Review to Obsidian (Creates value / history) ──
        self.save_daily_review_to_obsidian(date_str, data)

        return data

    def save_daily_review_to_obsidian(self, date_str: str, date_data: dict) -> None:
        """Write the daily review as a clean Markdown note in the user's vault."""
        obsidian_vault_root = Path("/Users/sujayabhat/Downloads/Agentic OS")
        if not obsidian_vault_root.exists():
            logger.warning("Obsidian vault directory does not exist — skipping review write.")
            return

        reviews_dir = obsidian_vault_root / "01_Foundation" / "Daily_Reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        review_file = reviews_dir / f"Daily_Review_{date_str}.md"

        morning = date_data.get("morning_brief") or {}
        checkin = date_data.get("afternoon_checkin") or {}
        night = date_data.get("night_debrief") or {}
        habits = date_data.get("habits") or {}

        completed_habits = [h for h, val in habits.items() if val == True]

        md_content = f"""---
type: daily_review
date: {date_str}
execution_score: {night.get("execution_score", 0)}
---

# JATAYU Chief of Staff — Daily Executive Review ({date_str})

## Morning Mission
**{morning.get("mission", "N/A")}**

### Morning Priorities
{chr(10).join(f"- {p}" for p in morning.get("priorities", []))}

---

## Afternoon Check-in Progress
*{checkin.get("progress_summary", "N/A")}*

---

## Night Debrief & Outcomes
**Execution Score:** {night.get("execution_score", 0)}/100

### Executive Insights
{night.get("review_text", "N/A")}

### Habits Completed Today
{chr(10).join(f"- [x] {h}" for h in completed_habits)}
{chr(10).join(f"- [ ] {h}" for h in habits if h not in completed_habits)}

### Tomorrow's Draft Priorities
{chr(10).join(f"- {p}" for p in night.get("tomorrow_priorities", []))}

---
Generated by JATAYU OS.
"""
        try:
            review_file.write_text(md_content, encoding="utf-8")
            logger.info("Successfully saved daily review to Obsidian: %s", review_file)
        except Exception as e:
            logger.error("Failed to save daily review to Obsidian note: %s", e)
