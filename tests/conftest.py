"""Shared pytest configuration: Hypothesis profiles."""
import os

from hypothesis import settings

settings.register_profile("default", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=500, derandomize=True, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
