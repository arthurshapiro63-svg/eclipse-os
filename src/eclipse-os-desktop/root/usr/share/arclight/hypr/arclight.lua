-- Eclipse OS (codename Arclight): the AI-native layer for Hyprland.
-- Loaded from the marked block at the end of ~/.config/hypr/hyprland.lua:
--     -- arclight:begin ... require("arclight") ... -- arclight:end
-- This file ships with the eclipse-os-desktop package (/usr/share/arclight/hypr/arclight.lua).
-- To customise it, copy it to ~/.config/hypr/arclight.lua: that copy wins.
-- Nothing here replaces one of the user's binds; it only adds new ones.

local M = {}

-- ------------------------------------------------------------------ environment
-- Accessibility on everywhere, so the AI can find buttons by name instead of guessing pixels.
hl.env("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "1")
hl.env("ACCESSIBILITY_ENABLED", "1")
hl.env("ARCLIGHT", "1")

-- ------------------------------------------------------------------ autostart
hl.on("hyprland.start", function ()
    -- the session daemon needs the compositor's environment in the systemd user manager
    hl.exec_cmd("dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE DISPLAY XAUTHORITY")
    hl.exec_cmd("systemctl --user restart arclight-session.service")
    -- one-time per-user setup (MCP registration, wallpapers, theme); a no-op once done
    hl.exec_cmd("arclight-firstrun --session")
    -- service failures -> notification with "Fix with AI"
    hl.exec_cmd("systemctl --user start arclight-watch.service")
    -- the eclipse wallpaper follows the time of day (idle on battery, in game mode / Totality)
    hl.exec_cmd("systemctl --user start arclight-livingwall.service")
end)

-- ------------------------------------------------------------------ look: liquid glass
-- Eclipse OS: the photo is the hero, glass frames it. Every pane is translucent (you see the
-- wallpaper through a strong, colour-keeping blur), has a bright specular edge on top, a soft
-- depth shadow, generous squircle corners, and the focused one catches the sun: a golden edge
-- that fades into dusk amber, with a faint golden corona behind it.
-- Colours come from the active theme (theme-apply renders arclight-colors.lua from the tokens).
local okCol, col = pcall(require, "arclight-colors")
if not okCol or type(col) ~= "table" then col = {} end
local function grad(stops, angle) return { colors = stops, angle = angle } end
hl.config({
    general = {
        border_size = 2,
        gaps_in     = 6,
        gaps_out    = 14,
        col = {
            -- 45deg puts the first (brightest) stop in the top-left corner
            -- 45deg puts the first (brightest) stop in the top-left corner; the sun timer below turns it
            active_border   = grad(col.active_border or { "rgba(fff6e4ff)", "rgba(ffc94af2)", "rgba(e89b2ab0)", "rgba(d08a4e70)", "rgba(6e4f3660)" }, 45),
            inactive_border = grad(col.inactive_border or { "rgba(eceae62e)", "rgba(34353a66)", "rgba(0b0b0d44)" }, 90),
        },
    },
    decoration = {
        rounding       = 18,
        rounding_power = 2.6,      -- between circle (2) and squircle (4): soft, liquid corners
        active_opacity     = 0.94, -- text stays crisp; apps that paint their own glass override to 1.0
        inactive_opacity   = 0.86,
        fullscreen_opacity = 1.0,
        dim_inactive = true,
        dim_strength = 0.12,       -- unfocused panes sink back a little (fadeDim eases it)
        blur = {
            enabled   = true,
            size      = 10,        -- strong, smooth frost: the photo turns into light and colour
            passes    = 3,
            noise     = 0.028,     -- frosted grain, stops the blur looking like plastic
            contrast  = 1.02,
            brightness = 0.90,     -- each pane darkens what is behind it, so blur stacks: the further back,
                                   -- the more frosted and the darker (the bar over a window over the photo)
            vibrancy  = 0.38,      -- keeps the dusk amber and the gold alive inside the glass
            vibrancy_darkness = 0.35,
            popups    = true,
            popups_ignorealpha = 0.2,
            new_optimizations = true,
            xray      = false,     -- panes sit OVER each other, not cut-outs of the wallpaper
            special   = true,
        },
        shadow = {
            enabled        = true,
            range          = 40,     -- the focused pane floats highest: biggest, softest shadow
            render_power   = 3,
            color          = col.shadow or "rgba(000000c8)",
            color_inactive = col.shadow_inactive or "rgba(00000080)",
            offset         = { 0, 10 },
        },
        glow = {
            enabled        = true,
            range          = 16,     -- the corona: warm light behind the focused pane only
            render_power   = 3,
            -- the corona is brightest on the side facing the sun and turns with the gold edge
            color          = grad(col.glow_ramp or { "rgba(ffc94a40)", "rgba(e89b2a1c)", "rgba(00000000)" }, 45),
            color_inactive = "rgba(00000000)",
        },
    },
    misc = {
        background_color = col.background or 0x0b0b0d,
    },
    plugin = {
        hyprbars = {
            bar_color    = col.bar or "rgba(17181ba6)",   -- title bars are glass too
            ["col.text"] = col.bar_text or "rgba(9a958eff)",
            bar_blur     = true,
        },
    },
})

-- ------------------------------------------------------------------ motion, depth, moving light
-- Every animation here is timed on the real clock (speed = tenths of a second), so a slow and a fast
-- machine take the same time; a slow one only draws fewer in-between frames. Totality / game mode
-- turns animations off altogether.
--   bloom   ease-out with a small overshoot: a window opens to ~101% and settles at 100%
--   sink    the reverse: slow start, quick finish, so a closing window folds back into itself
--   glass   easeOutQuint: layers, fades and dimming glide in and land softly
--   drift   easeInOut: workspaces and moves, gentle at both ends
hl.curve("bloom",    { type = "bezier", points = { {0.20, 1.22}, {0.32, 1.00} } })
hl.curve("sink",     { type = "bezier", points = { {0.45, 0.00}, {0.78, 0.40} } })
hl.curve("glass",    { type = "bezier", points = { {0.22, 1.00}, {0.36, 1.00} } })
hl.curve("drift",    { type = "bezier", points = { {0.45, 0.05}, {0.15, 1.00} } })
for _, a in ipairs({
    -- windows bloom open from 86% and settle; closing reverses it (shrinks back to 86% and fades)
    { leaf = "windowsIn",   speed = 4.2, bezier = "bloom", style = "popin 86%" },
    { leaf = "windowsOut",  speed = 2.4, bezier = "sink",  style = "popin 86%" },
    { leaf = "windowsMove", speed = 3.6, bezier = "drift" },
    { leaf = "fadeIn",      speed = 2.6, bezier = "glass" },
    { leaf = "fadeOut",     speed = 2.2, bezier = "sink" },
    { leaf = "fadeSwitch",  speed = 3.0, bezier = "glass" },
    { leaf = "fadeDim",     speed = 4.5, bezier = "glass" },   -- windows sink back slowly when they lose focus
    { leaf = "fadeShadow",  speed = 4.5, bezier = "glass" },
    { leaf = "fadeGlow",    speed = 4.5, bezier = "glass" },
    { leaf = "border",      speed = 4.5, bezier = "glass" },
    -- shell surfaces (bar popups, notifications, launcher, Ask) slide a little from their edge + fade
    { leaf = "layersIn",      speed = 3.4, bezier = "glass", style = "slide" },
    { leaf = "layersOut",     speed = 2.4, bezier = "sink",  style = "slide" },
    { leaf = "fadeLayersIn",  speed = 2.8, bezier = "glass" },
    { leaf = "fadeLayersOut", speed = 2.2, bezier = "sink" },
    { leaf = "fadePopupsIn",  speed = 2.0, bezier = "glass" },
    { leaf = "fadePopupsOut", speed = 1.6, bezier = "sink" },
    -- workspaces: the windows slide 18% and fade while the photo stays put (the photo is the far
    -- layer, the glass the near one: that is the parallax)
    { leaf = "workspaces",       speed = 4.2, bezier = "drift", style = "slidefade 18%" },
    { leaf = "specialWorkspace", speed = 3.8, bezier = "glass", style = "slidefadevert 14%" },
    -- the turning light is the sun timer below, not Hyprland's borderangle loop (capped at one turn
    -- per 10 s, too fast for "the sun moving"); a focus change still sweeps the edge once
    { leaf = "borderangle", speed = 8, bezier = "glass", style = "once" },
}) do
    hl.animation({ leaf = a.leaf, enabled = true, speed = a.speed, bezier = a.bezier, style = a.style })
