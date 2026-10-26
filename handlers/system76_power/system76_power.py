import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["System76Power"]


class System76Power:
    perf_profiles = ['performance', 'balanced', 'battery']
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

    def _run(self, cmd: list[str], check: bool = False, timeout: float | None = 30.0):
        started = time.time()
        try:
            result = subprocess.run(
                cmd,
                check=check,
                capture_output=True,
                timeout=timeout,
                start_new_session=True,
                close_fds=True,
            )
            ended = time.time()
            record = {
                'command': cmd,
                'returncode': result.returncode,
                'stdout': result.stdout.decode(encoding='utf-8', errors='replace'),
                'stderr': result.stderr.decode(encoding='utf-8', errors='replace'),
                'duration': ended - started,
            }
            self._log({'type': 'command', **record})
            return record
        except subprocess.TimeoutExpired as e:
            ended = time.time()
            record = {
                'command': cmd,
                'returncode': None,
                'stdout': e.stdout.decode(encoding='utf-8', errors='replace') if e.stdout else '',
                'stderr': e.stderr.decode(encoding='utf-8', errors='replace') if e.stderr else '',
                'duration': ended - started,
                'timeout': timeout,
            }
            self._log({'type': 'command_timeout', **record})
            raise
        except subprocess.CalledProcessError as e:
            ended = time.time()
            record = {
                'command': cmd,
                'returncode': e.returncode,
                'stdout': e.stdout.decode(encoding='utf-8', errors='replace') if e.stdout else '',
                'stderr': e.stderr.decode(encoding='utf-8', errors='replace') if e.stderr else '',
                'duration': ended - started,
            }
            self._log({'type': 'command_failed', **record})
            if check:
                raise
            return record

    def switchable(self):
        result = self._run(['system76-power', 'graphics', 'switchable'], check=False)
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

    def switch_perf_profile(self, profile=None):
        if not profile:
            current = self.get_perf_profile()
            if not current or current not in self.perf_profiles:
                return False
            idx = self.perf_profiles.index(current)
            profile = self.perf_profiles[(idx + 1) % len(self.perf_profiles)]
        result = self._run(['system76-power', 'profile', profile], check=False)
        time.sleep(1)
        if result['returncode'] == 0:
            self._log({'type': 'perf_profile_switched', 'profile': profile})
            return True
        else:
            self._log({'type': 'perf_profile_switch_failed', 'profile': profile, 'stderr': result.get('stderr')})
            return False

    def get_perf_profile(self):
        result = self._run(['system76-power', 'profile'], check=False)
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
        result = self._run(['system76-power', 'graphics'], check=False)
        if result['returncode'] == 0 and result['stdout'].strip():
            try:
                return result['stdout'].split('\n')[0].strip()
            except Exception:
                pass
        return None

    def switch_graphics_mode(self, mode=None):
        if not mode:
            current = self.get_graphics_mode()
            if not current or current not in self.graphics_modes:
                return
            idx = self.graphics_modes.index(current)
            mode = self.graphics_modes[(idx + 1) % len(self.graphics_modes)]
        result = self._run(['system76-power', 'graphics', mode], check=False)
        time.sleep(1)
        if result['returncode'] == 0:
            self._log({'type': 'graphics_mode_switched', 'mode': mode})
            return True
        else:
            self._log({'type': 'graphics_mode_switch_failed', 'mode': mode, 'stderr': result.get('stderr')})
            return False

    def get_graphics_power(self):
        result = self._run(['system76-power', 'graphics', 'power'], check=False)
        if result['returncode'] == 0 and result['stdout'].strip():
            try:
                return result['stdout'].strip().lower()
            except Exception:
                pass
        return None

    def set_graphics_power(self, state=None):
        if state not in ('on', 'off'):
            return
        result = self._run(['system76-power', 'graphics', 'power', state], check=False)
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

    def reboot(self) -> bool:
        # Try polkit-based reboot first (works on Pop!_OS without sudo).
        result = self._run(['systemctl', 'reboot'], check=False)
        if result.get('returncode') in (0, None):
            return True
        # Fallback to sudo (needed on some Ubuntu configurations).
        result = self._run(['sudo', 'systemctl', 'reboot'], check=False)
        if result.get('returncode') in (0, None):
            return True
        # Last resort.
        result = self._run(['sudo', 'reboot'], check=False)
        return result.get('returncode') in (0, None)

    def wait_for_boot(self, timeout: float = 600.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = self._run(['systemctl', 'is-system-running'], check=False)
                if state.get('returncode') == 0 and (state.get('stdout') or '').strip():
                    return True
            except Exception:
                pass
            time.sleep(5)
        return False

    def setup_autologin(self, username: str | None = None) -> bool:
        """Enable autologin for the detected GUI user.

        Delegates to :mod:`harness.reboot.session`, which knows both the GNOME
        (gdm) and COSMIC (cosmic-greeter/greetd) configuration formats and
        restores the previous setup when the run finishes.
        """
        try:
            from harness.reboot import AutologinManager

            return AutologinManager().enable(username=username).enabled
        except Exception:
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
