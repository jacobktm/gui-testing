# Code review — gui-testing

Reviewed at `cabf558` ("Rewrite idle handling with per-desktop backends", == `origin/main`).
Date: 2026-11-05.

**Method:** static review only — the suite reboots the machine and mutates desktop
settings, so nothing here was produced by running it. Findings come from three
scoped sub-reviews (capture/vision layer, artifacts/reboot/conftest, docs &
packaging) plus a direct pass over the core, workflows, tests and shell scripts.
Every `file:line` citation was read and confirmed. Items marked
**[verify-on-hw]** need a check on real hardware before acting on them.

**Tracking:** `- [ ]` = open. Tick as fixed; add a `fixed in <commit>` note when done.
Severity: **critical** > **high** > **medium** > **low**.

---

## Verdict

The vision-driven approach is sound and the scaffolding is largely well-built
(atomic manifest writes, reboot-aware phase machines, platform flavor registry,
artifact discipline). The systemic problem is the opposite of missing features:
**failures are swallowed at every layer, so a broken run still reports success.**
The `except Exception: pass` / `2>/dev/null || true` idiom has quietly turned
several "features" into no-ops.

### Top risks

| # | Severity | Issue | Status |
|---|---|---|---|
| 1 | critical | Sudoers rule grants `python3 -m harness.reboot` → trivial root escalation | [x] fixed 2026-11-05 |
| 2 | critical | Autologin + sudoers + resume unit leak permanently on any run that never reboots | [x] fixed 2026-11-05 (boot recovery unit + conftest username fix) |
| 3 | high | Report prints `passed: 8 / total: 8` — it reports artifacts, not pytest outcomes | [x] fixed 2026-11-05 (§3) |
| 4 | high | GUI visual verification can never fail a CLI graphics transition test | [x] fixed 2026-11-05 (§4) |
| 5 | high | Original-graphics-mode cleanup is a guaranteed no-op | [x] fixed 2026-11-05 |
| 6 | high | Resume script uses bash-only `${PIPESTATUS}` under `#!/bin/sh` | [x] fixed 2026-11-05 |

### What's good (keep)

- Rename-atomic manifest writes (`harness/artifacts/manifest.py:144-159`).
- Per-item persisted phase state lets transitions survive reboots
  (`harness/workflows/base.py:23-63`, used by `workflows/system76_power/cli.py`).
- Brightness reboot test already does durable-write correctly: `sync()` + verify
  re-read + abort before rebooting (`workflows/system76_power/cli.py:610-641`) —
  good template for the other reboot paths.
- Platform flavor registry (`harness/platform/{base,registry}.py`) is the right
  shape for "register, don't branch".
- `AutologinManager.enable()` refuses to overwrite an unreadable config and
  snapshots first (`harness/reboot/session.py:548-562`); `force_restore_autologin()`
  escape hatch; `detect_gui_user()` handles pytest-under-sudo
  (`harness/reboot/session.py:308-346`).
- Screenshot capture race handling and per-capture crop scale
  (`harness/screenshots/screenshot.py:557-629`); display-detection fallback chain
  (`harness/gui/coords.py:87-180`); Set-of-Mark ID-lookup strategy.
- `config.json` is gitignored and untracked; no secrets committed;
  `requires-python >= 3.11` consistent everywhere.

---

## 1. Security: sudoers rule — critical *(resolved 2026-11-05)*

