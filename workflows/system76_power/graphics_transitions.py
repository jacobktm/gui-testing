"""Shared graphics-transition machinery for the CLI and GUI workflows.

Both ``System76PowerCLIWorkflow`` and ``System76PowerGUIWorkflow`` drive the
same reboot-aware phase machine (``start`` -> ``rebooting`` -> ``done``, with
the phase persisted so a test resumes on the boot after a reboot).  The only
differences are *how the mode is switched* (CLI command vs GUI clicks) and
*how the desktop is visually verified*.  Those are hooks here; everything
else — skip gating, resume bookkeeping, the reboot gate, result recording —
lives in exactly one place so the two drivers can never drift apart (they
had already diverged on ``gui_verified`` semantics before this was written).
"""
from __future__ import annotations

from handlers.system76_power import probe_switchable
from handlers.system76_power.power_state import (
    load_graphics_chain as _load_chain,
    load_switchable_state as _load_switchable,
    save_graphics_chain as _save_chain,
    save_switchable_state as _save_switchable,
)
from harness.reboot.system import setup_autologin as _setup_autologin
from harness.workflows.base import WorkflowResult, rotate_circuit

#: Closed chained circuit over the four System76 graphics modes: each
#: transition's source is the previous transition's target, the last edge
#: returns to the first one's source, and every one of the 12 directed edges
#: appears exactly once — so the run never needs a redundant priming switch.
#: Not an algorithmically computed Eulerian circuit — it is a hand-written
#: chain.  Tests rotate it (``harness.workflows.base.rotate_circuit``) to
#: start from whatever mode the machine is actually in, so no
#: ``transition_to_hybrid`` priming test (and its extra reboot) is required;
#: see :func:`get_graphics_chain` for the per-run order.
GRAPHICS_CHAIN_ORDER: list[tuple[str, str]] = [
    ("hybrid", "integrated"),
    ("integrated", "nvidia"),
    ("nvidia", "integrated"),
    ("integrated", "hybrid"),
    ("hybrid", "compute"),
    ("compute", "integrated"),
    ("integrated", "compute"),
    ("compute", "hybrid"),
    ("hybrid", "nvidia"),
    ("nvidia", "compute"),
    ("compute", "nvidia"),
    ("nvidia", "hybrid"),
]


def get_graphics_chain() -> list[tuple[str, str]]:
    """This run's graphics chain, rotated to start from the current mode.

    Because ``GRAPHICS_CHAIN_ORDER`` is a *closed* circuit, it can be rotated
    to begin wherever the machine actually is — the first transition then has
    ``source == current``, so no priming ``to_hybrid`` switch (and its extra
    reboot) is needed.  A resumed boot (``GUI_TESTING_RESUME_RUN`` set by the
    resume unit) must reuse the chain chosen on the first boot: re-rotating
    mid-run would move the edge whose reboot is in flight away from the front
    of the chain, and the transitions running before it would change the mode
    it is supposed to verify.
    """
    import os

    saved = _load_chain()
    if saved and os.environ.get("GUI_TESTING_RESUME_RUN"):
        return saved

    mode: str | None = None
    try:
        from handlers.system76_power import System76Power

        mode = System76Power().get_graphics_mode()
    except Exception:
        pass  # non-switchable machines have no graphics mode: canonical order
    chain = rotate_circuit(GRAPHICS_CHAIN_ORDER, mode)
    try:
        _save_chain(chain)
    except Exception:
        pass  # unwritable state dir must not break collection; resume just re-rotates
    return chain


