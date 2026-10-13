"""Eclipse liquid glass for the Store. The window also wears the Settings classes (same sidebar, header,
lists, switches, buttons), so this only adds what a store needs: the photo hero with the big search, app
tiles, result rows, source badges, the app page and the golden progress card. Gold = act (Install, Open,
Update all, focus, progress); red = Remove and errors only."""
from .. import glass
from ..glass import CORONA, RIM
from ..settings import style as settings_style

CSS = """
window.arclight-store { font-size: $fs_body; }
window.arclight-store .sidebar-pane { min-width: 230px; }

/* ---------- sidebar extras */
.st-count { font-size: $fs_micro; font-weight: 800; color: #1A1205; background-color: $gold; border-radius: 99px;
  padding: 1px 8px; min-width: 10px; }
button.st-askcard {
  margin: 8px 10px 12px 10px; padding: 12px 14px; border-radius: $r_md; border: none; color: $text;
  background-color: rgba($accent_dim_rgb, 0.55);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.20), transparent 62%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22), inset 0 0 0 1px rgba($gold_rgb, 0.45);
}
button.st-askcard:hover { box-shadow: inset 0 1px 0 rgba(255,255,255,0.26), CORONA; }
.st-askcard-title { font-size: $fs_lead; font-weight: 800; color: $gold_soft; }
.st-askcard-sub { font-size: $fs_small; color: rgba($text_rgb, 0.78); }

/* ---------- header "Ask the AI" pill */
window.arclight-store headerbar button.st-askbtn {
  color: $gold_soft; font-weight: 700; padding: 4px 14px; border-radius: 99px;
  background-color: rgba($gold_rgb, 0.10); box-shadow: inset 0 0 0 1px rgba($gold_rgb, 0.45);
}
window.arclight-store headerbar button.st-askbtn:hover { background-color: rgba($gold_rgb, 0.20); color: #FFFFFF; }

/* ---------- hero: the photo, frosted, with the search front and centre */
.st-hero { border-radius: $r_xl;
  box-shadow: inset 0 1px rgba(255,255,255,0.20), 0 0 0 1px rgba($text_rgb, 0.08), 0 0 30px rgba($gold_rgb, 0.10),
              0 14px 34px rgba($shadow_rgb, 0.55); }
.st-hero-scrim { border-radius: $r_xl;
  background-image: linear-gradient(to right, rgba($base_rgb, 0.78), rgba($base_rgb, 0.30) 55%, rgba($base_rgb, 0.05)),
                    linear-gradient(to bottom, rgba($base_rgb, 0.0) 40%, rgba($base_rgb, 0.55)); }
.st-kicker { font-size: $fs_small; font-weight: 800; letter-spacing: 3px; color: $gold; }
.st-hero-title { font-size: $fs_hero; font-weight: 800; color: #FFFFFF; }
.st-hero-sub { font-size: $fs_lead; color: rgba($text_rgb, 0.86); }
.st-corona-line { min-height: 2px;
  background-image: linear-gradient(to right, rgba($gold_rgb, 0.0), rgba($gold_rgb, 0.95) 25%, rgba($gold_soft_rgb, 0.0)); }
window.arclight-store entry.st-search {
  font-size: $fs_title; min-height: 54px; padding: 0 18px; border-radius: $r_md; color: #FFFFFF; caret-color: $gold;
  background-color: rgba($sunken_rgb, 0.72);
  box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.16), inset 0 2px 6px rgba(0,0,0,0.40), 0 8px 22px rgba($shadow_rgb, 0.45);
}
window.arclight-store entry.st-search:focus-within {
  box-shadow: inset 0 0 0 2px rgba($gold_rgb, 0.90), 0 0 18px rgba($gold_rgb, 0.28), 0 8px 22px rgba($shadow_rgb, 0.45);
}
window.arclight-store entry.st-search image { color: $gold_soft; -gtk-icon-size: 20px; }

/* ---------- sections + tiles */
.st-sec-title { font-size: $fs_heading; font-weight: 800; color: #FFFFFF; }
.st-sec-sub { font-size: $fs_body; color: $text_dim; }
window.arclight-store flowbox, window.arclight-store flowboxchild { background: transparent; padding: 0; }
window.arclight-store flowboxchild:focus-visible { outline: none; }
button.st-tile {
  padding: 14px 14px 12px 14px; border-radius: $r_lg; border: none; color: $text;
  background-color: rgba($raised_rgb, 0.42);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.06), rgba($text_rgb, 0) 64px);
  box-shadow: RIM, 0 8px 22px rgba($shadow_rgb, 0.35);
}
button.st-tile:hover {
  background-color: rgba($hover_rgb, 0.60);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.24), inset 0 0 0 1px rgba($gold_rgb, 0.50), 0 0 18px rgba($gold_rgb, 0.18),
              0 8px 22px rgba($shadow_rgb, 0.35);
}
/* hover: the tile lifts toward you (eased, glass.MOTION transitions) and its shadow grows */
button.st-tile:hover { transform: translateY(-3px); }
button.st-tile:hover { box-shadow: inset 0 1px 0 rgba(255,255,255,0.24), inset 0 0 0 1px rgba($gold_rgb, 0.50), 0 0 18px rgba($gold_rgb, 0.18),
              0 14px 30px rgba($shadow_rgb, 0.45); }
button.st-tile:active { transform: translateY(-1px) scale(0.985); }
.st-tile-name { font-size: $fs_lead; font-weight: 800; color: #FFFFFF; }
.st-tile-blurb { font-size: $fs_small; color: rgba($text_rgb, 0.74); }

/* icons: real ones float; missing ones become a glass coin with a golden letter */
.st-icon-tile { border-radius: $r_md; background-color: rgba($text_rgb, 0.06);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.14), inset 0 0 0 1px rgba($text_rgb, 0.07); }
.st-letter { border-radius: $r_md; color: $gold_soft; font-weight: 800;
  background-color: rgba($accent_dim_rgb, 0.70);
  background-image: radial-gradient(circle at 30% 25%, rgba($gold_rgb, 0.28), transparent 62%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22), inset 0 0 0 1px rgba($gold_rgb, 0.55); }

/* ---------- badges */
.st-badge { font-size: $fs_micro; font-weight: 800; letter-spacing: 0.8px; border-radius: 99px; padding: 2px 9px; }
.st-badge.repo { color: $base; background-color: $accent_bright; }
.st-badge.aur { color: $gold_soft; background-color: rgba($gold_rgb, 0.14); box-shadow: inset 0 0 0 1px rgba($gold_rgb, 0.55); }
.st-badge.flatpak { color: $text; background-color: rgba($text_rgb, 0.12); box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.40); }
.st-badge.eclipse { color: #1A1205; background-color: $gold; }
.st-badge.installed { color: #08251A; background-color: $success; }
.st-badge.old { color: #FFD9D9; background-color: rgba($red_rgb, 0.35); }
.st-size { font-size: $fs_small; font-weight: 700; color: $gold_soft; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }

/* ---------- search results */
.st-status { font-size: $fs_body; color: $text_dim; }
.st-note { font-size: $fs_small; color: $text_dim; }
window.arclight-store list.st-results { border-radius: $r_lg; }
window.arclight-store list.st-results > row { padding: 10px 14px; }
window.arclight-store list.st-results > row:hover { background-color: rgba($gold_rgb, 0.06); }
.st-row-name { font-size: $fs_lead; font-weight: 800; color: #FFFFFF; }
.st-row-blurb { font-size: $fs_small; color: rgba($text_rgb, 0.74); }
.st-chev { color: rgba($text_rgb, 0.40); }
button.st-askrow {
  padding: 16px 20px; border-radius: $r_lg; border: none; color: $text;
  background-color: rgba($accent_dim_rgb, 0.48);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.18), transparent 60%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), inset 0 0 0 1px rgba($gold_rgb, 0.40);
}
button.st-askrow:hover { box-shadow: inset 0 1px 0 rgba(255,255,255,0.26), CORONA; }
.st-askrow-title { font-size: $fs_lead; font-weight: 800; color: $gold_soft; }
.st-askrow-sub { font-size: $fs_small; color: rgba($text_rgb, 0.78); }

/* ---------- app page */
.st-app-title { font-size: $fs_display; font-weight: 800; color: #FFFFFF; }
.st-app-blurb { font-size: $fs_title; color: rgba($text_rgb, 0.88); }
.st-pkgname { font-size: $fs_small; color: $text_dim; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
window.arclight-store button.st-primary {
  background-image: linear-gradient(to bottom, $gold_soft, $gold 55%, $gold_deep); background-color: $gold;
  color: #1A1205; font-weight: 800; font-size: $fs_lead; border: none; border-radius: $r_md; padding: 10px 34px; min-height: 30px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.65), 0 0 18px rgba($gold_rgb, 0.35), 0 6px 16px rgba($shadow_rgb, 0.45);
}
window.arclight-store button.st-primary:hover {
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.7), 0 0 26px rgba($gold_rgb, 0.60), 0 6px 16px rgba($shadow_rgb, 0.45); }
window.arclight-store button.st-primary:disabled { background-image: none; background-color: rgba($text_rgb, 0.10);
  color: rgba($text_rgb, 0.40); box-shadow: none; }
window.arclight-store button.st-ghost {
  background-color: rgba($text_rgb, 0.07); color: $text; font-size: $fs_lead; font-weight: 700; border: none;
  border-radius: $r_md; padding: 10px 22px; box-shadow: inset 0 1px rgba(255,255,255,0.12), inset 0 0 0 1px rgba($text_rgb, 0.08);
}
window.arclight-store button.st-ghost:hover { background-color: rgba($text_rgb, 0.13); }
window.arclight-store button.st-ghost.gold { color: $gold_soft; box-shadow: inset 0 1px rgba(255,255,255,0.12), inset 0 0 0 1px rgba($gold_rgb, 0.45); }
window.arclight-store button.st-danger {
  background-color: rgba($red_rgb, 0.16); color: #FF9A9A; font-size: $fs_lead; font-weight: 700; border: none;
  border-radius: $r_md; padding: 10px 22px; box-shadow: inset 0 0 0 1px rgba($red_rgb, 0.75);
}
window.arclight-store button.st-danger:hover { background-color: $red; color: #FFFFFF; box-shadow: 0 0 16px rgba($red_rgb, 0.45); }
window.arclight-store button.st-danger:disabled, window.arclight-store button.st-ghost:disabled { opacity: 0.4; }
window.arclight-store button.st-small { font-size: $fs_small; padding: 5px 14px; border-radius: $r_sm; min-height: 22px; }
/* in long lists Remove stays quiet (a row of red buttons shouts); it turns red when you point at it */
window.arclight-store button.st-danger.st-small { background-color: rgba($text_rgb, 0.06); color: #F0A0A0;
  box-shadow: inset 0 1px rgba(255,255,255,0.10), inset 0 0 0 1px rgba($text_rgb, 0.10); }
window.arclight-store button.st-danger.st-small:hover { background-color: $red; color: #FFFFFF;
  box-shadow: 0 0 14px rgba($red_rgb, 0.40); }

.st-card {
  border-radius: $r_lg; padding: 18px 22px;
  background-color: rgba($raised_rgb, 0.40);
  background-image: linear-gradient(to bottom, rgba($text_rgb, 0.05), rgba($text_rgb, 0) 60px);
  box-shadow: RIM, 0 8px 24px rgba($shadow_rgb, 0.40);
}
.st-card.gold { background-color: rgba($gold_rgb, 0.08); box-shadow: inset 0 1px rgba(255,255,255,0.12), inset 0 0 0 1px rgba($gold_rgb, 0.45); }
.st-card.red { background-color: rgba($red_rgb, 0.14); box-shadow: inset 0 0 0 1px rgba($red_rgb, 0.70); }
.st-fact-key { font-size: $fs_small; font-weight: 700; color: $text_dim; }
.st-fact-val { font-size: $fs_lead; color: #FFFFFF; }
.st-fact-note { font-size: $fs_small; color: $text_dim; }
.st-about { font-size: $fs_lead; color: rgba($text_rgb, 0.86); }
.st-link { color: $gold_soft; }

/* ---------- progress */
.st-prog-now { font-size: $fs_title; font-weight: 800; color: #FFFFFF; }
.st-prog-pct { font-size: $fs_title; font-weight: 800; color: $gold; }
.st-prog-line { font-size: $fs_small; color: $text_dim; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
window.arclight-store progressbar.st-bar trough { min-height: 12px; border-radius: 99px; background-color: rgba($text_rgb, 0.10); }
window.arclight-store progressbar.st-bar progress { min-height: 12px; border-radius: 99px; }
window.arclight-store progressbar.st-bar-failed progress {
  background-image: none; background-color: rgba($red_rgb, 0.85); box-shadow: none;
}
.st-done { font-size: $fs_lead; font-weight: 700; color: $success; }
.st-snap { font-size: $fs_body; color: $gold_soft; }
.st-err { font-size: $fs_lead; font-weight: 700; color: #FF8080; }
.st-log, .st-log text { background-color: rgba($sunken_rgb, 0.70); color: rgba($text_rgb, 0.85);
  font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: $fs_micro; }
.st-logbox { border-radius: $r_sm; box-shadow: inset 0 0 0 1px rgba($text_rgb, 0.08); }
window.arclight-store expander title { color: $text_dim; }
window.arclight-store expander title:hover { color: $gold_soft; }

/* ---------- updates + installed */
.st-big-num { font-size: $fs_display; font-weight: 800; color: #FFFFFF; }
.st-ver { font-size: $fs_small; color: $text_dim; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
.st-ver-new { font-size: $fs_small; color: $gold_soft; font-weight: 700; font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; }
.st-empty-title { font-size: $fs_heading; font-weight: 800; color: #FFFFFF; }
.st-ok-mark { color: #1A1205; font-size: $fs_display; font-weight: 900; min-width: 56px; min-height: 56px; border-radius: 99px;
  background-image: radial-gradient(circle, $gold_soft, $gold 60%, $gold_deep); box-shadow: 0 0 24px rgba($gold_rgb, 0.50); }

/* dialog */
/* the window stays visible (softly dimmed) behind the question */
window.arclight-store dialog-host > dimming { background-color: rgba(0, 0, 0, 0.35); }
dialog.alert sheet { background-color: rgba($surface_rgb, 0.97); color: $text;
  box-shadow: inset 0 1px rgba(255,255,255,0.14), 0 0 0 1px rgba($text_rgb, 0.08), 0 18px 48px rgba($shadow_rgb, 0.6); }
dialog.alert .heading, dialog.alert label.title-2 { font-size: $fs_title; color: #FFFFFF; }
dialog.alert .body { font-size: $fs_lead; }
dialog.alert button.destructive { color: #FF8A8A; font-weight: 800; }
dialog.alert button.destructive:hover { background-color: rgba($red_rgb, 0.85); color: white; }
""".replace("CORONA", CORONA).replace("RIM", RIM)


def install():
    settings_style.install()
    return glass.install(CSS)
