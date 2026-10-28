import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

SWITCHABLE_STATE_PATH = Path.home() / ".local" / "share" / "gui-testing" / "switchable.json"

__all__ = ["System76Power"]


class System76Power:
    perf_profiles = ['performance', 'balanced', 'battery']

    GRAPHICS_MODE_STATE_PATH = __import__('pathlib').Path.home() / '.local' / 'share' / 'gui-testing' / 'graphics_mode.json'
    graphics_modes = ['nvidia', 'integrated', 'hybrid', 'compute']

    def __init__(
        self,
        test_id: str | None = None,
        item_id: str | None = None,
        phase: str = "action",
        log_dir: str | Path | None = None,
        log_path: str | Path | None = None,
        context: dict | None = None,
        artifacts=None,
    ):
        self.test_id = test_id
        self.item_id = item_id
        self.phase = phase
        self.context = context or {}
        self.artifacts = artifacts
        self.log_path = self._resolve_log_path(log_dir, log_path)

        # State is never cached: every get/set calls system76-power directly.

    def _resolve_log_path(self, log_dir: str | Path | None, log_path: str | Path | None) -> Path | None:
        if log_path is not None:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        if log_dir is not None:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            name_parts = []
            if self.item_id:
                name_parts.append(self.item_id)
            if self.test_id:
                name_parts.append(self.test_id)
            name_parts.append(timestamp)
            name = '-'.join(p.replace('/', '_') for p in name_parts) if name_parts else f'system76-power-{timestamp}'
            return log_dir / f'{name}.jsonl'
        return None

    def _log(self, event: dict) -> None:
        record = {
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'test_id': self.test_id,
            'item_id': self.item_id,
            'phase': self.phase,
            **self.context,
            **event,
        }
        if self.log_path is not None:
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
            except Exception:
                pass
        if self.artifacts is not None and self.item_id:
            try:
                payload = {
                    'handler': 'system76_power',
                    **record,
                }
                step = event.get('type')
                self.artifacts.save_detection(self.item_id, self.phase, payload, step=step)
            except Exception:
                pass

    def _run(self, cmd: list[str], check: bool = False, timeout: float | None = 120.0, retries: int = 2):
        """Run a command with retry on timeout.

        Uses Popen with start_new_session=True so the child gets its own
        process group.  On timeout the entire group is killed to avoid
        orphaned grandchildren holding pipes open.
        """
        last_exc = None
        for attempt in range(retries + 1):
            started = time.time()
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    close_fds=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Kill the entire process group.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        try:
                            proc.kill()
                        except (OSError, ProcessLookupError):
                            pass
                    stdout, stderr = proc.communicate()
                    raise

                ended = time.time()
                record = {
                    'command': cmd,
                    'returncode': proc.returncode,
                    'stdout': stdout.decode(encoding='utf-8', errors='replace'),
                    'stderr': stderr.decode(encoding='utf-8', errors='replace'),
                    'duration': ended - started,
                    'attempt': attempt,
                }
                self._log({'type': 'command', **record})
                if check and proc.returncode != 0:
                    raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)
                return record

            except subprocess.TimeoutExpired as e:
                ended = time.time()
                last_exc = e
                record = {
                    'command': cmd,
                    'returncode': None,
                    'stdout': (e.stdout or b'').decode(encoding='utf-8', errors='replace') if e.stdout else '',
                    'stderr': (e.stderr or b'').decode(encoding='utf-8', errors='replace') if e.stderr else '',
                    'duration': ended - started,
                    'timeout': timeout,
                    'attempt': attempt,
                }
                self._log({'type': 'command_timeout', **record})
                if attempt < retries:
                    time.sleep(5 * (attempt + 1))
            except subprocess.CalledProcessError as e:
                ended = time.time()
                record = {
                    'command': cmd,
                    'returncode': e.returncode,
                    'stdout': e.stdout.decode(encoding='utf-8', errors='replace') if e.stdout else '',
                    'stderr': e.stderr.decode(encoding='utf-8', errors='replace') if e.stderr else '',
                    'duration': ended - started,
                    'attempt': attempt,
                }
                self._log({'type': 'command_failed', **record})
                if check:
                    raise
                return record
            finally:
                if proc is not None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                            proc.wait()
                        except (OSError, ProcessLookupError):
                            pass
        # All retries exhausted.
        raise last_exc

    def switchable(self):
        result = self._run(['system76-power', 'graphics', 'switchable'], check=False, timeout=60.0)
        print(f"  [switchable] rc={result.get('returncode')} stdout={result.get('stdout', '').strip()!r} stderr={result.get('stderr', '').strip()!r}", flush=True)
        stdout = (result.get('stdout') or '').strip()
        stderr = (result.get('stderr') or '').strip()
        if stdout:
            # Current behavior for switchable systems
            if stdout == 'switchable':
                return 'switchable'
            if stdout == 'not switchable':
                return 'not switchable'
            return stdout
        # New behavior: non-switchable systems error out when graphics subcommands are used
        if stderr:
            if 'not switchable' in stderr.lower() or 'not supported' in stderr.lower() or 'no switchable' in stderr.lower():
                self._log({'type': 'switchable_not_switchable', 'stderr': stderr})
                return 'not switchable'
            self._log({'type': 'switchable_unknown_error', 'stderr': stderr})
            return stderr
        if result.get('returncode') not in (0, None):
            return 'not switchable'
        return 'unknown'

    @staticmethod
    def save_switchable_state(result: str) -> None:
        """Persist the switchable graphics result so other tests don't re-query."""
        try:
            SWITCHABLE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SWITCHABLE_STATE_PATH.write_text(json.dumps({"switchable": result}))
        except Exception:
            pass

    @staticmethod
    def load_switchable_state() -> str | None:
        """Load the persisted switchable graphics result, or None if not saved."""
        try:
            if SWITCHABLE_STATE_PATH.exists():
                data = json.loads(SWITCHABLE_STATE_PATH.read_text())
                return data.get("switchable")
        except Exception:
            pass
        return None

    def switch_perf_profile(self, profile=None):
        if not profile:
            current = self.get_perf_profile()
            if not current or current not in self.perf_profiles:
                return False
            idx = self.perf_profiles.index(current)
            profile = self.perf_profiles[(idx + 1) % len(self.perf_profiles)]
        result = self._run(['system76-power', 'profile', profile], check=False, timeout=60.0)
        time.sleep(1)
        if result['returncode'] == 0:
            self._log({'type': 'perf_profile_switched', 'profile': profile})
            return True
        else:
            self._log({'type': 'perf_profile_switch_failed', 'profile': profile, 'stderr': result.get('stderr')})
            return False

    def get_perf_profile(self):
        result = self._run(['system76-power', 'profile'], check=False, timeout=30.0)
        if result['returncode'] == 0:
            try:
                output = result['stdout'].split('\n')[0]
                if ': ' in output:
                    return output.split(': ')[1].strip().lower()
                elif output.strip():
                    return output.strip().lower()
            except Exception:
                pass
        return None

    def get_graphics_mode(self):
        result = self._run(['system76-power', 'graphics'], check=False, timeout=120.0)
        raw = (result.get('stdout') or '').strip()
        rc = result.get('returncode')
        print(f"  [get_graphics_mode] rc={rc} raw={raw!r}", flush=True)
        if rc == 0 and raw:
            try:
                mode = raw.split('\n')[0].strip()
                print(f"  [get_graphics_mode] parsed mode={mode!r}", flush=True)
                return mode
            except Exception as e:
                print(f"  [get_graphics_mode] parse error: {e}", flush=True)
        return None

    def switch_graphics_mode(self, mode=None):
        if not mode:
            current = self.get_graphics_mode()
            if not current or current not in self.graphics_modes:
                return
            idx = self.graphics_modes.index(current)
            mode = self.graphics_modes[(idx + 1) % len(self.graphics_modes)]
        result = self._run(['system76-power', 'graphics', mode], check=False, timeout=300.0)
        raw_out = (result.get('stdout') or '').strip()
        raw_err = (result.get('stderr') or '').strip()
        rc = result.get('returncode')
        print(f"  [switch_graphics_mode({mode})] rc={rc} stdout={raw_out!r} stderr={raw_err!r}", flush=True)
        time.sleep(1)
        if result['returncode'] == 0:
            self._log({'type': 'graphics_mode_switched', 'mode': mode})
            return True
        else:
            self._log({'type': 'graphics_mode_switch_failed', 'mode': mode, 'stderr': result.get('stderr')})
            return False

    def get_graphics_power(self):
        result = self._run(['system76-power', 'graphics', 'power'], check=False, timeout=60.0)
        if result['returncode'] == 0 and result['stdout'].strip():
            try:
                return result['stdout'].strip().lower()
            except Exception:
                pass
        return None

    def set_graphics_power(self, state=None):
        if state not in ('on', 'off'):
            return
        result = self._run(['system76-power', 'graphics', 'power', state], check=False, timeout=60.0)
        if result['returncode'] == 0:
            self._log({'type': 'graphics_power_set', 'state': state})
        else:
            self._log({'type': 'graphics_power_set_failed', 'state': state, 'stderr': result.get('stderr')})

    def restart_daemon(self) -> bool:
        """Restart the system76-power daemon.

        Tries passwordless sudo first (works when pytest.sh sets up the
        sudoers rule), then falls back to interactive sudo.
        """
        # Try passwordless first.
        result = self._run(
            ["sudo", "-n", "systemctl", "restart", "com.system76.PowerDaemon.service"],
            check=False,
        )
        if result.get("returncode") == 0:
            return True
        # Fall back to interactive sudo.
        result = self._run(
            ["sudo", "systemctl", "restart", "com.system76.PowerDaemon.service"],
            check=False,
        )
        return result.get("returncode") == 0

    def save_original_graphics_mode(self) -> None:
        """Persist the current graphics mode so it can be restored later."""
        try:
            import json
            from pathlib import Path
            mode = self.get_graphics_mode()
            if mode is None:
                return
            path = self.GRAPHICS_MODE_STATE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"mode": mode}))
        except Exception:
            pass

    def restore_original_graphics_mode(self) -> bool:
        """Restore the graphics mode saved by save_original_graphics_mode.

        Returns True if the mode was changed (reboot needed to apply).
        """
        try:
            import json
            from pathlib import Path
            path = self.GRAPHICS_MODE_STATE_PATH
            if not path.exists():
                return False
            data = json.loads(path.read_text())
            original = data.get("mode")
            if original is None:
                return False
            current = self.get_graphics_mode()
            if current == original:
                return False
            # Switch back to original mode.
            result = self._run(['system76-power', 'graphics', original], check=False)
            if result.get('returncode') in (0, None):
                try:
                    path.unlink()
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False

    def reboot(self) -> bool:
        # Enable SysRq for reliable reboot fallback.
        try:
            self._run(['sh', '-c', 'echo 1 | sudo tee /proc/sys/kernel/sysrq > /dev/null'], check=False, timeout=5)
        except Exception:
            pass
        # Restart system76-power daemon to ensure it's not in a bad state.
        try:
            self.restart_daemon()
        except Exception:
            pass
        # Sync filesystems before rebooting.
        try:
            self._run(['sync'], check=False, timeout=10)
        except Exception:
            pass
        # Record boot ID before reboot.  /proc/sys/kernel/random/boot_id
        # changes on every boot, so comparing before/after reliably detects
        # whether a reboot actually happened (works across process boundaries).
        try:
            self._boot_id_before = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception:
            self._boot_id_before = None

        # Create persistent + ephemeral markers (supplementary detection).
        # Persistent: in run dir (survives reboot). Ephemeral: in /tmp (cleared).
        self._persistent_marker = None
        self._ephemeral_marker = Path("/tmp/gui-testing-reboot-marker")
        if self.artifacts is not None:
            try:
                pm = self.artifacts.run_dir / "reboot-marker"
                pm.write_text("reboot_pending", encoding="utf-8")
                self._persistent_marker = pm
            except Exception:
                self._persistent_marker = None
        try:
            self._ephemeral_marker.write_text("reboot_pending", encoding="utf-8")
        except Exception:
            self._ephemeral_marker = None

        # Try each method until one actually reboots the system.
        # systemctl reboot can return 0 without rebooting on some systems
        # (e.g. blocked by inhibitor locks or confirmation dialogs).
        reboot_cmds = [
            ['sh', '-c', 'echo b | sudo tee /proc/sysrq-trigger > /dev/null'],  # SysRq (most reliable)
        ]
        for cmd in reboot_cmds:
            print(f"  Trying reboot: {' '.join(cmd)}", flush=True)
            result = self._run(cmd, check=False, timeout=30)
            rc = result.get('returncode')
            stderr = (result.get('stderr') or '').strip()
            print(f"    rc={rc} stderr={stderr!r}", flush=True)
            if rc in (0, None):
                # Wait to see if reboot actually happens.
                print(f"  Waiting 5s to see if reboot happens...", flush=True)
                time.sleep(5)
                # If we're still here, reboot didn't work.
                print(f"  Reboot not confirmed, trying next method...", flush=True)
        # If none confirmed a reboot, force it via sysrq.
        print(f"  No reboot method confirmed; forcing reboot via sysrq", flush=True)
        try:
            self._run(['sh', '-c', 'echo b | sudo tee /proc/sysrq-trigger > /dev/null'], check=False, timeout=10)
        except Exception:
            pass
        return True

    def wait_for_boot(self, timeout: float = 600.0) -> bool:
        # Give the system time to actually start rebooting before polling.
        print("Waiting for system to reboot...", flush=True)
        time.sleep(5)
        deadline = time.time() + timeout
        elapsed = 0
        boot_id_before = getattr(self, "_boot_id_before", None)
        persistent_marker = getattr(self, "_persistent_marker", None)
        ephemeral_marker = getattr(self, "_ephemeral_marker", None)
        # Also check from a previous (killed) process.
        if persistent_marker is None and self.artifacts is not None:
            pm = self.artifacts.run_dir / "reboot-marker"
            if pm.exists():
                persistent_marker = pm
        if ephemeral_marker is None:
            ephemeral_marker = Path("/tmp/gui-testing-reboot-marker")

        while time.time() < deadline:
            rebooted = False
            # Check boot_id change.
            try:
                boot_id_after = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                if boot_id_before is not None and boot_id_after != boot_id_before:
                    rebooted = True
            except Exception:
                pass
            # Check markers: persistent exists + ephemeral gone => rebooted.
            p_exists = persistent_marker is not None and Path(persistent_marker).exists()
            e_exists = Path(ephemeral_marker).exists() if ephemeral_marker else False
            if p_exists and not e_exists:
                rebooted = True
            if rebooted:
                print(f"  Reboot confirmed", flush=True)

            try:
                state = self._run(['systemctl', 'is-system-running'], check=False)
                status = (state.get('stdout') or '').strip() if state else ''
                rc = state.get('returncode') if state else None
                if status in ('running', 'degraded') or (rc == 0 and status):
                    if not rebooted and boot_id_before is not None:
                        print(f"  Warning: boot ID/markers unchanged, system may not have rebooted", flush=True)
                    else:
                        print(f"  System rebooted and is {status} (after {elapsed}s)", flush=True)
                    # Clean up markers.
                    for m in (persistent_marker, ephemeral_marker):
                        try:
                            if m is not None and Path(m).exists():
                                Path(m).unlink()
                        except Exception:
                            pass
                    return True
                if status:
                    print(f"  ... {status} ({elapsed}s)", flush=True, end='\r')
            except Exception:
                pass
            time.sleep(5)
            elapsed += 5
        print(f"  Timed out after {timeout}s", flush=True)
        return False

    def did_reboot(self) -> bool:
        """Check if a reboot occurred since the last reboot() call."""
        persistent = None
        if self.artifacts is not None:
            persistent = self.artifacts.run_dir / "reboot-marker"
        ephemeral = Path("/tmp/gui-testing-reboot-marker")
        p_exists = persistent is not None and persistent.exists()
        e_exists = ephemeral.exists()
        if p_exists and not e_exists:
            return True
        # Fallback to boot_id.
        try:
            boot_id_before = getattr(self, "_boot_id_before", None)
            boot_id_after = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            if boot_id_before is not None and boot_id_after != boot_id_before:
                return True
        except Exception:
            pass
        return False

    def setup_autologin(self, username: str | None = None) -> bool:
        """Enable autologin for the detected GUI user.

        Delegates to :mod:`harness.reboot.session`, which knows both the GNOME
        (gdm) and COSMIC (cosmic-greeter/greetd) configuration formats and
        restores the previous setup when the run finishes.

        Skips if pytest.sh already set up autologin (GUI_TESTING_SETUP_DONE=1).
        Uses passwordless sudo only (never blocks on password prompt).
        """
        if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
            print("  [setup_autologin] already done by pytest.sh, skipping", flush=True)
            return True
        # Also skip if autologin is already enabled (e.g., resumed run).
        try:
            from harness.reboot.session import COSMIC_GREETER_CONFIG, GREETD_CONFIG, _read_privileged
            for cfg in (COSMIC_GREETER_CONFIG, GREETD_CONFIG):
                if cfg.exists():
                    text = _read_privileged(cfg)
                    if text and "[initial_session]" in text:
                        print("  [setup_autologin] autologin already enabled, skipping", flush=True)
                        return True
        except Exception:
            pass
        try:
            from harness.reboot import AutologinManager

            result = AutologinManager().enable(username=username)
            print(f"  [setup_autologin] enabled={result.enabled} reason={result.reason}", flush=True)
            return result.enabled
        except Exception as e:
            print(f"  [setup_autologin] exception: {e}", flush=True)
            return False


if __name__ == "__main__":
    transition_graph = {s: [target for target in System76Power.perf_profiles if target != s] for s in System76Power.perf_profiles}
    sys76_power = System76Power()
    stack = [sys76_power.get_perf_profile()]
    circuit = []

    while stack:
        current = stack[-1]
        if transition_graph[current]:
            next_state = transition_graph[current].pop()
            stack.append(next_state)
        else:
            circuit.append(stack.pop())

    sequence = circuit[::-1]

    from_profile = None
    for profile in sequence:
        if not from_profile:
            from_profile = profile
        if profile == sys76_power.get_perf_profile():
            continue
        print(f'Transition from {from_profile} to {profile}')
        sys76_power.switch_perf_profile(profile)
        from_profile = profile

    print(sys76_power.switchable())
