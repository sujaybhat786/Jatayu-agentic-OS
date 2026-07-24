"""Smoke test for the Phase 5 propagation and intelligence pipelines."""

import asyncio
from pathlib import Path

from jatayu.brain import Brain
from jatayu.web.server import _build_pipeline
from jatayu.pipeline.event_log import PipelineEvent

async def run_smoke_test():
    data_dir = "/Users/sujayabhat/Downloads/Agentic OS/data"
    brain = Brain()
    
    # We mock conversation service for the build pipeline
    class MockConvService:
        pass
        
    pipeline = _build_pipeline(data_dir, brain, MockConvService())
    
    # 1. Test Proactive Intelligence Engine
    proactive = pipeline.get("proactive_engine")
    if proactive:
        proactive.evaluate_all()
        obs = proactive.get_all()
        print(f"✅ Generated {len(obs)} proactive observations.")
        for o in obs:
            print(f"   - {o.priority} {o.type}: {o.reason}")
    else:
        print("❌ ProactiveIntelligenceEngine missing from pipeline")
        
    # 2. Test Morning Brief Generation
    daily_brief = pipeline.get("daily_brief")
    if daily_brief:
        brief = daily_brief.generate()
        d = brief.to_dict()
        print("✅ Daily Brief generated with Phase 5 fields:")
        print(f"   - High Priority Observations: {len(d.get('high_priority_observations', []))}")
    else:
        print("❌ DailyBriefAggregator missing from pipeline")
        
    # 3. Test Knowledge Propagation
    prop = pipeline.get("knowledge_propagation")
    if prop:
        print("✅ KnowledgePropagationService initialized.")
        # We manually inject a mocked event
        event = PipelineEvent(
            event_id="test_evt_1",
            type="relationship.created",
            session_id="system",
            source="test",
            timestamp="2026-07-20T00:00:00",
            data={
                "relationship_type": "works_on",
                "source_name": "Test User",
                "target_name": "Test Project"
            }
        )
        prop._queue.put(event)
        # Give it a second to process
        await asyncio.sleep(1.5)
        # Check if run was tracked
        runs = list(prop._runs.values())
        print(f"✅ Propagation processed {len(runs)} events. Latest status: {runs[-1].status if runs else 'None'}")
        prop.shutdown()
    else:
        print("❌ KnowledgePropagationService missing from pipeline")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
