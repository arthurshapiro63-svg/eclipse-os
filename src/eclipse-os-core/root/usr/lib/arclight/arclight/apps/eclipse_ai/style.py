"""Eclipse liquid glass for Eclipse AI (shared material: apps/glass.py).

Arch AI's Midnight Blue look (by Arthur) re-made in Eclipse's: warm graphite glass the compositor blurs
the photo through, a bright top edge on every pane, the sun's gold for focus, the send button, your own
messages and progress; the model's replies sit on plain glass; tool cards are deeper wells with a thin
gold line; approval cards wear the corona. Red only for Stop and errors."""
from .. import glass
from ..glass import BACKDROP, CORONA, MATERIAL, RIM, RIM_LIFT

CSS = """
window.eclipse-ai, window.eclipse-ai.background {
  font-family: "Inter", "Noto Sans", sans-serif;
  background-color: rgba($base_rgb, 0.52);
  background-image: MATERIAL;
  color: $text;
  BACKDROP
}
window.eclipse-ai headerbar {
  background: transparent; box-shadow: none; border: none; color: $text; min-height: 46px;
  border-bottom: 1px solid rgba($text_rgb, 0.06);
}
window.eclipse-ai headerbar button { color: $text_dim; border-radius: $r_xs; background: transparent; box-shadow: none; }
window.eclipse-ai headerbar button:hover { color: $text; background-color: rgba($text_rgb, 0.08); }
window.eclipse-ai windowcontrols button.close:hover { background-color: rgba($red_rgb, 0.85); color: white; }
.ea-title { font-weight: 700; font-size: 1.08em; letter-spacing: 0.3px; color: $text; }
.ea-sub { color: $text_dim; font-size: 0.86em; }

/* model picker: a glass pill with a gold dot */
button.ea-model {
  background-color: rgba($text_rgb, 0.07); box-shadow: RIM; border-radius: 999px; padding: 3px 12px 3px 10px;
  color: $text;
}
button.ea-model:hover { background-color: rgba($text_rgb, 0.12); box-shadow: RIM, 0 0 0 1px rgba($gold_rgb, 0.40); }
.ea-dot { min-width: 8px; min-height: 8px; border-radius: 99px; background-color: $gold;
  box-shadow: 0 0 6px rgba($gold_rgb, 0.8); }
.ea-dot.online { background-color: $accent_bright; box-shadow: 0 0 6px rgba($accent_rgb, 0.8); }
popover.ea-pop > contents {
  background-color: rgba($surface_rgb, 0.95); border-radius: $r_md; padding: 6px;
  box-shadow: RIM, 0 12px 32px rgba($shadow_rgb, 0.6); color: $text;
}
.ea-pop list, .ea-pop row, .ea-pop label { color: $text; background: transparent; }
.ea-pop row { border-radius: $r_sm; padding: 8px 10px; margin: 1px 0; background: transparent; }
.ea-pop row:hover { background-color: rgba($text_rgb, 0.06); }
.ea-pop row.ea-current {
  background-color: rgba($accent_dim_rgb, 0.55);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.16), transparent 60%);
  box-shadow: CORONA;
}
.ea-pop .ea-mname { font-weight: 700; }
.ea-pop row.ea-current .ea-mname { color: $gold_soft; }
.ea-pop .ea-mhint { color: $text_dim; font-size: 0.88em; }

/* chat */
scrolledwindow.ea-scroll, scrolledwindow.ea-scroll > viewport { background: transparent; }
.bubble { padding: 10px 14px; border-radius: $r_md; }
.bubble-user {
  background-color: rgba($accent_dim_rgb, 0.60);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.18), transparent 70%);
  box-shadow: inset 0 1px rgba(255,255,255,0.20), inset 0 0 0 1px rgba($gold_rgb, 0.38);
  color: #FFFFFF;
}
.bubble-assistant {
  background-color: rgba($raised_rgb, 0.40);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 50px);
  box-shadow: RIM;
}
.bubble-note { background-color: rgba($sunken_rgb, 0.30); color: $text_dim; box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.07); }
.ea-hello { font-size: 1.5em; font-weight: 800; color: #FFFFFF; }
.ea-hello-sub { color: rgba($text_rgb, 0.78); }
.corona-line {
  min-height: 1px; margin: 2px 0;
  background-image: linear-gradient(to right, rgba($gold_rgb, 0.0), rgba($gold_rgb, 0.9) 30%, rgba($gold_soft_rgb, 0.0));
}
.code-block {
  font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 0.92em;
  background-color: rgba($sunken_rgb, 0.62); border-radius: $r_xs; padding: 8px 10px; color: $gold_soft;
  box-shadow: inset 0 1px 2px rgba($shadow_rgb, 0.5), inset 0 0 0 1px rgba($text_rgb, 0.06);
}
.tool-card {
  background-color: rgba($sunken_rgb, 0.46); border-radius: $r_sm; padding: 8px 12px;
  box-shadow: inset 2px 0 rgba($gold_rgb, 0.70), inset 0 0 0 1px rgba($text_rgb, 0.06);
}
.tool-kind { color: $gold; font-weight: 700; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
.tool-cmd { color: $text; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 0.94em; }
.tool-status { color: $text_dim; }
.tool-status.ok { color: $success; } .tool-status.fail { color: #F07373; } .tool-status.queued { color: $warning; }
.tool-out { color: rgba($text_rgb, 0.70); font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 0.88em; }
expander title { color: $text_dim; }

/* approval: the corona asks */
.approval-card {
  background-color: rgba($raised_rgb, 0.55);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.16), transparent 55%);
  border-radius: $r_md; padding: 14px 16px;
  box-shadow: inset 0 1px rgba(255,255,255,0.22), CORONA, 0 8px 22px rgba($shadow_rgb, 0.45);
}
.approval-card.answered-yes { box-shadow: inset 0 0 0 1px rgba($success_rgb, 0.6); }
.approval-card.answered-no { box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.2); }
.approval-title { color: $gold_soft; font-weight: 800; font-size: 1.05em; }
.approval-tag { color: #1A1205; background-color: $gold; border-radius: 99px; padding: 1px 9px; font-weight: 700; font-size: 0.82em; }
.approval-tag.root { background-color: rgba($red_rgb, 0.90); color: #FFFFFF; }
.approval-cmd {
  color: #FFFFFF; background-color: rgba($sunken_rgb, 0.70); padding: 8px 10px; border-radius: $r_xs;
  font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
  box-shadow: inset 0 1px 2px rgba($shadow_rgb, 0.5);
}
.dim { color: $text_dim; font-size: 0.92em; }
.statusline { color: $muted; font-size: 0.88em; }

/* the timed run: a glass strip with the sun's progress */
.ea-run {
  background-color: rgba($raised_rgb, 0.45); border-radius: $r_sm; padding: 8px 12px;
  box-shadow: RIM, inset 0 0 0 1px rgba($gold_rgb, 0.30);
}
.ea-run-title { font-weight: 700; color: $gold_soft; }
.ea-run-meta { color: $text_dim; font-size: 0.9em; font-family: "JetBrainsMono Nerd Font", monospace; }
.ea-run progressbar trough { min-height: 4px; border-radius: 4px; }
.ea-run progressbar progress { min-height: 4px; border-radius: 4px; }

/* typing */
.entry-frame {
  background-color: rgba($sunken_rgb, 0.50); border-radius: $r_md;
  box-shadow: inset 0 1px 2px rgba($shadow_rgb, 0.55), inset 0 0 0 1px rgba($text_rgb, 0.08);
}
.entry-frame:focus-within { box-shadow: CORONA; }
textview.entry, textview.entry text { background: transparent; color: $text; caret-color: $gold; }
button.suggested-action, button.ea-gold {
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep);
  background-color: $gold; color: #1A1205; border: none; border-radius: $r_sm; font-weight: 700;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.55), 0 0 14px rgba($gold_rgb, 0.30);
}
button.suggested-action:hover, button.ea-gold:hover { box-shadow: inset 0 1px rgba(255,255,255,0.6), 0 0 20px rgba($gold_rgb, 0.45); }
button.suggested-action:disabled { opacity: 0.5; }
button.destructive-action { background-color: rgba($red_rgb, 0.88); color: white; border: none; border-radius: $r_sm;
  box-shadow: inset 0 1px rgba(255,255,255,0.22); }
window.eclipse-ai button:not(.suggested-action):not(.destructive-action):not(.ea-gold):not(.ea-model):not(.quick-btn):not(.titlebutton) {
  background-color: rgba($text_rgb, 0.07); color: $text; border: none; border-radius: $r_sm; box-shadow: RIM;
}
window.eclipse-ai headerbar button:not(.ea-model) { box-shadow: none; background-color: transparent; }
window.eclipse-ai headerbar button:not(.ea-model):hover { background-color: rgba($text_rgb, 0.08); }
dropdown.duration > button { border-radius: $r_sm; }
popover > contents { background-color: rgba($surface_rgb, 0.95); color: $text; border-radius: $r_sm;
  box-shadow: RIM, 0 10px 30px rgba($shadow_rgb, 0.6); }
popover modelbutton:hover { background-color: rgba($gold_rgb, 0.14); }
button.quick-btn {
  background-color: rgba($raised_rgb, 0.40);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 40px);
  border: none; border-radius: $r_sm; padding: 10px 12px; color: $text; box-shadow: RIM;
}
button.quick-btn:hover { background-color: rgba($hover_rgb, 0.55);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22), inset 0 0 0 1px rgba($gold_rgb, 0.45), 0 0 16px rgba($gold_rgb, 0.18); }

/* full-window cards: AI off, get the model, engine missing */
.ea-card {
  background-color: rgba($raised_rgb, 0.42);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.12), transparent 50%),
                    linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 80px);
  border-radius: 24px; padding: 34px 40px; box-shadow: RIM_LIFT;
}
.ea-card-title { font-size: 1.6em; font-weight: 800; color: #FFFFFF; }
.ea-card-text { font-size: 1.05em; color: rgba($text_rgb, 0.80); }
.ea-card-small { color: $text_dim; font-size: 0.92em; }
.ea-card.off image.ea-logo { opacity: 0.55; }
button.ea-big { padding: 10px 26px; font-size: 1.08em; }
.error-text { color: #F07373; }
"""


def install():
    return glass.install(CSS.replace("MATERIAL", MATERIAL).replace("BACKDROP", BACKDROP).replace("RIM_LIFT", RIM_LIFT)
                         .replace("CORONA", CORONA).replace("RIM", RIM))
