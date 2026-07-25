# JATAYU Core v1.0 — Plugin Architecture & Hardening Boundaries

As mandated by the **Product Hardening & Reliability Sprint**, JATAYU Core enforces strict architectural stability and separation between production-ready core features and experimental laboratory modules.

---

## 1. Core vs. Labs Boundary

| Layer | Directory | Policy | Allowed Contents |
| :--- | :--- | :--- | :--- |
| **JATAYU Core (Production)** | `jatayu/` | **STABLE** — No new frameworks or abstractions without explicit architectural review. | Core Brain, memory store, Google Workspace, Telegram, Obsidian, SQLite vault, FastAPI server. |
| **JATAYU Labs (Experimental)** | `labs/` | **UNSAFE / SANDBOXED** — Non-production scripts, experimental engines, and unverified integrations. | `browser_use` plugin, legacy offline routing experiments, debug scripts, graph databases. |

---

## 2. Plugin Manager (`jatayu/core/plugin_manager.py`)

JATAYU Core uses a lightweight plugin loader that exposes integrations as standard tools via `ToolRegistry`:

- **Active Integrations**:
  - `hermes` (AI agent integration)
  - `obsidian` (Local REST API note management)
- **Experimental Plugins**:
  - `browser_use`: Isolated in `labs/plugins/browser_use/`. It is NOT loaded in default production runtime (`demo_mode: false`), preventing unverified browser automation dependencies from destabilizing core workflows.

---

## 3. Adding New Integrations

Any new tool or plugin must satisfy three hardening rules before entering `jatayu/tools/`:
1. **No External Frameworks**: Must use native Python HTTP libraries (`httpx`, `requests`, `urllib3`) or official SDKs (e.g., `google-api-python-client`).
2. **Standardized Return Signatures**: Must return strings starting with `✅` or `❌` with clear error recovery guidance.
3. **Regression Test Coverage**: Must be added to `tests/regression/test_suite.py` with full mock coverage.
