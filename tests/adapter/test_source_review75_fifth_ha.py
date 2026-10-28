"""Fifth source-review regressions through actual HA, synthetic only."""
# ruff: noqa: S101, SLF001, INP001, F811, F401
import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from homeassistant.exceptions import HomeAssistantError
from test_audioserver_ha import audio_setup
from test_source_simple_session_ha import session_room
