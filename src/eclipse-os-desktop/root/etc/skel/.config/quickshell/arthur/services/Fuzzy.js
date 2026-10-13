.pragma library

// arthur-shell launcher scoring (pure JS; QML library + Node-testable).
// Written by Codex (gpt, xhigh) from agent D's spec, reviewed by agent D.
// Test: node ~/.cache/arthur-shell/tests/D/test_fuzzy.js
// API: score(query, entry), frecency({count,last}), rank(query, entries, usageMap, limit)

// Raw tiers: exact 1000; prefix 900; word prefix 780..820;
// substring 610..650; subsequence 200..550; one-edit typo 130..150.
// Weights: name 1, keywords .84, genericName .70, exec .58, comment .28.
// Multi-word queries require every word; use their mean weighted score,
// or a stronger whole-phrase match. Prefix scores ignore field length.
//
// Usage: min(60, 12 * log2(1 + count)), with a 14-day half-life.
// Thus even maximum usage cannot lift a fuzzy name (<=550) or any
// comment (<=280) above a name prefix (900), for a single query word.
// The same bound holds for multi-word queries weak on every word.
//
// WeakMap caching works with frozen entries without modifying them.
// Scalar edits and in-place keyword edits invalidate the cache.
// Matching uses UTF-16 characters; camelCase detection is ASCII.

var _FZ_CACHE = new WeakMap();
var _FZ_EMPTY = [];
var _FZ_HALF_LIFE = 14 * 24 * 60 * 60 * 1000;
var _FZ_CAP = 60;

function _text(value) {
    return value === undefined || value === null ? "" : String(value);
}

function _query(value) {
    return _text(value).trim().toLowerCase().replace(/\s+/g, " ");
}

function _upper(c) {
    return c >= "A" && c <= "Z";
}

function _lower(c) {
    return c >= "a" && c <= "z";
}

function _field(value, weight, typos) {
    var source = _text(value).trim().replace(/\s+/g, " ");
    var text = source.toLowerCase();
    var starts = [];
    var words = [];
    var start = -1;
    var position = 0;

    for (var i = 0; i < source.length; i++) {
        var c = source.charAt(i);
        var previous = source.charAt(i - 1);
        var next = source.charAt(i + 1);
        var separator = /[\s_.\/\\-]/.test(c);
        var camel = i > 0 && _upper(c) &&
            (_lower(previous) || (previous >= "0" && previous <= "9") ||
             (_upper(previous) && _lower(next)));

        if (separator || camel) {
            if (start >= 0) {
                words.push(text.slice(start, position));
            }
            start = -1;
        }
        if (!separator && start < 0) {
            start = position;
            starts[position] = true;
        }
        // Preserve offsets when lowercasing expands a character.
        position += c.toLowerCase().length;
    }
    if (start >= 0) {
        words.push(text.slice(start));
    }
    return {text: text, starts: starts, words: words,
            weight: weight, typos: typos};
}

// Tokenize common desktop Exec quoting; never execute or expand anything.
function _execTokens(command) {
    var tokens = [];
    var token = "";
    var quote = "";
    var started = false;
    var escaped = false;
    for (var i = 0; i < command.length; i++) {
        var c = command.charAt(i);
        if (escaped) {
            token += c;
            escaped = false;
            started = true;
        } else if (c === "\\" && quote !== "'") {
            escaped = true;
            started = true;
        } else if (quote) {
            if (c === quote) {
                quote = "";
            } else {
                token += c;
            }
        } else if (c === '"' || c === "'") {
            quote = c;
            started = true;
        } else if (/\s/.test(c)) {
            if (started) {
                tokens.push(token);
                token = "";
                started = false;
            }
        } else {
            token += c;
            started = true;
        }
    }
    if (escaped) {
        token += "\\";
    }
    if (started) {
        tokens.push(token);
    }
    return tokens;
}

function _basename(path) {
    return path.slice(Math.max(path.lastIndexOf("/"),
                               path.lastIndexOf("\\")) + 1);
}

function _assignment(token) {
    return /^[A-Za-z_][A-Za-z0-9_]*=/.test(token);
}

