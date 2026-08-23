"""ASGI entry point for local development."""

from research_report_agent.api import create_app

app = create_app()
