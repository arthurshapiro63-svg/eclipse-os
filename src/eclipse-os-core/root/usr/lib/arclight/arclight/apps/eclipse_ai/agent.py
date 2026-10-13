"""The chat loop: send messages to Ollama, stream text, run tool calls, repeat (from Arch AI by Arthur)."""
import json
import platform
import time

from . import config, rootq, tools, ultra
from .ollama_client import Ollama, OllamaError

RULES_ROOT_QUEUE = """- Nothing runs as root right now. Work inside the home folder: ~/.local/bin, ~/.config, systemctl --user. install_packages still works (Eclipse's package service makes a restore point first).
- If something truly needs root, call run_command with sudo anyway: it is NOT run, it is queued in the root review script for the user to run later. Then carry on and tell the user it is waiting there. Never retry a queued command.
- Never ask for the user's password in chat. There is no password on this machine's AI path."""

RULES_ROOT_ASK = """- You are not root. For changes, prefer user-level ways: ~/.local/bin, ~/.config, systemctl --user.
- When the user asks for a command with sudo, run it exactly as given, WITH sudo. When a command fails with "Permission denied" and root would fix it, run it again as plain `sudo <command>` instead of giving up.
- If something truly needs root, call run_command with plain `sudo <command>`. The user sees the exact command and clicks yes; then it runs as root through Eclipse's root service. There is no password. Every part must start with plain sudo: put `cd`, user steps and pipes without sudo in their own call, never `sudo -u`/`sudo -i`, never sudo with yay or paru.
- Install, remove and update software with install_packages, remove_packages and update_system (official repos and the AUR; a restore point is made first). Do not use pacman or yay in run_command for that.
- If the user says no, stop. If a command is queued in the root review script (mixed command), do not retry it unchanged; tell the user it is waiting there.
- Never ask for the user's password in chat."""


def root_rules(root_mode: str = "ask", autonomous: bool = False) -> str:
    return RULES_ROOT_QUEUE if autonomous or root_mode == "queue" else RULES_ROOT_ASK


def system_prompt(autonomous: bool = False, root_mode: str = "ask", model_name: str = "Eclipse Crescent") -> str:
    root_now = not autonomous and root_mode != "queue"
    base = f"""You are Eclipse AI, the local desktop assistant of Eclipse OS: Arthur's own AI-native Arch Linux with the Hyprland Wayland compositor, the DankMaterialShell bar and the ghostty terminal. You run fully on this computer: the model runs locally through Ollama. Nothing goes to the cloud.

The user is dyslexic and often dictates. Messages may have typos or odd words: guess the meaning and act. Never correct their spelling. If a request is truly unclear, ask one short question.
Write short, clear sentences. No walls of text. Use a short bullet list when listing things. Plain words. No markdown headers.

You can act on this machine with your tools: run shell commands, install software, open apps, read and edit files (including the Hyprland and terminal configs), change Eclipse settings (find_settings, then change_setting: look, wallpaper, gaps, blur, input, sound, screens, power, AI) and report system info. "Update everything" means the update_system tool (it lists updates and {'runs the real update after the user clicks yes' if root_now else 'queues the real update for the user'}).

Rules:
- Use a tool to act. Never pretend you ran something.
- Safe read-only commands run right away. Anything that deletes or overwrites files asks the user first. If the user says no, stop and say so.
{root_rules(root_mode, autonomous)}
- For anything that is a setting, prefer find_settings + change_setting over editing config files.
- After a tool finishes, confirm what you did in one short line.
- If a command fails, say what failed and suggest one fix.
- Before editing a config file, read it first and change only the needed lines.
- Do not ask for permission in text; call the tool and the app will ask.
- If asked which model you are: you are {model_name}, Eclipse AI's local model.

Facts: user = {config.HOME.name}, home = {config.HOME}. Kernel {platform.release()}.
Hyprland config: ~/.config/hypr/hyprland.lua (Lua format, Hyprland 0.56; binds look like hl.bind("SUPER + A", hl.dsp.exec_cmd("cmd"))). Eclipse's own layer: /usr/share/arclight/hypr/arclight.lua.
Eclipse machine API: the `arc` command (`arc --help`; `arc doctor` checks the whole system). Terminal: ~/.config/ghostty/config.
Today: {time.strftime('%A %Y-%m-%d')}."""
    if not autonomous:
        return base
    return base + f"""

TIMED AUTONOMOUS RUN. Nobody is watching. You work alone toward one goal until it is done or time runs out.
- Each step you get the goal, the plan, the notes (what worked, what failed) and recent actions. That is your only memory: use log_progress for anything a later step must know, and update_plan when the plan changes.
- Loop: pick the next step from the plan, act with tools, check the result with a real command (run the program, run the tests, read the file back), fix what is wrong, repeat.
- Do not repeat a failed action unchanged. Try a different way or move on.
- Actions inside the home folder are approved automatically. Commands with sudo are queued in {rootq.SCRIPT}, not run (nobody is here to say yes); the user can run the whole queue with one click after the run.
- Keep text tiny: one line about what you are doing. Spend your effort on tool calls.
- Call log_progress at least once per step (what you tried, worked or failed). Commands run from the home folder: use cd or full paths.
- When the goal is done and verified, call finish right away. Do not keep working just to use the time."""


