"""Pure helpers for the Windows tray agent (no GUI)."""

from __future__ import annotations

from steadygrind.windows_agent import is_kickr_command, parse_netstat_listening_pids


def test_is_kickr_command_matches_names() -> None:
    assert is_kickr_command(r"C:\Apps\steadyGrind\steadyGrind.exe --windows-agent")
    assert is_kickr_command("python -m steadygrind")
    assert is_kickr_command("kickr_pi --server-only")
    assert not is_kickr_command("chrome.exe")


def test_parse_netstat_listening_pids() -> None:
    sample = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       4242
  TCP    0.0.0.0:80800          0.0.0.0:0              LISTENING       9999
  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       111
"""
    assert parse_netstat_listening_pids(sample, 8080) == [4242]
    assert parse_netstat_listening_pids(sample, 80) == [111]
    assert parse_netstat_listening_pids(sample, 9) == []
