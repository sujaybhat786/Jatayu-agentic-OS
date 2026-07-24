#!/usr/bin/env python3
"""
JATAYU Stabilization Smoke Tests
Run after every fix to confirm regressions are resolved and no new ones introduced.
Usage:  python smoke_tests.py
Exit code 0 = all tests pass. Non-zero = failure.
"""
import ast
import re
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []


def check(test_id, description, condition, reason=""):
    if condition:
        print(f"  {PASS}  [{test_id}] {description}")
        results.append((test_id, True, description))
    else:
        print(f"  {FAIL}  [{test_id}] {description}")
        if reason:
            print(f"         -> {reason}")
        results.append((test_id, False, description + (f" — {reason}" if reason else "")))


def read_file(rel_path):
    with open(os.path.join(ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


def read_yaml(rel_path):
    import yaml
    with open(os.path.join(ROOT, rel_path), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_R1():
    print("\n[R1] session.session_id attribute must exist on SessionState")
    src = read_file("jatayu/brain.py")
    has_field = bool(re.search(r"session_id\s*:\s*str", src))
    check("R1-a", "SessionState has session_id: str field", has_field,
          "Add `session_id: str = 'default'` to SessionState dataclass")
    has_assign = bool(re.search(r"session\.session_id\s*=\s*session_id", src))
    check("R1-b", "brain.send() assigns session.session_id = session_id", has_assign,
          "Add `session.session_id = session_id` after _get_or_create_session() call")


def test_R2():
    print("\n[R2] config.yaml model_routing must not use gemini-3.5-flash or invalid model names")
    try:
        cfg = read_yaml("config.yaml")
    except Exception as e:
        check("R2-a", "config.yaml parses cleanly", False, str(e))
        return
    routing = cfg.get("model_routing", {})
    bad_35 = [k for k, v in routing.items() if v == "gemini-3.5-flash"]
    check("R2-a", "No model_routing entry uses gemini-3.5-flash", len(bad_35) == 0,
          f"Still using gemini-3.5-flash: {bad_35}")
    costs = cfg.get("model_costs", {})
    default_model = cfg.get("model", "")
    check("R2-b", f"Default model '{default_model}' has a model_costs entry",
          default_model in costs,
          f"Add {default_model} to model_costs in config.yaml")
    bad_invalid = [v for v in routing.values() if v and "3.1-pro-preview" in str(v)]
    check("R2-c", "No model_routing uses non-existent gemini-3.1-pro-preview",
          len(bad_invalid) == 0, f"Invalid model names: {bad_invalid}")


def test_R3():
    print("\n[R3] Confirmation gate must be per-session (confirm_fn param on brain.send)")
    brain_src = read_file("jatayu/brain.py")
    check("R3-a", "brain.send() accepts confirm_fn parameter",
          bool(re.search(r"def send\(.*confirm_fn", brain_src, re.DOTALL)),
          "Add `confirm_fn=None` to brain.send() signature")
    check("R3-b", "_execute_tools() accepts confirm_fn parameter",
          bool(re.search(r"def _execute_tools\(.*confirm_fn", brain_src, re.DOTALL)),
          "Thread confirm_fn into _execute_tools()")
    server_src = read_file("jatayu/web/server.py")
    still_installs = bool(re.search(
        r"install_ws_confirmation_callback.*ws_confirmation_gate", server_src))
    check("R3-c", "install_ws_confirmation_callback not called per-message in run_brain",
          not still_installs,
          "Remove install_ws_confirmation_callback from inside run_brain()")


def test_R4():
    print("\n[R4] app.js handleConfirmRequest must use existing element #chat-thread, not #chat-messages")
    src = read_file("jatayu/web/static/app.js")
    # Verify $ is defined as a vanilla JS helper (not jQuery loaded externally)
    has_vanilla_dollar = bool(re.search(r"const \$ = \(sel\) => document\.querySelector", src))
    check("R4-a", "$ is defined as vanilla document.querySelector helper (not jQuery)",
          has_vanilla_dollar, "$ helper definition not found — check app.js header")
    # The broken selector pointed to #chat-messages which doesn't exist in index.html
    broken_selector = bool(re.search(r'\$\s*\(\s*["\']#chat-messages["\']', src))
    check("R4-b", "handleConfirmRequest does not use non-existent #chat-messages selector",
          not broken_selector,
          "Change #chat-messages to #chat-thread in handleConfirmRequest()")


def test_R5():
    print("\n[R5] Idempotency must use correct Telegram tool name")
    src = read_file("jatayu/safety/idempotency.py")
    has_old = bool(re.search(r'"telegram_send"', src))
    has_new = bool(re.search(r'"send_telegram_message"', src))
    check("R5-a", "'telegram_send' removed from _DESTRUCTIVE_TOOLS", not has_old,
          "Remove 'telegram_send' from idempotency._DESTRUCTIVE_TOOLS")
    check("R5-b", "'send_telegram_message' present in _DESTRUCTIVE_TOOLS", has_new,
          "Add 'send_telegram_message' to idempotency._DESTRUCTIVE_TOOLS")


def test_R6():
    print("\n[R6] hermes_status() must have 'breaker' in scope")
    src = read_file("jatayu/tools/hermes.py")
    status_pos = src.find("def hermes_status")
    if status_pos == -1:
        check("R6-a", "hermes_status() function exists", False, "Function not found")
        return
    before_status = src[:status_pos]
    module_level_breaker = bool(re.search(
        r"^breaker\s*=\s*get_breaker", before_status, re.MULTILINE))
    check("R6-a", "Module-level breaker = get_breaker(...) defined before hermes_status()",
          module_level_breaker,
          "Move `breaker = get_breaker('hermes')` to module level in hermes.py")


def test_R7():
    print("\n[R7] memory/retriever.py must guard against empty terms set")
    src = read_file("jatayu/memory/retriever.py")
    division_pos = src.find("/ len(terms)")
    if division_pos == -1:
        check("R7-a", "Division by len(terms) exists", False,
              "Could not find the division expression")
        return
    before_div = src[:division_pos]
    has_guard = bool(re.search(r"if not terms", before_div))
    check("R7-a", "'if not terms' guard appears before '/ len(terms)'", has_guard,
          "Move `if not terms: return 0.0` to immediately after terms is computed")


def test_R8():
    print("\n[R8] Plugins must call handler(**kwargs), not handler(kwargs)")
    for plugin_file in [
        "jatayu/plugins/anythingllm/plugin.py",
        "jatayu/plugins/browser_use/plugin.py",
    ]:
        src = read_file(plugin_file)
        bad_calls = re.findall(r'\bhandler\s*\(\s*kwargs\s*\)', src)
        plugin_name = os.path.basename(os.path.dirname(plugin_file))
        check(f"R8-{plugin_name}", f"{plugin_name}/plugin.py uses handler(**kwargs)",
              len(bad_calls) == 0,
              f"Found {len(bad_calls)} handler(kwargs) — change to handler(**kwargs)")


def test_R10():
    print("\n[R10] Obsidian must not use port 27125")
    for path in ["jatayu/tools/obsidian.py", "jatayu/web/server.py"]:
        src = read_file(path)
        wrong = re.findall(r'27125', src)
        fname = os.path.basename(path)
        check(f"R10-{fname}", f"{fname} does not reference port 27125",
              len(wrong) == 0, f"Found {len(wrong)} reference(s) to port 27125")


def test_R16():
    print("\n[R16] No debug print() left in /api/speak handler")
    src = read_file("jatayu/web/server.py")
    debug_prints = re.findall(r'print\s*\(.*\[DEBUG\].*speak', src)
    check("R16-a", "No [DEBUG] print in /api/speak handler", len(debug_prints) == 0,
          f"Found: {debug_prints}")


def test_R24():
    print("\n[R24] google_gmail_send must have requires_confirmation=True")
    src = read_file("jatayu/tools/google_workspace.py")
    block_match = re.search(
        r'Tool\s*\([^)]*name\s*=\s*["\']google_gmail_send["\'][^)]*\)',
        src, re.DOTALL)
    if not block_match:
        check("R24-a", "google_gmail_send Tool() registration found", False,
              "Could not find Tool() block for google_gmail_send")
        return
    block = block_match.group(0)
    check("R24-a", "google_gmail_send has requires_confirmation=True",
          "requires_confirmation=True" in block,
          "Add requires_confirmation=True to google_gmail_send Tool registration")


def test_syntax():
    print("\n[SYNTAX] All key Python files must parse without SyntaxError")
    key_files = [
        "jatayu/brain.py",
        "jatayu/web/server.py",
        "jatayu/safety/gates.py",
        "jatayu/safety/idempotency.py",
        "jatayu/tools/hermes.py",
        "jatayu/tools/google_workspace.py",
        "jatayu/tools/obsidian.py",
        "jatayu/tools/telegram_tool.py",
        "jatayu/memory/retriever.py",
        "jatayu/plugins/anythingllm/plugin.py",
        "jatayu/plugins/browser_use/plugin.py",
    ]
    for rel_path in key_files:
        full = os.path.join(ROOT, rel_path)
        fname = os.path.basename(rel_path)
        if not os.path.exists(full):
            check(f"SYNTAX-{fname}", f"{rel_path} exists", False, "File not found")
            continue
        try:
            with open(full, encoding="utf-8") as f:
                ast.parse(f.read())
            check(f"SYNTAX-{fname}", f"{rel_path} parses cleanly", True)
        except SyntaxError as e:
            check(f"SYNTAX-{fname}", f"{rel_path} parses cleanly", False, str(e))


ALL_TESTS = [
    test_R1, test_R2, test_R3, test_R4, test_R5,
    test_R6, test_R7, test_R8, test_R10, test_R16,
    test_R24, test_syntax,
]

if __name__ == "__main__":
    print("=" * 60)
    print("JATAYU Stabilization Smoke Tests")
    print("=" * 60)
    for fn in ALL_TESTS:
        fn()
    print("\n" + "=" * 60)
    passed = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("\nFailed checks:")
        for r in failed:
            print(f"  x [{r[0]}] {r[2]}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)