**What was done:** `pytest.sh` now installs a root-owned wrapper at
`/usr/local/libexec/gui-testing-privileged` plus a root-owned snapshot of
`harness/` at `/usr/local/libexec/gui-testing`, and the sudoers rule grants only
three fixed absolute paths (the wrapper, `/usr/bin/systemctl reboot`, and
`/usr/bin/systemctl restart com.system76.PowerDaemon.service`) — no wildcards.
The wrapper `cd`s into the snapshot before exec'ing `python3 -B -s -m
harness.reboot`, so no user-writable directory is ever on `sys.path` for the
root-side code. New module `harness/reboot/helper.py` holds both the client
helpers and the root-side primitives, with a hard-coded path allowlist; the
sudoers file itself is only ever removed, never written, so a run cannot widen
its own grant. Reboot paths in `harness/reboot/system.py`, cleanup paths in
`harness/reboot/__init__.py` / `autostart.py` / `conftest.py`, and the
autologin writes in `session.py` all route through it. Verified: no `sudo -n
python3 -m`, `sudo -n tee/cat/rm/mkdir` call sites remain; allowlist rejects
`/etc/shadow`, `/etc/sudoers`, traversal paths and nested state paths;
`bash -n` and `compileall` clean. **Not yet verified on hardware** — needs a
real `./pytest.sh` run to confirm the reboot/autologin sequence end to end.

- [x] **critical** `pytest.sh:128-132` — rule granted
  `/usr/bin/python3 -m harness.reboot <subcmd>`; `sudo` keeps CWD and `python3 -m`
  puts CWD on `sys.path`, so
  `mkdir /tmp/evil/harness && cd /tmp/evil && sudo -n python3 -m harness.reboot status`
  ran attacker-controlled Python **as root**. → replaced by the fixed root-owned
  wrapper described above.
- [x] **critical** same rule granted `tee /etc/greetd/config.toml` (arbitrary
  autologin as root), `tee /proc/sysrq-trigger`, and `reboot -f`. → all wildcard
  grants removed; autologin edits and SysRq writes are now allowlisted
  subcommands of the helper.
- [x] **high** `pytest.sh:129-131` — the sudoers file was installed *before*
  `visudo -c`, and validation was `|| true` → a typo could break `sudo`
  system-wide while the script continued. → now built in a temp file, validated
  with `sudo visudo -cf`, and only then installed with
  `sudo install -m 0440 -o root -g root`; on validation failure the rule is not
  installed and the script says so.
- [x] **medium** whitelist drift: `disable` is not a valid subcommand
  (`harness/reboot/__main__.py:76`); `reboot` **is** used
  (`harness/reboot/system.py:153`) but was not whitelisted, so that fallback always
  failed; `tee /var/lib/gui-testing/autologin` did not match the real path
  `/var/lib/gui-testing/autologin.json` (`harness/reboot/session.py:48`);
  `tee /etc/greetd/gdm3` matched nothing. → moot: the wildcard entries are gone,
  and the previously-broken `reboot` fallback now works through the helper.
  `systemctl restart com.system76.PowerDaemon.service` was deliberately kept as a
  narrow grant because the brightness and graphics tests use it.

**Fix:** root-owned helper script at a fixed path
(`/usr/local/libexec/gui-testing-reboot`, `root:root 0755`, not user-writable) with
behaviour hard-coded; whitelist exactly that path. Validate with `visudo -cf` on a
temp file *before* installing.

---

## 2. Run lifecycle & cleanup — critical/high

Cleanup is bolted to the end of the pytest process — the one component a reboot or
crash kills.

- [x] **critical** `pytest.sh:176,179` use `exec pytest`, which replaces the shell
  → `trap cleanup EXIT` (`pytest.sh:162`) is dead code.
  Fixed: pytest runs as a child, its status is captured and re-raised via
  `exit "$status"`, so the trap fires on normal completion. A hard reboot still
  kills the shell before any trap — the boot-time recovery unit (§2 cross-
  cutting fix, now implemented) is the backstop for that case.
- [x] **critical** `conftest.py:309` returns early when `username is None`. On the
  initial non-resumed run started by `pytest.sh`, `_gui_reboot_setup` is `None`
  because `GUI_TESTING_SETUP_DONE=1` (`conftest.py:256-268`). So a run that
  completes *without* rebooting skips `finish_reboot`, the graphics restore, and
  sudoers removal → autologin stays enabled and `/etc/sudoers.d/gui-testing` stays
  on disk forever, plus an enabled resume unit that hijacks the next boot.
  `RUN_DESTRUCTIVE_TESTS` defaults to `1` (`pytest.sh:23`) and setup is
  unconditional (`pytest.sh:110-113`), so this is the normal case on a
  non-switchable machine.
  Fixed: the username fallback now also triggers on `GUI_TESTING_SETUP_DONE=1`,
  so `finish_reboot` runs even when the run never rebooted.
- [x] **high** `conftest.py:341-367` — final reboot runs *before* sudoers removal,
  so the removal code never executes; `finish_reboot`'s
  `sudo rm -f /etc/sudoers.d/gui-testing` (`harness/reboot/__init__.py:254-259`) is
  not whitelisted. Net: sudoers survives every multi-boot run.
  Fixed: `finish_reboot(revoke_sudoers=False)` keeps the grant alive across the
  final reboot attempts, the explicit removal after them handles the
  reboot-failed case, and when the reboot *succeeds* (killing pytest before the
  removal) the run marker is cleared before the reboot, so the boot-time
  recovery unit revokes sudoers on the way back up.
- [x] **high** `harness/reboot/autostart.py:99,173` — generated resume script is
  `#!/bin/sh` but uses `${PIPESTATUS[0]}`. Under dash that's a fatal "Bad
  substitution", so the script's `systemctl --user disable` never runs; only
  `finish_reboot` ever removes the unit.
  Fixed: output now appends straight to the log file (`status=$?`), which is
  POSIX; the unit's journal keeps the live stream. Verified with `sh -n` on the
  generated script. This was the direct cause of the resume unit re-arming on
  every boot in the Pop!_OS run logs.
- [x] **high** `autostart.py:33` `MAX_ATTEMPTS = 60` vs
  `harness/reboot/resume.py:76-85` `bump_attempts(limit=10)` (no callers — dead).
  A corrupt resume dir (`RunArtifacts.load` raises in `pytest_configure`,
  `harness/artifacts/store.py:177`) burns up to 60 autonomous autologin boots with
  no cleanup.
  Fixed: cap lowered to 12 boots, hitting it writes `<run_dir>/resume/GAVE_UP`
  and disables the unit; the 60-boot loop is further defused by the boot
  recovery unit. `bump_attempts` remains dead but is now documented as such in
  `autostart.py`. *(Since deleted outright — see §8.)*
- [ ] **high** `autostart.py:140-143` — no graphical session within 120 s ⇒ disable
  unit and give up, stranding autologin + sudoers. COSMIC cold boot can exceed
  120 s **[verify-on-hw]**. *(Mitigated 2026-11-05: the stranded autologin and
  sudoers now self-heal via the boot recovery unit once the marker ages out;
  the 120 s budget itself is still unverified.)*
- [x] **high** durability: primary reboot is `sudo -n reboot -f`
  (`harness/reboot/system.py:102-108`); `sync` only on the last-resort path
  (`system.py:151`). `save_state` is not rename-atomic
  (`harness/artifacts/store.py:434` `destination.write_text`), `resume.py:70-73`
  writes lack `fsync`. A hard reboot mid-write rolls the phase machine back to
  `"start"` → re-switch graphics, re-reboot, silently re-run completed GUI tests.
  *(fixed 2026-11-05: `manifest.durable_write_text()` — mkstemp → fsync →
  atomic replace → dir fsync — now backs `write_manifest`, `store._save_text`
  (hence `save_state`), `resume.py` completion/attempts records, the reboot
  markers + boot-id file in `system.py`, `power_state.py` documents, and the
  run marker in `recovery.py`.)*
- [x] **high** `harness/reboot/system.py:112-170` — `reboot()` returns `True` even
  when every method failed; `wait_for_boot()` returns `True` when unconfirmed →
  post-reboot verification can "pass" on a machine that never rebooted.
  *(fixed 2026-11-05: `reboot()` records the pre-reboot boot ID durably (marker
  content + `~/.local/share/gui-testing/boot-id`) and returns `False` when no
  method changed it, SysRq included; `wait_for_boot()` confirms the new boot
  (boot-ID change, or legacy marker signature) and returns `False` with a loud
  error if the system is up on the same boot. All `_reboot_and_wait` callers in
  `workflows/system76_power/{cli,gui}.py` now fail the transition with a
  persisted `{"error": "reboot did not happen"}` entry instead of verifying
  anyway. Offline selftest covers unconfirmed and confirmed paths.)*
