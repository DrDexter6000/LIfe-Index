# Agent Onboarding Guide: Life Index

> Purpose: upgrade through `life-index upgrade --plan --json`; first-install or clean-replace through `life-index bootstrap --json`.
>
> Authority: `CHARTER.md` owns invariants. `bootstrap-manifest.json` owns the
> current required authority documents.

This short document delegates each lifecycle to its named CLI authority; the agent
does not rebuild a parallel decision tree from prose.

## System Overview

Life Index is a deterministic toolset for a host agent, not a standalone human-facing intelligent app.
CLI (life-index) is the deterministic tool layer installed in the host agent environment. It records and retrieves journals through explicit commands and has no built-in LLM.
Host agent (for example, Hermes) is the intelligence layer. It reads skills, plans work, orchestrates CLI tools, and synthesizes grounded answers.
GUI is the optional UX layer over the same CLI-backed capabilities. It presents data and relays AI+ questions through /host-agent; the intelligence comes from your host agent, not from the GUI.
Data stays separate from program code. Journals are your local data and remain independent from this repository.

## 1. Before You Start

Verify Python 3.11+, Git, enough package/index disk space, and network access
unless installing from an already available checkout.

If a prerequisite is missing, stop and report the exact missing item.

## 2. Data Safety Rule

Never delete, overwrite, move, or "clean slate" the user's data directory.

The default `~/Documents/Life-Index` data stays separate from code. "fresh install",
"repair", "reinstall", or "upgrade" authorize only code/package work
unless the user explicitly asks for data work. Dedicated venvs, host-managed
checkouts, package metadata, and dependencies are disposable program state;
replace them with a fresh dedicated install when required.
Leave shared/global Python environments and existing developer- or user-owned checkouts untouched. Never uninstall from, repair, or delete them automatically.

## 3. Upgrade, Bootstrap, And Lifecycle Boundaries

Existing program upgrade starts with `life-index upgrade --plan --json`. Do not use
`bootstrap` as the program-upgrade command. Bootstrap is for first-install and
separately authorized data lifecycle planning. If `upgrade` reports
`reinstall_managed_environment`, or no installed command works, use 3A.

### 3A. Program replacement validation

Create a new dedicated checkout and validate only through its exact venv from a neutral cwd, with `PYTHONPATH` cleared and explicit synthetic data. POSIX:
```bash
NEW_ROOT="<new-target>/life-index"
NEUTRAL_CWD="$(mktemp -d)"
SANDBOX_DATA="$(mktemp -d)"
git clone https://github.com/DrDexter6000/life-index.git "$NEW_ROOT"
python3 -m venv "$NEW_ROOT/.venv"
"$NEW_ROOT/.venv/bin/python" -m pip install -e "$NEW_ROOT"
cd "$NEUTRAL_CWD"
env -u PYTHONPATH LIFE_INDEX_DATA_DIR="$SANDBOX_DATA" "$NEW_ROOT/.venv/bin/life-index" --version
env -u PYTHONPATH LIFE_INDEX_DATA_DIR="$SANDBOX_DATA" "$NEW_ROOT/.venv/bin/life-index" bootstrap --json
env -u PYTHONPATH LIFE_INDEX_DATA_DIR="$SANDBOX_DATA" "$NEW_ROOT/.venv/bin/life-index" health --json
```
Windows PowerShell:
```powershell
$NewRoot = Join-Path "<new-target>" "life-index"
$PythonExe = "<path-to-supported-python.exe>"
$NeutralCwd = Join-Path ([IO.Path]::GetTempPath()) ("life-index-neutral-" + [guid]::NewGuid())
$SandboxData = Join-Path ([IO.Path]::GetTempPath()) ("life-index-data-" + [guid]::NewGuid())
git clone https://github.com/DrDexter6000/life-index.git $NewRoot
& $PythonExe -c 'import sys; assert sys.version_info >= (3, 11), f"Python >=3.11 required, got {sys.version}"'
& $PythonExe -m venv (Join-Path $NewRoot ".venv")
& (Join-Path $NewRoot ".venv\Scripts\python.exe") -m pip install -e $NewRoot
New-Item -ItemType Directory -Path $NeutralCwd, $SandboxData | Out-Null
Set-Location $NeutralCwd
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:LIFE_INDEX_DATA_DIR = $SandboxData
& (Join-Path $NewRoot ".venv\Scripts\life-index.exe") --version
& (Join-Path $NewRoot ".venv\Scripts\life-index.exe") bootstrap --json
& (Join-Path $NewRoot ".venv\Scripts\life-index.exe") health --json
```
These version/bootstrap/health results validate program replacement. Do not substitute bare Python, the checkout cwd, or real user data. After they pass, the initiating operator may remove an old root only after proving it is one dedicated managed program directory with user data outside it; ambiguous, shared/global, developer-owned, and user-owned roots stay untouched.