function _execName(command) {
    var tokens = _execTokens(_text(command));
    var i = 0;
    while (i < tokens.length && _assignment(tokens[i])) {
        i++;
    }
    if (i < tokens.length && _basename(tokens[i]) === "env") {
        i++;
        while (i < tokens.length) {
            var token = tokens[i];
            if (_assignment(token)) {
                i++;
            } else if (token === "--") {
                i++;
                break;
            } else if (token === "-u" || token === "--unset" ||
                       token === "-C" || token === "--chdir" ||
                       token === "-a" || token === "--argv0") {
                i += 2;
            } else if (token === "-S" || token === "--split-string") {
                tokens = _execTokens(tokens.slice(i + 1).join(" "));
                i = 0;
            } else if (token.indexOf("--split-string=") === 0) {
                tokens = _execTokens(token.slice(15)).concat(tokens.slice(i + 1));
                i = 0;
            } else if (token.charAt(0) === "-") {
                i++;
            } else {
                break;
            }
        }
    }
    while (i < tokens.length &&
           (_assignment(tokens[i]) || /^%[A-Za-z]$/.test(tokens[i]))) {
        i++;
    }
    return i < tokens.length && tokens[i].charAt(0) !== "-" ?
        _basename(tokens[i]) : "";
}

function _cache(entry) {
    var keywords = Array.isArray(entry.keywords) ? entry.keywords : _FZ_EMPTY;
    var cached = _FZ_CACHE.get(entry);
    var valid = cached && cached.name === entry.name &&
        cached.genericName === entry.genericName &&
        cached.comment === entry.comment && cached.exec === entry.exec &&
        cached.keywords.length === keywords.length;
    var i;
    if (valid) {
        for (i = 0; i < keywords.length; i++) {
            if (cached.keywords[i] !== keywords[i]) {
                valid = false;
                break;
            }
        }
        if (valid) {
            return cached;
        }
    }

    var fields = [_field(entry.name, 1, true)];
    for (i = 0; i < keywords.length; i++) {
        fields.push(_field(keywords[i], 0.84, true));
    }
    fields.push(_field(entry.genericName, 0.70, false));
    fields.push(_field(_execName(entry.exec), 0.58, true));
    fields.push(_field(entry.comment, 0.28, false));
    cached = {
        name: entry.name,
        genericName: entry.genericName,
        comment: entry.comment,
        exec: entry.exec,
        keywords: keywords.slice(),
        nameKey: _text(entry.name).toLowerCase(),
        fields: fields
    };
    _FZ_CACHE.set(entry, cached);
    return cached;
}

// Best subsequence alignment, O(query length * field length).
// +14 per consecutive pair, +12 per word start,
// -2 per skipped character, -1.5 per character before the first match.
function _subsequence(query, field) {
    var text = field.text;
    var m = query.length;
    var n = text.length;
    var position = -1;
    var i;
    var j;
    for (i = 0; i < m; i++) {
        position = text.indexOf(query.charAt(i), position + 1);
        if (position < 0) {
            return 0;
        }
    }

    var previous = new Array(n).fill(-Infinity);
    for (j = 0; j < n; j++) {
        if (text.charAt(j) === query.charAt(0)) {
            previous[j] = (field.starts[j] ? 12 : 0) - 1.5 * j;
        }
    }
    for (i = 1; i < m; i++) {
        var current = new Array(n).fill(-Infinity);
        var gapBest = -Infinity;
        for (j = 0; j < n; j++) {
            if (j >= 2) {
                gapBest = Math.max(gapBest, previous[j - 2] + 2 * (j - 2));
            }
            if (text.charAt(j) === query.charAt(i)) {
                var run = j > 0 ? previous[j - 1] + 14 : -Infinity;
                var gap = gapBest - 2 * (j - 1);
                current[j] = Math.max(run, gap) + (field.starts[j] ? 12 : 0);
            }
        }
        previous = current;
    }
    var best = -Infinity;
    for (j = 0; j < n; j++) {
        best = Math.max(best, previous[j]);
    }
    return Math.max(200, Math.min(550, 350 + 8 * best / m));
}

// At most one insertion, deletion, substitution, or adjacent transposition
// between query and the first length characters of word. No DP allocation.
function _oneEdit(query, word, length) {
    var i = 0;
    var j = 0;
    var edits = 0;
    while (i < query.length && j < length) {
        if (query.charAt(i) === word.charAt(j)) {
            i++;
            j++;
        } else {
            if (edits === 1) {
                return false;
            }
            edits++;
            if (query.length > length) {
                i++;
            } else if (query.length < length) {
                j++;
            } else if (i + 1 < query.length && j + 1 < length &&
                       query.charAt(i) === word.charAt(j + 1) &&
                       query.charAt(i + 1) === word.charAt(j)) {
                i += 2;
                j += 2;
            } else {
                i++;
                j++;
            }
        }
    }
    return edits + (i < query.length || j < length ? 1 : 0) <= 1;
}

