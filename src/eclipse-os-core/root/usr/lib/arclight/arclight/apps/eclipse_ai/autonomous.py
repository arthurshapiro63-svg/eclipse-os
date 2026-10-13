"""Timed autonomous mode: keep working toward one goal until it is done or time is up.
(From Arch AI by Arthur.)

A run owns a folder ~/.local/share/eclipse-ai/runs/<timestamp>/ with:
  goal.md      the goal, as given
  plan.md      the agent's current plan (it rewrites this with update_plan)
  notes.md     what was tried / worked / failed (log_progress + harness lines)
  actions.log  every tool call with its result line, written by the harness
  status.json  live status (elapsed, remaining, step, last action)
  report.md    the final report
  steps/N.json the raw model messages of each step (for debugging)

Each step starts with a fresh context built from those files, so the run has
continuity without the transcript growing without bound.
"""
import json
import re
import threading
import time
from pathlib import Path

from . import config, rootq, tools
from .agent import Agent

RUNS_DIR = config.RUNS_DIR
WRAP_UP_MIN, WRAP_UP_MAX = 30, 90   # seconds reserved at the end of the budget for the closing summary
IDLE_STEPS_TO_STOP = 3         # steps with no tool call in a row => treat as finished


def parse_duration(text: str) -> int:
    """'45m' | '1h' | '1h30m' | '90s' | '2' (minutes) -> seconds. Raises ValueError."""
    s = str(text).strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s) * 60)
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)([hms]|min|hr|hour|hours|minutes|seconds|sec)", s):
        total += float(num) * {"h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "m": 60, "min": 60, "minutes": 60,
                               "s": 1, "sec": 1, "seconds": 1}[unit]
    if total <= 0 or not re.fullmatch(r"(\d+(\.\d+)?(h|hr|hours?|m|min|minutes|s|sec|seconds))+", s):
        raise ValueError(f"could not read duration '{text}' (try 10m, 45m, 1h, 1h30m)")
    return int(total)


def fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def plain_time(seconds) -> str:
    """1800 -> '30 min', 5400 -> '1 h 30 min' (the clock form 30:00 reads like a time of day)."""
    m = max(1, round(int(seconds) / 60))
    h, m = divmod(m, 60)
    return (f"{h} h" + (f" {m} min" if m else "")) if h else f"{m} min"


class _StepChat:
    """Agent.run needs .messages and .save(); each step is its own short transcript."""
    def __init__(self, path: Path):
        self.messages: list[dict] = []
        self.path = path

    def save(self):
        try:
            self.path.write_text(json.dumps(self.messages, indent=1))
        except Exception:
            pass


