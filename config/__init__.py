"""
Expose the project settings as a local package and avoid pulling the external
`config` library that may be installed in the environment.
"""

from . import settings

__all__ = ["settings"]
