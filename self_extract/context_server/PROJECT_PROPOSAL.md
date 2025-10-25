# Personal Context Server — Project Proposal (v1)

## Summary

- Purpose: Give AI tools a private, up‑to‑date understanding of the user (or team) — on the user’s terms.
- Outcome: More relevant, consistent help from AI across providers, with strong privacy and clear sharing rules.
- Approach: A small, vendor‑neutral service that any AI assistant can consult to retrieve only the information the user chooses to share.

## The Problem

- AI assistants don’t “know you” well enough: their built‑in memories are limited, often out of date, and tied to a single vendor.
- Users repeat the same context (systems, projects, preferences) and copy/paste from notes to get relevant answers.
- Privacy risk: personal journals, medical details, and sensitive opinions shouldn’t be sent to external services.

## The Solution

- A self‑hostable Personal Context Server that centralizes approved facts about the user and makes them available to any AI assistant the user chooses to connect.
- Works across vendors (no lock‑in) so context follows the user, not the platform.
- Open source and low friction: run locally or on your own server; clear controls for what can be shared.

## What It Does (v1)

- Central profile: Keeps a concise, structured set of facts about the user and their work (e.g., projects, tech setup, goals, skills).
- Smart retrieval: Assistants ask for relevant facts instead of the user re‑typing context.
- Rules and tiers: The user defines what different tools can access (e.g., local model can see more; cloud assistants see less).
- Safety filters: Automatically screens sensitive content (e.g., medical, sexual, private details, opinions) before anything is shared.
- Transparency: Preview what would be shared and see why something is allowed or blocked.
- Read‑only by design: Tools can only read approved context; they cannot write or modify it.

## Why It Matters

- Relevance: Assistants respond with the user’s real context, reducing back‑and‑forth and off‑base suggestions.
- Time saved: Less copy/paste from notes and settings across tools and providers.
- Control: Users set boundaries once; they apply everywhere.
- Portability: Switch providers without rebuilding your “memory”.

## Example Scenarios

- Tech Support: “How do I set up Nginx on my OS?” — The assistant already knows the user runs NixOS and offers the right steps.
- Project Help: “What are the blockers in my robotics project?” — The assistant summarizes from approved project notes.
- Study Aid: “Relate today’s lecture to my class notes.” — It teaches with examples tailored to the user’s material.

## Audience & Benefits

- Individuals
  - Host locally or on a home server; allow limited access to cloud assistants and full access to local tools.
  - Keep private data private by default; selectively share what helps productivity.
- Teams & Organizations
  - Provide employees with secure personalization at work without exposing sensitive data externally.
  - Establish shared rules and policies while preserving individual privacy.

## What’s Included in v1

- Private, read‑only context service that other tools can query for user‑approved facts.
- Search that balances keyword matches and meaning‑based similarity for better relevance.
- Rule‑based access tiers (allow/deny by topic, domain, or tags) to tailor what different tools can access.
- Built‑in sensitive‑content filter with an audit trail for transparency.
- Terminal interface to review and manage rules and preview sharing outcomes.
- Simple deployment (local environment or Docker). No logins or accounts required in v1.

## Not Included in v1 (Roadmap Items)

- Web dashboard
- Authentication and per‑client identities
- Connectors and syncing (e.g., Google Drive, OneDrive, Notion, bookmarks)
- Browser extension to inject approved context into web assistants
- Richer graph‑style knowledge and advanced reasoning prompts

## Roadmap (Next)

- Add a web dashboard for easier management and team administration.
- Introduce authentication and per‑client policies to define fine‑grained access tiers.
- Offer optional connectors/importers (Drive, OneDrive, Notion, social/bookmarks) and local file watchers.
- Provide a browser extension that can (optionally) add approved user context to web assistants’ prompts.
- Support graph‑structured knowledge for deeper relationships between facts and better reasoning.

## Success Measures

- Reduced context repetition and copy/paste during AI use.
- Higher relevance and satisfaction with responses across tools.
- Clear audits showing what would be shared and why.
- “Safe by default”: sensitive information remains private.

## Operating Model

- Self‑hosted, open source, vendor‑neutral.
- Users retain control of their data: the server shares nothing unless rules allow it.
- Designed to work alongside any AI assistant or local model that can consult a simple, read‑only API.