class GraphicsTransitionMixin:
    """Phase machine shared by the CLI and GUI graphics-transition workflows.

    The host class must provide ``_make_handler(item_id, phase)`` and the two
    transition hooks (``_switch_graphics_mode`` / ``_gui_verify_transition``),
    and inherits :class:`harness.workflows.base.Workflow` for
    ``persist_state`` / ``resume_progress`` / ``artifacts``.
    """

    # --- host-class hooks ----------------------------------------------------

    def _make_handler(self, item_id: str, phase: str):
        raise NotImplementedError

    def _switch_graphics_mode(self, handler, target: str) -> tuple[bool, str, str]:
        """Issue the mode switch. Returns ``(ok, stdout, stderr)``."""
        raise NotImplementedError

    def _gui_verify_transition(self, target: str, item_id: str) -> bool | None:
        """Visual confirmation of *target* on the desktop.

        ``True``/``False`` = confirmed/not confirmed (required evidence);
        ``None`` only when this platform flavor has no graphics UI.
        """
        raise NotImplementedError

    def _transition_log_prefix(self) -> str:
        return ""

    def _reboot_after_switch(self, handler, target: str) -> bool:
        """Settle, ensure autologin, then reboot and confirm the new boot.

        The GPU needs time after a mode switch (switching to ``integrated``
        powers the dGPU off and needs longer).  The GUI driver overrides
        this on flavors whose shell shows the post-switch modal: there the
        *system* triggers the reboot when it is ready, because forcing it
        early corrupts the machine (see the popup flow in
        ``workflows/system76_power/util.py``).
        """
        import time

        settle = 30 if target == "integrated" else 10
        time.sleep(settle)
        _setup_autologin()
        from .util import reboot_and_wait

        return reboot_and_wait(handler)

    # --- shared gating --------------------------------------------------------

    def _transition_skip_result(self, handler, item_id: str, *, os_id: str | None = None) -> WorkflowResult | None:
        """Return a skip result when transitions do not apply to this machine.

        Covers both reasons — a flavor without the graphics-switching UI
        (``os_id`` given) and hardware that is not switchable — and records
        the skip in the artifact manifest (the GUI driver used to do that,
        the CLI one did not; now neither forgets).
        """
        if os_id is not None:
            from harness.platform import get_flavor_for_os_id

            if not get_flavor_for_os_id(os_id).supports_graphics_switching():
                return self._record_skip(item_id, f"{os_id} has no graphics-switching UI")
        switchable = _load_switchable()
        if switchable is None:
            switchable = probe_switchable(handler)
            _save_switchable(switchable)
        if switchable != "switchable":
            return self._record_skip(item_id, "not switchable")
        return None

    def _record_skip(self, item_id: str, summary: str) -> WorkflowResult:
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="skipped")
            except Exception:
                pass
        return WorkflowResult(success=True, item_id=item_id, summary=summary, data={"skipped": True})

    # --- shared order ----------------------------------------------------------

    def _transition_graphics_core(self, source: str, target: str, item_id: str = "graphics_transitions") -> WorkflowResult:
        """One reboot-aware graphics transition (``source`` -> ``target``).

        The source is recorded for reporting; the chained order guarantees the
        system is already in it.  Persisted phases survive the reboot::

            start      -> switch, persist "rebooting", reboot
            rebooting  -> (next boot) verify CLI state + GUI panel, record
            done       -> replay the recorded result idempotently

        Verification requires BOTH the CLI query and — on flavors that expose
        the graphics UI — the visual read of the panel; a transition on a
        machine that never actually rebooted is a hard failure, never a pass.
        """
        prefix = self._transition_log_prefix()
        handler = self._make_handler(item_id, "action")
        skipped = self._transition_skip_result(handler, item_id)
        if skipped is not None:
            return skipped

        progress = self.resume_progress(item_id, kind="graphics_transition") if item_id else {}
        results = progress.get("results", [])
        done = {(e.get("from"), e.get("to")) for e in results if isinstance(e, dict)}

        # Already completed in a previous run/boot.
        if (source, target) in done:
            entry = next((e for e in results if e.get("from") == source and e.get("to") == target), {})
            return WorkflowResult(
                success=entry.get("verified", True),
                item_id=item_id,
                summary=f"{source}->{target} (already done, verified={entry.get('verified', '?')})",
                data={"from": source, "to": target, "actual": entry.get("actual"), "verified": entry.get("verified", True)},
            )

        in_progress = (progress.get("source"), progress.get("target")) == (source, target)
        phase = progress.get("phase", "start") if in_progress else "start"

        current = handler.get_graphics_mode()
        print(f"{prefix}transition {source}->{target}: current (source) mode = {current!r}", flush=True)

        import time

        # Settle delay: give the system time to fully initialize after boot.
        time.sleep(15)

        def persist(new_phase: str, current_value: str, *, logged_output: str | None = None) -> None:
            state = {
                "kind": "graphics_transition",
                "phase": new_phase,
                "source": source,
                "target": target,
                "current": current_value,
                "results": results,
            }
            if new_phase == "done":
                state["completed"] = len(results)
            if logged_output is not None:
                state["logged_output"] = logged_output
            self.persist_state(item_id, "state", state)

        def record(entry: dict, *, mark_done: bool = True) -> WorkflowResult:
            results.append(entry)
            if mark_done:
                done.add((source, target))
                persist("done", entry.get("actual", current))
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(
                        item_id, "action",
                        f"transition -> {source} to {target} (verified={entry.get('verified')})\n",
                        step="transition",
                    )
                except Exception:
                    pass
            return WorkflowResult(
                success=bool(entry.get("verified")),
                item_id=item_id,
                summary=f"{source}->{target} (actual: {entry.get('actual')}, verified={entry.get('verified')}, gui={entry.get('gui_verified')})",
                data=entry,
            )

        # --- phase: start -----------------------------------------------------
        if phase == "start":
            if current == target:
                # Already in the target mode: no switch, no reboot — but the
                # panel must still visibly agree (required where the UI exists).
                print(f"{prefix}  Already in {target} mode, no transition needed.", flush=True)
                gui_verified = self._gui_verify_transition(target, item_id)
                verified = gui_verified is not False
                entry = {"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified}
                return record(entry)

            print(f"{prefix}  switching to {target}...", flush=True)
            ok, logged_output, stderr = self._switch_graphics_mode(handler, target)
            if not ok:
                entry = {"from": source, "to": target, "actual": current, "verified": False, "error": "switch failed"}
                results.append(entry)
                persist("done", current)
                return WorkflowResult(
                    success=False,
                    item_id=item_id,
                    summary=f"{source}->{target} (switch failed: {stderr})",
                    data=entry,
                )

            # Save state BEFORE reboot (durable): this document is what makes
            # the test resume after the reboot instead of restarting the
            # switch forever.
            persist("rebooting", target, logged_output=logged_output)
            if not self._reboot_after_switch(handler, target):
                print(f"{prefix}ERROR: reboot did not happen; cannot verify {source}->{target}", flush=True)
                entry = {"from": source, "to": target, "actual": current, "verified": False, "error": "reboot did not happen"}
                return record(entry)
            # Reboot confirmed: continue into verification below (this line
            # only runs if the reboot somehow did not kill the process).
            current = handler.get_graphics_mode()
            phase = "rebooting"
            print(f"{prefix}after reboot: mode = {current!r} (target={target!r})", flush=True)

        # --- phase: rebooting (i.e. resuming on the next boot) ------------------
        if phase in ("rebooting", "done"):
            current = handler.get_graphics_mode()
            print(f"{prefix}verify: current={current!r} target={target!r} match={current == target}", flush=True)
            try:
                with open("/proc/uptime") as fh:
                    print(f"{prefix}  uptime after boot: {float(fh.read().split()[0]):.0f}s", flush=True)
            except Exception:
                pass
            target_ok = current == target

            # Visual verification: required on flavors that expose the
            # graphics-switching UI; None only when the flavor has no such UI.
            gui_verified = self._gui_verify_transition(target, item_id)

            verified = target_ok and gui_verified is not False
            if target_ok and gui_verified is False:
                print(
                    f"{prefix}  CLI reports {target!r} but the GUI did not confirm it — failing the transition",
                    flush=True,
                )

            entry = {"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified}
            return record(entry)

        return WorkflowResult(success=False, item_id=item_id, summary=f"{source}->{target} (unexpected phase: {phase})")

    # --- shared "ensure starting in hybrid" step ---------------------------------

    def _transition_to_hybrid_core(self, item_id: str = "graphics_transition.to_hybrid") -> WorkflowResult:
        """Switch to hybrid if needed (no visual requirement) and verify."""
        prefix = self._transition_log_prefix()
        handler = self._make_handler(item_id, "action")
        skipped = self._transition_skip_result(handler, item_id)
        if skipped is not None:
            return skipped

        current = handler.get_graphics_mode()
        print(f"{prefix}transition_to_hybrid: current mode = {current!r}", flush=True)

        import time

        time.sleep(15)
        if current == "hybrid":
            print(f"{prefix}  Already in hybrid mode, no transition needed.", flush=True)
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary="already hybrid",
                data={"from": current, "to": "hybrid", "actual": current, "verified": True},
            )

        ok, logged_output, stderr = self._switch_graphics_mode(handler, "hybrid")
        if not ok:
            return WorkflowResult(
                success=False,
                item_id=item_id,
                summary=f"switch to hybrid failed: {stderr}",
                data={"from": current, "to": "hybrid", "actual": current, "verified": False},
            )

        self.persist_state(item_id, "state", {
            "kind": "graphics_transition",
            "phase": "rebooting",
            "source": current,
            "target": "hybrid",
            "current": "hybrid",
            "logged_output": logged_output,
        })
        if not self._reboot_after_switch(handler, "hybrid"):
            print(f"{prefix}ERROR: reboot did not happen; cannot verify hybrid transition", flush=True)
            entry = {"from": current, "to": "hybrid", "actual": current, "verified": False, "error": "reboot did not happen"}
            self.persist_state(item_id, "state", {
                "kind": "graphics_transition",
                "phase": "done",
                "source": current,
                "target": "hybrid",
                "current": current,
                "results": [entry],
                "completed": 1,
            })
            return WorkflowResult(
                success=False,
                item_id=item_id,
                summary="to_hybrid failed: reboot did not happen",
                data=entry,
            )
        actual = handler.get_graphics_mode()
        verified = actual == "hybrid"
        print(f"{prefix}After reboot: mode = {actual!r}, verified = {verified}", flush=True)

        entry = {"from": current, "to": "hybrid", "actual": actual, "verified": verified}
        self.persist_state(item_id, "state", {
            "kind": "graphics_transition",
            "phase": "done",
            "source": current,
            "target": "hybrid",
            "current": actual,
            "results": [entry],
            "completed": 1,
        })
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"transition -> {actual} to hybrid (verified={verified})\n", step="transition")
            except Exception:
                pass
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"to_hybrid (actual: {actual}, verified={verified})",
            data=entry,
        )
