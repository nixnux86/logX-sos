# logX sos

**logX sos** is a web-based sosreport analysis tool built with **Python + Flask**.  
It helps Linux administrators and support engineers upload, parse, review, and troubleshoot Linux sosreport bundles from a modern browser UI.

---

## Description

logX sos extracts useful information from a sosreport archive, stores parsed data in SQLite, and presents it through structured pages such as Dashboard, Summary, System Information, Messages, Dmesg, Network, Storage, Console, and Recent Files.

Supported sosreport archive formats:

- `.tar`
- `.tar.xz`
- `.tgz`
- `.tar.gz`
- `.tar.bz2`

The main goal is to make sosreport analysis faster by combining system facts, logs, SAR graphs, process snapshots, and troubleshooting findings in one web interface.

---

## Main Features

### Upload Sosreport

- Upload sosreport files from a modal popup.
- Supports drag-and-drop.
- Optional case name / alias.
- Upload and parsing progress shown inside the drop zone.
- Automatically generates a case ID.
- If no sosreport exists, the app opens the Dashboard and shows the upload modal.

Example case ID:

```text
case_PROD-DB01_20260503_100220_00a3a051
```

### Dashboard

The Dashboard provides a visual overview of the selected sosreport.

It includes:

- System metadata
- OS Version
- CPU Usage
- Memory Usage
- Disk Usage
- SAR graphs
- Process Snapshot

SAR graphs are shown in a 2x2 layout:

- CPU Usage
- Memory Usage
- Disk Throughput
- Network Throughput

Each graph can be opened in a modal view with Download PNG, Download JPG, Reset Zoom, and Close actions.

If no SAR data is available, a compact “No data available” placeholder is shown.

### SOSREPORT Summary

The Summary page displays `xsos` output when `xsos` is installed.

The app attempts to run:

```bash
xsos -a
```

or:

```bash
xsos --all
```

ANSI colors from `xsos` are preserved in the browser.

### Troubleshooting

The Troubleshooting page lists detected issues and recommendations.

Example findings:

- OOM killer events
- Kernel panic / BUG / Oops traces
- MCE / hardware errors
- SELinux denials
- Failed systemd services
- High filesystem usage
- Storage I/O errors
- Network link-down events

Each finding includes severity, module, recommendation, and supporting evidence.

### System Information

The System Information page combines:

- System Identity
- Hardware
- Kernel & Logs
- Services

Example data:

- Hostname
- Kernel version
- OS release
- Hardware model
- Serial number
- CPU threads
- RAM total
- Swap usage
- DIMM slots
- PCIe NICs
- PCIe HBAs / storage controllers
- Failed systemd units
- Top memory consumers

### Messages

The Messages page provides a compact log viewer for `/var/log/messages` or equivalent logs.

Features:

- Search bar
- Clear search button
- Clear with `Esc`
- Pagination
- Filter buttons with counters:
  - Total Lines
  - Errors
  - Warnings
  - Failed
  - Info
- Raw log text is preserved.

### Dmesg

The Dmesg page displays kernel ring buffer logs from the sosreport.

Features:

- Search bar
- Clear search button
- Clear with `Esc`
- Compact line display
- Original formatting is preserved as much as possible.

### Network

The Network page shows:

- Interface addresses
- Interface state
- Route table
- Listening ports
- Link-down events

### Storage

The Storage page shows:

- Disk usage
- Mount points
- LVM PV/VG/LV
- Multipath information
- Filesystems above threshold
- I/O errors

### Console

The Console page provides a lightweight web command runner inside the extracted sosreport directory.

Features:

- Default working directory is the extracted sosreport root.
- Persistent `cd`.
- `pwd` support.
- `clear` and `Ctrl+L` support.
- Command history with `↑` and `↓`.
- Basic tab auto-completion.
- Shortened prompt path.

Example commands:

```bash
pwd
ls -la
find . -maxdepth 3 -type f | head
cat etc/redhat-release
ls var/log
ls var/log/sa
sar -u -f var/log/sa/sa01
```

Note: this console is not a full native interactive terminal. A full terminal would require a PTY backend and WebSocket frontend such as `xterm.js`.

### Recent Files

The Recent Files page allows you to:

- View recent sosreport cases.
- Open a case.
- Delete a case.

---

## Requirements

### Required

- Linux server
- Python 3
- Python venv
- pip
- SQLite3
- tar / gzip / xz / bzip2 utilities

For Ubuntu / Debian:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 tar xz-utils bzip2 gzip
```

For RHEL / Rocky / AlmaLinux:

```bash
sudo dnf install -y python3 python3-pip sqlite sqlite-devel tar xz bzip2 gzip
```

### Optional but Recommended

For SAR parsing:

```bash
sudo apt install -y sysstat
```

or:

```bash
sudo dnf install -y sysstat
```

This provides:

```bash
sar
sadf
```

For Summary page output:

```bash
xsos
```

---

## Installation

### 1. Extract the project

```bash
unzip logX-sos-v1.zip
cd logX-sos-v1
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Initialize database

```bash
python init_db.py
```

### 5. Run the application

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

For remote access, configure the app to bind to:

```python
host="0.0.0.0"
```

Then open:

```text
http://SERVER-IP:5000
```

---

## Production Note

For production or shared usage, run behind a proper web server or process manager such as:

- Nginx
- Apache reverse proxy
- Gunicorn
- systemd

Example:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Directory Structure

```text
logX-sos/
├── app.py
├── init_db.py
├── requirements.txt
├── README.md
├── parser/
│   ├── __init__.py
│   └── analyzer.py
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   ├── style.css
│   └── logx-icon-scanlines.jpeg
├── uploads/
├── extracted/
└── logX.db
```

---

## SAR Notes

Many sosreports contain SAR files under:

```text
var/log/sa/saXX
```

Manual test:

```bash
sar -u -f var/log/sa/saXX
```

If charts are not shown, make sure `sysstat` is installed on the server running SOSInsight.

---

## Security Notes

The Console feature executes commands on the server inside the extracted sosreport directory.

Recommended precautions:

- Use only in a trusted internal network.
- Do not expose publicly without authentication.
- Do not run the app as root.
- Use a dedicated Linux user.
- Add authentication before production use.
- Consider command allow-listing for multi-user environments.

---

## Project Identity

```text
logX sos tool v1.0
© 2026 – ideas by nixnux
```
