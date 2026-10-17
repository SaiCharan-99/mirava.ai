"""Test defaults: fakes everywhere, never real keys."""

import os

os.environ["LLM_BACKEND"] = "fake"
os.environ["DECISION_BACKEND"] = "fake"
os.environ["BQ_BACKEND"] = "duckdb"
os.environ["OPENROUTER_API_KEY"] = ""
