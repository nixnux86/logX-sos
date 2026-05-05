import os
import re
import tarfile
import uuid
import sqlite3
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "sosinsight.db"
EXTRACT_DIR = BASE_DIR / "extracted"


def connect_db():
    return sqlite3.connect(DB_PATH)


def safe_extract(tar, path):
    path = Path(path).resolve()
    for member in tar.getmembers():
        member_path = (path / member.name).resolve()
        if not str(member_path).startswith(str(path)):
            raise Exception("Unsafe tar path detected")
    tar.extractall(path)


def detect_sos_root(target):
    """Return the real sosreport root.

    Many archives extract into case_id/sosreport-host-date/. xsos and
    several parsers expect the inner directory, not the case wrapper.
    """
    target = Path(target)
    children = [p for p in target.iterdir() if p.is_dir()]
    if len(children) == 1:
        child = children[0]
        markers = [
            child / "sos_commands", child / "etc", child / "proc",
            child / "var", child / "installed-rpms", child / "sos_logs"
        ]
        if any(m.exists() for m in markers) or child.name.startswith("sosreport"):
            return child
    return target


def extract_archive(archive_path, case_label=""):
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", (case_label or "").strip()).strip("_")
    if safe_label:
        safe_label = safe_label[:40]
        case_id = "case_" + safe_label + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    else:
        case_id = "case_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    target = EXTRACT_DIR / case_id
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as tar:
        safe_extract(tar, target)
    return case_id, detect_sos_root(target)


def read_text(path):
    if not path:
        return ""
    try:
        return Path(path).read_text(errors="ignore")
    except Exception:
        return ""


def find_first(root, patterns):
    for pattern in patterns:
        matches = list(Path(root).rglob(pattern))
        if matches:
            return matches[0]
    return None


def find_all(root, patterns):
    out = []
    for pattern in patterns:
        out.extend(list(Path(root).rglob(pattern)))
    return out


def insert_fact(conn, case_id, section, key, value):
    conn.execute("INSERT INTO facts(case_id, section, key, value) VALUES (?, ?, ?, ?)", (case_id, section, key, str(value)))