end
-- The light that moves: the sun sits off-screen and slowly circles, so the gold on the focused window's
-- edge (and the corona glow behind it) turns once every 20 s. The angle comes from the wall clock
-- (os.time, plus tenths counted since the last whole second), never from a frame or tick count, so a
-- slow machine shows the same position at the same moment. 10 small steps a second; the "border" fade
-- above blends each step into the next. Skipped while animations are off (Totality / game mode / Settings).
local SUN_PERIOD, SUN_STEP_MS = 20.0, 100
local sunSec, sunSub = os.time(), 0.0
local function sunAngle()
    local s = os.time()
    if s ~= sunSec then sunSec, sunSub = s, 0.0 else sunSub = math.min(sunSub + SUN_STEP_MS / 1000, 0.95) end
    local now = sunSec + sunSub
    return (45 + 360 * ((now % SUN_PERIOD) / SUN_PERIOD)) % 360
end
-- Where the light stays still (the gold edge simply rests in the top-left corner, as before):
--   * software rendering (no GPU: llvmpipe): every step redraws the blurred desktop on the CPU
--     (measured in a 1-CPU VM: Hyprland 84% busy with it, 0% without; on a GPU 4-6%)
--   * on battery (checked every 5 s), like the living wallpaper
--   * when you picked your own border colour in Settings (it is left exactly as you set it)
--   * ~/.local/state/arclight/moving-light containing "off" (or "on" to force it)
local function readFile(path, max)
    local f = io.open(path, "r")
    if not f then return nil end
    local t = f:read(max or "a")
    f:close()
    return t