### 3B. Host integration and skill delivery

Host integration is a separate cutover action and is not evidence that program replacement is valid. For a known host home, use the validated launcher to preview then apply on POSIX:
```bash
NEW_ROOT="<new-target>/life-index"
HOST_HOME="<host-home>"
env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --list --json
env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --install --host-home "$HOST_HOME" --dry-run --json
env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --install --host-home "$HOST_HOME" --json
env -u PYTHONPATH "$NEW_ROOT/.venv/bin/life-index" sync-skill --uninstall --host-home "$HOST_HOME" --json
```
Windows PowerShell:
```powershell
$NewRoot = Join-Path "<new-target>" "life-index"
$HostHome = "<host-home>"
$LifeIndex = Join-Path $NewRoot ".venv\Scripts\life-index.exe"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& $LifeIndex sync-skill --list --json
& $LifeIndex sync-skill --install --host-home $HostHome --dry-run --json
& $LifeIndex sync-skill --install --host-home $HostHome --json
& $LifeIndex sync-skill --uninstall --host-home $HostHome --json
```
Surface `delivered=false`. Bare `sync-skill` does not create host directories.
Use the exact commands above to inspect or reverse host delivery. Uninstall only removes agent skill artifacts and never deletes journals, data, checkouts, packages, or host-home parents.

### 3C. Owner-authorized data maintenance

Real-data `migrate`, `index`, `index --rebuild`, and similar maintenance require a separate owner-authorized data-maintenance plan. A bootstrap plan obtained against a real data root is a separate data-maintenance plan. Never execute it merely to accept program replacement. Bootstrap remains authoritative only inside that separately authorized lifecycle.

For an existing checkout, pass `--checkout-path <path>` and, when known, `--checkout-origin host_managed` or `--checkout-origin user_designated`. Use `LIFE_INDEX_NO_NET=1` only when intentionally offline; `freshness: "unknown"` is then expected.

## 4. Execute The Bootstrap Plan

Read the JSON in this order:

1. `needs_human`: if non-empty, relay every item and stop; do not adopt, delete, repair, or continue around it.
2. `execution_policy`: obey it literally. It means:
   - run `safe_next_steps` in order without additions;
   - on uncertainty or command failure, stop and report exact output;
   - replacement creates a fresh dedicated program install, then reruns bootstrap;
   - data is never deleted or overwritten.
3. `safe_next_steps`: run each command exactly within the authorized lifecycle. During 3A, use only its exact venv and synthetic root; never redirect writes into real data, a shared/global environment, or a developer/user checkout.
4. `detected_state`: report facts such as `data_dir`, `install_type`, `freshness`, and `update_available`.

`bootstrap` is read-only. It does not install, migrate, rebuild indexes, sync
skills, modify `.venv`, or touch user journal content. Those actions happen
only if their exact commands appear in `safe_next_steps`.

Retrieval is keyword (FTS5) + Entity Graph — there is no semantic/vector
indexing to wait for, so keyword readiness is all onboarding needs. The
`--semantic*` flags are accepted as deprecated no-ops for backward
compatibility (see WP-CLI-SEM-RM).

## 5. Completion Report

After all `safe_next_steps` finish, report status, route, install and data
locations, steps executed, applicable health/skill-delivery status, and warnings.

If a command fails, include its exact command, exit code, stdout, and stderr.

Do not write test entries in the real data directory. If a user asks for a smoke
test, use an explicit temporary `LIFE_INDEX_DATA_DIR` sandbox.
