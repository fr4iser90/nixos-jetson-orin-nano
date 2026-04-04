"""
Default shipped plugin tree: one **domain folder** per concern, each containing ``*.py`` modules
(``TOOLS`` + ``HANDLERS``). The registry scans **recursively** (see ``registry._iter_plugin_py_files``).

Layout (examples)::

    clocks/clock.py
    github/github.py
    gmail/gmail.py
    calendar/calendar_ics.py
    kb/kb.py
    todos/todos.py
    web_search/web_search.py
    workspace/workspace.py
    secrets/register_secrets.py, secrets/secrets_help.py
    tool_help/tool_help.py
    plugin_factory/create_tool.py

Extra plugins under ``AGENT_PLUGINS_EXTRA_DIR`` may use the same nested layout.
"""
