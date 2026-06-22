import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_check_python_version_passes():
    """Current Python should pass the >=3.12 check."""
    from setup_wizard import check_python_version

    # Should not raise
    check_python_version()


def test_check_python_version_fails_on_old():
    """Python <3.12 should fail."""
    from setup_wizard import check_python_version

    with patch.object(sys, "version_info", (3, 11, 0)):
        with pytest.raises(SystemExit):
            check_python_version()


def test_check_command_exists_finds_python():
    """python3 should be found on PATH."""
    from setup_wizard import check_command_exists

    assert check_command_exists("python3") is True


def test_check_command_exists_missing():
    """A nonsense command should not be found."""
    from setup_wizard import check_command_exists

    assert check_command_exists("definitely_not_a_real_command_xyz") is False


def test_copy_template_creates_file(tmp_path):
    """copy_template should copy a source file to dest if dest doesn't exist."""
    from setup_wizard import copy_template

    src = tmp_path / "template.md"
    src.write_text("# Template\n")
    dest = tmp_path / "output.md"

    result = copy_template(src, dest)
    assert result is True
    assert dest.read_text() == "# Template\n"


def test_copy_template_skips_existing(tmp_path):
    """copy_template should not overwrite an existing file."""
    from setup_wizard import copy_template

    src = tmp_path / "template.md"
    src.write_text("# Template\n")
    dest = tmp_path / "output.md"
    dest.write_text("# My custom content\n")

    result = copy_template(src, dest)
    assert result is False
    assert dest.read_text() == "# My custom content\n"


def test_exa_credential_exists_detects_env_var(monkeypatch):
    """exa_credential_exists returns True when EXA_API_KEY is already set."""
    from setup_wizard import exa_credential_exists

    monkeypatch.setenv("EXA_API_KEY", "sk-exa-xxx")
    assert exa_credential_exists() is True


def test_exa_credential_exists_returns_false_when_missing(monkeypatch):
    """exa_credential_exists returns False when EXA_API_KEY is absent."""
    from setup_wizard import exa_credential_exists

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert exa_credential_exists() is False


def test_setup_exa_credential_no_mcp_add(monkeypatch, tmp_path):
    """setup_exa_credential must NOT shell out to `claude mcp add` — the Exa MCP
    server is retired; the credential is the EXA_API_KEY env var (§6)."""
    from setup_wizard import setup_exa_credential

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "sk-exa-test-key")
    profile = tmp_path / ".zshrc"
    monkeypatch.setattr("setup_wizard.shell_profile_path", lambda: profile)

    with patch("setup_wizard.subprocess.run") as mock_run:
        setup_exa_credential()
        # Nothing should have been shelled out — no `claude mcp add`.
        for call in mock_run.call_args_list:
            argv = call.args[0] if call.args else []
            assert "mcp" not in argv

    # The key must be persisted as an EXA_API_KEY export in the shell profile.
    written = profile.read_text()
    assert 'export EXA_API_KEY="sk-exa-test-key"' in written


def test_setup_exa_credential_skips_when_already_set(monkeypatch, tmp_path):
    """When EXA_API_KEY is already in the environment, no prompt and no write."""
    from setup_wizard import setup_exa_credential

    monkeypatch.setenv("EXA_API_KEY", "sk-already-set")
    profile = tmp_path / ".zshrc"
    monkeypatch.setattr("setup_wizard.shell_profile_path", lambda: profile)

    def _no_input(_):
        raise AssertionError("should not prompt when EXA_API_KEY already set")

    monkeypatch.setattr("builtins.input", _no_input)
    setup_exa_credential()
    assert not profile.exists()


def test_setup_exa_credential_skip_on_empty_input(monkeypatch, tmp_path):
    """An empty key entry skips persistence (user can add it later)."""
    from setup_wizard import setup_exa_credential

    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "")
    profile = tmp_path / ".zshrc"
    monkeypatch.setattr("setup_wizard.shell_profile_path", lambda: profile)

    setup_exa_credential()
    assert not profile.exists()


def test_validate_install_success():
    """validate_install should return True using the current interpreter."""
    from setup_wizard import validate_install

    # sys.executable is the Python running this test suite — board_aggregator
    # is installed in that environment, so this always runs without skipping.
    assert validate_install(Path(sys.executable)) is True


# --- T3-1: Windows Microsoft Store Python stub detection ----------------------


def test_bare_python_is_stub_detects_exit_49():
    """A bare `python --version` exiting 49 is the Store stub."""
    from setup_wizard import bare_python_is_stub

    with patch("setup_wizard.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=49, stdout="", stderr=""
        )
        assert bare_python_is_stub("python") is True


def test_bare_python_is_stub_detects_localized_message():
    """The Spanish-locale stub message is also recognized (T3-3)."""
    from setup_wizard import bare_python_is_stub

    with patch("setup_wizard.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=9009, stdout="", stderr="No se encontró Python"
        )
        assert bare_python_is_stub("python") is True


