"""The MCP server registers exactly the trading tools (skipped where the mcp package isn't installed)."""
import asyncio
import unittest

try:
    from trader import server
except ModuleNotFoundError:  # the mcp package is only needed by the session
    server = None

TOOLS = {"start_day", "wait_for_open", "screen", "get_facts", "company_news", "account_status", "review_trade",
         "place_trade", "skip_trade", "note_pass", "adjust_stop", "exit_position", "wait_for_next_candle",
         "end_of_day_report"}


@unittest.skipIf(server is None, "mcp not installed")
class ServerTest(unittest.TestCase):
    def test_tool_list(self):
        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(names, TOOLS)

    def test_the_session_workflow_allows_exactly_these_tools(self):
        import re
        from pathlib import Path
        text = Path(__file__).resolve().parent.parent.joinpath(".github/workflows/trading-session.yml").read_text()
        listed = set(re.search(r"for t in (.*?); do", text, re.S).group(1).replace("\\", " ").split())
        self.assertEqual(listed, TOOLS)

    def test_a_failing_tool_returns_its_error(self):
        self.assertEqual(server._safe(lambda: 1 / 0)["error"][:17], "ZeroDivisionError")


if __name__ == "__main__":
    unittest.main()
