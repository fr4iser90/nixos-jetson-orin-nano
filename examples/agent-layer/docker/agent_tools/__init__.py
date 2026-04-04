"""
Default shipped tool tree: one **domain folder** per concern, each containing ``*.py`` modules
(``TOOLS`` + ``HANDLERS``). The registry scans **recursively** (see ``registry._iter_tool_py_files``).

Layout (examples)::

    clocks/clock.py
    github/github.py
    gmail/gmail.py
    calendar/calendar_ics.py
    kb/kb.py
    todos/todos.py
    web_search/web_search.py
    openweather/openweather.py
    workspace/workspace.py
    secrets/register_secrets.py, secrets/secrets_help.py
    tool_help/tool_help.py
    tool_factory/create_tool.py
    tool_factory/list_tools.py
    tool_factory/read_tool.py
    tool_factory/update_tool.py
    tool_factory/replace_tool.py
    tool_factory/rename_tool.py

Extra tools under ``AGENT_TOOLS_EXTRA_DIR`` may use the same nested layout.
"""
