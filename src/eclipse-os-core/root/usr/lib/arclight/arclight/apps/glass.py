"""Eclipse liquid glass for our GTK4 apps (Settings, Ask, Welcome).

One material everywhere, themed around Arthur's photo: translucent warm-graphite glass the compositor's
blur shows through, a 1px bright specular top edge, a soft inner rim, a warm golden glint in the
top-left corner (light from the eclipse), frosted grain, and the sun's gold for focus, selection and
progress. Red only for stop/close/errors (the car's accent lines).

Colours follow the active theme's tokens (~/.config/theme/tokens/<current>.json), so a theme switch
recolours our apps too; the Eclipse values are the fallback. CSS is written with $names
(string.Template), e.g. `rgba($gold_rgb, 0.5)` or `$text`.
"""
import json
import os
from pathlib import Path
from string import Template

HOME = Path.home()
REPO = Path(__file__).resolve().parents[3]

ECLIPSE = {
    "base": "#0B0B0D", "sunken": "#070708", "surface": "#17181B", "raised": "#222327", "hover": "#2B2C31",
    "border": "#34353A", "border_strong": "#4A4A50", "accent": "#D08A4E", "accent_bright": "#EDB98A",
    "accent_dim": "#6E4F36", "gold": "#FFC94A", "gold_soft": "#FFE6B8", "gold_deep": "#E89B2A",
    "core": "#FFF6E4", "red": "#D42B2B", "text": "#ECEAE6", "text_dim": "#9A958E", "muted": "#6A665F",
    "success": "#3FD69A", "warning": "#E0B040", "shadow": "#000000",
}
_MAP = {"bg-base": "base", "bg-sunken": "sunken", "surface": "surface", "surface-raised": "raised",
        "surface-hover": "hover", "border-subtle": "border", "border-strong": "border_strong", "accent": "accent",
        "accent-bright": "accent_bright", "accent-dim": "accent_dim", "error": "red", "text-primary": "text",
        "text-secondary": "text_dim", "text-muted": "muted", "success": "success", "warning": "warning",
        "shadow": "shadow"}
_SUN = {"gold": "gold", "gold-soft": "gold_soft", "gold-deep": "gold_deep", "core": "core"}


def _tokens():
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "theme"
    try:
        slug = (cfg / "current").read_text().strip()
    except OSError:
        slug = "eclipse"
    if slug == "dynamic":
        slug = "midnight-blue"
    for d in (cfg / "tokens", Path("/usr/share/arclight/theme"), REPO / "desktop/overlay/.config/theme/tokens",
              REPO / "desktop/skel/.config/theme/tokens"):
        f = d / f"{slug}.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except (OSError, ValueError):
                break
    return None


def palette():
    p = dict(ECLIPSE)
    tok = _tokens()
    if tok and tok.get("meta", {}).get("variant", "dark") == "dark":
        c = tok.get("color", {})
        for k, v in _MAP.items():
            if c.get(k):
                p[v] = c[k]
        sun = tok.get("sun") or {"gold": c.get("accent"), "gold-soft": c.get("accent-bright"),
                                 "gold-deep": c.get("accent-dim"), "core": tok.get("glow", {}).get("peak")}
        for k, v in _SUN.items():
            if sun.get(k):
                p[v] = sun[k]
    for k in list(p):
        h = p[k].lstrip("#")
        p[k + "_rgb"] = ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    p["noise"] = asset_uri("glass-noise.png")
    p["hero"] = asset_uri("hero.jpg")
    p.update(SCALE)
    return p


def asset(name):
    """A liquid-glass asset: installed (/usr/share/arclight/eclipse), else the source tree."""
    for d in (Path("/usr/share/arclight/eclipse"), REPO / "desktop/eclipse", REPO / "art/eclipse/glass"):
        if (d / name).exists():
            return d / name
    return None


def asset_uri(name):
    a = asset(name)
    return a.as_uri() if a else ""


def render(css):
    p = palette()
    text = Template(css).safe_substitute(p)
    if not p["noise"]:
        text = text.replace('url(""), ', "").replace(', url("")', "")
    return text


# Shared pieces. The glass "material" is three layers in one background-image stack (top first):
# frosted grain, a warm golden glint in the top-left corner, a faint top-down sheen.
MATERIAL = ('url("$noise"), radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.13), transparent 46%), '
            'linear-gradient(to bottom, rgba($text_rgb, 0.06), rgba($text_rgb, 0.0) 38%)')
# 1px specular top edge + soft inner rim + depth shadow
RIM = ('inset 0 1px 0 rgba(255, 255, 255, 0.20), inset 0 0 0 1px rgba($text_rgb, 0.07), '
       'inset 0 -1px 0 rgba($shadow_rgb, 0.35)')
RIM_LIFT = RIM + ', 0 8px 24px rgba($shadow_rgb, 0.45)'
# focus / selection: dark disc with a golden rim, like the eclipse itself
CORONA = 'inset 0 0 0 1px rgba($gold_rgb, 0.62), 0 0 12px rgba($gold_rgb, 0.22), 0 0 26px rgba($gold_deep_rgb, 0.16)'

# GTK 4.24 binds ext-background-effect-v1 and, unless CSS asks for it, requests NO blur: Hyprland then
# draws GTK4 windows unfrosted (measured in the VM: kitty blurred, every GTK4 window sharp). A
# backdrop-filter on the window makes GTK publish its blur region, and the compositor frosts behind it.
BACKDROP = "backdrop-filter: blur(24px);"