def think_setting(model: str, cfg: dict):
    t = cfg.get("think", "auto")
    if t == "auto":
        return "low" if "gpt-oss" in model else False
    return t


class Agent:
    """Runs on a worker thread. Callbacks are called from that thread; the UI wraps them in idle_add."""

    def __init__(self, cfg: dict, autonomous: bool = False):
        self.cfg = cfg
        self.client = Ollama(cfg.get("host", config.DEFAULTS["host"]))
        self.cancelled = False
        self.cancel_reason = "stopped"
        self.autonomous = autonomous
        self.deadline: float | None = None   # epoch seconds: no new model round or tool starts after it
        self.tool_calls_made = 0
        self.proc = None     # Ultra's running process (killed on cancel)

    def cancel(self, reason: str = "stopped"):
        self.cancel_reason = reason
        self.cancelled = True
        self.client.cancel()
        if self.proc is not None:
            ultra._kill(self.proc)

    def out_of_time(self) -> bool:
        return self.deadline is not None and time.time() >= self.deadline

    def run(self, chat, ctx: tools.ToolContext, on_text, on_tool_start, on_tool_done, on_status, max_rounds: int | None = None,
            use_tools: bool = True, num_predict: int | None = None):
        """chat.messages already contains the new user message. Returns the last assistant text."""
        self.cancelled = False
        model = self.cfg["model"]
        if model == ultra.MODEL_ID:
            return ultra.run(self, chat, ctx, on_text, on_tool_start, on_tool_done, on_status,
                             use_tools=use_tools, num_predict=num_predict)
        options = {"num_ctx": int(self.cfg.get("num_ctx", 8192)), "temperature": float(self.cfg.get("temperature", 0.3))}
        if num_predict:
            options["num_predict"] = int(num_predict)
        tool_list = (tools.TOOLS + (tools.AUTONOMOUS_TOOLS if self.autonomous else [])) if use_tools else None
        rounds = 0
        stats = {}
        content = ""
        limit = int(self.cfg.get("max_tool_rounds", 8)) if max_rounds is None else max_rounds
        while rounds <= limit:
            if self.out_of_time():
                on_text("\n(time is up)")
                break
            rounds += 1
            messages = [{"role": "system", "content": system_prompt(self.autonomous, str(self.cfg.get("root_mode", "ask")),
                                                                    config.display_name(self.cfg, model))}] + chat.messages
            content, thinking, tool_calls = "", "", []
            on_status("thinking…")
            try:
                for chunk in self.client.chat_stream(model, messages, tool_list, think_setting(model, self.cfg),
                                                     options, self.cfg.get("keep_alive", "15m")):
                    if self.cancelled:
                        break
                    msg = chunk.get("message", {})
                    if msg.get("thinking"):
                        thinking += msg["thinking"]
                        on_status("thinking…")
                    if msg.get("content"):
                        content += msg["content"]
                        on_text(msg["content"])
                    if msg.get("tool_calls"):
                        tool_calls.extend(msg["tool_calls"])
                    if chunk.get("done"):
                        ec, ed = chunk.get("eval_count", 0), chunk.get("eval_duration", 0)
                        if ec and ed:
                            stats = {"tok_s": ec / (ed / 1e9), "tokens": ec}
            except OllamaError as e:
                on_text(f"\n\n⚠ Model error: {e}")
                break
            except Exception as e:
                if self.cancelled:
                    on_text(f"\n\n({self.cancel_reason})")
                else:
                    on_text(f"\n\n⚠ Could not reach the model server: {e}")
                break
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            chat.messages.append(assistant_msg)
            if self.cancelled or not tool_calls:
                break
            for call in tool_calls:
                fn = call.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"command": args} if name == "run_command" else {}
                shown = tools.describe(name, args)
                on_status(f"running: {shown[:60]}")
                card = on_tool_start(name, shown, args)
                if self.cancelled:
                    result = tools.ToolResult(f"not run: {self.cancel_reason}", ok=False)
                elif self.out_of_time() and name not in ("log_progress", "update_plan", "finish"):
                    result = tools.ToolResult("not run: time is up", ok=False)
                else:
                    ctx.on_output = lambda s, c=card: on_tool_done(c, s, None)  # streaming output
                    self.tool_calls_made += 1
                    try:
                        result = tools.execute(name, args, ctx)
                    except tools.StopRun:
                        on_tool_done(card, None, tools.ToolResult("run finished"))
                        chat.messages.append({"role": "tool", "tool_name": name, "content": "run finished"})
                        chat.save()
                        return content
                on_tool_done(card, None, result)
                chat.messages.append({"role": "tool", "tool_name": name, "content": result.text})
            chat.save()
        on_status(f"{stats['tok_s']:.1f} tok/s" if stats else "")
        chat.save()
        return content
