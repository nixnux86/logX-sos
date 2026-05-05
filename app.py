import os
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from init_db import schema
from parser.analyzer import analyze

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sosinsight.db"
UPLOAD_DIR = BASE_DIR / "uploads"
EXTRACT_DIR = BASE_DIR / "extracted"

UPLOAD_DIR.mkdir(exist_ok=True)
EXTRACT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


def init_db_if_needed():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)


def db_rows(query, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


@app.route("/")
def index():
    init_db_if_needed()
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    init_db_if_needed()
    if "sosfile" not in request.files:
        return jsonify(ok=False, error="No file uploaded"), 400
    f = request.files["sosfile"]
    if not f.filename:
        return jsonify(ok=False, error="Empty filename"), 400
    filename = secure_filename(f.filename)
    target = UPLOAD_DIR / filename
    suffix = 1
    while target.exists():
        stem = target.stem
        ext = ''.join(target.suffixes)
        target = UPLOAD_DIR / f"{stem}_{suffix}{ext}"
        suffix += 1
    f.save(target)
    try:
        case_label = request.form.get("case_name", "")
        case_id = analyze(str(target), case_label=case_label)
        return jsonify(ok=True, case_id=case_id, filename=filename)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500




def one_value(case_id, section, key):
    rows = db_rows("SELECT value FROM facts WHERE case_id=? AND section=? AND key=? LIMIT 1", (case_id, section, key))
    return rows[0]["value"] if rows else ""


@app.route("/api/dashboard")
def dashboard():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400

    facts = db_rows("SELECT section, key, value FROM facts WHERE case_id=?", (case_id,))
    fmap = {(r["section"], r["key"]): r["value"] for r in facts}

    def fact(section, key, default=""):
        return fmap.get((section, key), default)

    cpu_rows = db_rows("SELECT user_pct, system_pct, iowait_pct, idle_pct FROM sar_cpu WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,))
    if cpu_rows:
        cpu = cpu_rows[0]
    else:
        cpu = {"user_pct": None, "system_pct": None, "iowait_pct": None, "idle_pct": None}

    net_rows = db_rows("SELECT SUM(rx_kbps) rx, SUM(tx_kbps) tx FROM sar_net WHERE case_id=? AND LOWER(interface)!='lo'", (case_id,))
    disk_usage = fact("Storage", "Disk Usage", "")

    # Parse simple df -h percentages for dashboard display.
    disks = []
    import re
    for line in disk_usage.splitlines():
        m = re.search(r"\s(\d+)%\s+(/\S*)$", line)
        if m:
            disks.append({"mount": m.group(2), "pct": int(m.group(1))})
    disks = sorted(disks, key=lambda x: x["pct"], reverse=True)[:4]

    mem_total = fact("Hardware", "RAM Total", "")
    ram_pressure = fact("Hardware", "RAM Pressure", "")
    loadavg = fact("System Identity", "Load Average", "") or fact("Hardware", "Load Average", "")
    cpu_threads = fact("Hardware", "CPU Threads", "")

    rows = db_rows("SELECT filename, created_at FROM cases WHERE case_id=? LIMIT 1", (case_id,))
    case_info = rows[0] if rows else {}

    return jsonify(ok=True, data={
        "hostname": fact("System Identity", "Hostname", "Unknown"),
        "kernel": fact("System Identity", "Kernel", ""),
        "os_release": fact("System Identity", "OS Release", "Unknown"),
        "collection_date": case_info.get("created_at", ""),
        "filename": case_info.get("filename", ""),
        "uptime": fact("System Identity", "Uptime", ""),
        "cpu_threads": cpu_threads,
        "cpu": cpu,
        "memory": {"total": mem_total, "pressure": ram_pressure},
        "network": net_rows[0] if net_rows else {"rx": 0, "tx": 0},
        "load_average": loadavg,
        "disks": disks,
    })

@app.route("/api/recent")
def recent():
    init_db_if_needed()
    rows = db_rows("""
        SELECT case_id, filename, created_at, last_opened_at
        FROM cases
        ORDER BY last_opened_at DESC
        LIMIT 5
    """)
    return jsonify(ok=True, data=rows)


@app.route("/api/open_case", methods=["POST"])
def open_case():
    init_db_if_needed()
    case_id = request.json.get("case") if request.is_json else request.form.get("case")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE cases SET last_opened_at=CURRENT_TIMESTAMP WHERE case_id=?", (case_id,))
    return jsonify(ok=True)


@app.route("/api/delete_case", methods=["POST"])
def delete_case():
    init_db_if_needed()
    case_id = request.json.get("case") if request.is_json else request.form.get("case")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400

    rows = db_rows("SELECT extracted_path FROM cases WHERE case_id=? LIMIT 1", (case_id,))
    with sqlite3.connect(DB_PATH) as conn:
        for table in ["facts", "findings", "messages", "dmesg_logs", "sar_cpu", "sar_mem", "sar_disk", "sar_net", "sar_load"]:
            conn.execute(f"DELETE FROM {table} WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM cases WHERE case_id=?", (case_id,))

    # Try to remove the extracted case directory. If extracted_path points to the inner sosreport
    # directory, remove its case wrapper under extracted/.
    if rows:
        extracted = Path(rows[0].get("extracted_path", ""))
        try:
            base = EXTRACT_DIR.resolve()
            target = extracted.resolve()
            if str(target).startswith(str(base)):
                rel = target.relative_to(base)
                wrapper = base / rel.parts[0] if rel.parts else target
                shutil.rmtree(wrapper, ignore_errors=True)
        except Exception:
            pass
    return jsonify(ok=True)


@app.route("/api/facts")
def facts():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    section = request.args.get("section", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT section, key, value
        FROM facts
        WHERE case_id=? AND (?='' OR section=?)
        ORDER BY section, key
    """, (case_id, section, section))
    return jsonify(ok=True, data=rows)


@app.route("/api/findings")
def findings():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT module, severity, title, detail, recommendation
        FROM findings
        WHERE case_id=?
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, module
    """, (case_id,))
    return jsonify(ok=True, data=rows)


@app.route("/api/messages")
def messages():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    category = request.args.get("category", "total")
    keyword = request.args.get("keyword", "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = max(min(int(request.args.get("per_page", 20) or 20), 200), 5)
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400

    def category_where(cat):
        cat = (cat or "total").lower()
        searchable = "LOWER(COALESCE(log_time,'') || ' ' || COALESCE(hostname,'') || ' ' || COALESCE(process,'') || ' ' || COALESCE(message,''))"
        # Category filters intentionally reflect the visible filter words.
        # This avoids surprising broad matches such as "Errors" also returning FAILED lines.
        if cat == "errors":
            return f"{searchable} LIKE '%error%'"
        if cat == "warnings":
            return f"{searchable} LIKE '%warn%'"
        if cat == "failed":
            return f"({searchable} LIKE '%failed%' OR {searchable} LIKE '%failure%')"
        if cat == "info":
            return f"({searchable} LIKE '%info%' OR severity='info')"
        return "1=1"

    def apply_keyword(where, params):
        if keyword:
            where.append("LOWER(COALESCE(log_time,'') || ' ' || COALESCE(hostname,'') || ' ' || COALESCE(process,'') || ' ' || COALESCE(message,'')) LIKE ?")
            params.append(f"%{keyword.lower()}%")
        return where, params

    # Counters are based on all lines in the selected case, not the current search term.
    counters = {"total": 0, "errors": 0, "warnings": 0, "failed": 0, "info": 0}
    for cat in counters:
        counters[cat] = db_rows(
            f"SELECT COUNT(*) AS c FROM messages WHERE case_id=? AND {category_where(cat)}",
            (case_id,)
        )[0]["c"]

    where = ["case_id=?", category_where(category)]
    params = [case_id]
    where, params = apply_keyword(where, params)
    where_sql = " AND ".join(where)

    total = db_rows(f"SELECT COUNT(*) AS c FROM messages WHERE {where_sql}", tuple(params))[0]["c"]
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    rows = db_rows(f"""
        SELECT id, log_time, hostname, process, severity, message
        FROM messages
        WHERE {where_sql}
        ORDER BY id ASC
        LIMIT ? OFFSET ?
    """, tuple(params + [per_page, offset]))
    return jsonify(ok=True, data=rows, counters=counters, page=page, per_page=per_page, total=total, total_pages=total_pages)


@app.route("/api/dmesg")
def dmesg():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    keyword = request.args.get("keyword", "").strip()
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    where = ["case_id=?"]
    params = [case_id]
    if keyword:
        where.append("LOWER(message) LIKE ?")
        params.append(f"%{keyword.lower()}%")
    rows = db_rows(f"""
        SELECT severity, message
        FROM dmesg_logs
        WHERE {' AND '.join(where)}
        ORDER BY id ASC
        LIMIT 3000
    """, tuple(params))
    return jsonify(ok=True, data=rows)


def _strip_ansi_runtime(text):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def _looks_like_ps_row(parts):
    if len(parts) < 11:
        return False
    if parts[0].upper() in {"USER", "UID"}:
        return False
    if not parts[1].isdigit():
        return False
    try:
        float(parts[2]); float(parts[3])
        return True
    except Exception:
        return False


def parse_ps_fact(text):
    """Parse ps aux style rows.

    xsos output often embeds a complete ps snapshot, while sosreport paths can
    differ by plugin/version. This parser intentionally scans any text and keeps
    only rows matching the ps aux shape:
    USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
    """
    rows = []
    seen = set()
    for raw in _strip_ansi_runtime(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        # Remove common xsos bullets/prefixes while preserving the actual ps row.
        line = line.lstrip("*|- ")
        parts = line.split(None, 10)
        if not _looks_like_ps_row(parts):
            continue
        key = (parts[1], parts[10])
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "user": parts[0],
            "pid": parts[1],
            "cpu_pct": parts[2],
            "mem_pct": parts[3],
            "vsz": parts[4],
            "rss": parts[5],
            "stat": parts[7] if len(parts) > 7 else "",
            "start": parts[8] if len(parts) > 8 else "",
            "time": parts[9] if len(parts) > 9 else "",
            "command": parts[10] if len(parts) > 10 else line,
        })
    return rows


def _sort_process_rows(rows, field):
    def key(row):
        try:
            return float(row.get(field, 0) or 0)
        except Exception:
            return 0.0
    return sorted(rows, key=key, reverse=True)


@app.route("/api/top_processes")
def top_processes():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    cpu_text = one_value(case_id, "Services", "Top CPU consumers")
    mem_text = one_value(case_id, "Services", "Top memory consumers")
    cpu_rows = parse_ps_fact(cpu_text)
    mem_rows = parse_ps_fact(mem_text)

    # Fallback: xsos -a often contains the process snapshot even when the
    # standalone sos_commands/process/ps_aux* file is missing or named
    # differently. Scan the stored xsos output and rank it here.
    if not cpu_rows or not mem_rows:
        xsos_text = one_value(case_id, "Summary", "xsos output")
        xsos_rows = parse_ps_fact(xsos_text)
        if not cpu_rows:
            cpu_rows = _sort_process_rows(xsos_rows, "cpu_pct")
        if not mem_rows:
            mem_rows = _sort_process_rows(xsos_rows, "mem_pct")

    return jsonify(ok=True, data={
        "cpu": _sort_process_rows(cpu_rows, "cpu_pct")[:10],
        "mem": _sort_process_rows(mem_rows, "mem_pct")[:10],
    })


@app.route("/api/sar_cpu")
def sar_cpu():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT sample_time, user_pct, system_pct, iowait_pct, idle_pct
        FROM sar_cpu
        WHERE case_id=?
        ORDER BY id ASC
    """, (case_id,))
    return jsonify(ok=True, data=rows)


@app.route("/api/sar_mem")
def sar_mem():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT sample_time, mem_used_pct, swap_used_pct
        FROM sar_mem
        WHERE case_id=?
        ORDER BY id ASC
    """, (case_id,))
    return jsonify(ok=True, data=rows)


@app.route("/api/sar_disk")
def sar_disk():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT sample_time, device, read_kbps, write_kbps, util_pct
        FROM sar_disk
        WHERE case_id=?
        ORDER BY id ASC
    """, (case_id,))
    return jsonify(ok=True, data=rows)


@app.route("/api/sar_net")
def sar_net():
    init_db_if_needed()
    case_id = request.args.get("case", "")
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    rows = db_rows("""
        SELECT sample_time, interface, rx_kbps, tx_kbps, rxpck_s, txpck_s
        FROM sar_net
        WHERE case_id=?
        ORDER BY id ASC
    """, (case_id,))
    return jsonify(ok=True, data=rows)


def resolve_console_paths(case_id, requested_cwd=""):
    rows = db_rows("SELECT extracted_path FROM cases WHERE case_id=? LIMIT 1", (case_id,))
    if not rows:
        return None, None, (jsonify(ok=False, error="Case not found"), 404)

    root = Path(rows[0].get("extracted_path") or "").resolve()
    base = EXTRACT_DIR.resolve()

    def valid_path(path):
        path = Path(path).resolve()
        return str(path).startswith(str(root)) and path.exists()

    try:
        if not str(root).startswith(str(base)) or not root.exists():
            return None, None, (jsonify(ok=False, error="Invalid extracted path"), 400)
        cwd = Path(requested_cwd).resolve() if requested_cwd else root
        if not valid_path(cwd):
            cwd = root
    except Exception:
        return None, None, (jsonify(ok=False, error="Invalid extracted path"), 400)

    return root, cwd, None


@app.route("/api/console_complete", methods=["POST"])
def console_complete():
    init_db_if_needed()
    payload = request.get_json(silent=True) or {}
    case_id = payload.get("case", "")
    line = payload.get("line", "") or ""
    requested_cwd = (payload.get("cwd", "") or "").strip()

    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400

    root, cwd, error = resolve_console_paths(case_id, requested_cwd)
    if error:
        return error

    token = line.split()[-1] if line.split() else ""
    prefix_line = line[:len(line) - len(token)] if token else line

    # First word: complete executable names plus local paths. Other words: complete file paths.
    is_command_position = (len(line.strip().split()) <= 1 and not line.endswith(" "))
    suggestions = []

    def inside_root(path):
        try:
            return str(Path(path).resolve()).startswith(str(root))
        except Exception:
            return False

    # Filesystem completion inside extracted sosreport root.
    raw = token or ""
    if raw.startswith("/"):
        base_path = Path(raw)
    else:
        base_path = cwd / raw
    search_dir = base_path.parent if raw and not raw.endswith("/") else base_path
    stem = base_path.name if raw and not raw.endswith("/") else ""
    try:
        if inside_root(search_dir) and search_dir.exists():
            for item in sorted(search_dir.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:80]:
                if item.name.startswith(stem):
                    rel = item.resolve().relative_to(cwd) if str(item.resolve()).startswith(str(cwd)) else item.resolve().relative_to(root)
                    val = str(rel)
                    if item.is_dir():
                        val += "/"
                    suggestions.append(prefix_line + shlex.quote(val))
    except Exception:
        pass

    if is_command_position:
        commands = ["cat", "cd", "clear", "find", "grep", "head", "ls", "more", "less", "pwd", "sed", "tail", "wc", "xsos", "awk", "sort", "uniq"]
        for c in commands:
            if c.startswith(token):
                suggestions.append(c + (" " if c != "clear" else ""))

    # de-duplicate while preserving order
    seen = set()
    clean = []
    for x in suggestions:
        if x not in seen:
            clean.append(x)
            seen.add(x)
    return jsonify(ok=True, suggestions=clean[:40])


@app.route("/api/console", methods=["POST"])
def console():
    init_db_if_needed()
    payload = request.get_json(silent=True) or {}
    case_id = payload.get("case", "")
    command = (payload.get("command", "") or "").strip()
    requested_cwd = (payload.get("cwd", "") or "").strip()
    if not case_id:
        return jsonify(ok=False, error="Missing case id"), 400
    root, cwd, error = resolve_console_paths(case_id, requested_cwd)
    if error:
        return error

    def valid_path(path):
        path = Path(path).resolve()
        return str(path).startswith(str(root)) and path.exists()

    if not command:
        command = "pwd && ls -la"

    # Terminal helpers: keep cwd persistent for common cd/clear behavior.
    if command == "pwd":
        return jsonify(ok=True, root=str(root), cwd=str(cwd), command=command, returncode=0, output=str(cwd))

    if command == "clear":
        return jsonify(ok=True, root=str(root), cwd=str(cwd), command=command, returncode=0, output="__CLEAR__")

    # This browser console is command-runner based, not a full PTY.
    # Interactive pagers cannot be controlled properly, so render them as plain output.
    if command == "more" or command.startswith("more ") or command == "less" or command.startswith("less "):
        parts = command.split(maxsplit=1)
        command = "cat " + (parts[1] if len(parts) > 1 else "")

    if command.startswith("cd"):
        parts = command.split(maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else str(root)
        if target in ["~", "$HOME"]:
            target_path = root
        else:
            target_path = (cwd / target).resolve() if not target.startswith("/") else Path(target).resolve()
        if valid_path(target_path) and target_path.is_dir():
            return jsonify(ok=True, root=str(root), cwd=str(target_path), command=command, returncode=0, output="")
        return jsonify(ok=False, root=str(root), cwd=str(cwd), command=command, returncode=1, output=f"cd: no such directory or outside sosreport root: {target}"), 400

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            executable="/bin/bash",
            text=True,
            capture_output=True,
            timeout=60,
            env={**os.environ, "TERM": "xterm-256color", "CLICOLOR_FORCE": "1", "PAGER": "cat", "LESS": "-FX"},
        )
        output = (completed.stdout or "")
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return jsonify(ok=True, root=str(root), cwd=str(cwd), command=command, returncode=completed.returncode, output=output[-200000:])
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="ignore")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="ignore")
        output = (stdout + "\n" + stderr).strip()
        return jsonify(ok=False, root=str(root), cwd=str(cwd), command=command, returncode=124, output=output[-200000:], error="Command timed out after 60 seconds"), 408


if __name__ == "__main__":
    init_db_if_needed()
    app.run(host="0.0.0.0", port=5000, debug=True)