end
local function sunWanted()
    local home = os.getenv("HOME") or ""
    local flag = (readFile(home .. "/.local/state/arclight/moving-light", 16) or ""):match("%a+")
    if flag == "off" then return false end
    if flag == "on" then return true end
    -- a border colour you picked yourself (Settings / arc set appearance.active_border) stays as you set it
    local cfg = os.getenv("XDG_CONFIG_HOME") or (home .. "/.config")
    if (readFile(cfg .. "/hypr/arclight-settings.lua") or ""):find("active_border", 1, true) then return false end
    local sig, run = os.getenv("HYPRLAND_INSTANCE_SIGNATURE"), os.getenv("XDG_RUNTIME_DIR")
    local log = (sig and run) and readFile(run .. "/hypr/" .. sig .. "/hyprland.log", 200000) or ""
    if log:find("Renderer: llvmpipe", 1, true) or log:find("Renderer: softpipe", 1, true) then return false end
    return true
end
local function onBattery()
    local p = io.popen("cat /sys/class/power_supply/*/type /sys/class/power_supply/*/online 2>/dev/null")
    if not p then return false end
    local out = p:read("a") or ""
    p:close()
    if not out:find("Mains", 1, true) then return false end   -- a desktop: no AC adapter listed
    return not out:find("1", 1, true)
end
if _G.__arclightSun then pcall(function () _G.__arclightSun:set_enabled(false) end) end
local sunBorder = col.active_border or { "rgba(fff6e4ff)", "rgba(ffc94af2)", "rgba(e89b2ab0)", "rgba(d08a4e70)", "rgba(6e4f3660)" }
local sunGlow = col.glow_ramp or { "rgba(ffc94a40)", "rgba(e89b2a1c)", "rgba(00000000)" }
local sunBattery, sunChecks = false, 0
local okT, sunTimer = false, nil
if sunWanted() then okT, sunTimer = pcall(hl.timer, function ()
    local okA, anim = pcall(hl.get_config, "animations:enabled")
    if okA and anim == false then return end
    sunChecks = sunChecks - 1
    if sunChecks <= 0 then sunBattery, sunChecks = onBattery(), 50 end
    if sunBattery then return end
    local a = sunAngle()
    hl.config({
        general    = { col = { active_border = grad(sunBorder, a) } },
        decoration = { glow = { color = grad(sunGlow, a) } },
    })
end, { timeout = SUN_STEP_MS, type = "repeat" }) end
if okT then _G.__arclightSun = sunTimer end

