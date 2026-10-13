"""Eclipse liquid glass for the Settings app (see apps/glass.py for the shared material).

The window is translucent night glass the compositor blurs the photo through; the sidebar is a deeper
pane, cards float as lighter glass tiles with a bright top edge, and whatever is selected or focused is
lit like the eclipse: a dark disc with a golden rim. Switches, sliders and progress run on sun-gold.
Red is only for errors and destructive actions."""
from .. import glass
from ..glass import BACKDROP, CORONA, MATERIAL, RIM, RIM_LIFT

CSS = """
:root {
  --accent-bg-color: $gold;
  --accent-fg-color: #1A1205;
  --accent-color: $gold_soft;
  --window-bg-color: rgba($base_rgb, 0.50);
  --window-fg-color: $text;
  --view-bg-color: transparent;
  --view-fg-color: $text;
  --headerbar-bg-color: transparent;
  --headerbar-fg-color: $text;
  --headerbar-backdrop-color: transparent;
  --headerbar-shade-color: rgba(0, 0, 0, 0);
  --headerbar-border-color: rgba($text_rgb, 0.06);
  --sidebar-bg-color: rgba($sunken_rgb, 0.40);
  --sidebar-backdrop-color: rgba($sunken_rgb, 0.40);
  --sidebar-fg-color: $text;
  --sidebar-border-color: rgba($text_rgb, 0.07);
  --secondary-sidebar-bg-color: rgba($sunken_rgb, 0.40);
  --card-bg-color: rgba($raised_rgb, 0.40);
  --card-fg-color: $text;
  --card-shade-color: rgba($shadow_rgb, 0.45);
  --popover-bg-color: rgba($surface_rgb, 0.95);
  --popover-fg-color: $text;
  --dialog-bg-color: rgba($surface_rgb, 0.96);
  --border-color: rgba($text_rgb, 0.08);
  --destructive-bg-color: $red;
  --destructive-color: #F07373;
  --error-bg-color: $red;
  --error-color: #F07373;
  --warning-bg-color: $warning;
  --warning-color: $warning;
  --success-bg-color: $success;
  --success-color: $success;
}

window.arclight-settings, window.arclight-settings.background {
  font-family: "Inter", "Noto Sans", sans-serif;
  font-size: $fs_body;   /* the shared type scale (glass.SCALE): same base as the Store */
  background-color: rgba($base_rgb, 0.50);
  background-image: MATERIAL;
  color: $text;
  BACKDROP
}

/* bars float on the glass: no paint, just a faint hairline under them */
window.arclight-settings headerbar, window.arclight-settings toolbarview > .top-bar {
  background: transparent; box-shadow: none; border: none; color: $text;
}
window.arclight-settings toolbarview > .top-bar { border-bottom: 1px solid rgba($text_rgb, 0.06); }
window.arclight-settings headerbar button { color: $text_dim; border-radius: $r_xs; }
window.arclight-settings headerbar button:hover { color: $text; background-color: rgba($text_rgb, 0.08); }
window.arclight-settings windowcontrols button.close:hover { background-color: rgba($red_rgb, 0.85); color: white; }

/* the sidebar is a deeper pane of the same glass */
window.arclight-settings .sidebar-pane, window.arclight-settings .sidebar-pane toolbarview {
  background-color: rgba($sunken_rgb, 0.40);
  background-image: none;
  box-shadow: inset -1px 0 rgba($text_rgb, 0.07);
}
.arc-sidebar-list, .arc-sidebar-list.navigation-sidebar { background: transparent; border: none; }
.arc-sidebar-list row {
  border-radius: $r_sm;
  margin: 2px 8px;
  padding: 3px 4px;
  min-height: 36px;
  color: rgba($text_rgb, 0.86);
}
.arc-sidebar-list row image { color: $accent_bright; opacity: 0.85; }
.arc-sidebar-list row:hover:not(:selected) { background-color: rgba($text_rgb, 0.05); }
.arc-sidebar-list row:selected {
  background-color: rgba($accent_dim_rgb, 0.62);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.16), transparent 60%);
  box-shadow: CORONA;
  color: #FFFFFF;
}
.arc-sidebar-list row:selected image { color: $gold; opacity: 1; }
.arc-sidebar-title { font-weight: 700; letter-spacing: 0.4px; }

/* search: a sunken well of glass, lit gold when typing */
.arc-search, window.arclight-settings entry {
  background-color: rgba($sunken_rgb, 0.50);
  border-radius: $r_sm;
  box-shadow: inset 0 1px 2px rgba($shadow_rgb, 0.55), inset 0 0 0 1px rgba($text_rgb, 0.08);
  color: $text;
}
.arc-search { margin: 6px 10px 8px 10px; }
.arc-search:focus-within, window.arclight-settings entry:focus-within { box-shadow: CORONA; outline: none; }

/* content: groups are floating glass tiles with a bright top edge */
window.arclight-settings preferencespage, window.arclight-settings preferencespage > scrolledwindow > viewport,
window.arclight-settings .arc-content { background: transparent; }
.boxed-list, list.boxed-list, preferencesgroup .boxed-list {
  border-radius: $r_md;
  background-color: rgba($raised_rgb, 0.40);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 60px);
  border: none;
  box-shadow: RIM_LIFT;
}
list.boxed-list > row { border-bottom: 1px solid rgba($text_rgb, 0.05); background: transparent; }
list.boxed-list > row:last-child { border-bottom: none; }
list.boxed-list > row:hover:not(:selected) { background-color: rgba($text_rgb, 0.04); }
preferencesgroup > box > box > label.heading, preferencesgroup .title { color: $text; }
/* hints under a row: plain words in the UI font, dimmed by colour (not opacity) so they stay readable */
.arc-row .subtitle { font-size: 0.9em; color: $text_dim; opacity: 1; }
.arc-value { font-weight: 600; color: $gold_soft; }

/* sliders and switches run on sunlight */
.arc-scale trough, window.arclight-settings scale trough {
  min-height: 4px; border-radius: 4px; background-color: rgba($text_rgb, 0.12);
}
.arc-scale highlight, window.arclight-settings scale highlight {
  background-image: linear-gradient(to right, rgba($gold_deep_rgb, 0.85), $gold, $gold_soft);
  border-radius: 4px;
  box-shadow: 0 0 8px rgba($gold_rgb, 0.40);
}
.arc-scale slider, window.arclight-settings scale slider {
  background-color: $core;
  box-shadow: 0 0 0 2px rgba($gold_rgb, 0.85), 0 0 12px rgba($gold_rgb, 0.45), 0 2px 4px rgba($shadow_rgb, 0.6);
}
window.arclight-settings switch {
  background-color: rgba($text_rgb, 0.14);
  box-shadow: inset 0 1px 2px rgba($shadow_rgb, 0.5);
}
window.arclight-settings switch:checked {
  background-image: linear-gradient(to right, $gold_deep, $gold);
  box-shadow: 0 0 10px rgba($gold_rgb, 0.35), inset 0 1px rgba(255, 255, 255, 0.35);
}
window.arclight-settings switch > slider { background-color: #FFFFFF; box-shadow: 0 1px 3px rgba($shadow_rgb, 0.6); }
window.arclight-settings checkbutton check:checked, window.arclight-settings radio:checked {
  background-color: $gold; color: #1A1205;
}

/* buttons: small glass pills; the suggested one is the sun */
window.arclight-settings button.text-button:not(.flat):not(.suggested-action):not(.destructive-action),
window.arclight-settings button.pill:not(.suggested-action):not(.destructive-action) {
  background-color: rgba($text_rgb, 0.07);
  box-shadow: RIM;
  border-radius: $r_sm;
  color: $text;
}
window.arclight-settings button.text-button:hover:not(.flat):not(.suggested-action):not(.destructive-action) {
  background-color: rgba($text_rgb, 0.12);
}
window.arclight-settings button.suggested-action {
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep);
  background-color: $gold;
  color: #1A1205;
  border: none;
  border-radius: $r_sm;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.55), 0 0 14px rgba($gold_rgb, 0.30);
}
window.arclight-settings button.suggested-action:hover { box-shadow: inset 0 1px rgba(255,255,255,0.6), 0 0 20px rgba($gold_rgb, 0.45); }
window.arclight-settings button.destructive-action {
  background-color: rgba($red_rgb, 0.85); color: white; border-radius: $r_sm;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.22);
}
window.arclight-settings popover > contents {
  background-color: rgba($surface_rgb, 0.95);
  border-radius: $r_sm;
  box-shadow: RIM, 0 10px 30px rgba($shadow_rgb, 0.6);
}
window.arclight-settings toast {
  background-color: rgba($surface_rgb, 0.92);
  border-radius: $r_sm;
  box-shadow: RIM, 0 0 0 1px rgba($gold_rgb, 0.35), 0 8px 24px rgba($shadow_rgb, 0.5);
  color: $text;
}

/* theme cards: tiny desktops; the active one wears the corona */
button.arc-theme-card, button.arc-wall {
  background-image: none;
  border: none;
}
button.arc-theme-card {
  padding: 8px 8px 10px 8px;
  border-radius: $r_md;
  background-color: rgba($raised_rgb, 0.34);
  box-shadow: RIM;
}
button.arc-theme-card:hover { background-color: rgba($hover_rgb, 0.50); }
button.arc-theme-card.arc-selected {
  background-color: rgba($accent_dim_rgb, 0.50);
  box-shadow: inset 0 1px rgba(255,255,255,0.22), CORONA;
}
.arc-theme-name { font-weight: 600; margin-left: 2px; }
button.arc-theme-card.arc-selected .arc-theme-name { color: $gold_soft; }

/* wallpaper grid */
button.arc-wall {
  padding: 4px;
  border-radius: $r_sm;
  background-color: rgba($raised_rgb, 0.28);
  box-shadow: RIM;
}
button.arc-wall picture { border-radius: $r_xs; }
button.arc-wall:hover { background-color: rgba($text_rgb, 0.10); }
button.arc-wall.arc-selected { background-color: rgba($accent_dim_rgb, 0.55); box-shadow: CORONA; }
.arc-wall-name { font-size: 0.82em; opacity: 0.75; }
.arc-hero {
  border-radius: $r_md;
  box-shadow: inset 0 1px rgba(255,255,255,0.18), 0 0 0 1px rgba($text_rgb, 0.08), 0 0 26px rgba($gold_rgb, 0.10),
              0 10px 28px rgba($shadow_rgb, 0.6);
}

/* about: the photo, frosted, behind the mark */
.arc-about-hero { border-radius: $r_lg; box-shadow: inset 0 1px rgba(255,255,255,0.18), 0 10px 28px rgba($shadow_rgb, 0.55); }
.arc-about-hero picture { border-radius: $r_lg; }
.arc-about-glass {
  border-radius: $r_lg;
  background-image: linear-gradient(to bottom, rgba($base_rgb, 0.0) 30%, rgba($base_rgb, 0.70));
}
.arc-brand { font-size: 2.4em; font-weight: 300; letter-spacing: 1px; color: #FFFFFF; }
.arc-tagline { color: $gold_soft; opacity: 0.9; }
.arc-corona-line {
  min-height: 1px;
  background-image: linear-gradient(to right, rgba($gold_rgb, 0), rgba($gold_rgb, 0.85), rgba($gold_rgb, 0));
}
.arc-dot-ok { color: $success; }
.arc-dot-bad { color: $red; }
.arc-mono { font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
.arc-keycap {
  font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
  font-size: 0.85em;
  padding: 2px 8px;
  border-radius: 7px;
  background-color: rgba($text_rgb, 0.07);
  box-shadow: inset 0 1px rgba(255,255,255,0.14), inset 0 -1px rgba($shadow_rgb, 0.5), 0 0 0 1px rgba($gold_rgb, 0.22);
  color: $gold_soft;
}
""".replace("MATERIAL", MATERIAL).replace("BACKDROP", BACKDROP).replace("RIM_LIFT", RIM_LIFT).replace("CORONA", CORONA).replace("RIM", RIM)


def install():
    return glass.install(CSS)
