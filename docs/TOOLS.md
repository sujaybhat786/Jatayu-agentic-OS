# JATAYU Core v1.0 — Tools Architecture & Consistency Standards

The `ToolRegistry` (`jatayu/tools/__init__.py`) provides the standardized execution interface for all capabilities in JATAYU Core.

---

## 1. Tool Signature & Return Standards

To ensure predictable parsing by the LLM and consistent UX presentation, all tool handlers MUST follow strict return guidelines:

### Standardized Return Formats
1. **Success**: Must begin with a checkmark emoji (`✅` or `✔`) followed by a human-readable summary.
   - Example: `✅ Telegram message sent to Alex (@alex_dev).`
   - Example: `✅ Note 'Meeting Notes' saved to Obsidian vault.`
2. **Error / Failure**: Must begin with a cross emoji (`❌`) or `Error:`, explaining the failure plainly with an actionable next step.
   - Example: `❌ Telegram error: Recipient @invalid_user not found (HTTP 400). Please check the username and try again.`
   - Example: `❌ Obsidian error: Vault connection refused. Please check that Obsidian is running and Local REST API is enabled.`

---

## 2. Latency Auditing (`execute_with_timing`)

The `ToolRegistry` wraps tool execution in monotonic latency tracking:

```python
result, duration_ms = registry.execute_with_timing("telegram_send", {"recipient": "@alex", "message": "Hi"})
```

- **Zero Overhead**: Direct in-memory callable invocation (< 0.001 ms wrapper overhead).
- **Audit Integration**: Duration and success status are recorded on `session.tools_called` and logged in `log_request_lifecycle` at the end of every request.

---

## 3. Core Tool Domains

| Domain | Tool Names | Handler Module | Safety Confirmation Required |
| :--- | :--- | :--- | :---: |
| **Google Workspace** | `google_gmail_read`, `google_gmail_draft`, `google_gmail_send`<br>`google_calendar_read`, `google_calendar_create`<br>`google_drive_search`, `google_drive_upload`, `google_drive_download`, `google_drive_move`, `google_drive_share`, `google_drive_delete`<br>`google_docs_create`, `google_docs_read`, `google_docs_edit`, `google_docs_delete`<br>`google_sheets_create`, `google_sheets_read`, `google_sheets_update`, `google_sheets_append`, `google_sheets_delete_rows` | `jatayu/tools/google_workspace.py` | Yes (for send/delete/share) |
| **Telegram** | `telegram_send` | `jatayu/tools/telegram_tool.py` | Yes |
| **Obsidian** | `obsidian_search`, `obsidian_write_note` | `jatayu/tools/obsidian.py` | No / Configurable |
| **Memory** | `remember`, `remember_entity`, `get_person`, `get_project` | `jatayu/memory/store.py` | No |
| **Reminders & Tasks** | `set_reminder`, `list_reminders`, `add_task`, `complete_task` | `jatayu/tools/` | No |