function _typo(query, field) {
    var best = 0;
    for (var i = 0; i < field.words.length; i++) {
        var word = field.words[i];
        for (var length = query.length - 1;
             length <= query.length + 1 && length <= word.length; length++) {
            if (_oneEdit(query, word, length)) {
                best = Math.max(best, (length === word.length ? 150 : 140) -
                                Math.min(10, i));
            }
        }
    }
    return best;
}

function _match(query, field, allowTypos) {
    var text = field.text;
    if (!text) {
        return 0;
    }
    if (text === query) {
        return 1000;
    }
    var first = text.indexOf(query);
    if (first === 0) {
        return 900;
    }
    if (first >= 0) {
        var position = first;
        while (position >= 0) {
            if (field.starts[position]) {
                return 820 - Math.min(40, position * 0.5);
            }
            position = text.indexOf(query, position + 1);
        }
        if (query.length > 1) {
            return 650 - Math.min(40, first * 0.5);
        }
    }
    if (query.length === 1) {
        return 0;
    }
    var fuzzy = _subsequence(query, field);
    if (fuzzy) {
        return fuzzy;
    }
    return allowTypos && field.typos && query.length >= 4 ?
        _typo(query, field) : 0;
}

function _bestField(query, cached, allowTypos) {
    var best = 0;
    for (var i = 0; i < cached.fields.length; i++) {
        var field = cached.fields[i];
        if (1000 * field.weight > best) {
            best = Math.max(best, _match(query, field, allowTypos) * field.weight);
        }
    }
    return best;
}

function _entryScore(words, phrase, cached) {
    var total = 0;
    for (var i = 0; i < words.length; i++) {
        var value = _bestField(words[i], cached, true);
        if (!value) {
            return 0;
        }
        total += value;
    }
    var combined = total / words.length;
    return words.length > 1 ?
        Math.max(combined, _bestField(phrase, cached, false)) : combined;
}

function score(query, entry) {
    var phrase = _query(query);
    if (!phrase || !entry || typeof entry !== "object") {
        return 0;
    }
    return _entryScore(phrase.split(" "), phrase, _cache(entry));
}

function _frecencyAt(usage, now) {
    if (!usage) {
        return 0;
    }
    var count = Number(usage.count);
    var last = Number(usage.last);
    if (!isFinite(count) || count <= 0 || !isFinite(last)) {
        return 0;
    }
    var age = Math.max(0, now - last);
    return Math.min(_FZ_CAP, Math.log2(1 + count) * 12) *
        Math.pow(0.5, age / _FZ_HALF_LIFE);
}

function frecency(usage) {
    return _frecencyAt(usage, Date.now());
}

function rank(query, entries, usageMap, limit) {
    var phrase = _query(query);
    var words = phrase ? phrase.split(" ") : [];
    var maximum = limit === undefined || limit === null ? entries.length :
        Math.max(0, Math.floor(Number(limit)) || 0);
    if (!maximum) {
        return [];
    }
    var now = Date.now();
    var rows = [];
    for (var i = 0; i < entries.length; i++) {
        var entry = entries[i];
        if (!entry || typeof entry !== "object") {
            continue;
        }
        var cached = _cache(entry);
        var value = phrase ? _entryScore(words, phrase, cached) : 0;
        if (phrase && !value) {
            continue;
        }
        var usage = usageMap &&
            Object.prototype.hasOwnProperty.call(usageMap, entry.id) ?
            usageMap[entry.id] : undefined;
        rows.push({
            entry: entry,
            score: value + _frecencyAt(usage, now),
            name: cached.nameKey,
            index: i
        });
    }
    rows.sort(function(a, b) {
        if (a.score !== b.score) {
            return b.score - a.score;
        }
        if (a.name !== b.name) {
            return a.name < b.name ? -1 : 1;
        }
        return a.index - b.index;
    });
    var result = [];
    for (var j = 0; j < rows.length && j < maximum; j++) {
        result.push({entry: rows[j].entry, score: rows[j].score});
    }
    return result;
}
