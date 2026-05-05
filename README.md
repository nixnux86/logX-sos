# SOS Insight Flask

Python + Flask-only web app for sosreport analysis and troubleshooting.

## v4 highlights

- Bootstrap Icons in the compact collapsible left sidebar.
- SAR graph cards are clickable and open a larger modal chart.
- Modal chart supports Download PNG, Download JPG, Reset Zoom, and Close.
- Upload dialog supports drag and drop plus optional Case name / alias.
- Generated case IDs can include the alias, for example: `case_CASEID_20260502_123716_96b8b38d`.
- Recent Files page has Open and Delete actions.
- Top header shrinks when the content section is scrolled vertically.

## Install

```bash
cd /var/www/html
unzip sosinsight-flask-enhanced-v4.zip
cd sosinsight-flask

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python init_db.py
python app.py
```

Open:

```text
http://SERVER-IP:5000
```

## Optional tools

For SAR binary `saXX` parsing:

```bash
sudo apt install -y sysstat
```

For Summary page:

```bash
# install xsos, then re-upload/re-parse the sosreport
xsos -a /path/to/extracted/sosreport-root
```


## v5 UI improvements

- Dashboard card layout refined with smaller meta text, smaller proportional cards, hover effects, and page footer.
- Existing Dashboard troubleshooting layout remains under the Troubleshooting menu, with recommendations shown before raw evidence.
- Topbar now uses a dynamic colorful wave-style background and still shrinks while scrolling.
- Summary xsos output now preserves ANSI color formatting in the browser.
- System Identity and Hardware were merged into a single System Information menu with two-column cards.

## v7 UI updates
- Brand icon uses the supplied logX scanline image.
- Brand icon spins when the sidebar is collapsed.
- Upload sosreport menu moved below Recent Files with a dashed separator.
- Summary page simplified to show SOSREPORT Summary and xsos output directly.
- Dmesg menu removed from the sidebar.

## v12 notes

- Added missing `import os` for the Console environment.
- Messages and Dmesg preserve raw log text. Keyword highlighting is disabled to avoid modifying displayed log entries.
- Console Tab auto-completion is available for common commands and files/directories inside the extracted sosreport root.
- `more` and `less` are rendered as plain output through `cat` because this browser console is a safe command-runner, not a full PTY/TTY session.
- A true native terminal requires a WebSocket PTY backend such as `xterm.js` + `ptyprocess`/`pexpect` and should only be enabled with strong authentication and command restrictions.

## v13 notes

- SAR binary parsing now tries both `sadf` and `sar -f`. If CPU charts were empty while `sar -u -f extracted/.../var/log/sa/saXX` worked manually, re-upload/re-parse the case after installing `sysstat` so the parser can populate `sar_cpu` rows.
- Console working directory display is shortened to `.../extracted/<case>/<sosreport-root>`.
- Messages pagination now uses more lines per page and a tighter log layout to reduce blank space.

## v16 updates

- Fixed process snapshot fallback so Top CPU/MEM tables can be built from stored `xsos -a` output when the raw `ps_aux` file path differs between sosreport versions.
- Refined Dashboard system card typography and vertical centering.
- Removed console `exit 0`/return-code tags from the UI output.
- Tightened Console path helper line spacing.
- Retained upload drop-zone progress and selected archive icon behavior.

Suggested next Dashboard cards:
- Critical/Warning Findings
- Failed Services
- Filesystems >=80%
- OOM/MCE/Hardware Alerts
- Network Link-down Events
- Recent Log Error Trend


## v16 changes
- Smaller modern case label typography in the sticky topbar.
- Dashboard metadata now appears as a compact single-line card.
- Added a System Info section title above dashboard system cards.
- Renamed the first dashboard card to OS Version.
- Dashboard cards now use top-aligned headings with centered main values.
- Main/content height now uses dynamic viewport units to reduce unnecessary vertical scrolling.

## v19 changes
- Upload modal now resets drop-zone/progress state on every open/close and after successful upload.
- SAR chart cards show a compact no-data illustration instead of a large blank chart when data is unavailable.
- Fact labels in System Information, Network, and Storage are lighter and smaller.
- Console working-directory helper spacing is tighter.
- Dashboard OS card spacing refined.


## v19 updates
- Refined dashboard System Info title/meta positioning.
- Rebalanced dashboard cards with top-left headings and centered values.
- Switched base typography to Inter and reduced heavy font weights.
- Adjusted fact-key labels to medium weight and larger size.
- Redesigned troubleshooting finding cards with cleaner UI.