-- Ask blooms out of the middle of the screen instead of sliding (it is a panel, not an edge)
hl.layer_rule({ name = "arclight-ask-bloom", match = { namespace = "^arclight-ask$" }, animation = "popin 90%" })
-- the wallpaper never animates (it is the far, still layer)
hl.layer_rule({ name = "arclight-wall-still", match = { namespace = "^(awww-daemon|hyprpaper|swww-daemon)$" }, no_anim = true })

-- Blur behind every shell surface (bar, notifications, launcher, control centre, OSD, dock),
-- wofi, the Ask overlay and the lock screen. ignore_alpha: fully transparent margins and
-- click-catchers are never frosted.
for i, l in ipairs({
    { ns = "^dms:.*$",          ignore = 0.12 },
    { ns = "^wofi$",            ignore = 0.15 },
    { ns = "^arclight-ask$",    ignore = 0.30 },  -- the corona halo around the panel stays unfrosted
    { ns = "^(notifications|mako)$", ignore = 0.15 },
    { ns = "^arthur-.*$",       ignore = 0.15 },
}) do
    hl.layer_rule({ name = "arclight-glass-" .. i, match = { namespace = l.ns }, blur = true, ignore_alpha = l.ignore })
end

-- Our own apps paint their own glass (translucent CSS + bright edges), so the compositor must not
-- fade their text as well.
hl.window_rule({
    name    = "arclight-own-glass",
    match   = { class = "^dev\\.arclight\\..*$" },
    opacity = "1.0 override 1.0 override",
})
-- The administrator password prompt (polkit-gnome, see hyprpolkitagent.service.d/eclipse.conf): centered, on
-- top, on every workspace, so a request is never hidden behind other windows.
hl.window_rule({
    name   = "arclight-polkit-prompt",
    match  = { class = "^(polkit-gnome-authentication-agent-1|hyprpolkitagent|org.hyprland.hyprpolkitagent)$" },
    float  = true,
    center = true,
    pin    = true,
})
-- Settings and Welcome draw their own glass header (with a close button): no second title bar.
hl.window_rule({
    name  = "arclight-own-header",
    match = { class = "^dev\\.arclight\\.(Settings|Welcome|Store)$" },
    ["hyprbars:no_bar"] = true,
})

-- ------------------------------------------------------------------ binds (new keys only)
local mainMod = "SUPER"
-- The core edition ("Eclipse OS", /etc/arclight/edition = core) has no built-in AI: no Ask keys, and
-- Super+A opens Claude Code in a terminal (eclipse-ai-toggle). The AI edition has everything.
local coreEdition = ((readFile("/etc/arclight/edition", 16) or ""):match("%a+") == "core")
if not coreEdition then
    -- Ask Eclipse: type (or dictate) a request; an agent with full machine access does it.
    hl.bind(mainMod .. " + SHIFT + A", hl.dsp.exec_cmd("arclight-ask"))
    hl.bind("CTRL + ALT + SHIFT + A",  hl.dsp.exec_cmd("arclight-ask"))
    -- ... or just say it: opens Ask already listening (your Hush engine, local). Click Stop when done.
    hl.bind(mainMod .. " + SHIFT + V", hl.dsp.exec_cmd("arclight-ask --voice"))
    -- select any text anywhere, then: ask about it ("explain this")
    hl.bind(mainMod .. " + SHIFT + E", hl.dsp.exec_cmd("arclight-ask --selection"))
