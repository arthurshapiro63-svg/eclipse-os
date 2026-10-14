#!/bin/bash
# 0.1.2 checks on an installed VM (after install_test.sh ... NAME left it running, user tester / Synthetic-Pw-0001):
#   sudo asks for a password; arclightd's changes need the administrator password; Eclipse AI's root path stops at
#   the polkit prompt even when its yes card is answered by software, and AI-injected keys do not get past it;
#   the person's password (typed on the VM keyboard) does. Then the passwordless opt-in, and the Codex (cloud) label.
#   auth_test.sh NAME
set -uo pipefail
H=$(dirname "$(realpath "$0")"); n=$1
VMDIR=${VMDIR:-/var/tmp/eclipse-vmtest}; d=$VMDIR/$n; S=${SHOTS:-$d}
PW=Synthetic-Pw-0001
ex() { "$H/vm.sh" exec "$n" "$@"; }
shot() { "$H/vm.sh" shot "$n" "$S/$n-$1.png" >/dev/null; echo "  screenshot: $S/$n-$1.png"; }
human_types() { python3 "$H/sendkeys.py" "$d/mon.sock" "$1" --enter; }   # the VM's own keyboard = a person
sig=$(ex 'ls /run/user/1000/hypr | head -1' | head -1 | tr -d '\r\n')
SESSION_ENV="XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus HYPRLAND_INSTANCE_SIGNATURE=$sig WAYLAND_DISPLAY=wayland-1"
as_tester() { ex "runuser -u tester -- env $SESSION_ENV $1" "${2:-60}"; }
in_session() {   # start a script inside the Hyprland session (a child of Hyprland, like an app the user opened)
    as_tester "hyprctl dispatch 'hl.dsp.exec_cmd(\"$1\")'" >/dev/null
}
ok=0; bad=0
ex 'faillock --user tester --reset' >/dev/null
check() { if eval "$2"; then echo "PASS  $1"; ok=$((ok+1)); else echo "FAIL  $1"; bad=$((bad+1)); fi; }

echo "== files"
ex 'ls /etc/sudoers.d /etc/polkit-1/rules.d /usr/share/polkit-1/rules.d 2>&1; cat /etc/sudoers.d/10-arclight'
check "no passwordless sudoers/polkit files on the installed system" \
    "! ex 'ls /etc/sudoers.d/90-eclipse-nopasswd /etc/polkit-1/rules.d/49-eclipse-nopasswd.rules /usr/share/polkit-1/rules.d/49-arclight.rules' >/dev/null 2>&1"

echo "== sudo"
out=$(ex 'runuser -u tester -- sudo -n true 2>&1; echo rc=$?'); echo "$out"
check "sudo -n as tester is refused (password required)" "grep -q 'password is required' <<<\"\$out\""
out=$(ex "printf '%s\n' $PW | runuser -u tester -- sudo -S -k -p '' id -u 2>&1"); echo "$out"
check "sudo with the right password works" "grep -qx 0 <<<\"\$out\""

echo "== arclightd: reading is open, changes are not"
out=$(as_tester 'arc pkg info pacman 2>&1 | head -3'); echo "$out"
check "reading (pkg.info) works without a password" "grep -qi 'pacman' <<<\"\$out\""

echo "== Eclipse AI's root path: the yes card is answered by software, then..."
cat > "$d/ai_root.py" <<'PY'
import json, sys
sys.path.insert(0, "/usr/lib/arclight")
from arclight.apps.eclipse_ai import tools
seen = []
def approve(a):          # an AI "clicking" its own yes: no person involved
    seen.append(a.command); a.approved = True; return a
