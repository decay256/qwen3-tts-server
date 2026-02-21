"""Shared fixtures for pytest."""

import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set test auth token before any imports
os.environ["AUTH_TOKEN"] = "test-token-12345"
