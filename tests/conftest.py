"""Shared fixtures for KMS tests."""

import sys
import os

# Ensure project root is on sys.path so imports work without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