- [x] **medium** `harness/reboot/__init__.py:174,196` use `subprocess` before it is
  imported (line 208) → the `sudo rm` fallbacks were swallowed `NameError`s, and
  that removal was never whitelisted anyway. Fixed with the change to §1:
  `subprocess` is imported at module level and the fallbacks now call the
  privileged helper (`cleanup-unit`, which also clears the `.wants` symlink).
  Still open: `finish_reboot` returns `unit_removed or restored`, masking
  "machine still auto-logs in".
- [x] **medium** `harness/reboot/__main__.py` — the trailing `restore` branch
  raised `UnboundLocalError` on `remove_resume_unit` (the `cleanup-all` branch
  imported it locally, making it local to `main()`), so `… reboot restore` always
  crashed *after* restoring autologin — hidden by `2>/dev/null || true` in
  `pytest.sh`. Discovered while routing `restore` through the helper; fixed.
- [x] **medium** `conftest.py:249-270` — resume unit installed at collection time
  can outlive the run; a stale `--resume-run` hijacks the next boot.
  Fixed: the resume script's `systemctl --user disable` now actually runs (the
  PIPESTATUS bug above), `finish_reboot`/`remove_resume_unit` also clear the
  `graphical-session.target.wants` symlink, and the boot recovery unit deletes
  any surviving unit + symlink when no run marker is fresh.
- [ ] **medium** `conftest.py:207` — completed-test override sets
  `item.runtest = lambda: None`, so fixtures still run on every boot.
- [x] **medium** `conftest.py:327-335` — graphics-restore cleanup can reboot,
  killing everything scheduled after it (sudoers cleanup, report).
  Fixed: the report is written before any of this (`_finalize_run` runs at the
  top of `pytest_sessionfinish`), the run marker is cleared *before* the
  graphics-restore reboot, and leftover sudoers teardown is guaranteed by the
  boot recovery unit.
- [ ] **medium** `harness/cleanup.py` is `atexit`-based → never fires under
  reboot/SIGKILL, i.e. exactly when the graphics-power cleanup
  (`handlers/system76_power/system76_power.py:293-301`) matters.
- [ ] **medium** `pytest.sh:59-72` `--clean` deletes failed/unknown runs by mtime
  (keeps 5), contradicting conftest's `KeepLast(10)+KeepFailures`
  (`conftest.py:104`).
- [x] **low** `harness/reboot/autostart.py:262-311` `remove_resume_unit` never runs
  `systemctl --user disable` (`pass` at 288-291) → stale `wants/` symlink.
  Fixed: `remove_resume_unit` and `finish_reboot` now unlink the wants symlink
  alongside the unit file (`wants_path_for`), the resume script's disable works
  again, and the recovery script sweeps dangling wants links as a last resort.
- [ ] **low** `harness/reboot/__main__.py:137-149` — `cleanup-all` globs resolve to
  `/home/artifacts/*` (never match) and its `rglob` can delete an **active** run's
  reboot markers.
- [x] **low** `harness/artifacts/store.py:74-75` — `__all__` lists methods, not names.
  Fixed: removed the nonexistent `load_state`/`save_state` entries (state I/O
  lives on `RunArtifacts`); `__all__` now matches what `__init__` re-exports.

**Cross-cutting fix that defuses most of the above — implemented 2026-11-05**
(`harness/reboot/recovery.py`, installed by `pytest.sh`): a system-level oneshot
**boot unit** (`gui-testing-recover.service`) that — unless
`/var/lib/gui-testing/keep-setup` exists and no run marker
(`~/.local/share/gui-testing/run-active`, refreshed every boot from
`conftest.py`) is fresher than 12 h — removes `/etc/sudoers.d/gui-testing`, runs
the helper's new `recover` action (restore autologin + delete resume units),
sweeps leftovers by hand when the helper is gone, and disables itself. The unit
stays enabled after clean boots (each `./pytest.sh` re-arms it) so the machine
converges back to a testable state no matter how the pytest process died —
reboot, crash, Ctrl-C, or a corrupt resume dir.

---

## 3. Reporting: the report is not a test report — high

- [x] **high** `harness/report/writer.py:57-70` counts **manifest entries**
  (artifact item ids), not pytest outcomes — that is why a session with 57
  collected tests, several failures and many skips printed `passed: 8 / total: 8`.
  Fixed: conftest now records per-test verdicts (`nodeid` →
  passed/failed/skipped/error across all phases, merged with the completed
  ledger across boots) and `write_text` drives the summary and per-test
  section from `manifest.metadata.pytest_results`, flagging collected-but-
  never-ran tests as `[NOT RUN]`. Manifest entries are listed under
  "Workflow item evidence".
- [x] **high** `conftest.py:418-425` stamps the current test's outcome onto
  **every** still-`unknown` manifest entry (`tests[:before]`), regardless of item
  id.
  Fixed: only entries created *during* the test (the `[before:]` slice) are
  stamped; pre-existing entries belong to other tests/boots and stay unknown
  until their own test verdicts them.
- [x] **high** `harness/artifacts/store.py:134-140` `_derive_status` treats
  `unknown` as non-failing, so `KeepFailures`
  (`harness/artifacts/retention.py:129-130`) deletes evidence from
  interrupted/failed runs.
  Fixed: any `unknown` item now derives an `unknown` run status (never
  `passed`), and `KeepFailures` keeps every non-passed run. conftest also
  sets the run status explicitly from pytest outcomes (failed on any
  failed/error; unknown on not-run leftovers, unknown items, or an all-skipped
  session).
- [x] **medium** `harness/report/writer.py:104` — `write_text` swallows all errors
  and returns `None`; `write_html`/`write_pdf` raise `NotImplementedError`
  (`writer.py:107-113`).
  Fixed: write/archive failures now print the error instead of vanishing.
  `write_html`/`write_pdf` still raise for unimplemented formats — intentional,
  nothing calls them.

**Fix:** drive the report from pytest's own outcome data (conftest already tracks
it), keep the manifest as supporting evidence, make `unknown` non-passing for
retention decisions.

---

## 4. GUI verification is vacuous on CLI graphics transitions — high

Why Pop 22.04 never visually verified a graphics transition (three independent
layers):

- [x] **high** `workflows/system76_power/cli.py:400-405` — `verified = target_ok`
  then `if gui_verified is not None and gui_verified is False:` →
  `verified = target_ok`. The branch is a literal no-op, so the visual check can
  never change the result.
  Fixed: no-op branch deleted. New `System76PowerCLIWorkflow._gui_verify_graphics_mode()`
  is the single source of truth (also captures detection screenshots under
  `<item_id>.gui`); `verified = target_ok and gui_verified is not False`.
