"""Additional tests for SessionManager — device sessions and chat management."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
config.MAX_MEMORY_TOKENS = 1000
config.MAX_HISTORY_TOKENS = 10000
config.MAX_TOOL_TURNS = 10
config.COMPACT_KEEP_FIRST = 2
config.COMPACT_KEEP_LAST = 4
config.CHIKA_API_KEY = ""

from api.session_manager import SessionManager
from chika.core.engine import ChikaEngine


class TestGetDeviceSession:
    def test_creates_session_for_new_device(self):
        sm = SessionManager()
        engine, session_id = sm.get_device_session("dev_test_001")
        assert isinstance(engine, ChikaEngine)
        assert session_id.startswith("sess_")

    def test_same_device_returns_same_session(self):
        sm = SessionManager()
        _, sid1 = sm.get_device_session("dev_test_002")
        _, sid2 = sm.get_device_session("dev_test_002")
        assert sid1 == sid2

    def test_different_devices_return_different_sessions(self):
        sm = SessionManager()
        _, sid1 = sm.get_device_session("dev_test_003a")
        _, sid2 = sm.get_device_session("dev_test_003b")
        assert sid1 != sid2


class TestNewChatForDevice:
    def test_creates_new_session(self):
        sm = SessionManager()
        _, sid1 = sm.get_device_session("dev_test_004")
        _, sid2 = sm.new_chat_for_device("dev_test_004")
        assert sid2.startswith("sess_")
        assert sid1 != sid2

    def test_new_chat_updates_device_mapping(self):
        sm = SessionManager()
        sm.get_device_session("dev_test_005")
        _, new_sid = sm.new_chat_for_device("dev_test_005")
        _, current_sid = sm.get_device_session("dev_test_005")
        assert current_sid == new_sid

    def test_new_chat_returns_engine(self):
        sm = SessionManager()
        engine, _ = sm.new_chat_for_device("dev_test_006")
        assert isinstance(engine, ChikaEngine)


class TestSwitchDeviceChat:
    def test_switches_to_specified_chat(self):
        sm = SessionManager()
        engine_a, sid_a = sm.new_chat_for_device("dev_test_007")
        engine_b, sid_b = sm.new_chat_for_device("dev_test_007")
        # Switch back to first session
        engine_switched, sid_switched = sm.switch_device_chat("dev_test_007", sid_a)
        assert sid_switched == sid_a

    def test_switch_updates_device_mapping(self):
        sm = SessionManager()
        _, sid_a = sm.new_chat_for_device("dev_test_008")
        _, sid_b = sm.new_chat_for_device("dev_test_008")
        sm.switch_device_chat("dev_test_008", sid_a)
        _, current_sid = sm.get_device_session("dev_test_008")
        assert current_sid == sid_a

    def test_switch_returns_engine(self):
        sm = SessionManager()
        _, sid_a = sm.new_chat_for_device("dev_test_009")
        engine, _ = sm.switch_device_chat("dev_test_009", sid_a)
        assert isinstance(engine, ChikaEngine)