# One shared scale for every app (Settings, Store, Welcome, Ask, installer): corner radii and type sizes
# come from here as $r_* / $fs_*, so the apps can never drift apart again.
SCALE = {
    "r_xs": "10px", "r_sm": "12px", "r_md": "16px", "r_lg": "20px", "r_xl": "24px", "r_pill": "99px",
    "fs_micro": "12px", "fs_small": "14px", "fs_body": "15px", "fs_lead": "17px", "fs_title": "20px",
    "fs_heading": "24px", "fs_display": "32px", "fs_hero": "40px",
}

# Motion (apps/motion.py has the Python half). All on the real clock: CSS animations and transitions are
# timed by GTK's frame clock in milliseconds; a slow machine skips frames, it never runs slower.
EASE_OUT = (0.22, 1.0, 0.36, 1.0)       # easeOutQuint-like: lands softly
EASE_BLOOM = (0.20, 1.22, 0.32, 1.0)    # a tiny overshoot, then settles (Hyprland's "bloom" curve)
RISE_MS, STEP_MS, MAX_STAGGER = 460, 45, 9


def _bez(p):
    return ", ".join(str(v) for v in p)


MOTION = ("""
/* ---- motion: everything eases on the real clock (never linear, never a pop) ---- */
@keyframes arc-rise {
  from { opacity: 0; transform: translateY(14px) scale(0.985); }
  to   { opacity: 1; transform: none; }
}
/* the same rise under a second name: switching names restarts it in the same frame (a replay never
   flashes the finished state first, which a slow machine would show for a whole frame) */
@keyframes arc-rise-again {
  from { opacity: 0; transform: translateY(14px) scale(0.985); }
  to   { opacity: 1; transform: none; }
}
@keyframes arc-bloom {
  from { opacity: 0; transform: scale(0.94); }
  to   { opacity: 1; transform: none; }
}
@keyframes arc-fade { from { opacity: 0; } to { opacity: 1; } }
.arc-rise  { animation: arc-rise RISE_MSms cubic-bezier(EASE_OUT) both; }
.arc-rise.arc-again { animation-name: arc-rise-again; }
.arc-bloom { animation: arc-bloom 380ms cubic-bezier(EASE_BLOOM) both; }
.arc-fade-in { animation: arc-fade 320ms cubic-bezier(EASE_OUT) both; }
STAGGER
/* micro-interactions: hover / press / focus ease instead of snapping */
button, list > row, flowboxchild, switch, switch > slider, entry, checkbutton check, scale slider, .boxed-list, .card {
  transition: background-color 200ms cubic-bezier(EASE_OUT), box-shadow 260ms cubic-bezier(EASE_OUT),
              color 200ms cubic-bezier(EASE_OUT), opacity 200ms cubic-bezier(EASE_OUT),
              transform 260ms cubic-bezier(EASE_BLOOM);
}
button:active:not(:disabled) { transform: scale(0.97); transition-duration: 90ms; }
/* the gliding selection (motion.SidebarGlide): the pill moves, rows no longer paint their own */
.arc-glide-pill {
  border-radius: 12px;
  background-color: rgba($accent_dim_rgb, 0.62);
  background-image: radial-gradient(ellipse at 0% 0%, rgba($gold_rgb, 0.16), transparent 60%);
  box-shadow: CORONA;
}
list.arc-glide > row:selected, list.arc-glide > row:selected:hover { background-color: transparent; background-image: none; box-shadow: none; }
@media (prefers-reduced-motion: reduce) {
  .arc-rise, .arc-rise.arc-again, .arc-bloom, .arc-fade-in { animation: none; }
  button:active:not(:disabled) { transform: none; }
}
""".replace("STAGGER", "\n".join(f".arc-rise.arc-d{i} {{ animation-delay: {i * STEP_MS}ms; }}" for i in range(1, MAX_STAGGER + 1)))
   .replace("RISE_MS", str(RISE_MS)).replace("EASE_BLOOM", _bez(EASE_BLOOM)).replace("EASE_OUT", _bez(EASE_OUT)))

COMMON = """
popover > contents, popover.menu > contents { backdrop-filter: blur(24px); }
/* ---- golden arcs for anything that loads ---- */
spinner, .arc-spinner { color: $gold; }
progressbar progress, levelbar block.filled {
  background-image: linear-gradient(to right, $gold_deep, $gold, $gold_soft);
  border: none; box-shadow: 0 0 8px rgba($gold_rgb, 0.45);
}
progressbar trough, levelbar trough { background-color: rgba($text_rgb, 0.10); border: none; }
/* ---- focus is sunlight ---- */
*:focus-visible { outline: 2px solid rgba($gold_rgb, 0.75); outline-offset: 1px; }
selection, text selection, label selection { background-color: rgba($gold_rgb, 0.32); color: $core; }
tooltip, tooltip.background {
  background-color: rgba($surface_rgb, 0.92); color: $text; border-radius: 10px;
  border: 1px solid rgba($text_rgb, 0.10); box-shadow: inset 0 1px rgba(255,255,255,0.12);
}
scrollbar slider { background-color: rgba($text_rgb, 0.22); border-radius: 99px; min-width: 6px; }
scrollbar slider:hover { background-color: rgba($gold_rgb, 0.55); }
""" + MOTION.replace("CORONA", CORONA)


def install(css):
    """Load `css` (with $tokens) above the user's gtk.css (theme-apply writes one at USER priority)."""
    from gi.repository import Gdk, Gtk
    prov = Gtk.CssProvider()
    data = render(COMMON + css)
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(data)
    else:
        prov.load_from_data(data.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    return prov
