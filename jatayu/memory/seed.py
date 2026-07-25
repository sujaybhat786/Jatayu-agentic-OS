"""
Seeds a fresh data/memory.db with:
  - identity/preference facts about Sujay (protected — always injected)
  - people entities
  - project entities

Run: python3 -m jatayu.memory.seed [--db data/memory.db]

Idempotent: remember_entity() upserts by (type, name_lower), so running
this twice does not create duplicates. Facts are only inserted if an
identical fact string doesn't already exist for that category.
"""

import argparse
import os
from pathlib import Path
from jatayu.memory.store import MemoryStore
from jatayu.config import get_config


def seed_facts(store: MemoryStore):
    identity_and_prefs = [
        ("identity", "The user's name is Sujay Bhat, based in Mysuru, Karnataka, India (IST)."),
        ("identity", "Sujay is a solo founder running multiple AI ventures: Artificial Budhi AI Studios (ABAS), "
                      "AI Gurukula, The 5th Veda, and JATAYU OS."),
        ("preference", "Greeting ritual: when Sujay says 'Jai Shri Ram Jatayu', respond 'Jai Shri Ram Captain'."),
        ("preference", "Sujay prefers concise answers: no fluff, no narration, action first."),
        ("preference", "Sujay takes espresso with oat milk."),
    ]
    existing = {(f["category"], f["fact"]) for f in store.list_memories()}
    for category, fact in identity_and_prefs:
        if (category, fact) not in existing:
            store.remember(fact, category=category)


def seed_people(store: MemoryStore):
    store.remember_entity(
        type="person",
        name="Tejaswini Hegde",
        aliases=["Tejaswini", "Bekku", "Bekkumari", "Bekkesha"],
        role="HR for the entire operation (all ventures); also manager of AI influencer project Kaamila Kastoori",
        relation="employee",
        email="hegdetejaswini29@gmail.com",
        email_verified=True,
        phone="+91 7349129851",
        projects=["Kaamila Kastoori"],
        notes=None,
    )

    store.remember_entity(
        type="person",
        name="Sumedha Bhat",
        aliases=["Sumedha", "Subbi"],
        role="Ayurveda doctor",
        relation="family — Sujay's sister; not part of the organization, but provides invaluable insights",
        email="bhatsumedha21@gmail.com",
        email_verified=True,
        phone="9353750749",
        projects=[],
        notes=None,
    )

    store.remember_entity(
        type="person",
        name="Ekansh Rastogi",
        aliases=["Ekansh"],
        role="Intern, working on AI Gurukula",
        relation="intern",
        email="rastogiie@gmail.com",
        email_verified=False,  # carried over from earlier records; not reconfirmed in the latest data pass
        phone=None,
        projects=["AI Gurukula"],
        notes="Email carried over from a prior record — flagged unverified since the latest data pass marked "
              "contact info as unknown; confirm before relying on it.",
    )

    store.remember_entity(
        type="person",
        name="Adithya",
        aliases=[],
        role="AI Engineering intern, working on Pinaka",
        relation="intern",
        email=None,
        email_verified=False,
        phone=None,
        projects=["Pinaka"],
        notes=None,
    )

    store.remember_entity(
        type="person",
        name="Ram Raghavan",
        aliases=["Ram"],
        role="CEO of Riddlebox / My Content Smart Hub (MCSH); mentor; also client for The 5th Veda",
        relation="mentor and client — speak of with great respect",
        email=None,
        email_verified=False,
        phone=None,
        projects=["My Content Smart Hub", "The 5th Veda"],
        notes=None,
    )

    store.remember_entity(
        type="person",
        name="Guenther",
        aliases=[],
        role="Owner, Framelux Studio",
        relation="client",
        email=None,
        email_verified=False,
        phone=None,
        projects=["Framelux Studio"],
        notes=None,
    )


def seed_projects(store: MemoryStore):
    store.remember_entity(
        type="project", name="Artificial Budhi AI Studios",
        aliases=["ABAS", "Artificial Budhi"],
        status="active",
        parent_org=None,
        description="Sujay's main AI company; parent entity for AI Gurukula, JATAYU OS, and other ventures.",
        people=[],
        contract=None,
    )

    store.remember_entity(
        type="project", name="JATAYU OS",
        aliases=["JATAYU"],
        status="active — being rebuilt",
        parent_org="Artificial Budhi AI Studios",
        description="Sujay's personal AI operating system. Currently mid-rebuild, starting with the memory layer.",
        people=[],
        contract=None,
    )

    store.remember_entity(
        type="project", name="Pinaka",
        aliases=[],
        status="active",
        parent_org="Artificial Budhi AI Studios",
        description="Project under ABAS; Adithya (AI engineering intern) is working on it.",
        people=["Adithya"],
        contract=None,
    )

    store.remember_entity(
        type="project", name="AI Gurukula",
        aliases=[],
        status="active",
        parent_org="Artificial Budhi AI Studios",
        description="AI education platform under ABAS. Ekansh Rastogi (intern) works on it.",
        people=["Ekansh Rastogi"],
        contract=None,
    )

    store.remember_entity(
        type="project", name="Kaamila Kastoori",
        aliases=[],
        status="active",
        parent_org="Artificial Budhi AI Studios",
        description="AI influencer project, managed by Tejaswini Hegde.",
        people=["Tejaswini Hegde"],
        contract=None,
    )

    store.remember_entity(
        type="project", name="The 5th Veda",
        aliases=["Fifth Veda", "5th Veda"],
        status="agreement in principle — not yet started",
        parent_org="Artificial Budhi AI Studios",
        description="Spiritual/content project, in collaboration with client Ram Raghavan.",
        people=["Ram Raghavan"],
        contract={
            "counterparty": "Ram Raghavan",
            "terms": "GBP 250 for 25 videos, plus free social media channel management for the "
                     "duration of the engagement (1 video/day for 25 days).",
            "currency": "GBP",
            "amount": 250,
            "deliverables": "25 videos",
            "status": "agreement in principle, work not yet begun",
        },
    )

    store.remember_entity(
        type="project", name="My Content Smart Hub",
        aliases=["MCSH", "Content Smart Hub"],
        status="active",
        parent_org=None,
        description="Sujay's first client. CEO is Ram Raghavan.",
        people=["Ram Raghavan"],
        contract=None,
    )

    store.remember_entity(
        type="project", name="Framelux Studio",
        aliases=["Framelux"],
        status="active — contract signed",
        parent_org=None,
        description="Video content contract for client Guenther. Goal: create videos for his platform "
                     "and grow it virally.",
        people=["Guenther"],
        contract={
            "counterparty": "Guenther",
            "terms": "USD 1,340/month. Expected output: 1 long-form video/week + 2-3 short-form videos/week "
                     "(~20-30 hours/week of work, 4-5 hours per video). Daily scrum call at 9:00 PM.",
            "currency": "USD",
            "amount": 1340,
            "billing_period": "monthly",
            "cadence": "daily scrum call, 9:00 PM",
            "status": "active",
        },
    )


def main():
    data_dir = get_config().get("data_dir", "data")
    default_db = str(Path(data_dir) / "memory.db")

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=default_db)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    store = MemoryStore(db_path=args.db)

    seed_facts(store)
    seed_people(store)
    seed_projects(store)

    print(f"Seeded {args.db}")
    print(f"  facts:    {len(store.list_memories())}")
    print(f"  entities: {len(store.list_entities())}")
    store.close()


if __name__ == "__main__":
    main()