- [x] **high** any failure in the verify block leaves `gui_verified = None`
  (`cli.py:373-398`); the "already in target mode" shortcut also sets it `None`
  (`cli.py:296-300`). `None` is treated as best-effort rather than failure.
  Fixed: open/detect/capture/exception failures all yield `False` now;
  `None` only means "flavor has no graphics-switching UI"
  (`supports_graphics_switching()` gate). The already-in-target shortcut runs
  the same visual check instead of skipping it.
- [x] **high** `cli.py:442-470` `verify_cli_graphics_reflected_in_extension`
  returns `success=True, skipped=True` when there is no data, and
  `tests/system76-power/test_cli_full.py:255-263` just returns on `skipped`.
  Fixed: skip is now capability-based (flavor check) or "no transitions ran";
  for UI flavors every transition that ran must have `gui_verified True` —
  `False` **and** missing count as failures. The test `pytest.skip`s honestly.
- Note: the GUI-side twin (`workflows/system76_power/gui.py:705-745`) gets this
  right (`gui_verified=False → verified=False`); the CLI side was the outlier.

**Fix:** for flavors where `supports_graphics_switching()` is true, make
`gui_verified` required and treat `None` as failure.
*(implemented 2026-11-05; offline selftests cover the phase machine with the
GUI helper stubbed — a real 22.04 run with switchable graphics is needed to
confirm the visual checks now actually gate the results)*

---

## 5. Idle / screen lock — high

Nothing in the harness *causes* locking (no lock key chords; `dotool` only moves
and clicks; `harness/screenshots/screenshot.py:66-75` sends `shift+print`), so the
observed locks are the desktop's own policy — i.e. the disabling did not take
effect.

- [x] **high** `harness/reboot/idle.py:118-123` + `:274-276` — `_gsettings_get()`
  returns `None` on *any* failure, and `disable_idle()` skips keys whose read
  returned `None`. If `gsettings` cannot reach the session bus (systemd user
  service, or pytest under `sudo`), **every** key is skipped, it logs
  `applied 0 GNOME idle setting(s)`, returns `False` — and no caller checks the
  return value (`pytest.sh:172` prints it, `conftest.py:126-133` ignores it). The
  suite then runs under the user's real idle+lock policy.
  *(fixed 2026-11-05: `gsettings list-keys` probe distinguishes undefined keys
  from an unreachable bus; `disable_idle()` returns a structured report
  (`backend/applied/values/readback_ok/errors`) and every caller — conftest,
  `pytest.sh`, the resume script — prints its errors with a loud warning when
  protection is not active; stubbed selftest covers dead-bus, healthy-bus and
  COSMIC paths.)*
- [x] **medium** `autostart.py:93-97` — `XDG_CURRENT_DESKTOP` is exported through a
  `&&` chain that silently no-ops if `loginctl` returns nothing → `_desktop_kind()`
  can return `None` → nothing gets disabled.
  *(fixed 2026-11-05: assign-then-export in plain `if` blocks; an empty
  loginctl answer no longer swallows the export.)*
- [x] **medium** `idle.py` never reads values back after setting them, and there is
  no guard test asserting the protection is actually active.
  *(fixed 2026-11-05: every applied GNOME key is read back and logged; the
  critical subset (`idle-delay`, `lock-enabled`) must verify or `readback_ok`
  is False; COSMIC files are re-read after write. New
  `tests/test_idle_guard.py`, sorted first by conftest, asserts GNOME
  read-back / COSMIC `None` files and fails the run in seconds.)*

Diagnostics to run on hardware:
1. `grep '\[idle\]' artifacts/<run>/resume/pytest-output.log` — look for
   `applied 0 …` or `detected desktop: None`.
2. Confirm the resume unit's environment has `DBUS_SESSION_BUS_ADDRESS` (the
   generated script sets it only if `$XDG_RUNTIME_DIR/bus` exists at that instant).

**Fix:** distinguish "key absent" from "read failed" (e.g. `gsettings list-keys
<schema>`), read back and log the applied values, return a structured report, add a
cheap guard test (`idle-delay == 0`, `lock-enabled == false`) that fails fast
instead of failing 20 minutes later inside `capture`, and apply idle protection
inside the generated resume script *before* pytest starts (covers the window
between autologin and `pytest_configure`).
*(all done 2026-11-05 — hardware confirmation of the dead-bus hypothesis on the
resume unit still rides on the next real run: check for
`[idle] ... ERROR: ... session bus` lines in the resume log.)*

---

## 6. Capture, vision and input layer

- [ ] **high** `harness/screenshots/screenshot.py:167-179` (plus `pytest.sh:82-86`
  and `conftest.py:150-160`) call portal `SetPermission` with signature `sbssas`;
  the store's signature is `sbssav` → all three calls deterministically fail and
  are wrapped in `except: pass` / `|| true`. **[verify-on-hw]** —
  `busctl introspect org.freedesktop.impl.portal.PermissionStore …`
- [ ] **high** `harness/gui/driver.py:28-37` + `harness/detection/mapper.py:6-17` —
  coordinates normalized to the *cropped active display* are passed straight to
  dotool's global bounding box. `DisplayCrop.origin` and
  `map_normalized_to_screen()` exist but are unused → misclicks whenever displays
  are offset or multiple.
- [ ] **high** `harness/gui/set_of_mark.py:163-171` — `ask_vlm_for_element()`
  ignores its `target_description` argument; the prompt is hard-coded to
  "currently selected or highlighted".
- [ ] **high** `set_of_mark.py:107,135,147-150` — OCR (`cv2.imread` + a tesseract
  subprocess, ~10 s each) runs **per contour** → one SoM pass can take minutes,
  multiplied by 5 driver retries.
- [ ] **medium** `harness/gui/coords.py:236-262` — `aspect_scale` is computed then
  unconditionally overwritten by the pixel mapping (dead code), and the clamp lets
  `nx` reach 1.5, which `to_dotool_normalized` (`mapper.py:15-17`) rejects with
  `ValueError` — surfaced only as a swallowed "open failed".