def test_bare_python_is_stub_false_for_real_python():
    """A real interpreter (returncode 0, prints version) is not the stub."""
    from setup_wizard import bare_python_is_stub

    with patch("setup_wizard.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Python 3.12.3\n", stderr=""
        )
        assert bare_python_is_stub("python") is False


def test_bare_python_is_stub_false_on_timeout():
    """A hung `python --version` (TimeoutExpired) is treated like not-a-stub (S2)."""
    from setup_wizard import bare_python_is_stub

    with patch("setup_wizard.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=10)
        assert bare_python_is_stub("python") is False


def test_bare_python_is_stub_passes_timeout_to_subprocess():
    """The --version probe must pass a timeout so it can't hang the wizard (S2)."""
    from setup_wizard import bare_python_is_stub

    with patch("setup_wizard.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Python 3.12.3\n", stderr=""
        )
        bare_python_is_stub("python")
    assert mock_run.call_args.kwargs.get("timeout") == 10


def test_check_python_version_rejects_store_stub():
    """check_python_version exits if the running interpreter is the Store stub."""
    from setup_wizard import check_python_version

    with patch("setup_wizard.is_store_stub", return_value=True):
        with pytest.raises(SystemExit):
            check_python_version()


def test_is_store_stub_recognizes_windowsapps_path():
    """An executable under WindowsApps is the Store stub."""
    from setup_wizard import is_store_stub

    fake = r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe"
    with patch("setup_wizard.sys.executable", fake):
        assert is_store_stub() is True


# --- T4-1 / T3-1 / T4-3 / T2-3: static guards on agent + config files ---------


def test_settings_grants_bash_for_prerequisites():
    """settings.json must auto-allow the shell commands primer-8 runs (T4-1)."""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    allow = settings["permissions"]["allow"]
    # Bare `Bash` or the specific prerequisite-check/install patterns must be present.
    assert any(
        rule == "Bash" or rule.startswith("Bash(uname") for rule in allow
    ), "settings.json must allow primer-8 to detect the OS (uname)"
    assert any(rule.startswith("Bash(python3") for rule in allow)
    assert any(rule.startswith("Bash(.venv/bin/pip install") for rule in allow)


def test_settings_grants_install_commands_primer8_runs():
    """settings.json must pre-approve the Stage 1-3 install commands so primer-8
    never has to hand them to the user (T4-1 bypass fix).

    The skeptic's reproducible scenario: Windows with no Node.js -> lead-0
    spawns primer-8 Stage 3 -> primer-8 runs `npm install`. Without an allow
    rule the harness prompts, which violates the 'NEVER hand commands back to
    the user' contract. Each install command primer-8.md issues must match an
    allow rule here.
    """
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    allow = set(settings["permissions"]["allow"])

    def covered(cmd: str) -> bool:
        """True if any Bash(...) rule (literal or trailing-* wildcard) matches cmd."""
        if "Bash" in allow:
            return True
        for rule in allow:
            if not (rule.startswith("Bash(") and rule.endswith(")")):
                continue
            pat = rule[len("Bash(") : -1]
            if pat.endswith(" *"):
                if cmd == pat[:-2] or cmd.startswith(pat[:-1]):
                    return True
            elif cmd == pat:
                return True
        return False

    # The Node/Playwright stage — the exact scenario the skeptic named.
    assert covered("npm install"), "primer-8 Stage 3 runs `npm install` unprompted"
    assert covered("npx playwright install chromium")
    assert covered("node --version")
    # Package-manager installs from Stage 1 / Stage 3.
    for cmd in (
        "brew install python",
        "brew install git",
        "brew install node",
        "sudo apt install python3.12",
        "sudo apt install git",
        "sudo apt install -y nodejs",
        "winget install Python.Python.3.12",
    ):
        assert covered(cmd), f"settings.json must pre-approve: {cmd}"


def test_primer8_declares_bash_tool():
    """primer-8 must declare Bash in its tools and never confess it can't run shell (T4-1)."""
    text = (REPO_ROOT / ".claude" / "agents" / "primer-8.md").read_text()
    # tools: line must include Bash.
    tools_line = next(l for l in text.splitlines() if l.startswith("tools:"))
    assert "Bash" in tools_line
    # The prompt must instruct primer-8 to run the commands itself.
    assert "You run the commands" in text
    assert "NEVER hand a command back to the user" in text


def test_primer8_documents_store_stub_and_utf8():
    """primer-8 must carry the Windows Store-stub + UTF-8 guidance (T3-1/T3-3)."""
    text = (REPO_ROOT / ".claude" / "agents" / "primer-8.md").read_text()
    assert "Microsoft Store" in text
    assert "49" in text  # the stub's exit code
    assert "PYTHONUTF8" in text


def test_primer8_handles_docx_cv():
    """primer-8 must extract .docx CVs itself, not ask the user to paste (T4-3)."""
    text = (REPO_ROOT / ".claude" / "agents" / "primer-8.md").read_text()
    assert "docx_to_text" in text
    assert "do NOT ask the user to paste" in text


def test_discoverer6_validates_urls_before_writing():
    """discoverer-6 must validate portal URLs and drop 4xx/5xx before writing (T2-3)."""
    text = (REPO_ROOT / ".claude" / "agents" / "discoverer-6.md").read_text()
    assert "Validate the URL before writing" in text
    assert "4xx/5xx" in text
    # A FAILed non-Workday probe yields the DROP verdict — entry not written.
    assert "DROP" in text


def test_discoverer6_enforces_validation_in_code():
    """T2-3/GH fix must be CODE-enforced, not prompt-guidance-only: discoverer-6
    needs the Bash tool and must route reachability through a deterministic
    validator whose HTTP-status verdict (not the LLM's judgment) decides the
    write."""
    text = (REPO_ROOT / ".claude" / "agents" / "discoverer-6.md").read_text()
    tools_line = next(l for l in text.splitlines() if l.startswith("tools:"))
    assert "Bash" in tools_line, "discoverer-6 needs Bash to run the validator"
    # A runnable validator that yields a status-driven OK/FAIL verdict.
    assert "urllib" in text
    assert "HTTPError" in text or "4xx/5xx" in text
    assert "OK" in text and "FAIL" in text
    # The agent must be bound to the verdict, not free to write on a hunch.
    assert "by CODE, not judgment" in text
    # GH bypass fix: the agent must call the code validator, not interpret a
    # raw OK/FAIL line itself, and the verdict must be one of three tokens.
    assert "probe-portal" in text, "discoverer-6 must invoke the code validator"
    for token in ("WRITE", "SKIP", "DROP"):
        assert token in text, f"verdict token {token} must be documented"


def test_discoverer6_workday_skip_is_not_a_write():
    """GH bypass: the Workday GET-FAIL path must be a SKIP that can NEVER be
    misread as 'write it with a note'. The prose must say only WRITE writes and
    that flagging is summary-only, never a write."""
    text = (REPO_ROOT / ".claude" / "agents" / "discoverer-6.md").read_text()
    assert "Only `WRITE` ever writes" in text
    # "Flag it" must be explicitly decoupled from writing.
    assert "NEVER means write the entry with a note" in text
    # A non-WRITE token (SKIP/DROP) must leave the entry out.
    assert "MUST NOT be written" in text


# --- GH: code-enforced portal verdict (the actual enforcement) ----------------


def test_portal_verdict_ok_writes():
    """A 2xx probe yields WRITE for any ATS."""
    from setup_wizard import portal_verdict

    for ats in ("greenhouse", "ashby", "lever", "workday", None):
        assert portal_verdict("OK 200", ats) == "WRITE"


def test_portal_verdict_non_workday_fail_drops():
    """A FAILed probe for a non-Workday ATS yields DROP (never written)."""
    from setup_wizard import portal_verdict

    for ats in ("greenhouse", "ashby", "lever", None):
        assert portal_verdict("FAIL http 500", ats) == "DROP"
        assert portal_verdict("FAIL unreachable URLError", ats) == "DROP"


def test_portal_verdict_workday_fail_skips_not_writes():
    """The crux of the GH bypass: a Workday GET FAIL must yield SKIP, and SKIP
    must NOT be WRITE — the entry can never be written off a Workday FAIL."""
    from setup_wizard import portal_verdict

    verdict = portal_verdict("FAIL http 500", "workday")
    assert verdict == "SKIP"
    assert verdict != "WRITE"
    # Redirect-to-error / timeout on Workday is also SKIP, not WRITE/DROP.
    assert portal_verdict("FAIL unreachable HTTPError", "workday") == "SKIP"


def test_probe_portal_routes_status_through_verdict():
    """probe_portal must derive its token from the HTTP status via portal_verdict,
    not from any LLM judgment — a mocked 500 on a non-Workday URL must DROP, and
    the same 500 on a Workday URL must SKIP (code, not prose, decides)."""
    import urllib.error

    from setup_wizard import probe_portal

    http_500 = urllib.error.HTTPError(
        url="x", code=500, msg="err", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=http_500):
        assert probe_portal("https://boards-api.greenhouse.io/v1/boards/x/jobs",
                            "greenhouse") == "DROP"
        assert probe_portal("https://acme.wd1.myworkdayjobs.com/careers",
                            "workday") == "SKIP"


def test_readme_uses_python3():
    """README must invoke python3 explicitly, never bare `python` (T3-1)."""
    text = (REPO_ROOT / "README.md").read_text()
    assert "python setup_wizard.py" not in text
    assert "python -m venv" not in text
    assert "python3 setup_wizard.py" in text
    assert "python3 -m venv" in text


def test_pyproject_includes_python_docx():
    """python-docx must be a declared dependency so the .docx reader is installable (T4-3)."""
    text = (REPO_ROOT / "pyproject.toml").read_text()
    assert "python-docx" in text