class Run:
    """One timed run. Call start() from a worker thread; stop() from anywhere."""

    def __init__(self, cfg: dict, goal: str, seconds: int, ui):
        """ui: object with on_text(delta), on_tool_start(name, shown, args)->card, on_tool_done(card, delta, result),
        on_status(text), on_note(text), on_run_status(dict). All called from the run thread."""
        self.cfg, self.goal, self.budget, self.ui = cfg, goal.strip(), int(seconds), ui
        self.id = time.strftime("%Y%m%d-%H%M%S")
        self.dir = RUNS_DIR / self.id
        (self.dir / "steps").mkdir(parents=True, exist_ok=True)
        self.started = 0.0
        self.deadline = 0.0
        self.step = 0
        self.last_action = "starting"
        self.outcome = "running"      # running | finished | timeout | stopped | error
        self.stop_requested = False
        self.finish_info: dict | None = None
        self.agent: Agent | None = None
        self.ctx: tools.ToolContext | None = None
        self._lock = threading.Lock()
        self._idle_steps = 0
        self._actions_this_step = 0
        self.reserve = int(max(WRAP_UP_MIN, min(WRAP_UP_MAX, self.budget * 0.12)))
        self.work_elapsed = 0.0
        self.report_path = self.dir / "report.md"
        (self.dir / "goal.md").write_text(self.goal + "\n")
        (self.dir / "plan.md").write_text("(no plan yet)\n")
        (self.dir / "notes.md").write_text("")
        (self.dir / "actions.log").write_text("")

    # ----- files -----
    def _read(self, name: str, tail: int | None = None) -> str:
        try:
            text = (self.dir / name).read_text()
        except FileNotFoundError:
            return ""
        if tail is not None:
            lines = text.splitlines()
            text = "\n".join(lines[-tail:])
        return text.strip()

    def set_plan(self, plan: str) -> None:
        (self.dir / "plan.md").write_text(plan.strip() + "\n")
        self._append("notes.md", f"[step {self.step}] plan updated")

    def note(self, outcome: str, text: str) -> None:
        self._append("notes.md", f"[step {self.step}] {outcome.upper()}: {text.strip()}")

    def _append(self, name: str, line: str) -> None:
        with self._lock:
            with open(self.dir / name, "a") as f:
                f.write(line.rstrip("\n") + "\n")

    def _action(self, shown: str, result: tools.ToolResult | None) -> None:
        if result is None:
            return
        lines = [l for l in result.text.strip().splitlines() if l.strip()]
        if lines and lines[0].startswith("exit code"):
            lines = lines[1:]
        mark = "queued" if result.queued else ("ok" if result.ok else "FAIL")
        gist = (lines[0][:100] if lines else "")
        if not result.ok and len(lines) > 1:
            gist = " | ".join(l.strip()[:80] for l in lines[-3:])   # the tail usually holds the error
        self._append("actions.log", f"[step {self.step} {fmt(time.time() - self.started)}] {mark}: {shown[:120]} -> {gist}")
        self.last_action = f"{shown[:70]} ({mark})"
        self._actions_this_step += 1
        self.write_status()

    def elapsed(self) -> float:
        return time.time() - self.started if self.started else 0.0

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.time()) if self.deadline else float(self.budget)

    def status(self) -> dict:
        return {"id": self.id, "goal": self.goal, "outcome": self.outcome, "step": self.step,
                "elapsed": int(self.elapsed()), "remaining": int(self.remaining()), "budget": self.budget,
                "last": self.last_action, "dir": str(self.dir)}

    def status_line(self) -> str:
        if self.outcome == "running":
            return f"⏱ {fmt(self.elapsed())} elapsed · {fmt(self.remaining())} left · step {self.step} · {self.last_action}"
        return f"⏱ {fmt(self.work_elapsed or self.elapsed())} · {self.outcome} · step {self.step} · {self.last_action}"

    def write_status(self) -> None:
        try:
            (self.dir / "status.json").write_text(json.dumps(self.status(), indent=1))
        except Exception:
            pass
        self.ui.on_run_status(self.status())

    # ----- control -----
    def stop(self) -> None:
        """One key / one button: stop cleanly. Kills the running command and the model call."""
        self.stop_requested = True
        if self.outcome == "running":
            self.outcome = "stopped"
        if self.ctx:
            self.ctx.cancelled = True
        if self.agent:
            self.agent.cancel("stopped by user")

    def finish_early(self, completed: str, verified: str, still_broken: str) -> None:
        self.finish_info = {"completed": completed, "verified": verified, "still_broken": still_broken}
        self.outcome = "finished"
        self._append("notes.md", f"[step {self.step}] FINISHED: {completed}")

    # ----- the loop -----
    def _step_prompt(self) -> str:
        plan = self._read("plan.md")
        notes = self._read("notes.md", tail=25) or "(none yet)"
        actions = self._read("actions.log", tail=15) or "(none yet)"
        last = getattr(self, "_last_text", "").strip()
        parts = [f"Timed run, step {self.step}. Elapsed {fmt(self.elapsed())}, {fmt(self.remaining())} left.",
                 f"GOAL:\n{self.goal}", f"PLAN (plan.md):\n{plan}", f"NOTES (what worked / failed):\n{notes}",
                 f"RECENT ACTIONS:\n{actions}"]
        if last:
            parts.append(f"LAST STEP ENDED WITH:\n{last[:600]}")
        if self.step == 1:
            parts.append("First: look at what exists, then call update_plan with 3-6 short numbered steps. Then start on step 1.")
        else:
            parts.append("Do the next useful thing now with tools. Verify your own work with a command. "
                         "When the goal is done and verified, call finish. Do not repeat a failed action unchanged.")
        if self._idle_steps:
            parts.append("Your last step made no tool call. Either act now or call finish.")
        return "\n\n".join(parts)

    def start(self) -> Path:
        """Blocks until the run ends. Returns the report path."""
        self.started = time.time()
        self.deadline = self.started + self.budget
        self.ui.on_note(f"▶ Working alone for {plain_time(self.budget)} on: {self.goal}\n   Notes and results go in {self.dir}")
        self.write_status()
        ticker = threading.Thread(target=self._tick, daemon=True)
        ticker.start()
        try:
            while self.outcome == "running":
                if self.stop_requested:
                    self.outcome = "stopped"; break
                if self.remaining() <= self.reserve:
                    self.outcome = "timeout"; break
                self._run_step()
                if self.outcome != "running":
                    break
                if self._actions_this_step == 0:
                    self._idle_steps += 1
                    if self._idle_steps >= IDLE_STEPS_TO_STOP:
                        self.outcome = "finished"
                        self._append("notes.md", f"[step {self.step}] stopped: {IDLE_STEPS_TO_STOP} steps without any action, treating the goal as done")
                        break
                else:
                    self._idle_steps = 0
        except Exception as e:
            self.outcome = "error"
            self._append("notes.md", f"[step {self.step}] ERROR in harness: {e!r}")
        finally:
            self.work_elapsed = self.elapsed()
            self._write_report()
            self.write_status()
        return self.report_path

    def _tick(self):
        while not self.report_path.exists():
            time.sleep(1)
            self.ui.on_run_status(self.status())

    def _run_step(self):
        self.step += 1
        self._actions_this_step = 0
        self.write_status()
        chat = _StepChat(self.dir / "steps" / f"{self.step}.json")
        chat.messages.append({"role": "user", "content": self._step_prompt()})
        self.agent = Agent(self.cfg, autonomous=True)
        self.agent.deadline = self.deadline - self.reserve
        ctx = tools.ToolContext(approve=lambda a: a)
        ctx.autonomous = True
        ctx.run = self
        ctx.deadline = self.agent.deadline
        ctx.max_out = int(self.cfg.get("autonomous_tool_output", 3000))
        ctx.note = self.ui.on_note
        ctx.cancelled = self.stop_requested
        self.ctx = ctx
        # watchdog: cut the model call at the deadline
        stop_wd = threading.Event()
        def watchdog():
            while not stop_wd.wait(1.0):
                if time.time() >= self.agent.deadline and not self.stop_requested:
                    self.agent.cancel("time is up"); return
        threading.Thread(target=watchdog, daemon=True).start()

        def on_tool_start(name, shown, args):
            self.last_action = shown[:70]
            self.write_status()
            return {"ui": self.ui.on_tool_start(name, shown, args), "shown": shown}

        def on_tool_done(card, delta, result):
            self._action(card["shown"], result)
            self.ui.on_tool_done(card["ui"], delta, result)

        try:
            self._last_text = self.agent.run(chat, ctx, self.ui.on_text, on_tool_start, on_tool_done, self.ui.on_status,
                                             max_rounds=int(self.cfg.get("autonomous_rounds_per_step", 6)))
        finally:
            stop_wd.set()
            self.agent = None
            self.ctx = None
        if self.stop_requested and self.outcome == "running":
            self.outcome = "stopped"

    # ----- report -----
    def _wrap_up_text(self) -> str:
        """On timeout: one short model call (no tools) for 'where it got to / next step'."""
        agent = Agent(self.cfg, autonomous=False)
        budget = max(20, self.reserve - 5)
        agent.deadline = time.time() + budget
        chat = _StepChat(self.dir / "steps" / "wrap-up.json")
        chat.messages.append({"role": "user", "content":
            f"Time is up. Do not call tools. In at most 8 short lines, using the notes and actions below, write: "
            f"what got done, what was verified, what is still broken, and the single next step.\n\n"
            f"GOAL:\n{self.goal}\n\nPLAN:\n{self._read('plan.md')}\n\nNOTES:\n{self._read('notes.md', tail=30)}\n\n"
            f"ACTIONS:\n{self._read('actions.log', tail=20)}"})
        out = []
        watchdog = threading.Timer(budget, lambda: agent.cancel("time is up"))
        watchdog.start()
        try:
            agent.run(chat, tools.ToolContext(approve=lambda a: a), out.append, lambda *a: {}, lambda *a: None,
                      lambda s: None, max_rounds=0, use_tools=False, num_predict=350)
        except Exception as e:
            out.append(f"(wrap-up failed: {e})")
        finally:
            watchdog.cancel()
        return "".join(out).strip()

    def _write_report(self) -> None:
        elapsed = fmt(self.work_elapsed or self.elapsed())
        actions = self._read("actions.log").splitlines()
        ok = [a for a in actions if "] ok:" in a]
        failed = [a for a in actions if "] FAIL:" in a]
        queued = [a for a in actions if "] queued:" in a]
        head = {"finished": "Finished early: the agent reported the goal done." if self.finish_info else
                            "Finished early: the agent stopped taking actions (it did not call finish, so check the result).",
                "timeout": "Time ran out before the agent called finish.",
                "stopped": "Stopped by you.",
                "error": "Stopped because of an internal error (see notes.md)."}.get(self.outcome, self.outcome)
        lines = [f"# Eclipse AI run {self.id}", "", f"**Goal:** {self.goal}", "",
                 f"**Outcome:** {head}", f"**Working time:** {elapsed} of {fmt(self.budget)} · **steps:** {self.step} · "
                 f"**tool calls:** {len(actions)} ({len(ok)} ok, {len(failed)} failed, {len(queued)} queued for root)", ""]
        if self.finish_info:
            lines += ["## Completed", self.finish_info["completed"] or "(none given)", "",
                      "## Verified", self.finish_info["verified"] or "(none given)", "",
                      "## Still broken", self.finish_info["still_broken"] or "nothing", ""]
        elif self.outcome in ("timeout", "finished") and not self.stop_requested:
            self.ui.on_status("writing the report…")
            self.ui.on_note("⏱ time is up. Writing where it got to…" if self.outcome == "timeout" else "✔ no more actions. Writing the report…")
            text = self._wrap_up_text()
            lines += ["## Where it got to" + (" (written when time ran out)" if self.outcome == "timeout" else ""), text or "(no summary)", ""]
        lines += ["## Plan at the end", self._read("plan.md") or "(none)", "",
                  "## Attempted (every tool call)"] + ([f"- {a}" for a in actions] or ["- nothing"]) + [""]
        if failed:
            lines += ["## Failed"] + [f"- {a}" for a in failed] + [""]
        notes = self._read("notes.md")
        if notes:
            lines += ["## Notes (what worked / failed, as the agent recorded them)", notes, ""]
        if queued or rootq.pending():
            lines += ["## Waiting for you (needs root)",
                      f"{len(rootq.pending())} command(s) are in `{rootq.SCRIPT}`. They were not run during the run "
                      "(nobody was watching, so Eclipse AI never runs root commands in a timed run). "
                      "Run the plain `sudo` lines with one click: the card in the window after the run, "
                      "menu → \"Run root queue now\", or `eclipse-ai --run-root-queue`. Or read it and run it yourself.", ""]
        lines += [f"Run folder: {self.dir}", ""]
        self.report_path.write_text("\n".join(lines))

    def summary_for_chat(self) -> str:
        """Short version shown in the chat / terminal at the end."""
        try:
            text = self.report_path.read_text()
        except FileNotFoundError:
            return "no report"
        # first block up to the "Attempted" section
        short = text.split("## Attempted", 1)[0].strip()
        if rootq.pending():
            short += f"\n\n⏸ {rootq.summary()}"
        short += f"\n\nFull report: {self.report_path}"
        return short