- [ ] **medium** `coords.py:31-37` — `UBUNTU_26` profile order is
  battery `.325` → balanced `.39` → performance `.35`; every other layout is
  monotonic, so performance/balanced look swapped. **[verify-on-hw]** against a
  real capture.
- [ ] **medium** `harness/ollama_client/ollama_client.py:30,50` and
  `set_of_mark.py:169-170` — no request timeout on either VLM path → a wedged
  Ollama hangs the suite indefinitely.
- [ ] **medium** `harness/dotool/dotool.py:37-55,134-144` — `GuiDriver(dtproc=None)`
  spawns a fresh dotool process and uinput device per click; `proc.wait()` has no
  timeout (can hang the suite); `key(x, press=False)` only ever presses.
- [ ] **medium** `harness/display/display.py:79-89` — the 10×10 probe window is not
  destroyed when the 250 ms timeout wins → leaked windows corrupt later
  screenshots (up to 5 retries).
- [ ] **medium** blind `(0.5, 0.5)` "dismiss" clicks in ~10 places
  (`gui.py:163-172,253-262,499-520,663-674`; `cli.py:438-441,666-671`;
  `ui_workflow.py:170-190`). Settings windows are centre-placed, so the click can
  activate the widget being validated. `Coords.UBUNTU_26_DISMISS = (0.1, 0.1)`
  exists (`coords.py:39`) while `gui.py:165` warns against clicking `(0.1,0.1)` —
  pick one policy and expose it as a flavor hook.
- [ ] **medium** `harness/detection/parser.py:63-76` — "prefer the LAST token
  matching expected" plus substring leniency means a rambling model answer is
  happily accepted with the wrong value (visible in the run logs).
  `workflows/system76_power/gui.py:581-626` then adds a 45-line `_normalize` regex
  heuristic to compensate. Fix at the source: constrain decoding
  (`format="json"` or raw + stop sequence, or require the answer token first).
- [ ] **medium** `screenshot.py:281` + `harness/imageutils/crop.py:24` ignore
  negative monitor origins (`x < 0` → `crop()` raises; never offsets by
  `min_x`/`min_y`); `screenshot.py:264-286` assumes one global max scale (breaks
  mixed 1x/2x layouts); `screenshot.py:218,593` mix `time.time()` (file freshness)
  with `time.monotonic()` (deadline), which an NTP step across a reboot can break.
- [ ] **low** `screenshot.py:195-199,221` — `unlink` errors swallowed,
  `shutil.move` can raise a non-`ScreenshotError`; `crop.py:13-17` floors origin
  *and* size; `set_of_mark.py:33` vs `:119` annotation type says 2-tuple but stores
  3-tuples; `:123,145` `str.replace(".", ...)` mangles paths and can overwrite the
  source screenshot; duplicate imports at `driver.py:57-58,135-136`.
- [ ] **low** `harness/screenshots/screenshot.py:59-77` — landing directories
  (`~/Pictures`, `~/Pictures/Screenshots`) and the `shift+print` shortcut are
  hard-coded per backend with no override; dead code at `:209-213` (unused "file"
  mode) and `:440-459` (unreachable fallback).

---

## 7. Architecture vs. the stated goal (register, don't branch; app-specific out of the harness) — medium

- [ ] **medium** `harness/brightness/brightness.py:67-135` parses
  **`system76-power profile` output** — application-specific logic inside
  `harness/`. Same category: `harness/power_state.py` (graphics-mode semantics).
  (`harness/reboot/__init__.py`'s stray `handlers.system76_power` import was
  removed with the §1 change.)
  *Progress (2026-11-06): `power_state.py` moved to
  `handlers/system76_power/power_state.py` with importers updated. **Brightness
  deliberately stays in `harness/`** — the backlight/sysfs and daemon-restart
  machinery is desktop-generic; only its profile-output *parsing* is app-specific
  and that remains open here.*
- [ ] **medium** flavor defaults hard-coded to Pop: `os_id="pop-22.04"` at
  `gui.py:87,105,255,341,553,772` and `transitions.py:95,161,192,220`.
- [ ] **medium** `harness/platform/README.md:14-35` is misleading: auto-discovery
  (`harness/platform/registry.py:26-37`) imports `harness/platform/*` non-package
  modules and each subpackage's `__init__`, so a new `popos/pop26.py` is
  **never registered** unless also imported in `harness/platform/popos/__init__.py:1-3`.
- [ ] **medium** `registry.py:26-37` — both discovery loops swallow import errors →
  a flavor module with a typo silently disappears.