end
-- Totality (was game mode): everything but the focus window melts into the sun, the moon covers it,
-- the rest of the desktop rests (effects off, other apps paused, performance); press again to restore
hl.bind(mainMod .. " + G",         hl.dsp.exec_cmd("arc totality toggle"))
-- the Totality overlay times its own animation on the real clock: no compositor fade on top of it
hl.layer_rule({ name = "arclight-totality", match = { namespace = "^arclight-totality$" }, no_anim = true })
-- Eclipse Settings (everything the AI can change, as a GUI)
hl.bind(mainMod .. " + I",         hl.dsp.exec_cmd("arclight-settings"))
hl.bind("CTRL + ALT + I",          hl.dsp.exec_cmd("arclight-settings"))
-- Eclipse AI (the Eclipse edition of Arch AI): Super+A / Ctrl+Alt+A open it, or focus it.
-- Your own hyprland.lua wins: when it already binds one of these keys (a fresh install's points at
-- eclipse-ai-toggle already; a migrated home's may open Arch AI), that key is left alone here, because
-- two binds on one key would both fire.
local function userBinds(combo)
    local ok, found = pcall(function ()
        local f = io.open((os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")) .. "/hypr/hyprland.lua", "r")
        if not f then return false end
        local text = f:read("a"):gsub("%-%-[^\n]*", ""):lower():gsub("%s+", "")   -- comments do not count
        f:close()
        local c = combo:lower():gsub("%s+", "")
        return text:find('hl.bind("' .. c .. '"', 1, true) ~= nil
            or text:find('hl.bind(mainmod.."' .. c:gsub("^super", "") .. '"', 1, true) ~= nil
    end)
    return (not ok) or found   -- cannot read it: do not risk a double bind
end
for _, combo in ipairs({ "SUPER + A", "CTRL + ALT + A" }) do
    if not userBinds(combo) then hl.bind(combo, hl.dsp.exec_cmd("eclipse-ai-toggle")) end
end

-- no "Hyprland was updated" / donation windows popping up over the desktop (Eclipse OS updates itself)
hl.config({ ecosystem = { no_update_news = true, no_donation_nag = true } })

-- ------------------------------------------------------------------ windows
hl.window_rule({
    name   = "arclight-settings",
    match  = { class = "^dev.arclight.Settings$" },
    float  = true,
    size   = "1180 760",
    center = true,
})
hl.window_rule({
    name   = "arclight-store",
    match  = { class = "^dev.arclight.Store$" },
    float  = true,
    size   = "1200 800",
    center = true,
})
hl.window_rule({
    name   = "eclipse-ai",
    match  = { class = "^dev\\.arclight\\.EclipseAI$" },
    float  = true,
    size   = "980 720",
    center = true,
})
-- Eclipse AI draws its own glass header (logo, model picker, close): no second title bar
hl.window_rule({
    name  = "eclipse-ai-own-header",
    match = { class = "^dev\\.arclight\\.EclipseAI$" },
    ["hyprbars:no_bar"] = true,
})
hl.window_rule({
    name   = "arclight-welcome",
    match  = { class = "^dev.arclight.Welcome$" },
    float  = true,
    center = true,
})
hl.window_rule({
    name   = "arclight-installer",
    match  = { class = "^dev.arclight.Installer$" },
    float  = true,
    size   = "1100 720",
    center = true,
})
-- the first-boot intro (arclight-intro): the whole screen, no bar, no border, no pop-in (it fades itself)
hl.window_rule({
    name        = "arclight-intro",
    match       = { class = "^dev\\.arclight\\.Intro$" },
    fullscreen  = true,
    border_size = 0,
    rounding    = 0,
    no_anim     = true,
    no_blur     = true,
    no_shadow   = true,
    ["hyprbars:no_bar"] = true,
})
-- the graphical installer (dev.arclight.Installer) draws its own glass header; the text one is a terminal
hl.window_rule({
    name  = "arclight-installer-own-header",
    match = { class = "^dev\\.arclight\\.Installer$" },
    ["hyprbars:no_bar"] = true,
})
hl.window_rule({
    name   = "arclight-installer-text",
    match  = { class = "^dev\\.arclight\\.InstallerText$" },
    float  = true,
    size   = "1100 720",
    center = true,
})

return M