def insert_finding(conn, case_id, module, severity, title, detail, recommendation):
    conn.execute(
        """INSERT INTO findings(case_id, module, severity, title, detail, recommendation)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (case_id, module, severity, title, detail, recommendation),
    )


def parse_system_identity(conn, case_id, root):
    hostname = read_text(find_first(root, ["hostname", "sos_commands/host/hostname"])).strip()
    uname = read_text(find_first(root, ["proc/version", "sos_commands/kernel/uname_-a", "uname"])).strip()
    os_release = read_text(find_first(root, ["etc/os-release", "etc/redhat-release", "sos_commands/host/redhat-release"])).strip()
    dmidecode = read_text(find_first(root, ["sos_commands/hardware/dmidecode", "dmidecode"]))

    if hostname:
        insert_fact(conn, case_id, "System Identity", "Hostname", hostname)
    if uname:
        insert_fact(conn, case_id, "System Identity", "Kernel", uname[:500])

    pretty = ""
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty = line.split("=", 1)[1].replace('"', "")
    if pretty or os_release:
        insert_fact(conn, case_id, "System Identity", "OS Release", pretty or os_release[:500])

    model = serial = ""
    for line in dmidecode.splitlines():
        line = line.strip()
        if line.startswith("Product Name:") and not model:
            model = line.split(":", 1)[1].strip()
        if line.startswith("Serial Number:") and not serial:
            serial = line.split(":", 1)[1].strip()
    if model:
        insert_fact(conn, case_id, "System Identity", "Hardware Model", model)
    if serial:
        insert_fact(conn, case_id, "System Identity", "Serial Number", serial)

    uptime_txt = read_text(find_first(root, ["proc/uptime", "uptime", "sos_commands/systemd/uptime"]))
    if uptime_txt:
        m = re.search(r"^(\d+(?:\.\d+)?)", uptime_txt.strip())
        if m:
            days = int(float(m.group(1)) // 86400)
            insert_fact(conn, case_id, "System Identity", "Uptime", f"{days} days")
        else:
            insert_fact(conn, case_id, "System Identity", "Uptime", uptime_txt.strip()[:300])

    loadavg_txt = read_text(find_first(root, ["proc/loadavg", "loadavg"]))
    if loadavg_txt:
        insert_fact(conn, case_id, "System Identity", "Load Average", loadavg_txt.strip()[:200])


def parse_hardware(conn, case_id, root):
    cpuinfo = read_text(find_first(root, ["proc/cpuinfo", "cpuinfo"]))
    meminfo = read_text(find_first(root, ["proc/meminfo", "meminfo"]))
    dmidecode = read_text(find_first(root, ["sos_commands/hardware/dmidecode", "dmidecode"]))
    lspci = read_text(find_first(root, ["sos_commands/pci/lspci", "sos_commands/pci/lspci_-nn", "lspci"]))

    cpu_threads = len(re.findall(r"^processor\s*:", cpuinfo, re.MULTILINE))
    if cpu_threads:
        insert_fact(conn, case_id, "Hardware", "CPU Threads", cpu_threads)

    mem_total = re.search(r"MemTotal:\s+(\d+)", meminfo)
    mem_avail = re.search(r"MemAvailable:\s+(\d+)", meminfo)
    swap_total = re.search(r"SwapTotal:\s+(\d+)", meminfo)
    swap_free = re.search(r"SwapFree:\s+(\d+)", meminfo)

    if mem_total:
        total = int(mem_total.group(1))
        insert_fact(conn, case_id, "Hardware", "RAM Total", f"{total/1024/1024:.2f} GB")
        if mem_avail:
            used_pct = (1 - int(mem_avail.group(1)) / total) * 100
            insert_fact(conn, case_id, "Hardware", "RAM Pressure", f"{used_pct:.2f}%")
            if used_pct >= 90:
                insert_finding(conn, case_id, "Hardware", "warning", "High memory pressure", f"RAM pressure is approximately {used_pct:.2f}%.", "Check memory consumers, leaks, cache pressure, and swap activity.")

    if swap_total:
        total = int(swap_total.group(1))
        insert_fact(conn, case_id, "Hardware", "Swap Total", f"{total/1024/1024:.2f} GB")
        if total > 0 and swap_free:
            used_pct = (1 - int(swap_free.group(1)) / total) * 100
            insert_fact(conn, case_id, "Hardware", "Swap Pressure", f"{used_pct:.2f}%")
            if used_pct >= 50:
                insert_finding(conn, case_id, "Hardware", "warning", "Swap usage is significant", f"Swap usage is approximately {used_pct:.2f}%.", "Investigate memory pressure and workload behavior.")

    dimms = len(re.findall(r"Memory Device", dmidecode))
    if dimms:
        insert_fact(conn, case_id, "Hardware", "DIMM Slots", dimms)

    nics, hbas = [], []
    for line in lspci.splitlines():
        lower = line.lower()
        if "ethernet" in lower or "network controller" in lower:
            nics.append(line)
        if "fibre channel" in lower or "raid" in lower or "storage" in lower or "sas" in lower:
            hbas.append(line)
    insert_fact(conn, case_id, "Hardware", "PCIe NICs", "\n".join(nics) if nics else "Not detected")
    insert_fact(conn, case_id, "Hardware", "PCIe HBAs / Storage Controllers", "\n".join(hbas) if hbas else "Not detected")


def detect_severity(line):
    lower = line.lower()
    if any(x in lower for x in ["panic", "oops", "bug:", "segfault", "oom-killer", "out of memory"]):
        return "critical"
    if any(x in lower for x in ["warning", "warn", "error", "failed", "failure", "denied", "mce", "hardware error", "reset"]):
        return "warning"
    return "info"


def parse_messages(conn, case_id, root):
    msg_file = find_first(root, ["var/log/messages", "var/log/syslog"])
    text = read_text(msg_file)
    if not text:
        insert_fact(conn, case_id, "Messages", "Status", "No /var/log/messages or syslog found")
        return
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        severity = detect_severity(line)
        m = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+)\s+(\S+)\s+([^:]+):\s+(.*)$", line)
        if m:
            log_time, hostname, process, message = m.groups()
        else:
            log_time = hostname = process = ""
            message = line
        conn.execute("INSERT INTO messages(case_id, log_time, hostname, process, severity, message) VALUES (?, ?, ?, ?, ?, ?)", (case_id, log_time, hostname, process, severity, message))
        count += 1
    insert_fact(conn, case_id, "Messages", "Total Messages Parsed", count)



def parse_dmesg(conn, case_id, root):
    dmesg = read_text(find_first(root, ["sos_commands/kernel/dmesg", "dmesg"]))
    if not dmesg:
        insert_fact(conn, case_id, "Dmesg", "Status", "No dmesg output found")
        return
    count = 0
    for line in dmesg.splitlines():
        if not line.strip():
            continue
        severity = detect_severity(line)
        conn.execute(
            "INSERT INTO dmesg_logs(case_id, severity, message) VALUES (?, ?, ?)",
            (case_id, severity, line)
        )
        count += 1
    insert_fact(conn, case_id, "Dmesg", "Total Dmesg Lines Parsed", count)

def parse_kernel_logs(conn, case_id, root):
    dmesg = read_text(find_first(root, ["sos_commands/kernel/dmesg", "dmesg"]))
    messages = read_text(find_first(root, ["var/log/messages", "var/log/syslog"]))
    combined = dmesg + "\n" + messages
    checks = [
        ("OOM Kill Events", r"(oom-killer|out of memory|killed process)", "critical", "OOM killer events detected", "Check top memory consumers, limits, leaks, and swap pressure."),
        ("Kernel Panic / BUG / Oops", r"(kernel panic|BUG:|Oops:)", "critical", "Kernel panic, BUG, or Oops traces detected", "Review kernel version, drivers, firmware, and hardware logs."),
        ("MCE Hardware Errors", r"(machine check|mce|hardware error)", "warning", "Machine Check or hardware errors detected", "Check CPU, DIMM, PCIe, firmware, and vendor diagnostics."),
        ("SELinux Denials", r"(avc:.*denied|selinux.*denied)", "warning", "SELinux denials detected", "Review audit logs, contexts, and policy configuration."),
    ]
    for name, pattern, severity, title, recommendation in checks:
        lines = [line for line in combined.splitlines() if re.search(pattern, line, re.IGNORECASE)]
        insert_fact(conn, case_id, "Kernel & Logs", name, len(lines))
        if lines:
            insert_finding(conn, case_id, "Kernel & Logs", severity, title, "\n".join(lines[:20]), recommendation)


def parse_services(conn, case_id, root):
    failed = read_text(find_first(root, ["sos_commands/systemd/systemctl_--failed", "sos_commands/systemd/systemctl_--failed_--no-legend", "systemctl_failed"]))
    ps = read_text(find_first(root, ["sos_commands/process/ps_auxwww", "sos_commands/process/ps_aux", "ps_aux"]))
    insert_fact(conn, case_id, "Services", "Failed systemd units", failed.strip() or "No data")
    if failed and "0 loaded units listed" not in failed.lower() and "no failed units" not in failed.lower():
        insert_finding(conn, case_id, "Services", "warning", "Failed systemd units detected", failed[:2000], "Run systemctl status and journalctl -u for the failed units.")
    top_mem = []
    top_cpu = []
    for line in ps.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            try:
                top_cpu.append((float(parts[2]), line))
            except ValueError:
                pass
            try:
                top_mem.append((float(parts[3]), line))
            except ValueError:
                pass
    if top_cpu:
        insert_fact(conn, case_id, "Services", "Top CPU consumers", "\n".join(x[1] for x in sorted(top_cpu, reverse=True)[:10]))
    if top_mem:
        insert_fact(conn, case_id, "Services", "Top memory consumers", "\n".join(x[1] for x in sorted(top_mem, reverse=True)[:10]))


def parse_network(conn, case_id, root):
    ip_addr = read_text(find_first(root, ["sos_commands/networking/ip_-o_addr", "sos_commands/networking/ip_addr", "ip_addr"]))
    ip_link = read_text(find_first(root, ["sos_commands/networking/ip_link", "sos_commands/networking/ip_-s_link", "ip_link"]))
    routes = read_text(find_first(root, ["sos_commands/networking/ip_route", "sos_commands/networking/ip_route_show_table_all", "route"]))
    ss = read_text(find_first(root, ["sos_commands/networking/ss_-tulpn", "sos_commands/networking/netstat_-tulpn", "ss"]))
    messages = read_text(find_first(root, ["var/log/messages", "var/log/syslog"]))
    link_down = [line for line in messages.splitlines() if re.search(r"(link is down|link down|nic.*down|interface.*down)", line, re.IGNORECASE)]
    insert_fact(conn, case_id, "Network", "Interface Addresses", ip_addr.strip() or "No data")
    insert_fact(conn, case_id, "Network", "Interface State", ip_link.strip() or "No data")
    insert_fact(conn, case_id, "Network", "Route Table", routes.strip() or "No data")
    insert_fact(conn, case_id, "Network", "Listening Ports", ss.strip() or "No data")
    insert_fact(conn, case_id, "Network", "Link-down Events", len(link_down))
    if link_down:
        insert_finding(conn, case_id, "Network", "warning", "Network link-down events detected", "\n".join(link_down[:20]), "Check cable/switch port, bonding/team, driver, firmware, and MTU consistency.")


def parse_storage(conn, case_id, root):
    df = read_text(find_first(root, ["sos_commands/filesys/df_-h", "sos_commands/filesys/df_-al", "df"]))
    mount = read_text(find_first(root, ["proc/mounts", "mount"]))
    lvs = read_text(find_first(root, ["sos_commands/lvm2/lvs", "lvs"]))
    pvs = read_text(find_first(root, ["sos_commands/lvm2/pvs", "pvs"]))
    vgs = read_text(find_first(root, ["sos_commands/lvm2/vgs", "vgs"]))
    multipath = read_text(find_first(root, ["sos_commands/multipath/multipath_-ll", "multipath"]))
    messages = read_text(find_first(root, ["var/log/messages", "var/log/syslog"]))
    high_usage = []
    for line in df.splitlines():
        m = re.search(r"\s(\d+)%\s+(/\S*)$", line)
        if m and int(m.group(1)) >= 80:
            high_usage.append(f"{m.group(2)}: {m.group(1)}%")
    io_errors = [line for line in messages.splitlines() if re.search(r"(I/O error|blk_update_request|buffer I/O error|rejecting I/O|multipath.*failed)", line, re.IGNORECASE)]
    insert_fact(conn, case_id, "Storage", "Disk Usage", df.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "Mounts", mount.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "LVM PV", pvs.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "LVM VG", vgs.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "LVM LV", lvs.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "Multipath", multipath.strip() or "No data")
    insert_fact(conn, case_id, "Storage", "Mounts >=80%", "\n".join(high_usage) if high_usage else "None")
    insert_fact(conn, case_id, "Storage", "I/O Errors", len(io_errors))
    if high_usage:
        insert_finding(conn, case_id, "Storage", "warning", "Filesystem usage above 80%", "\n".join(high_usage), "Clean old logs, rotate logs, extend filesystem, or archive unused data.")
    if io_errors:
        insert_finding(conn, case_id, "Storage", "critical", "Storage I/O errors detected", "\n".join(io_errors[:20]), "Check disk path, SAN, multipath, controller, HBA, firmware, and array events.")



def _to_float(value):
    try:
        return float(str(value).replace(',', '.'))
    except Exception:
        return None


def _sar_time_and_fields(parts):
    """Return (sample_time, remaining_fields) for common sar text formats."""
    if not parts:
        return "", []
    if parts[0] == "Average:":
        return "Average", parts[1:]
    if len(parts) >= 2 and parts[1] in ("AM", "PM"):
        return f"{parts[0]} {parts[1]}", parts[2:]
    return parts[0], parts[1:]



def _insert_sar_cpu(conn, case_id, sample_time, user_pct, system_pct, iowait_pct, idle_pct):
    conn.execute(
        "INSERT INTO sar_cpu(case_id, sample_time, user_pct, system_pct, iowait_pct, idle_pct) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, sample_time, user_pct, system_pct, iowait_pct, idle_pct),
    )


def _insert_sar_mem(conn, case_id, sample_time, mem_used_pct, swap_used_pct):
    conn.execute(
        "INSERT INTO sar_mem(case_id, sample_time, mem_used_pct, swap_used_pct) VALUES (?, ?, ?, ?)",
        (case_id, sample_time, mem_used_pct, swap_used_pct),
    )


def _insert_sar_disk(conn, case_id, sample_time, device, read_kbps, write_kbps, util_pct):
    conn.execute(
        "INSERT INTO sar_disk(case_id, sample_time, device, read_kbps, write_kbps, util_pct) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, sample_time, device, read_kbps, write_kbps, util_pct),
    )


def _insert_sar_net(conn, case_id, sample_time, iface, rx_kbps, tx_kbps, rxpck, txpck):
    conn.execute(
        "INSERT INTO sar_net(case_id, sample_time, interface, rx_kbps, tx_kbps, rxpck_s, txpck_s) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (case_id, sample_time, iface, rx_kbps, tx_kbps, rxpck, txpck),
    )


def _parse_sar_text(conn, case_id, text):
    mode = None
    columns = []
    inserted = {"cpu": 0, "mem": 0, "disk": 0, "net": 0}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Linux ") or line.startswith("#"):
            continue
        parts = line.split()
        sample_time, fields = _sar_time_and_fields(parts)
        if not fields:
            continue
        if "CPU" in fields and "%user" in fields:
            mode = "cpu"; columns = fields; continue
        if "%memused" in fields or "%commit" in fields or "kbmemused" in fields:
            mode = "mem"; columns = fields; continue
        if "DEV" in fields and ("rkB/s" in fields or "wkB/s" in fields or "rd_sec/s" in fields or "wr_sec/s" in fields or "%util" in fields):
            mode = "disk"; columns = fields; continue
        if "IFACE" in fields and ("rxkB/s" in fields or "txkB/s" in fields or "rxpck/s" in fields or "txpck/s" in fields):
            mode = "net"; columns = fields; continue
        if not columns or sample_time == "":
            continue
        row = dict(zip(columns, fields))
        try:
            if mode == "cpu" and row.get("CPU") == "all":
                vals = (_to_float(row.get("%user")), _to_float(row.get("%system")), _to_float(row.get("%iowait", 0)), _to_float(row.get("%idle")))
                if None not in vals:
                    _insert_sar_cpu(conn, case_id, sample_time, *vals); inserted["cpu"] += 1
            elif mode == "mem":
                mem_used = _to_float(row.get("%memused"))
                swap_used = _to_float(row.get("%swpused", row.get("%swapused", 0))) or 0
                if mem_used is not None:
                    _insert_sar_mem(conn, case_id, sample_time, mem_used, swap_used); inserted["mem"] += 1
            elif mode == "disk":
                device = row.get("DEV", "")
                if device:
                    _insert_sar_disk(conn, case_id, sample_time, device, _to_float(row.get("rkB/s", row.get("rd_sec/s", 0))) or 0, _to_float(row.get("wkB/s", row.get("wr_sec/s", 0))) or 0, _to_float(row.get("%util", 0)) or 0); inserted["disk"] += 1
            elif mode == "net":
                iface = row.get("IFACE", "")
                if iface:
                    _insert_sar_net(conn, case_id, sample_time, iface, _to_float(row.get("rxkB/s", 0)) or 0, _to_float(row.get("txkB/s", 0)) or 0, _to_float(row.get("rxpck/s", 0)) or 0, _to_float(row.get("txpck/s", 0)) or 0); inserted["net"] += 1
        except Exception:
            continue
    return inserted


def _parse_sadf_csv(conn, case_id, csv_text, wanted):
    # sadf -d produces semicolon-separated rows: host;interval;timestamp;...
    inserted = 0
    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        return 0
    header = None
    for line in lines:
        clean = line[1:].strip() if line.startswith('#') else line
        parts = clean.split(';')
        if any(x in clean for x in ['%user','%memused','rkB/s','rxkB/s']):
            header = parts
            continue
        if line.startswith('#'):
            continue
        if not header or len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        sample_time = row.get('timestamp') or row.get('time') or (parts[2] if len(parts)>2 else '')
        try:
            if wanted == 'cpu' and row.get('CPU') == 'all':
                vals = (_to_float(row.get('%user')), _to_float(row.get('%system')), _to_float(row.get('%iowait', 0)), _to_float(row.get('%idle')))
                if None not in vals:
                    _insert_sar_cpu(conn, case_id, sample_time, *vals); inserted += 1
            elif wanted == 'mem':
                mem = _to_float(row.get('%memused'))
                swp = _to_float(row.get('%swpused', row.get('%swapused', 0))) or 0
                if mem is not None:
                    _insert_sar_mem(conn, case_id, sample_time, mem, swp); inserted += 1
            elif wanted == 'disk':
                dev = row.get('DEV') or row.get('dev') or ''
                if dev:
                    _insert_sar_disk(conn, case_id, sample_time, dev, _to_float(row.get('rkB/s', 0)) or 0, _to_float(row.get('wkB/s', 0)) or 0, _to_float(row.get('%util', 0)) or 0); inserted += 1
            elif wanted == 'net':
                iface = row.get('IFACE') or ''
                if iface:
                    _insert_sar_net(conn, case_id, sample_time, iface, _to_float(row.get('rxkB/s', 0)) or 0, _to_float(row.get('txkB/s', 0)) or 0, _to_float(row.get('rxpck/s', 0)) or 0, _to_float(row.get('txpck/s', 0)) or 0); inserted += 1
        except Exception:
            continue
    return inserted


def _run_sadf_on_binary_sa(conn, case_id, root):
    sadf = shutil.which('sadf')
    if not sadf:
        insert_fact(conn, case_id, 'SAR Graphs', 'sadf Status', 'sadf command not found. Install sysstat to parse binary /var/log/sa/saXX files.')
        return {'cpu':0,'mem':0,'disk':0,'net':0}
    sa_files = []
    for p in Path(root).rglob('sa[0-9][0-9]'):
        if p.is_file():
            sa_files.append(p)
    for p in Path(root).rglob('sa[0-9][0-9][0-9]'):
        if p.is_file():
            sa_files.append(p)
    total = {'cpu':0,'mem':0,'disk':0,'net':0}
    seen = set()
    for sa in sa_files[:40]:
        if sa in seen: continue
        seen.add(sa)
        commands = {
            'cpu': [sadf, '-d', str(sa), '--', '-u'],
            'mem': [sadf, '-d', str(sa), '--', '-r', '-S'],
            'disk': [sadf, '-d', str(sa), '--', '-d'],
            'net': [sadf, '-d', str(sa), '--', '-n', 'DEV'],
        }
        for kind, cmd in commands.items():
            try:
                r = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
                if r.stdout:
                    total[kind] += _parse_sadf_csv(conn, case_id, r.stdout, kind)
            except Exception:
                pass
    insert_fact(conn, case_id, 'SAR Graphs', 'Binary sa files parsed by sadf', f"CPU={total['cpu']}, Memory={total['mem']}, Disk={total['disk']}, Network={total['net']}")


def _run_sar_on_binary_sa(conn, case_id, root):
    """Fallback parser using the normal sar command against binary saXX files.

    Many sosreports contain only var/log/sa/saXX binary sysstat files. If the
    server can run `sar -u -f <saXX>`, then the app should parse the same output
    and visualize it. This fallback is intentionally separate from sadf because
    some environments have sar installed but sadf parsing/output differs by
    sysstat version.
    """
    sar = shutil.which('sar')
    if not sar:
        insert_fact(conn, case_id, 'SAR Graphs', 'sar Status', 'sar command not found. Install sysstat to parse binary /var/log/sa/saXX files with sar -f.')
        return {'cpu':0,'mem':0,'disk':0,'net':0}

    sa_files = []
    for pattern in ('sa[0-9][0-9]', 'sa[0-9][0-9][0-9]'):
        for p in Path(root).rglob(pattern):
            if p.is_file() and p.name.startswith('sa') and not p.name.startswith('sar'):
                sa_files.append(p)

    total = {'cpu': 0, 'mem': 0, 'disk': 0, 'net': 0}
    seen = set()
    for sa in sorted(sa_files)[:62]:
        if sa in seen:
            continue
        seen.add(sa)
        commands = {
            'cpu': [sar, '-u', '-f', str(sa)],
            'mem': [sar, '-r', '-S', '-f', str(sa)],
            'disk': [sar, '-d', '-p', '-f', str(sa)],
            'net': [sar, '-n', 'DEV', '-f', str(sa)],
        }
        for kind, cmd in commands.items():
            try:
                r = subprocess.run(
                    cmd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=90,
                    check=False,
                    env={**os.environ, 'S_TIME_FORMAT': 'ISO'},
                )
                if r.stdout:
                    ins = _parse_sar_text(conn, case_id, r.stdout)
                    # _parse_sar_text may return rows for multiple modes if sar output contains multiple sections.
                    for k in total:
                        total[k] += ins.get(k, 0)
            except Exception:
                continue

    insert_fact(conn, case_id, 'SAR Graphs', 'Binary sa files parsed by sar', f"CPU={total['cpu']}, Memory={total['mem']}, Disk={total['disk']}, Network={total['net']}")
    return total

def parse_sar_all(conn, case_id, root):
    """Parse SAR data from readable text first, then binary saXX files via sadf if available."""
    sar_files = find_all(root, [
        "sos_commands/sar/sar*", "sos_commands/sysstat/sar*",
        "var/log/sa/sar*", "sar*",
    ])
    totals = {"cpu": 0, "mem": 0, "disk": 0, "net": 0}
    for sar_file in sar_files:
        # Skip likely binary sa files here. They are handled by sadf below.
        if re.fullmatch(r"sa\d{2,3}", Path(sar_file).name):
            continue
        text = read_text(sar_file)
        ins = _parse_sar_text(conn, case_id, text)
        for k, v in ins.items():
            totals[k] += v

    # Always try binary saXX files too; many sosreports only contain these.
    # Try both sadf and sar because sysstat output/availability differs by OS/version.
    sadf_totals = _run_sadf_on_binary_sa(conn, case_id, root) or {'cpu':0,'mem':0,'disk':0,'net':0}
    if sadf_totals.get('cpu', 0) == 0:
        _run_sar_on_binary_sa(conn, case_id, root)
    insert_fact(conn, case_id, "SAR Graphs", "Text SAR rows parsed", f"CPU={totals['cpu']}, Memory={totals['mem']}, Disk={totals['disk']}, Network={totals['net']}")

def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def parse_xsos_summary(conn, case_id, root):
    """Run xsos against the real extracted sosreport root.

    xsos often prints useful output even when it returns non-zero because some
    optional files are missing. Therefore we store stdout when it exists and
    store warnings separately instead of treating all non-zero exits as failure.
    """
    xsos_path = shutil.which("xsos")
    if not xsos_path:
        insert_fact(conn, case_id, "Summary", "Summary Status", "xsos command was not found on this server. Install xsos, then upload/parse the sosreport again to generate this page.")
        insert_fact(conn, case_id, "Summary", "Suggested Command", f"xsos -a {root}")
        return

    attempts = [
        [xsos_path, "-a", str(root)],
        [xsos_path, "--all", str(root)],
    ]
    last_error = ""
    for cmd in attempts:
        try:
            result = subprocess.run(cmd, cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False)
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if output:
                insert_fact(conn, case_id, "Summary", "Summary Status", "Generated using: " + " ".join(cmd) + f" (exit code {result.returncode})")
                insert_fact(conn, case_id, "Summary", "xsos output", output[:80000])
                if error:
                    insert_fact(conn, case_id, "Summary", "xsos warnings", error[:10000])
                return
            last_error = error or f"xsos exited with code {result.returncode} and no stdout"
        except Exception as exc:
            last_error = str(exc)

    insert_fact(conn, case_id, "Summary", "Summary Status", "xsos was found, but no usable stdout was produced.")
    insert_fact(conn, case_id, "Summary", "xsos Error", last_error[:10000])
    insert_fact(conn, case_id, "Summary", "Suggested Command", f"xsos -a {root}")

def analyze(archive_path, case_label=""):
    case_id, extracted_path = extract_archive(archive_path, case_label)
    with connect_db() as conn:
        conn.execute("INSERT INTO cases(case_id, filename, extracted_path, created_at, last_opened_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (case_id, os.path.basename(archive_path), str(extracted_path)))
        parse_xsos_summary(conn, case_id, extracted_path)
        parse_system_identity(conn, case_id, extracted_path)
        parse_hardware(conn, case_id, extracted_path)
        parse_messages(conn, case_id, extracted_path)
        parse_dmesg(conn, case_id, extracted_path)
        parse_kernel_logs(conn, case_id, extracted_path)
        parse_services(conn, case_id, extracted_path)
        parse_network(conn, case_id, extracted_path)
        parse_storage(conn, case_id, extracted_path)
        parse_sar_all(conn, case_id, extracted_path)
    return case_id