- [x] **medium** string-prefix OS gating remains: `tests/system76-power/test_gui_profile.py:144,148,160-265`
  (`startswith("pop-22")`, `"ubuntu"`, `"pop-24"`), `gui.py:230`
  (`os_id.startswith("ubuntu")`). Replace with
  `flavor.supports_graphics_switching()` / a dedicated hook.
  *(fixed 2026-11-06: GUI/CLI transition tests gate on
  `get_flavor_for_os_id(os_id).supports_graphics_switching()`; the shared mixin
  (`graphics_transitions.py`) does capability gating for both drivers, and
  `detect_graphics_mode` consults the flavor. The only string-prefix left in
  `gui.py` is the Ubuntu extra-dismiss branch (line ~214), which belongs to
  P2 #12's flavor dismiss policy, not graphics gating.)*
- [x] **high** `harness/power_state.py:88` checks `hasattr(handler, "set_graphics")`
  but the handler only implements `switch_graphics_mode`
  (`handlers/system76_power/system76_power.py:249`) → `restore_original_graphics_mode()`
  always returns `False`, so `conftest.py:330-336` never restores the user's
  original graphics mode. `pytest.sh:156` additionally calls
  `h.restore_original_graphics_mode()` / `h.reboot()` — methods that do not exist
  on `System76Power` (AttributeError swallowed by `2>/dev/null || true`).
  *(fixed 2026-11-05: `power_state.restore_original_graphics_mode()` checks
  `switch_graphics_mode`, skips when already in the original mode, and returns
  True only when a switch was issued — conftest and `pytest.sh` cleanup both
  reboot when it returns True. Truth-table selftest covers all three cases.)*
- [x] **high** `handlers/system76_power/system76_power.py:66` — `_log()` calls
  `json.dumps` but `json` is never imported (lines 1-6); the `NameError` is
  swallowed, so the JSONL handler log has never been written.
  *(fixed 2026-11-05: `import json` added.)*
- [x] **medium** latent crashes found by the type checker while fixing the above:
  `system76_power.py` `_run()` ended with `raise last_exc` which can be `None`
  (`TypeError: exceptions must derive from BaseException`), and
  `gui.py` `detect_power_profile`/`detect_graphics_mode` read
  `result.normalized` when `result` can be `None` (empty capture value).
  *(fixed 2026-11-05: `RuntimeError` fallback when `last_exc is None`;
  `getattr(result, "normalized", None)` at both sites.)*
- [ ] **medium** `system76_power.py:338-341` — `restart_daemon()` falls back to
  *interactive* sudo inside `_run`'s 120 s default timeout → ~2 min stall in a
  headless/resumed run.
- [ ] **low-medium** `system76_power.py:297,315` — `pkill -9 -f system76-power`
  kills any matching process; `_run` default `retries=2` adds 5 s/10 s sleeps.
- [ ] **low** `harness/workflows/base.py:44,55,59` print on every persist/load —
  the dominant noise in reboot logs.
- [ ] **low** `harness/config/config.py:81-89` — unreachable duplicate block after
  `return`; `ollama_config()` prints `ERROR:` and returns `{}` on a missing file
  while `json.load` is uncaught on a malformed one; `set_ollama_*` rewrite
  `config.json` wholesale.
- [ ] **low** `harness/ollama_client/ollama_client.py:33` mutable default arg
  `images: list = []`; `:62-64` `__main__` block hard-codes a personal screenshot
  path; `connect()` is never called automatically, so `send_message` returns `None`
  (a silent-failure chain into best-effort passes).

---

## 8. Duplication, dead code, hygiene — medium/low

- [x] **medium** `cli.py` and `gui.py` each carry a full copy of the
  graphics-transition phase machine, and `get_transition_order` is verbatim
  duplicated (`cli.py:176-236`, `gui.py:244-286`) — while their `gui_verified`
  semantics disagree (see §4). Skip-guard boilerplate repeats 5× in `gui.py`.
  *(fixed 2026-11-06: one phase machine in `workflows/system76_power/graphics_transitions.py`
  (`GraphicsTransitionMixin` + `GRAPHICS_CHAIN_ORDER`), CLI and GUI provide only
  switch/verify hooks; `gui_verified` semantics unified (required evidence,
  `None` only when the flavor has no graphics UI); one shared skip guard. Offline
  selftest covered replay/resume/unconfirmed-reboot paths.)*
- [x] **medium** test duplication: 13 near-identical GUI transition tests and 6 CLI
  ones (`test_cli_full.py:104-253`, `test_gui_profile.py:160-265`); then
  `test_cli_profile_reflected_in_extension` re-runs all six CLI transitions via
  `run_all_cli_validate` (~6 min of duplicate work). Note parametrization must
  respect the per-item `item_id` resume scheme.
  *(fixed 2026-11-06: both files parametrize the transition chains
  (`test_gui_perf_profile_transition`, `test_gui_graphics_transition`,
  `test_graphics_transition`, `test_cli_profile_reflected`). Resume preserved:
  CLI keeps per-transition `item_id`s, GUI keeps its single shared
  `gui.graphics_transitions` document. The aggregate no longer re-runs the
  switches — `verify_all_cli_profiles_reflected_in_extension` was revived as a
  pure aggregation over the persisted per-test results, and
  `run_all_cli_validate` was deleted. Caveat: resume-completed ledgers are
  nodeid-keyed, so an interrupted *pre-parametrization* run will not match the
  new node ids — per-workflow phase state (item_id-keyed) still resumes.
  Follow-up 2026-11-06: the priming tests (`to_hybrid` x2,
  `transition_to_performance` x2) are gone — both circuits are closed, so
  `rotate_circuit` (`harness/workflows/base.py`) re-anchors them at the
  machine's current state at collection; the graphics rotation is persisted
  (`power_state` `graphics_chain.json`) and reused while
  `GUI_TESTING_RESUME_RUN` is set, keeping the in-flight rebooting edge at the
  front of the chain.)*
- [ ] **medium** hardcoded sleeps everywhere: `transitions.py:79,118,126`
  (20/25 s), `cli.py:107,147,281,293,349` (10/15/30 s), `gui.py:408` (90 s),
  `detect_*` retry loops (6/8/10/12 s). Prefer polling the CLI state instead.
  *(2026-11-06: the Pop!_OS 22.04 GUI graphics transition now deliberately
  sleeps ≥ 90 s before Tab/Tab/Enter into the post-switch modal — that wait
  is load-bearing (user-verified on hardware: forcing a reboot earlier
  corrupts the machine), so do not "optimize" it into a poll.)*
- [x] **low** dead code: `transitions.py` `GraphicsTransitionWorkflow` (never
  instantiated), `run_all_gui` ×2, `validate_graphics`; `cli.py:706`
  `verify_all_cli_profiles_reflected_in_extension`; `base_workflow.py:14,40`;
  `ui_workflow.py:53,82`; `reboot/__init__.py:230-234,249`;
  `resume.py:76-85` `bump_attempts`.
  *(fixed 2026-11-06: deleted `GraphicsTransitionWorkflow`, `run_all_gui`,
  `run_all_cli_validate`, `transition_to` (only served `run_all_gui`),
  `validate_graphics`, `take_screenshot`/`query_llm` (`ui_workflow`), the unused
  `Workflow.run` stub, and `bump_attempts`/`ResumeState` (+ their
  `harness.reboot` re-exports). `verify_all_cli_profiles_reflected_in_extension`
  was revived as the aggregate test's delegator (see above) instead of deleted.
  The `reboot/__init__.py` lines became live force-restore code after the §1
  rewrite. `cli.py:query_switchable` was deleted later the same day — the
  rewritten probe test supersedes it.)*
- [x] **low** `transitions.py:169` docstring claims an Eulerian circuit is
  *computed*; it returns a hardcoded 12-edge list. `cli.py:158` prints
  "EXCEPTION in transition_to_integrated" from `transition_to_hybrid`.
  `cli.py:63-76` `set_graphics` returns `success=True` unconditionally.
  *(fixed 2026-11-06: `GRAPHICS_CHAIN_ORDER` carries an honest comment (a
  hand-written 12-edge chain, not a computed circuit); the misleading print and
  `set_graphics` were removed with the duplicated phase machine.)*
- [x] **low** `test_cli_full.py:29-36` `test_laptop_switchable_graphics_can_be_queried`
  fails in every run log on both machines — confirm the assertion message in an
  artifact before assuming the cause.
  *(fixed 2026-11-06. Root cause: on non-switchable systems the CLI exits
  non-zero with the refusal on **stderr**, and the old `switchable()`
  string-heuristic **returned the raw stderr as the result** when its keyword
  match missed — the membership assertion then failed with a wall of text.
  The handler now raises a typed `GraphicsSwitchingUnsupported` carrying the
  CLI message; skip-gating call sites (mixin, probe tests, power-query test)
  use `probe_switchable()` which maps the refusal to `'not switchable'` data,
  while the probe test asserts on the refusal message (the `pytest.raises
  match=` equivalent — unconditional `pytest.raises` can't work here because
  whether the machine answers or refuses is exactly what the test is probing).
  The test also passes `item_id` to the handler so the raw rc/stdout/stderr
  lands in artifacts for exactly this kind of diagnosis. Dead
  `cli.py:query_switchable` deleted in the same pass.)*
- [ ] **low** `/tmp/opencode/gui` as the scratch dir (`ui_workflow.py:147-150`,
  `test_gui_profile.py:28`) is unrelated to the project and outside artifacts.

---

## 9. Docs & packaging — medium

Docs verified wrong:

- [ ] `README.md:53` attributes sudoers setup to `setup.sh`; it happens in
  `pytest.sh:117-133`.
- [ ] `docs/configuration.md:91`, `docs/testing.md:45`,
  `docs/reboot-handling.md:151,156` show artifact dirs as `YYYY-MM-DD_HH-MM-SS`;
  the code emits `YYYYMMDDTHHMMSSZ-<6hex>` (`harness/artifacts/store.py:100`).
- [ ] `docs/testing.md:171-173` promises `summary.txt` / `report.json`; actual
  outputs are `manifest.json` + `test_report.txt`
  (`harness/report/writer.py:57,100`).
- [ ] `docs/testing.md:52-59` lists test files that do not exist (actual four:
  `test_brightness.py`, `test_cli_full.py`, `test_gui_profile.py`,
  `test_perf_profile.py`).
- [ ] `docs/adding-applications.md:272` example
  `SIMPLE_SELECTION.render(item=…, choices=…)` raises — `extra_instructions` is
  required (`harness/llm/prompts/templates.py:19-23`, enforced at `base.py:14-19`).
- [ ] `docs/configuration.md:26-28` claims ollama defaults that do not exist
  (`harness/ollama_client/ollama_client.py:18-20,27-29` no-op with
  "ERROR: No IP or port.").
- [ ] `README.md:74-85`, `docs/configuration.md:14-21`, `config.example.json:7`
  hard-code `"screenshot_tool": "cosmic-screenshot"` — wrong for GNOME; only
  `setup.sh:50-58,275-289` auto-detects. Valid values:
  `cosmic-screenshot` / `gnome-dotool` (`harness/screenshots/screenshot.py:59-77`).
- [ ] `docs/reboot-handling.md:111` uses marker `graphics_individual` (declared in
  `pytest.ini:12`, used by **no** test); `:75-77` attributes sudoers creation to
  conftest; `docs/testing.md:95` says test markers are auto-applied (only the
  program marker is — `conftest.py:186-196`).
- [ ] `conftest.py:210-212` skip reason is backwards ("set RUN_DESTRUCTIVE_TESTS=0
  to skip" fires when it *is* 0) and no test carries the `destructive` marker.
- [x] `harness/reboot/system.py:9-11` docstring claimed the sudoers rule
  whitelists `python3 -m harness.reboot *`; the real list omitted `reboot` and
  included the invalid `disable`. (Rewritten to describe the helper.)
- [x] `docs/reboot-handling.md` — the setup section attributed the sudoers rule
  to conftest and listed the old `python3 -m harness.reboot` recovery commands;
  both now document the wrapper, the three narrow grants, and `cleanup-all`.
- [x] `harness/report/writer.py:40` docstring says `.tar.gz`; the code writes
  `.tar.xz` (`writer.py:116-128`).
- [ ] `harness/reboot/session.py:527-533` `_remember()` ignores write failures so
  `restore()` (`:578-579`) returns `True` vacuously — worth documenting as a caveat.

Packaging:

- [ ] **high** `opencv-python` and `numpy` are undeclared in `pyproject.toml` yet
  required by `harness/gui/set_of_mark.py:21-22,39-40` (installed only by
  `setup.sh:190,194`).
- [ ] `gi`/PyGObject undeclared and works only because `setup.sh:179` builds the
  venv with `--system-site-packages` plus apt `python3-gi` (`setup.sh:103`);
  `harness/display/display.py:1-8` depends on it.
- [ ] `tesseract-ocr`, `jq`, `libinput-tools` and the build deps
  (`setup.sh:107`) are not in `docs/configuration.md:125-138`.
- [ ] `hypothesis` declared (`pyproject.toml:18`) but unused.

`setup.sh`:

- [ ] no `set -euo pipefail` → a failed apt/pip still `touch`es
    `.venv/.deps_installed` (gate at `:191,195`), so later runs skip repair.
- [ ] `:85-90` claims python3.11 ships in Pop!_OS 22.04 repos (jammy ships 3.10 —
    needs deadsnakes) **[verify-on-hw]**.
- [ ] `:118` package check gated on `! -d .venv`; `:142-144` no `modprobe uinput`.
- [ ] `:148-170` permanently `groupadd -f input`, `usermod -aG input`, and enables a
    boot-time `~/.config/systemd/user/dotoold.service` — no teardown or
    re-login-requirement documented.
- [ ] `:236,243,251,255-269,311` blank Enter writes empty config strings;
    `:206,255,311` an unparseable or `jq`-less `config.json` is silently clobbered.
- [ ] `:291-300` `--update` prunes unknown top-level keys, including
    `artifacts_root`, which `conftest.py:45-50` reads.

Documentation gaps:

- [ ] the platform-flavor how-to (`harness/platform/README.md`) is orphaned — not
    linked from `README.md:151-159`, and `harness/platform/` is missing from the
    `docs/architecture.md:18-33` table; `docs/adding-applications.md` never
    mentions the flavor API.
- [ ] `artifacts_root` undocumented; retention duality (`--clean` keeps 5 vs
    `KeepLast(10)`) unexplained;
    ~~`python -m harness.reboot cleanup-all` (the best recovery command)
    undocumented~~ (now documented in `docs/reboot-handling.md`); idle/lock
    disabling undocumented.
- [ ] README/docs duplicate four blocks (config JSON, run commands, architecture
    tree, workflow snippets) and three have already drifted → single-source into
    `docs/`.

---

## Verify on hardware

These need a real-machine check before being "fixed" or dismissed:

- [ ] `busctl introspect org.freedesktop.impl.portal.PermissionStore …` — confirm
  `SetPermission` signature (`sbssav` vs the `sbssas` the code uses).
- [ ] COSMIC cold boot time to a usable Wayland session (does it exceed the
  resume unit's 120 s budget?).
- [ ] Ubuntu GNOME screenshot landing directory (hard-coded as
  `~/Pictures/Screenshots`).
- [ ] `UBUNTU_26` profile click ordering against a real capture.
- [ ] Multi-monitor / negative-origin display mapping behaviour.
- [ ] `python3 --version` available from Pop!_OS 22.04 repos (setup.sh claim).
- [ ] Why `test_laptop_switchable_graphics_can_be_queried` fails in every log —
  root cause identified and fixed 2026-11-06 (raw stderr leaked into
  `switchable()`'s return; handler now raises `GraphicsSwitchingUnsupported`).
  Remaining check: confirm the refusal's message actually matches the test's
  `not (supported|switchable)` regex on both machines, and that the transition
  tests skip cleanly off pop-22 hardware (see `items/cli.laptop_switchable…`
  artifacts and `~/.local/share/gui-testing/switchable.json`).

---

## Priority order

**P0 — machine safety and security**

1. [x] Replace the sudoers rule with a fixed root-owned helper (`pytest.sh:128`);
   validate with `visudo -cf` on a temp before installing. *(done 2026-11-05 —
   needs one real `./pytest.sh` run on the laptop to confirm the reboot and
   autologin sequence still works unattended)*
2. [x] Add the boot-time cleanup unit (self-healing sudoers / autologin /
   resume-unit removal); make `conftest.py:309` resolve a username on
   never-rebooted runs; move sudoers removal before the final reboot.
   *(done 2026-11-05: `recovery.py` + `gui-testing-recover.service` + run
   marker + helper `recover` action + the conftest username/sudoers-ordering
   fixes; confirmed by the same real `./pytest.sh` run needed for item 1)*
3. [x] Fix the resume script shebang / `${PIPESTATUS}` (`autostart.py:99,173`) and
   reconcile the 60 vs 10 attempt caps.
   *(done 2026-11-05: POSIX `status=$?`, cap 12, `resume/GAVE_UP` marker)*

**P1 — trustworthy results**

4. [x] Drive `test_report.txt` from pytest outcomes; stop stamping unrelated
   manifest entries (`conftest.py:418-425`); make `unknown` non-passing for
   retention. *(done 2026-11-05: §3 all ticked; end-to-end selftest in /tmp
   covers report layout, verdict merging, status derivation and KeepFailures
   retention; still needs a real multi-boot run to confirm across reboots)*
5. [x] Make `gui_verified` mandatory-and-failing for flavors that support graphics
   switching; delete the no-op at `cli.py:402-405`.
   *(done 2026-11-05: `_gui_verify_graphics_mode` + required semantics at all
   three CLI sites + honest `pytest.skip` in the aggregate test)*
6. [x] `sync()` + rename-atomic state writes before every non-graceful reboot;
   return `False` from `reboot()` / `wait_for_boot()` when unconfirmed.
   *(done 2026-11-05: `durable_write_text()` everywhere a document must survive
   an abrupt reboot; boot-ID confirmation in `system.py`; every workflow call
   site gates on the confirmed result. Offline selftest green — real-hardware
   confirmation rides on the next full `./pytest.sh` run.)*
7. [x] Fix `power_state.py:88` (`set_graphics` → `switch_graphics_mode`) and
   `pytest.sh:156`; add the missing `import json` in the handler.
   *(done 2026-11-05: restore is now real — switch + reboot when one was
   issued; `pytest.sh` cleanup uses `power_state` + `reboot()`; handler logs
   actually get written now.)*
8. [x] Idle: distinguish read-failure from absent key, read back and log applied
   values, fail fast with a guard test.
   *(done 2026-11-05: §5 all ticked — list-keys probe + structured report +
   read-back in `idle.py`, resume-script pre-apply + export fix in
   `autostart.py`, `tests/test_idle_guard.py` pinned first; offline selftests
   green, collection order verified with `--collect-only`.)*

**P2 — reliability and cost**

9. [ ] Constrain VLM decoding instead of regex-scraping; add timeouts to both
   Ollama paths.
10. [ ] Fix the SoM prompt to use `target_description`; run OCR once per sheet
    rather than per contour.
11. [ ] Coordinates: use `DisplayCrop.origin` when mapping to dotool; clamp
    `adjust_coords` to `[0,1]`; verify `UBUNTU_26` ordering; destroy the probe
    window on timeout; verify the `busctl` signature.
12. [ ] Replace blind `(0.5,0.5)` dismiss clicks with a flavor-provided dismiss
    policy.
13. [ ] Docs and `pyproject.toml` corrections from §9.

**P3 — cleanup**

14. [x] Share one phase-machine implementation between the CLI and GUI flows;
    parametrize the 13 duplicate tests; replace `startswith("pop-22")` gating with
    flavor capability checks; move brightness/power-state out of `harness/`;
    delete dead code.
    *(done 2026-11-06 — all parts; exception: brightness stays in `harness/`
    (desktop-generic), only `power_state` moved; see §7/§8 notes.)*
