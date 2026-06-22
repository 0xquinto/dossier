#!/usr/bin/env python3
"""Guided setup wizard for the dossier pipeline.

Run: python3 setup_wizard.py

This script uses only the standard library so it works before
the virtual environment exists.

Windows note: bare ``python`` frequently resolves to the Microsoft Store
stub, which exits with code 49 and prints "Python was not found" instead of
running. Use ``python3`` (or a real Python 3.12+ from python.org / winget);
``check_prerequisites`` rejects the Store stub if it slips through. Output is
forced to UTF-8 so localized (cp1252) Windows shells don't mangle non-ASCII
characters into mojibake.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Force UTF-8 I/O so localized (cp1252) Windows shells don't mangle non-ASCII
# output into mojibake (T3-3). reconfigure exists on 3.7+; guard for safety.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def is_store_stub() -> bool:
    """Return True if the running interpreter is the Windows Store stub.

    The Microsoft Store ``python``/``python3`` aliases live under
    ``...\\WindowsApps`` and don't actually run code — a bare ``python`` call
    against the stub exits 49 with "Python was not found". If the wizard itself
    was launched through the stub we'd never get here (it wouldn't execute), but
    detect it defensively in case a venv/symlink points back at it.
    """
    exe = sys.executable or ""
    return "windowsapps" in exe.replace("/", "\\").lower()


def check_python_version():
    """Exit if Python < 3.12 or if running under the Windows Store stub."""
    if is_store_stub():
        print(
            "ERROR: this is the Microsoft Store Python stub, not a real "
            "interpreter.\n"
            "  Install real Python 3.12+ (winget install Python.Python.3.12, "
            "or python.org),\n"
            "  then re-run with: py -3 setup_wizard.py"
        )
        sys.exit(1)
    if sys.version_info < (3, 12):
        print(f"ERROR: Python >= 3.12 required (found {sys.version})")
        sys.exit(1)
    print(f"  Python {sys.version_info.major}.{sys.version_info.minor} ✓")


def check_command_exists(cmd: str) -> bool:
    """Return True if cmd is found on PATH."""
    return shutil.which(cmd) is not None


def portal_verdict(probe_line: str, ats: str | None) -> str:
    """Map an HTTP-probe result line + ATS to a mechanical write verdict.

    This is the CODE that decides whether discoverer-6 may write a portal
    entry — the verdict is derived from the HTTP status the server returned,
    NOT from the agent's interpretation of a snippet. discoverer-6 invokes
    this (see ``probe_portal`` / the CLI below) and obeys the printed token
    verbatim. Three tokens, and only ``WRITE`` ever results in a write:

    - ``WRITE`` — the probe returned ``OK <2xx>``; the URL is reachable.
    - ``SKIP``  — a Workday entry whose GET probe FAILed. Workday postings
      live behind a POST ``cxs`` endpoint a GET can't exercise, so a GET FAIL
      is NOT proof the portal is dead — but it is NOT proof it's live either,
      so the entry is still NOT written this run (flag it in the summary).
      ``SKIP`` is deliberately distinct from ``WRITE`` so "flag it" can never
      be misread as "write it with a note".
    - ``DROP``  — any other FAIL (greenhouse/ashby/lever/custom 4xx/5xx,
      redirect-to-error, network/DNS/timeout). The link is broken; never write.

    The probe line is what the urllib one-liner prints: ``OK <status>`` for a
    2xx, ``FAIL ...`` for anything else.
    """
    is_ok = probe_line.strip().startswith("OK ")
    if is_ok:
        return "WRITE"
    # Not OK. Workday GET FAIL is inconclusive -> SKIP (still never written);
    # every other ATS FAIL is a confirmed dead link -> DROP.
    if ats == "workday":
        return "SKIP"
    return "DROP"


def probe_portal(url: str, ats: str | None = None) -> str:
    """Probe a portal URL over HTTP(GET) and return a mechanical verdict token.

    Stdlib only (works before the venv exists). Performs the same GET the
    scanner will hit, then routes the ``OK``/``FAIL`` result through
    ``portal_verdict`` so the Workday special case is enforced in code, not
    prose. Prints/returns exactly one of ``WRITE`` / ``SKIP`` / ``DROP``.
    """
    import urllib.error
    import urllib.request

    try:
        resp = urllib.request.urlopen(
            urllib.request.Request(
                url, method="GET", headers={"User-Agent": "dossier-portal-validator"}
            ),
            timeout=15,
        )
        probe_line = f"OK {resp.status}"
    except urllib.error.HTTPError as ex:
        probe_line = f"FAIL http {ex.code}"
    except Exception as ex:  # URLError, timeout, DNS, etc.
        probe_line = f"FAIL unreachable {type(ex).__name__}"
    return portal_verdict(probe_line, ats)


# Exit code the Microsoft Store Python stub returns when invoked.
_STORE_STUB_EXIT_CODE = 49


def bare_python_is_stub(cmd: str = "python") -> bool:
    """Return True if a bare ``python`` resolves to the Windows Store stub.

    The stub exits with code 49 ("Python was not found" / localized
    "No se encontró Python") instead of running. Used to warn the user off the
    bare alias and steer them to the real interpreter / venv path.

    A hung probe (no exit, no output) is treated like a missing/non-stub
    interpreter: ``timeout`` caps the wait and ``TimeoutExpired`` returns False,
    same as the ``OSError`` (command-not-found) path.
    """
    try:
        result = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode == _STORE_STUB_EXIT_CODE:
        return True
    blob = (result.stdout + result.stderr).lower()
    return "was not found" in blob or "no se encontr" in blob


def check_prerequisites():
    """Check all required tools are available."""
    print("\n=== Step 1: Checking prerequisites ===\n")
    check_python_version()

    if os.name == "nt" and bare_python_is_stub("python"):
        print(
            "  NOTE: bare `python` on this machine is the Microsoft Store stub "
            "(exit 49).\n"
            "  Always call the venv interpreter by path "
            "(.venv\\Scripts\\python.exe) — not bare `python` — in this project."
        )

    if check_command_exists("claude"):
        print("  Claude Code ✓")
    else:
        print("ERROR: Claude Code is required — install from https://claude.ai/download")
        sys.exit(1)

    if check_command_exists("git"):
        print("  git ✓")
    else:
        print("ERROR: git is required")
        sys.exit(1)


def copy_template(src: Path, dest: Path) -> bool:
    """Copy src to dest if dest doesn't exist. Returns True if copied."""
    if dest.exists():
        print(f"  {dest.name} already exists — skipping")
        return False
    shutil.copy2(src, dest)
    print(f"  Created {dest.name} from template")
    return True


