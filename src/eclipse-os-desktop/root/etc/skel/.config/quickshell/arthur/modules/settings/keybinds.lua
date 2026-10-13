-- keybinds.lua: list every keybind in ~/.config/hypr/hyprland.lua as JSON lines.
--
-- Live binds are Lua closures (`hyprctl binds` only shows "__lua <ref>"), so the only
-- honest source of "what does this key do" is the config itself. This runs hyprland.lua
-- in a sandbox where `hl` is a recording stub: hl.bind() records the key and a readable
-- description of its dispatcher, everything else (rules, config, exec, events) is a no-op.
-- Loops (workspaces 1-10) and variables (mainMod, terminal, shellctl) resolve naturally.
--
-- Usage: lua keybinds.lua [path/to/hyprland.lua]
-- Output: one JSON object per line: {"key","action","group","line","note","flags"}

local path = arg[1] or (os.getenv("HOME") .. "/.config/hypr/hyprland.lua")
local f = assert(io.open(path, "r"))
local src = f:read("a")
f:close()

local lines = {}
for l in (src .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end

-- ---- a value that swallows any use: field access, calls, concatenation, methods ----
local Stub = {}
local stub
local mt = {
    __index = function() return stub end,
    __call = function() return stub end,
    __concat = function(a, b) return (type(a) == "table" and "" or tostring(a)) .. (type(b) == "table" and "" or tostring(b)) end,
    __tostring = function() return "" end,
}
stub = setmetatable(Stub, mt)

-- ---- dispatcher descriptions: hl.dsp.<path>(args) -> {path=, args=} ----
local function dsp(pathParts)
    return setmetatable({}, {
        __index = function(_, k)
            local p = {}
            for i, v in ipairs(pathParts) do p[i] = v end
            p[#p + 1] = k
            return dsp(p)
        end,
        __call = function(_, a) return { __dsp = table.concat(pathParts, "."), args = a } end,
    })
end

local function home(s) return (tostring(s):gsub("^~/%.local/bin/", ""):gsub("^/home/[^/]+/", "~/")) end

local function describe(d)
    if type(d) ~= "table" or not d.__dsp then return "Lua function", "Other" end
    local p, a = d.__dsp, d.args
    if p == "exec_cmd" then
        local cmd = tostring(a or "")
        local shell = cmd:match("shellctl%s+(%S+)")
        if shell then return "Open " .. shell, "Shell" end
        if cmd:match("^wpctl") or cmd:match("^playerctl") or cmd:match("^brightnessctl") then return home(cmd), "Media" end
        if cmd:match("shot ") then return "Screenshot: " .. cmd:match("shot (%S+)"), "Screenshots" end
        if cmd:match("hyprlock") then return "Lock screen", "Session" end
        if cmd:match("hyprshutdown") then return "Exit Hyprland", "Session" end
        return "Run " .. home(cmd), "Apps"
    end
    a = type(a) == "table" and a or {}
    if p == "focus" then
        if a.direction then return "Focus " .. a.direction, "Windows" end
        if a.workspace then
            local w = tostring(a.workspace)
            if w == "e+1" then return "Next workspace", "Workspaces" end
            if w == "e-1" then return "Previous workspace", "Workspaces" end
            return "Go to workspace " .. w, "Workspaces"
        end
    elseif p == "window.move" and a.workspace then
        local w = tostring(a.workspace)
        if w:match("^special") then return "Hide window (scratchpad)", "Workspaces" end
        return "Move window to workspace " .. w, "Workspaces"
    elseif p == "window.close" then return "Close window", "Windows"
    elseif p == "window.float" then return "Toggle floating", "Windows"
    elseif p == "window.fullscreen" then return "Toggle fullscreen", "Windows"
    elseif p == "window.pseudo" then return "Pseudo-tile", "Windows"
    elseif p == "window.drag" then return "Drag window", "Windows"
    elseif p == "window.resize" then return "Resize window", "Windows"
    elseif p == "layout" then return "Layout: " .. tostring(d.args), "Windows"
    elseif p == "workspace.toggle_special" then return "Show scratchpad", "Workspaces"
    end
    return p, "Other"
end

local out = {}
local function jstr(s)
    return '"' .. tostring(s):gsub('[%c"\\]', function(c)
        if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" end
        return string.format("\\u%04x", c:byte())
    end) .. '"'
end

local function prettyKey(k)
    local parts = {}
    for raw in tostring(k):gmatch("[^+]+") do
        local p = raw:match("^%s*(.-)%s*$")
        local names = { ["mouse:272"] = "Left click", ["mouse:273"] = "Right click",
                        mouse_down = "Scroll down", mouse_up = "Scroll up", Return = "Enter",
                        space = "Space", left = "Left", right = "Right", up = "Up", down = "Down",
                        CTRL = "Ctrl", ALT = "Alt", SHIFT = "Shift", SUPER = "Super" }
        parts[#parts + 1] = names[p] or p
    end
    return table.concat(parts, " + ")
end

local hl = setmetatable({
    dsp = dsp({}),
    bind = function(key, action, opts)
        local info = debug.getinfo(2, "l")
        local ln = info and info.currentline or 0
        local note = (lines[ln] or ""):match("%)%s*%-%-%s*(.-)%s*$") or ""
        local text, group = describe(action)
        local flags = {}
        if type(opts) == "table" then
            for _, k in ipairs({ "locked", "repeating", "mouse" }) do if opts[k] then flags[#flags + 1] = k end end
        end
        out[#out + 1] = string.format('{"key":%s,"action":%s,"group":%s,"line":%d,"note":%s,"flags":%s}',
            jstr(prettyKey(key)), jstr(text), jstr(group), ln, jstr(note), jstr(table.concat(flags, ",")))
        return stub
    end,
}, { __index = function() return stub end })

local env = setmetatable({
    hl = hl,
    require = function(name) error("module '" .. tostring(name) .. "' not found (sandbox)") end,
}, { __index = function(_, k)
    local allowed = { pairs = pairs, ipairs = ipairs, tostring = tostring, tonumber = tonumber, type = type,
                      pcall = pcall, error = error, select = select, next = next, string = string,
                      math = math, table = table, setmetatable = setmetatable, getmetatable = getmetatable }
    return allowed[k]
end })

local chunk, err = load(src, "=hyprland.lua", "t", env)
if not chunk then io.stderr:write("parse error: " .. tostring(err) .. "\n"); os.exit(2) end
local ok, rerr = pcall(chunk)
if not ok then io.stderr:write("run error: " .. tostring(rerr) .. "\n"); os.exit(3) end
print(table.concat(out, "\n"))