ctx = tools.ToolContext(approve)
r = tools.execute("run_command", {"command": "sudo touch /root/ai-was-here"}, ctx)
json.dump({"ok": r.ok, "text": r.text, "approved": seen}, open("/tmp/ai_root.result", "w"))
PY
"$H/vm.sh" push "$n" "$d/ai_root.py" /tmp/ai_root.py >/dev/null
ex 'rm -f /root/ai-was-here /tmp/ai_root.result; chmod 644 /tmp/ai_root.py'
in_session "python3 /tmp/ai_root.py"
sleep 6
shot ai-root-prompt
out=$(ex 'pgrep -a pkcheck; pgrep -a hyprpolkitagent'); echo "$out"
check "a polkit password prompt is waiting (pkcheck running)" "grep -q dev.arclight.admin <<<\"\$out\""
check "nothing ran yet" "! ex 'test -e /root/ai-was-here'"
echo "-- the AI now drives the keyboard through Eclipse (input.key / input.type): Enter, then a guess"
as_tester 'arc input key Return' >/dev/null; sleep 4
as_tester 'arc input type password123' >/dev/null; as_tester 'arc input key Return' >/dev/null; sleep 5
shot ai-root-after-injected-keys
check "AI-injected keys did not authorize it" "! ex 'test -e /root/ai-was-here'"
echo "-- a person types the password on the VM keyboard"
sleep 6   # the prompt waits a moment after each wrong password before it takes input again
out=$(as_tester 'arc screen ocr 2>/dev/null'); echo "$out" | grep -i -A1 'Administrator change' | head -3
check "the prompt names the command" "grep -q 'ai-was-here' <<<\"\$out\""
human_types "$PW"; sleep 8
shot ai-root-after-password
for i in $(seq 20); do ex 'test -s /tmp/ai_root.result' >/dev/null 2>&1 && break; sleep 2; done
ex 'cat /tmp/ai_root.result; echo; ls -l /root/ai-was-here'
check "with the person's password it ran as root" "ex 'test -e /root/ai-was-here' >/dev/null"

echo "== passwordless admin opt-in (Settings key system.sudo_nopasswd)"
cat > "$d/optin.sh" <<'SH'
#!/bin/bash
arc settings set system.sudo_nopasswd true > /tmp/optin.out 2>&1; echo "rc=$?" >> /tmp/optin.out
SH
"$H/vm.sh" push "$n" "$d/optin.sh" /tmp/optin.sh >/dev/null; ex 'chmod 755 /tmp/optin.sh; rm -f /tmp/optin.out'
in_session /tmp/optin.sh; sleep 6
shot optin-prompt
out=$(as_tester 'arc screen ocr 2>/dev/null'); echo "$out" | grep -i 'passwordless' | head -2
check "the prompt says it turns ON passwordless admin" "grep -qi 'ON passwordless' <<<\"\$out\""
check "turning it on asks for the password first" "! ex 'test -e /etc/sudoers.d/90-eclipse-nopasswd'"
human_types "$PW"; sleep 8
ex 'cat /tmp/optin.out'
out=$(ex 'runuser -u tester -- sudo -n true 2>&1; echo rc=$?'); echo "$out"
check "after opting in, sudo needs no password" "grep -q rc=0 <<<\"\$out\""
as_tester 'arc settings set system.sudo_nopasswd false' >/dev/null
out=$(ex 'runuser -u tester -- sudo -n true 2>&1; echo rc=$?'); echo "$out"
check "turning it off again restores the password" "grep -q 'password is required' <<<\"\$out\""

echo "== Codex (cloud) label (a stub codex CLI that reports 'Logged in'; the real one is not on the ISO)"
cat > "$d/codex" <<'SH'
#!/bin/sh
if [ "$1 $2" = "login status" ]; then echo "Logged in using ChatGPT"; exit 0; fi
echo '{"type":"item.completed","item":{"type":"agent_message","text":"stub reply"}}'
SH
"$H/vm.sh" push "$n" "$d/codex" /usr/local/bin/codex >/dev/null
ex 'chmod 755 /usr/local/bin/codex; mkdir -p /home/tester/.config/eclipse-ai
    python3 -c "import json,os; p=\"/home/tester/.config/eclipse-ai/config.json\"; c=json.load(open(p)) if os.path.exists(p) else {}; c[\"model\"]=\"ultra\"; json.dump(c,open(p,\"w\"))"
    chown -R tester: /home/tester/.config/eclipse-ai'
in_session eclipse-ai; sleep 20
shot codex-chat
out=$(as_tester 'arc screen ocr 2>/dev/null | head -80'); echo "$out" | grep -i -E 'codex|cloud|openai|totality' | head
check "the window says Codex (cloud)" "grep -qi 'codex' <<<\"\$out\""
check "the window says messages go to OpenAI / leave the computer" "grep -qi -E 'openai|leave this|your messages' <<<\"\$out\""
check "the name Totality is not used for the model" "! grep -qi 'Eclipse Totality' <<<\"\$out\""
check "the greeting does not claim it runs on this PC" "! grep -qi 'I run on this PC' <<<\"\$out\""
as_tester "arc ui press 'Codex (cloud)'" >/dev/null; sleep 2
shot codex-picker
out=$(as_tester 'arc screen ocr 2>/dev/null'); echo "$out" | grep -i 'leave' | head -2
check "the picker says messages leave this computer" "grep -qi 'leave this computer' <<<\"\$out\""
echo "RESULT: $ok passed, $bad failed"