def setup_venv():
    """Create virtual environment and install the package."""
    print("\n=== Step 2: Setting up virtual environment ===\n")
    venv_dir = ROOT / ".venv"
    if venv_dir.exists():
        print("  .venv already exists — skipping creation")
    else:
        print("  Creating .venv ...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        print("  .venv created ✓")

    pip = venv_dir / "bin" / "pip"
    print("  Installing board-aggregator + dev deps ...")
    subprocess.run(
        [str(pip), "install", "-e", ".[dev]"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
    )
    print("  Installed ✓")


def setup_templates():
    """Copy template files for user customization."""
    print("\n=== Step 3: Setting up your profile ===\n")
    templates = ROOT / "templates"

    skills_copied = copy_template(
        templates / "skills-inventory.example.md",
        ROOT / "skills-inventory.md",
    )
    resume_copied = copy_template(
        templates / "resume.example.md",
        ROOT / "resume.md",
    )

    editor = os.environ.get("EDITOR")
    files_to_edit = []
    if skills_copied:
        files_to_edit.append(ROOT / "skills-inventory.md")
    if resume_copied:
        files_to_edit.append(ROOT / "resume.md")

    if files_to_edit and editor:
        for f in files_to_edit:
            print(f"\n  Opening {f.name} in {editor} ...")
            subprocess.run([editor, str(f)])
    elif files_to_edit:
        print("\n  Please edit these files with your information:")
        for f in files_to_edit:
            print(f"    - {f}")


def exa_credential_exists() -> bool:
    """Return True if the EXA_API_KEY environment variable is already set."""
    return bool(os.environ.get("EXA_API_KEY"))


def shell_profile_path() -> Path:
    """Return the shell profile file the EXA_API_KEY export should be appended to.

    Prefers the file matching the user's $SHELL (~/.zshrc for zsh, ~/.bashrc
    otherwise), defaulting to ~/.zshrc — matches primer-8's onboarding path.
    """
    shell = os.environ.get("SHELL", "")
    if "bash" in shell:
        return Path.home() / ".bashrc"
    return Path.home() / ".zshrc"


def setup_exa_credential():
    """Configure the EXA_API_KEY environment variable for the shared client.

    Phase 3 (contact research) and discovery reach Exa through the shared
    ``dossier-research`` client, which reads ``EXA_API_KEY`` — not an MCP
    server. Persist the key as an ``export`` in the user's shell profile so
    every pipeline session can authenticate.
    """
    print("\n=== Step 4: Exa credential (EXA_API_KEY) ===\n")

    if exa_credential_exists():
        print("  EXA_API_KEY already set ✓")
        return

    print("  An Exa API key is required for Phase 3 (contact research).")
    print("  Get a free key at https://dashboard.exa.ai/home")
    exa_key = input("  Exa API key (Enter to skip): ").strip()

    if not exa_key:
        print("  Skipped — set it later by adding this to your shell profile:")
        print('    export EXA_API_KEY="<key>"')
        return

    profile = shell_profile_path()
    with open(profile, "a", encoding="utf-8") as fh:
        fh.write(f'\nexport EXA_API_KEY="{exa_key}"\n')
    print(f"  EXA_API_KEY exported in {profile} ✓")
    print("  Open a new shell (or re-source the profile) to pick it up.")


def validate_install(python_path: Path | None = None) -> bool:
    """Run smoke tests to verify the installation works."""
    print("\n=== Step 5: Validating installation ===\n")
    python = str(python_path) if python_path else str(ROOT / ".venv" / "bin" / "python")

    # Test import
    result = subprocess.run(
        [python, "-c", "from board_aggregator import __version__; print(__version__)"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  FAIL: could not import board_aggregator")
        print(f"  {result.stderr.strip()}")
        return False
    print(f"  board_aggregator {result.stdout.strip()} ✓")

    # Test CLI
    board_agg = Path(python).parent / "board-aggregator"
    result = subprocess.run(
        [str(board_agg), "--list-scrapers"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  FAIL: board-aggregator CLI not working")
        return False
    scraper_count = len([l for l in result.stdout.strip().split("\n") if l.strip().startswith("-")])
    print(f"  board-aggregator CLI ({scraper_count} scrapers) ✓")

    return True


def print_next_steps():
    """Print what the user should do next."""
    print("\n" + "=" * 50)
    print("Setup complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print()
    print("  1. Edit your skills inventory:")
    print("     skills-inventory.md")
    print()
    print("  2. Edit your resume:")
    print("     resume.md")
    print()
    print("  3. Run the pipeline:")
    print("     claude --agent lead-0")
    print()


def main():
    """Run the full setup wizard."""
    print("=" * 50)
    print("dossier — Setup Wizard")
    print("=" * 50)

    check_prerequisites()
    setup_venv()
    setup_templates()
    setup_exa_credential()

    python = ROOT / ".venv" / "bin" / "python"
    if not validate_install(python):
        print("\nSetup had errors. Please check the messages above.")
        sys.exit(1)

    print_next_steps()


if __name__ == "__main__":
    # `probe-portal <url> [ats]` — discoverer-6 invokes this to get a
    # code-derived WRITE/SKIP/DROP verdict instead of judging reachability
    # itself. Kept as a subcommand so the wizard's normal run is unaffected.
    if len(sys.argv) >= 3 and sys.argv[1] == "probe-portal":
        url = sys.argv[2]
        ats = sys.argv[3] if len(sys.argv) > 3 else None
        print(probe_portal(url, ats))
        sys.exit(0)
    main()
