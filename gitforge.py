#!/usr/bin/env python3
"""
GitForge - Complete GitHub Repository Manager
Clone, sync, backup, search, and manage all your GitHub repos from one tool.
"""

import sys, os, subprocess, json, shutil, zipfile, glob, fnmatch
from pathlib import Path


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


def _bootstrap():
    """Auto-install dependencies before any other imports."""
    if sys.version_info < (3, 8):
        print("Python 3.8+ required"); sys.exit(1)
    try:
        import pip
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'ensurepip', '--default-pip'])
    required = ['PyQt6', 'requests']
    for pkg in required:
        try:
            __import__(pkg.split('[')[0].replace('-', '_').lower())
        except ImportError:
            for flags in [[], ['--user'], ['--break-system-packages']]:
                try:
                    subprocess.check_call(
                        [sys.executable, '-m', 'pip', 'install', pkg, '-q'] + flags,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except subprocess.CalledProcessError:
                    continue

_bootstrap()

import traceback, ctypes, re, time, threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QProgressBar,
    QTextEdit, QPlainTextEdit, QCheckBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QSplitter, QFrame,
    QTabWidget, QComboBox, QSpinBox, QToolButton, QStatusBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QTextCursor, QIcon

# ═══════════════════════════════════════════════════════════════════════════════
# CRASH LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
def exception_handler(exc_type, exc_value, exc_tb):
    msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    crash_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log')
    with open(crash_file, 'w') as f:
        f.write(msg)
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(0, f"Crash log: {crash_file}\n\n{msg[:500]}", "Fatal Error", 0x10)
    sys.exit(1)

sys.excepthook = exception_handler

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════
APP_NAME = "GitForge"

def get_config_dir():
    base = os.environ.get('APPDATA', os.path.expanduser('~'))
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path

def load_config():
    cfg_file = os.path.join(get_config_dir(), 'config.json')
    try:
        with open(cfg_file) as f: return json.load(f)
    except: return {}

def save_config(cfg):
    cfg_file = os.path.join(get_config_dir(), 'config.json')
    with open(cfg_file, 'w') as f: json.dump(cfg, f, indent=2)

# ═══════════════════════════════════════════════════════════════════════════════
# GIT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════
def find_git():
    """Locate git executable across PATH, GitHub Desktop, and common installs."""
    git_on_path = shutil.which("git")
    if git_on_path:
        return git_on_path
    if sys.platform != 'win32':
        return None

    candidates = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    userprofile = os.environ.get("USERPROFILE", "")

    # GitHub Desktop bundled git
    if local_app:
        ghd_base = os.path.join(local_app, "GitHubDesktop")
        if os.path.isdir(ghd_base):
            for entry in sorted(os.listdir(ghd_base), reverse=True):
                if entry.startswith("app-"):
                    for sub in ["resources/app/git/cmd/git.exe", "resources/app/git/mingw64/bin/git.exe"]:
                        c = os.path.join(ghd_base, entry, sub.replace("/", os.sep))
                        if os.path.isfile(c):
                            candidates.append(c)

    # Standard Git for Windows
    for base in [prog_files, prog_x86]:
        for sub in ["Git/cmd/git.exe", "Git/bin/git.exe", "Git/mingw64/bin/git.exe"]:
            c = os.path.join(base, sub.replace("/", os.sep))
            if os.path.isfile(c):
                candidates.append(c)

    # Scoop
    scoop_git = os.path.join(userprofile, "scoop", "shims", "git.exe")
    if os.path.isfile(scoop_git):
        candidates.append(scoop_git)

    for c in candidates:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return c
        except:
            continue
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# GITHUB API HELPER
# ═══════════════════════════════════════════════════════════════════════════════
class GitHubAPI:
    """Centralized GitHub API access."""
    BASE = "https://api.github.com"

    def __init__(self, username="", token=""):
        self.username = username
        self.token = token

    @property
    def headers(self):
        h = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    def get(self, path, params=None):
        resp = requests.get(f"{self.BASE}{path}", headers=self.headers, params=params, timeout=30)
        return resp

    def patch(self, path, data):
        resp = requests.patch(f"{self.BASE}{path}", headers=self.headers, json=data, timeout=30)
        return resp

    def post(self, path, data):
        resp = requests.post(f"{self.BASE}{path}", headers=self.headers, json=data, timeout=30)
        return resp

    def delete(self, path):
        resp = requests.delete(f"{self.BASE}{path}", headers=self.headers, timeout=30)
        return resp

    def fetch_all_repos(self, log_cb=None):
        repos = []
        page = 1
        if self.token:
            base_path = "/user/repos"
            params_base = {"per_page": 100, "affiliation": "owner"}
        else:
            base_path = f"/users/{self.username}/repos"
            params_base = {"per_page": 100}

        while True:
            params = {**params_base, "page": page}
            if log_cb: log_cb(f"Fetching page {page}...")
            resp = self.get(base_path, params)
            if resp.status_code == 401:
                raise Exception("Authentication failed. Check your token.")
            if resp.status_code == 403:
                raise Exception("Rate limited by GitHub. Try later or add a token.")
            if resp.status_code != 200:
                raise Exception(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            if not data: break
            for r in data:
                repos.append({
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "description": r.get("description") or "",
                    "private": r["private"],
                    "fork": r["fork"],
                    "archived": r.get("archived", False),
                    "clone_url": r["clone_url"],
                    "ssh_url": r["ssh_url"],
                    "html_url": r["html_url"],
                    "size": r.get("size", 0),
                    "language": r.get("language") or "",
                    "updated_at": r.get("updated_at", ""),
                    "pushed_at": r.get("pushed_at", ""),
                    "default_branch": r.get("default_branch", "main"),
                    "stargazers_count": r.get("stargazers_count", 0),
                    "forks_count": r.get("forks_count", 0),
                    "open_issues_count": r.get("open_issues_count", 0),
                    "topics": r.get("topics", []),
                    "has_wiki": r.get("has_wiki", False),
                    "has_issues": r.get("has_issues", True),
                })
            if len(data) < 100: break
            page += 1
        return repos


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER THREADS
# ═══════════════════════════════════════════════════════════════════════════════
class GenericWorker(QThread):
    """Runs any callable in a background thread with progress/log signals."""
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, progress_cb=self.progress.emit, log_cb=self.log.emit, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# DARK THEME
# ═══════════════════════════════════════════════════════════════════════════════
DARK_STYLE = """
QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; }
QTabWidget::pane {
    border: 1px solid #45475a; background: #1e1e2e;
    border-radius: 4px; margin-top: -1px;
}
QTabBar::tab {
    background: #181825; color: #6c7086; padding: 10px 20px;
    border: 1px solid #45475a; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px; font-weight: bold;
}
QTabBar::tab:selected {
    color: #89b4fa; background: #1e1e2e;
    border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover:!selected { color: #a6adc8; background: #313244; }
QPushButton {
    background-color: #89b4fa; color: #1e1e2e; border: none;
    padding: 8px 16px; border-radius: 6px; font-weight: bold;
}
QPushButton:hover { background-color: #74c7ec; }
QPushButton:pressed { background-color: #89dceb; }
QPushButton:disabled { background-color: #45475a; color: #6c7086; }
QPushButton[class="danger"] { background-color: #f38ba8; color: #1e1e2e; }
QPushButton[class="danger"]:hover { background-color: #eba0ac; }
QPushButton[class="success"] { background-color: #a6e3a1; color: #1e1e2e; }
QPushButton[class="success"]:hover { background-color: #94e2d5; }
QPushButton[class="secondary"] { background-color: #45475a; color: #cdd6f4; }
QPushButton[class="secondary"]:hover { background-color: #585b70; }
QPushButton[class="warning"] { background-color: #fab387; color: #1e1e2e; }
QPushButton[class="warning"]:hover { background-color: #f9e2af; }
QPushButton[class="small"] { padding: 4px 10px; font-size: 11px; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 6px;
    selection-background-color: #89b4fa; selection-color: #1e1e2e;
}
QComboBox {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 4px; padding: 6px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1e1e2e; color: #cdd6f4;
    border: 1px solid #45475a; selection-background-color: #89b4fa;
}
QGroupBox {
    border: 1px solid #45475a; border-radius: 8px;
    margin-top: 1em; padding-top: 10px; color: #cdd6f4; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QProgressBar {
    background-color: #313244; border: none; border-radius: 4px;
    text-align: center; color: #cdd6f4; min-height: 22px;
}
QProgressBar::chunk { background-color: #a6e3a1; border-radius: 4px; }
QCheckBox { spacing: 6px; color: #cdd6f4; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid #45475a; background-color: #313244;
}
QCheckBox::indicator:checked { background-color: #89b4fa; border-color: #89b4fa; }
QCheckBox::indicator:hover { border-color: #89b4fa; }
QHeaderView::section {
    background-color: #181825; color: #a6adc8;
    border: none; border-bottom: 2px solid #45475a;
    padding: 6px 10px; font-weight: bold;
}
QTableWidget {
    background-color: #1e1e2e; alternate-background-color: #181825;
    color: #cdd6f4; border: 1px solid #45475a;
    gridline-color: #313244; border-radius: 6px;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background-color: #313244; color: #cdd6f4; }
QScrollBar:vertical { background: #181825; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #181825; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #45475a; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #585b70; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel[class="title"] { font-size: 16px; font-weight: bold; color: #89b4fa; }
QLabel[class="subtitle"] { color: #6c7086; font-size: 11px; }
QLabel[class="ok"] { color: #a6e3a1; }
QLabel[class="warn"] { color: #fab387; }
QLabel[class="err"] { color: #f38ba8; }
QLabel[class="stat-value"] { font-size: 22px; font-weight: bold; color: #89b4fa; }
QLabel[class="stat-label"] { color: #6c7086; font-size: 11px; }
QSplitter::handle { background: #45475a; height: 2px; }
QStatusBar { background-color: #181825; color: #6c7086; }
QFrame[class="card"] {
    background-color: #181825; border: 1px solid #45475a;
    border-radius: 8px; padding: 12px;
}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Styled table with checkboxes
# ═══════════════════════════════════════════════════════════════════════════════
def make_table(columns, checkbox_col=None):
    t = QTableWidget()
    t.setColumnCount(len(columns))
    t.setHorizontalHeaderLabels([c[0] for c in columns])
    for i, (_, width, mode) in enumerate(columns):
        if mode == "stretch":
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        else:
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            t.setColumnWidth(i, width)
    t.setAlternatingRowColors(True)
    t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return t

def add_checkbox_to_table(table, row, col, checked=True):
    chk = QCheckBox()
    chk.setChecked(checked)
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.addWidget(chk)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.setContentsMargins(0, 0, 0, 0)
    table.setCellWidget(row, col, w)
    return chk

def get_table_checkbox(table, row, col):
    w = table.cellWidget(row, col)
    if w:
        return w.findChild(QCheckBox)
    return None

def format_size(size_kb):
    if size_kb >= 1048576:
        return f"{size_kb / 1048576:.1f} GB"
    elif size_kb >= 1024:
        return f"{size_kb / 1024:.1f} MB"
    return f"{size_kb} KB"


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: CLONE
# ═══════════════════════════════════════════════════════════════════════════════
class CloneTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.repos = []
        self.worker = None
        self.clone_worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Fetch controls
        row = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch Repos from GitHub")
        self.fetch_btn.clicked.connect(self.fetch_repos)
        row.addWidget(self.fetch_btn)
        row.addSpacing(10)
        self.ssh_check = QCheckBox("Use SSH URLs")
        row.addWidget(self.ssh_check)
        self.include_forks = QCheckBox("Include Forks")
        self.include_forks.setChecked(True)
        row.addWidget(self.include_forks)
        row.addStretch()
        self.count_label = QLabel("No repositories loaded")
        self.count_label.setProperty("class", "subtitle")
        row.addWidget(self.count_label)
        layout.addLayout(row)

        # Table
        self.table = make_table([
            ("", 40, "fixed"), ("Repository", 0, "stretch"), ("Language", 90, "fixed"),
            ("Size", 80, "fixed"), ("Updated", 100, "fixed"), ("Status", 90, "fixed")
        ])
        layout.addWidget(self.table, 1)

        # Action row
        actions = QHBoxLayout()
        sel_btn = QPushButton("Select All")
        sel_btn.setProperty("class", "secondary")
        sel_btn.setFixedWidth(90)
        sel_btn.clicked.connect(lambda: self.toggle_all(True))
        actions.addWidget(sel_btn)
        desel_btn = QPushButton("Deselect All")
        desel_btn.setProperty("class", "secondary")
        desel_btn.setFixedWidth(100)
        desel_btn.clicked.connect(lambda: self.toggle_all(False))
        actions.addWidget(desel_btn)
        actions.addStretch()

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m repos")
        self.progress.setValue(0)
        self.progress.setMaximum(1)
        self.progress.setFixedWidth(300)
        actions.addWidget(self.progress)

        self.clone_btn = QPushButton("Clone Selected")
        self.clone_btn.setProperty("class", "success")
        self.clone_btn.setEnabled(False)
        self.clone_btn.clicked.connect(self.start_cloning)
        actions.addWidget(self.clone_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("class", "danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_btn)
        layout.addLayout(actions)

    def log(self, msg):
        self.log_signal.emit(msg)

    def fetch_repos(self):
        if not self.app.username:
            QMessageBox.warning(self, "Setup Required", "Set your GitHub username in the Settings tab.")
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        self.clone_btn.setEnabled(False)
        self.table.setRowCount(0)

        def do_fetch(progress_cb, log_cb):
            api = GitHubAPI(self.app.username, self.app.token)
            return api.fetch_all_repos(log_cb)

        self.worker = GenericWorker(do_fetch)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._on_fetched)
        self.worker.error.connect(self._on_fetch_err)
        self.worker.start()

    def _on_fetched(self, repos):
        if not self.include_forks.isChecked():
            repos = [r for r in repos if not r["fork"]]
        self.repos = sorted(repos, key=lambda r: r["name"].lower())
        self.app.repos_cache = self.repos
        self.populate_table()
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch Repos from GitHub")
        self.clone_btn.setEnabled(len(self.repos) > 0)
        self.count_label.setText(f"{len(self.repos)} repositories")
        self.log(f"Found {len(self.repos)} repositories")

    def _on_fetch_err(self, err):
        self.log(f"ERROR: {err}")
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch Repos from GitHub")
        QMessageBox.critical(self, "Fetch Error", err)

    def populate_table(self):
        self.table.setRowCount(len(self.repos))
        for i, r in enumerate(self.repos):
            add_checkbox_to_table(self.table, i, 0, True)
            name = r["name"]
            if r["private"]: name += "  [private]"
            if r["fork"]: name += "  [fork]"
            if r["archived"]: name += "  [archived]"
            item = QTableWidgetItem(name)
            if r["description"]: item.setToolTip(r["description"])
            self.table.setItem(i, 1, item)
            self.table.setItem(i, 2, QTableWidgetItem(r["language"]))
            si = QTableWidgetItem(format_size(r["size"]))
            si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 3, si)
            self.table.setItem(i, 4, QTableWidgetItem(r["updated_at"][:10] if r["updated_at"] else ""))
            st = QTableWidgetItem("--")
            st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 5, st)

    def toggle_all(self, state):
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk: chk.setChecked(state)

    def get_selected(self):
        sel = []
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk and chk.isChecked():
                sel.append(self.repos[i])
        return sel

    def start_cloning(self):
        if not self.app.git_exe:
            QMessageBox.critical(self, "Git Not Found", "Git not found. Check Settings tab.")
            return
        dest = self.app.repos_dir
        if not dest:
            QMessageBox.warning(self, "No Destination", "Set a repos folder in the Settings tab.")
            return
        selected = self.get_selected()
        if not selected:
            QMessageBox.warning(self, "Nothing Selected", "Select at least one repository.")
            return

        os.makedirs(dest, exist_ok=True)
        self.clone_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setMaximum(len(selected))
        self.progress.setValue(0)
        use_ssh = self.ssh_check.isChecked()
        git = self.app.git_exe
        self._cancelled = False

        def do_clone(progress_cb, log_cb):
            stats = {"cloned": 0, "updated": 0, "errors": 0}
            total = len(selected)
            for i, repo in enumerate(selected):
                if self._cancelled: break
                name = repo["name"]
                url = repo["ssh_url"] if use_ssh else repo["clone_url"]
                rpath = os.path.join(dest, name)
                progress_cb(i, total)
                try:
                    if os.path.isdir(os.path.join(rpath, ".git")):
                        log_cb(f"[{i+1}/{total}] Pulling {name}...")
                        r = subprocess.run([git, "-C", rpath, "pull", "--ff-only"],
                                           capture_output=True, text=True, timeout=120)
                        if r.returncode == 0:
                            stats["updated"] += 1
                            self._set_status(name, "Updated", "#89b4fa")
                        else:
                            stats["errors"] += 1
                            self._set_status(name, "Error", "#f38ba8")
                            log_cb(f"  -> {r.stderr.strip()}")
                    else:
                        log_cb(f"[{i+1}/{total}] Cloning {name}...")
                        r = subprocess.run([git, "clone", url, rpath],
                                           capture_output=True, text=True, timeout=300)
                        if r.returncode == 0:
                            stats["cloned"] += 1
                            self._set_status(name, "Cloned", "#a6e3a1")
                        else:
                            stats["errors"] += 1
                            self._set_status(name, "Error", "#f38ba8")
                            log_cb(f"  -> {r.stderr.strip()}")
                except subprocess.TimeoutExpired:
                    stats["errors"] += 1
                    self._set_status(name, "Timeout", "#f38ba8")
                except Exception as e:
                    stats["errors"] += 1
                    log_cb(f"  -> {e}")
            progress_cb(total, total)
            return stats

        self.clone_worker = GenericWorker(do_clone)
        self.clone_worker.progress.connect(lambda c, t: self.progress.setValue(c))
        self.clone_worker.log.connect(self.log)
        self.clone_worker.finished.connect(self._on_clone_done)
        self.clone_worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.clone_worker.start()

    def _set_status(self, name, text, color):
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 1)
            if item and item.text().startswith(name):
                si = self.table.item(i, 5)
                if si:
                    si.setText(text)
                    si.setForeground(QColor(color))
                break

    def _on_clone_done(self, stats):
        self.clone_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        msg = f"Cloned: {stats['cloned']}, Updated: {stats['updated']}, Errors: {stats['errors']}"
        self.log(f"Done! {msg}")
        QMessageBox.information(self, "Complete", msg)

    def cancel(self):
        self._cancelled = True
        self.cancel_btn.setEnabled(False)
        self.log("Cancelling...")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: SYNC STATUS
# ═══════════════════════════════════════════════════════════════════════════════
class SyncTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.local_repos = []
        self.worker = None
        self._cancelled = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Local Repos")
        self.scan_btn.clicked.connect(self.scan_repos)
        row.addWidget(self.scan_btn)
        row.addSpacing(10)
        self.count_label = QLabel("Scan your repos folder to see sync status")
        self.count_label.setProperty("class", "subtitle")
        row.addWidget(self.count_label)
        row.addStretch()
        layout.addLayout(row)

        self.table = make_table([
            ("", 40, "fixed"), ("Repository", 0, "stretch"), ("Branch", 100, "fixed"),
            ("Status", 130, "fixed"), ("Ahead", 60, "fixed"), ("Behind", 60, "fixed"),
            ("Dirty", 60, "fixed"), ("Last Commit", 140, "fixed"),
        ])
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        sel_btn = QPushButton("Select All")
        sel_btn.setProperty("class", "secondary")
        sel_btn.setFixedWidth(90)
        sel_btn.clicked.connect(lambda: self._toggle(True))
        actions.addWidget(sel_btn)
        desel_btn = QPushButton("Deselect All")
        desel_btn.setProperty("class", "secondary")
        desel_btn.setFixedWidth(100)
        desel_btn.clicked.connect(lambda: self._toggle(False))
        actions.addWidget(desel_btn)
        actions.addStretch()

        self.progress = QProgressBar()
        self.progress.setFixedWidth(250)
        self.progress.setValue(0)
        self.progress.setMaximum(1)
        actions.addWidget(self.progress)

        fetch_btn = QPushButton("Fetch All")
        fetch_btn.setProperty("class", "secondary")
        fetch_btn.clicked.connect(lambda: self._bulk_action("fetch"))
        actions.addWidget(fetch_btn)

        pull_btn = QPushButton("Pull Selected")
        pull_btn.setProperty("class", "success")
        pull_btn.clicked.connect(lambda: self._bulk_action("pull"))
        actions.addWidget(pull_btn)

        gc_btn = QPushButton("GC Selected")
        gc_btn.setProperty("class", "warning")
        gc_btn.clicked.connect(lambda: self._bulk_action("gc"))
        actions.addWidget(gc_btn)
        layout.addLayout(actions)

    def log(self, msg):
        self.log_signal.emit(msg)

    def scan_repos(self):
        dest = self.app.repos_dir
        if not dest or not os.path.isdir(dest):
            QMessageBox.warning(self, "No Folder", "Set a valid repos folder in Settings.")
            return
        if not self.app.git_exe:
            QMessageBox.critical(self, "Git Not Found", "Git not found. Check Settings.")
            return

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.table.setRowCount(0)
        git = self.app.git_exe

        def do_scan(progress_cb, log_cb):
            repos = []
            entries = sorted([d for d in os.listdir(dest)
                             if os.path.isdir(os.path.join(dest, d, ".git"))])
            total = len(entries)
            log_cb(f"Found {total} local repos, analyzing...")

            for i, name in enumerate(entries):
                progress_cb(i, total)
                rpath = os.path.join(dest, name)
                info = {"name": name, "path": rpath, "branch": "?", "ahead": 0, "behind": 0,
                        "dirty": 0, "status": "Unknown", "last_commit": ""}
                try:
                    # Current branch
                    r = subprocess.run([git, "-C", rpath, "rev-parse", "--abbrev-ref", "HEAD"],
                                       capture_output=True, text=True, timeout=10)
                    info["branch"] = r.stdout.strip() if r.returncode == 0 else "detached"

                    # Fetch remote info silently
                    subprocess.run([git, "-C", rpath, "fetch", "--quiet"],
                                   capture_output=True, timeout=30)

                    # Ahead/behind
                    r = subprocess.run([git, "-C", rpath, "rev-list", "--left-right", "--count",
                                        f"HEAD...@{{upstream}}"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0:
                        parts = r.stdout.strip().split()
                        if len(parts) == 2:
                            info["ahead"] = int(parts[0])
                            info["behind"] = int(parts[1])

                    # Dirty (uncommitted changes)
                    r = subprocess.run([git, "-C", rpath, "status", "--porcelain"],
                                       capture_output=True, text=True, timeout=10)
                    info["dirty"] = len([l for l in r.stdout.strip().split("\n") if l.strip()]) if r.returncode == 0 else 0

                    # Last commit date
                    r = subprocess.run([git, "-C", rpath, "log", "-1", "--format=%ci"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0 and r.stdout.strip():
                        info["last_commit"] = r.stdout.strip()[:19]

                    # Determine status
                    if info["dirty"] > 0 and info["ahead"] > 0:
                        info["status"] = "Dirty + Ahead"
                    elif info["dirty"] > 0:
                        info["status"] = "Dirty"
                    elif info["ahead"] > 0 and info["behind"] > 0:
                        info["status"] = "Diverged"
                    elif info["ahead"] > 0:
                        info["status"] = "Ahead"
                    elif info["behind"] > 0:
                        info["status"] = "Behind"
                    else:
                        info["status"] = "Up to date"

                except Exception as e:
                    info["status"] = f"Error"
                    log_cb(f"  {name}: {e}")

                repos.append(info)
            progress_cb(total, total)
            return repos

        self.worker = GenericWorker(do_scan)
        self.worker.progress.connect(lambda c, t: self.progress.setValue(c) or self.progress.setMaximum(max(t, 1)))
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._on_scanned)
        self.worker.error.connect(lambda e: (self.log(f"ERROR: {e}"), self._reset_scan_btn()))
        self.worker.start()

    def _reset_scan_btn(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan Local Repos")

    def _on_scanned(self, repos):
        self.local_repos = repos
        self._reset_scan_btn()
        self.count_label.setText(f"{len(repos)} local repositories")
        self.progress.setValue(self.progress.maximum())

        status_colors = {
            "Up to date": "#a6e3a1", "Behind": "#fab387", "Ahead": "#89b4fa",
            "Diverged": "#f38ba8", "Dirty": "#f9e2af", "Dirty + Ahead": "#f9e2af", "Error": "#f38ba8",
        }

        self.table.setRowCount(len(repos))
        for i, r in enumerate(repos):
            add_checkbox_to_table(self.table, i, 0, True)
            self.table.setItem(i, 1, QTableWidgetItem(r["name"]))
            self.table.setItem(i, 2, QTableWidgetItem(r["branch"]))

            st = QTableWidgetItem(r["status"])
            st.setForeground(QColor(status_colors.get(r["status"], "#cdd6f4")))
            st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 3, st)

            for col, key in [(4, "ahead"), (5, "behind"), (6, "dirty")]:
                val = r[key]
                item = QTableWidgetItem(str(val) if val else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if val > 0:
                    item.setForeground(QColor("#fab387" if key != "ahead" else "#89b4fa"))
                self.table.setItem(i, col, item)

            self.table.setItem(i, 7, QTableWidgetItem(r["last_commit"]))

        # Summary
        dirty = sum(1 for r in repos if r["dirty"] > 0)
        behind = sum(1 for r in repos if r["behind"] > 0)
        up = sum(1 for r in repos if r["status"] == "Up to date")
        self.log(f"Scan complete: {up} up-to-date, {behind} behind, {dirty} dirty")

    def _toggle(self, state):
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk: chk.setChecked(state)

    def _get_selected(self):
        sel = []
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk and chk.isChecked():
                sel.append(self.local_repos[i])
        return sel

    def _bulk_action(self, action):
        selected = self._get_selected()
        if not selected:
            QMessageBox.warning(self, "Nothing Selected", "Select repos first.")
            return
        git = self.app.git_exe
        if not git: return
        self._cancelled = False
        self.progress.setMaximum(len(selected))
        self.progress.setValue(0)

        cmds = {
            "fetch": lambda p: [git, "-C", p, "fetch", "--all"],
            "pull": lambda p: [git, "-C", p, "pull", "--ff-only"],
            "gc": lambda p: [git, "-C", p, "gc", "--aggressive", "--prune=now"],
        }

        def do_action(progress_cb, log_cb):
            stats = {"ok": 0, "err": 0}
            for i, repo in enumerate(selected):
                if self._cancelled: break
                progress_cb(i, len(selected))
                name = repo["name"]
                log_cb(f"[{i+1}/{len(selected)}] {action}: {name}...")
                try:
                    r = subprocess.run(cmds[action](repo["path"]),
                                       capture_output=True, text=True, timeout=180)
                    if r.returncode == 0:
                        stats["ok"] += 1
                    else:
                        stats["err"] += 1
                        log_cb(f"  -> {r.stderr.strip()[:200]}")
                except Exception as e:
                    stats["err"] += 1
                    log_cb(f"  -> {e}")
            progress_cb(len(selected), len(selected))
            return stats

        self.worker = GenericWorker(do_action)
        self.worker.progress.connect(lambda c, t: self.progress.setValue(c))
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda s: (
            self.log(f"{action.title()} complete: {s['ok']} ok, {s['err']} errors"),
            self.progress.setValue(self.progress.maximum())
        ))
        self.worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.worker.start()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: BACKUP & EXPORT
# ═══════════════════════════════════════════════════════════════════════════════
class BackupTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.worker = None
        self._cancelled = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Mirror Clone section
        mirror_group = QGroupBox("  Mirror Clone (Full Backup with all branches/tags/refs)")
        mg = QVBoxLayout(mirror_group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Backup To:"))
        self.mirror_dest = QLineEdit()
        self.mirror_dest.setPlaceholderText("Select mirror destination folder...")
        row.addWidget(self.mirror_dest, 1)
        browse = QPushButton("Browse")
        browse.setProperty("class", "secondary")
        browse.setFixedWidth(80)
        browse.clicked.connect(lambda: self._browse(self.mirror_dest))
        row.addWidget(browse)
        mg.addLayout(row)
        row2 = QHBoxLayout()
        self.mirror_btn = QPushButton("Mirror Clone All Repos")
        self.mirror_btn.setProperty("class", "success")
        self.mirror_btn.clicked.connect(self.start_mirror)
        row2.addWidget(self.mirror_btn)
        row2.addStretch()
        mg.addLayout(row2)
        layout.addWidget(mirror_group)

        # Zip Export section
        zip_group = QGroupBox("  Export Repos as ZIP Archives")
        zg = QVBoxLayout(zip_group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Export To:"))
        self.zip_dest = QLineEdit()
        self.zip_dest.setPlaceholderText("Select zip export folder...")
        row.addWidget(self.zip_dest, 1)
        browse2 = QPushButton("Browse")
        browse2.setProperty("class", "secondary")
        browse2.setFixedWidth(80)
        browse2.clicked.connect(lambda: self._browse(self.zip_dest))
        row.addWidget(browse2)
        zg.addLayout(row)
        row2 = QHBoxLayout()
        self.zip_btn = QPushButton("Zip All Local Repos")
        self.zip_btn.setProperty("class", "success")
        self.zip_btn.clicked.connect(self.start_zip)
        row2.addWidget(self.zip_btn)
        self.zip_git_check = QCheckBox("Exclude .git folder (source only)")
        self.zip_git_check.setChecked(True)
        row2.addWidget(self.zip_git_check)
        row2.addStretch()
        zg.addLayout(row2)
        layout.addWidget(zip_group)

        # Cleanup section
        clean_group = QGroupBox("  Cleanup & Maintenance")
        cg = QVBoxLayout(clean_group)
        row = QHBoxLayout()
        self.orphan_btn = QPushButton("Find Orphaned Local Repos")
        self.orphan_btn.setToolTip("Find repos that exist locally but were deleted from GitHub")
        self.orphan_btn.clicked.connect(self.find_orphans)
        row.addWidget(self.orphan_btn)
        row.addSpacing(10)
        self.bulk_gc_btn = QPushButton("Bulk Git GC (All Repos)")
        self.bulk_gc_btn.setProperty("class", "warning")
        self.bulk_gc_btn.clicked.connect(self.bulk_gc)
        row.addWidget(self.bulk_gc_btn)
        row.addStretch()
        cg.addLayout(row)
        layout.addWidget(clean_group)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setMaximum(1)
        layout.addWidget(self.progress)
        layout.addStretch()

    def log(self, msg):
        self.log_signal.emit(msg)

    def _browse(self, field):
        f = QFileDialog.getExistingDirectory(self, "Select Folder")
        if f: field.setText(f)

    def start_mirror(self):
        dest = self.mirror_dest.text().strip()
        if not dest:
            QMessageBox.warning(self, "No Destination", "Select a mirror destination.")
            return
        if not self.app.username:
            QMessageBox.warning(self, "Setup", "Set username in Settings.")
            return
        git = self.app.git_exe
        if not git: return
        os.makedirs(dest, exist_ok=True)
        self.mirror_btn.setEnabled(False)
        self._cancelled = False

        def do_mirror(progress_cb, log_cb):
            api = GitHubAPI(self.app.username, self.app.token)
            repos = api.fetch_all_repos(log_cb)
            stats = {"ok": 0, "err": 0}
            total = len(repos)
            for i, repo in enumerate(repos):
                if self._cancelled: break
                progress_cb(i, total)
                name = repo["name"]
                rpath = os.path.join(dest, name + ".git")
                url = repo["clone_url"]
                try:
                    if os.path.isdir(rpath):
                        log_cb(f"[{i+1}/{total}] Updating mirror: {name}...")
                        r = subprocess.run([git, "-C", rpath, "remote", "update"],
                                           capture_output=True, text=True, timeout=180)
                    else:
                        log_cb(f"[{i+1}/{total}] Mirror cloning: {name}...")
                        r = subprocess.run([git, "clone", "--mirror", url, rpath],
                                           capture_output=True, text=True, timeout=300)
                    if r.returncode == 0:
                        stats["ok"] += 1
                    else:
                        stats["err"] += 1
                        log_cb(f"  -> {r.stderr.strip()[:200]}")
                except Exception as e:
                    stats["err"] += 1
                    log_cb(f"  -> {e}")
            progress_cb(total, total)
            return stats

        self.worker = GenericWorker(do_mirror)
        self.worker.progress.connect(lambda c, t: (self.progress.setMaximum(max(t, 1)), self.progress.setValue(c)))
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda s: (
            self.mirror_btn.setEnabled(True),
            self.log(f"Mirror complete: {s['ok']} ok, {s['err']} errors")
        ))
        self.worker.error.connect(lambda e: (self.mirror_btn.setEnabled(True), self.log(f"ERROR: {e}")))
        self.worker.start()

    def start_zip(self):
        src = self.app.repos_dir
        dest = self.zip_dest.text().strip()
        if not src or not dest:
            QMessageBox.warning(self, "Missing Paths", "Set repos folder in Settings and zip destination.")
            return
        os.makedirs(dest, exist_ok=True)
        exclude_git = self.zip_git_check.isChecked()
        self.zip_btn.setEnabled(False)

        def do_zip(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            total = len(entries)
            stats = {"ok": 0, "err": 0}
            for i, name in enumerate(entries):
                progress_cb(i, total)
                log_cb(f"[{i+1}/{total}] Zipping {name}...")
                rpath = os.path.join(src, name)
                zpath = os.path.join(dest, f"{name}.zip")
                try:
                    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, dirs, files in os.walk(rpath):
                            if exclude_git and '.git' in root.split(os.sep):
                                continue
                            for f in files:
                                fpath = os.path.join(root, f)
                                arcname = os.path.relpath(fpath, src)
                                zf.write(fpath, arcname)
                    stats["ok"] += 1
                except Exception as e:
                    stats["err"] += 1
                    log_cb(f"  -> {e}")
            progress_cb(total, total)
            return stats

        self.worker = GenericWorker(do_zip)
        self.worker.progress.connect(lambda c, t: (self.progress.setMaximum(max(t, 1)), self.progress.setValue(c)))
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda s: (
            self.zip_btn.setEnabled(True),
            self.log(f"Zip complete: {s['ok']} ok, {s['err']} errors")
        ))
        self.worker.error.connect(lambda e: (self.zip_btn.setEnabled(True), self.log(f"ERROR: {e}")))
        self.worker.start()

    def find_orphans(self):
        src = self.app.repos_dir
        if not src: return
        if not self.app.repos_cache:
            QMessageBox.information(self, "Fetch First", "Fetch repos from GitHub first (Clone tab).")
            return
        local = set(d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d, ".git")))
        remote = set(r["name"] for r in self.app.repos_cache)
        orphans = sorted(local - remote)
        if orphans:
            self.log(f"Found {len(orphans)} orphaned repos (local only): {', '.join(orphans)}")
            QMessageBox.information(self, "Orphaned Repos",
                f"Found {len(orphans)} repos that exist locally but not on GitHub:\n\n" +
                "\n".join(orphans[:20]) + ("\n..." if len(orphans) > 20 else ""))
        else:
            self.log("No orphaned repos found - local and remote are in sync.")
            QMessageBox.information(self, "All Clean", "No orphaned repos found.")

    def bulk_gc(self):
        src = self.app.repos_dir
        git = self.app.git_exe
        if not src or not git: return
        self.bulk_gc_btn.setEnabled(False)

        def do_gc(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            total = len(entries)
            freed = 0
            for i, name in enumerate(entries):
                progress_cb(i, total)
                rpath = os.path.join(src, name)
                # Measure before
                before = sum(f.stat().st_size for f in Path(rpath).rglob("*") if f.is_file()) // 1024
                log_cb(f"[{i+1}/{total}] GC: {name}...")
                subprocess.run([git, "-C", rpath, "gc", "--aggressive", "--prune=now"],
                               capture_output=True, timeout=120)
                after = sum(f.stat().st_size for f in Path(rpath).rglob("*") if f.is_file()) // 1024
                diff = before - after
                if diff > 0:
                    freed += diff
                    log_cb(f"  -> Freed {format_size(diff)}")
            progress_cb(total, total)
            return freed

        self.worker = GenericWorker(do_gc)
        self.worker.progress.connect(lambda c, t: (self.progress.setMaximum(max(t, 1)), self.progress.setValue(c)))
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda freed: (
            self.bulk_gc_btn.setEnabled(True),
            self.log(f"GC complete! Total freed: {format_size(freed)}")
        ))
        self.worker.error.connect(lambda e: (self.bulk_gc_btn.setEnabled(True), self.log(f"ERROR: {e}")))
        self.worker.start()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: SEARCH
# ═══════════════════════════════════════════════════════════════════════════════
class SearchTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Search bar
        row = QHBoxLayout()
        row.addWidget(QLabel("Search:"))
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search across all repos (supports regex)...")
        self.query_input.returnPressed.connect(self.do_search)
        row.addWidget(self.query_input, 1)

        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText("File filter (e.g. *.py, *.js)")
        self.ext_input.setFixedWidth(180)
        row.addWidget(self.ext_input)

        self.regex_check = QCheckBox("Regex")
        row.addWidget(self.regex_check)
        self.case_check = QCheckBox("Case Sensitive")
        row.addWidget(self.case_check)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.do_search)
        row.addWidget(self.search_btn)
        layout.addLayout(row)

        # Quick actions
        quick = QHBoxLayout()
        dirty_btn = QPushButton("Find Dirty Repos")
        dirty_btn.setProperty("class", "warning")
        dirty_btn.clicked.connect(self.find_dirty)
        quick.addWidget(dirty_btn)

        unpushed_btn = QPushButton("Find Unpushed Work")
        unpushed_btn.setProperty("class", "warning")
        unpushed_btn.clicked.connect(self.find_unpushed)
        quick.addWidget(unpushed_btn)

        large_btn = QPushButton("Find Large Files (>10MB)")
        large_btn.setProperty("class", "secondary")
        large_btn.clicked.connect(self.find_large_files)
        quick.addWidget(large_btn)
        quick.addStretch()
        layout.addLayout(quick)

        # Results
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setFont(QFont("Consolas", 9) if sys.platform == 'win32' else QFont("Monospace", 9))
        layout.addWidget(self.results, 1)

        self.status_label = QLabel("")
        self.status_label.setProperty("class", "subtitle")
        layout.addWidget(self.status_label)

    def log(self, msg):
        self.log_signal.emit(msg)

    def _append(self, text):
        self.results.appendPlainText(text)

    def do_search(self):
        query = self.query_input.text().strip()
        if not query: return
        src = self.app.repos_dir
        git = self.app.git_exe
        if not src or not git: return

        self.results.clear()
        self.search_btn.setEnabled(False)
        self.search_btn.setText("Searching...")
        ext_filter = self.ext_input.text().strip()
        use_regex = self.regex_check.isChecked()
        case_sens = self.case_check.isChecked()

        def do_grep(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            total_matches = 0
            repos_with_matches = 0

            for i, name in enumerate(entries):
                progress_cb(i, len(entries))
                rpath = os.path.join(src, name)
                cmd = [git, "-C", rpath, "grep", "-n", "--color=never"]
                if not case_sens: cmd.append("-i")
                if use_regex: cmd.append("-E")
                else: cmd.append("-F")
                cmd.append(query)
                if ext_filter:
                    cmd.extend(["--", ext_filter])

                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if r.returncode == 0 and r.stdout.strip():
                        lines = r.stdout.strip().split("\n")
                        total_matches += len(lines)
                        repos_with_matches += 1
                        # Emit results
                        self.results.appendPlainText(f"\n=== {name} ({len(lines)} matches) ===")
                        for line in lines[:50]:  # Cap per repo
                            self.results.appendPlainText(f"  {line}")
                        if len(lines) > 50:
                            self.results.appendPlainText(f"  ... and {len(lines)-50} more")
                except:
                    pass
            progress_cb(len(entries), len(entries))
            return {"matches": total_matches, "repos": repos_with_matches, "searched": len(entries)}

        self.worker = GenericWorker(do_grep)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda s: (
            self.search_btn.setEnabled(True),
            self.search_btn.setText("Search"),
            self.status_label.setText(
                f"{s['matches']} matches across {s['repos']} repos (searched {s['searched']})")
        ))
        self.worker.error.connect(lambda e: (
            self.search_btn.setEnabled(True), self.search_btn.setText("Search"), self.log(f"ERROR: {e}")
        ))
        self.worker.start()

    def find_dirty(self):
        src = self.app.repos_dir
        git = self.app.git_exe
        if not src or not git: return
        self.results.clear()
        self.results.appendPlainText("Scanning for repos with uncommitted changes...\n")

        def do_find(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            dirty = []
            for i, name in enumerate(entries):
                progress_cb(i, len(entries))
                rpath = os.path.join(src, name)
                r = subprocess.run([git, "-C", rpath, "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    files = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
                    dirty.append((name, files))
                    self.results.appendPlainText(f"{name}: {len(files)} changed files")
                    for f in files[:10]:
                        self.results.appendPlainText(f"  {f}")
                    if len(files) > 10:
                        self.results.appendPlainText(f"  ...and {len(files)-10} more")
            progress_cb(len(entries), len(entries))
            return dirty

        self.worker = GenericWorker(do_find)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda d: self.status_label.setText(
            f"{len(d)} repos with uncommitted changes" if d else "All repos are clean!"))
        self.worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.worker.start()

    def find_unpushed(self):
        src = self.app.repos_dir
        git = self.app.git_exe
        if not src or not git: return
        self.results.clear()
        self.results.appendPlainText("Scanning for repos with unpushed commits...\n")

        def do_find(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            unpushed = []
            for i, name in enumerate(entries):
                progress_cb(i, len(entries))
                rpath = os.path.join(src, name)
                r = subprocess.run([git, "-C", rpath, "log", "@{upstream}..HEAD", "--oneline"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    commits = r.stdout.strip().split("\n")
                    unpushed.append((name, commits))
                    self.results.appendPlainText(f"{name}: {len(commits)} unpushed commits")
                    for c in commits[:5]:
                        self.results.appendPlainText(f"  {c}")
            progress_cb(len(entries), len(entries))
            return unpushed

        self.worker = GenericWorker(do_find)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda u: self.status_label.setText(
            f"{len(u)} repos with unpushed work" if u else "Everything is pushed!"))
        self.worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.worker.start()

    def find_large_files(self):
        src = self.app.repos_dir
        if not src: return
        self.results.clear()
        self.results.appendPlainText("Scanning for files larger than 10MB...\n")

        def do_find(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d))])
            large = []
            for i, name in enumerate(entries):
                progress_cb(i, len(entries))
                rpath = os.path.join(src, name)
                for root, dirs, files in os.walk(rpath):
                    dirs[:] = [d for d in dirs if d != '.git']
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            sz = os.path.getsize(fp)
                            if sz > 10 * 1024 * 1024:
                                rel = os.path.relpath(fp, src)
                                large.append((rel, sz))
                                self.results.appendPlainText(f"  {format_size(sz // 1024):>10}  {rel}")
                        except: pass
            progress_cb(len(entries), len(entries))
            return sorted(large, key=lambda x: -x[1])

        self.worker = GenericWorker(do_find)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda l: self.status_label.setText(
            f"Found {len(l)} files over 10MB" if l else "No large files found."))
        self.worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.worker.start()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════════
class InsightsTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Generate Insights")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        row.addStretch()
        layout.addLayout(row)

        # Stats cards row
        self.stats_row = QHBoxLayout()
        self.stat_cards = {}
        for key, label in [("total", "Total Repos"), ("languages", "Languages"),
                            ("disk", "Disk Usage"), ("stars", "Total Stars"),
                            ("forks", "Total Forks"), ("private", "Private")]:
            card = QFrame()
            card.setProperty("class", "card")
            card.setStyleSheet("QFrame { background-color: #181825; border: 1px solid #45475a; border-radius: 8px; padding: 12px; }")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            val = QLabel("--")
            val.setProperty("class", "stat-value")
            val.setStyleSheet("font-size: 22px; font-weight: bold; color: #89b4fa;")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(val)
            lbl = QLabel(label)
            lbl.setProperty("class", "stat-label")
            lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(lbl)
            self.stat_cards[key] = val
            self.stats_row.addWidget(card)
        layout.addLayout(self.stats_row)

        # Details
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Language breakdown
        lang_container = QWidget()
        ll = QVBoxLayout(lang_container)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Language Breakdown"))
        self.lang_table = make_table([
            ("Language", 0, "stretch"), ("Repos", 60, "fixed"), ("Size", 80, "fixed")
        ])
        ll.addWidget(self.lang_table)
        splitter.addWidget(lang_container)

        # Largest repos
        size_container = QWidget()
        sl = QVBoxLayout(size_container)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(QLabel("Largest Repositories"))
        self.size_table = make_table([
            ("Repository", 0, "stretch"), ("Size", 80, "fixed"), ("Language", 80, "fixed")
        ])
        sl.addWidget(self.size_table)
        splitter.addWidget(size_container)

        # Recent activity
        act_container = QWidget()
        al = QVBoxLayout(act_container)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(QLabel("Recently Updated"))
        self.activity_table = make_table([
            ("Repository", 0, "stretch"), ("Pushed", 100, "fixed")
        ])
        al.addWidget(self.activity_table)
        splitter.addWidget(act_container)

        layout.addWidget(splitter, 1)

    def log(self, msg):
        self.log_signal.emit(msg)

    def refresh(self):
        if not self.app.repos_cache:
            QMessageBox.information(self, "Fetch First", "Fetch repos from GitHub first (Clone tab).")
            return

        repos = self.app.repos_cache
        src = self.app.repos_dir

        # Summary stats
        self.stat_cards["total"].setText(str(len(repos)))
        languages = set(r["language"] for r in repos if r["language"])
        self.stat_cards["languages"].setText(str(len(languages)))
        self.stat_cards["stars"].setText(str(sum(r["stargazers_count"] for r in repos)))
        self.stat_cards["forks"].setText(str(sum(r["forks_count"] for r in repos)))
        self.stat_cards["private"].setText(str(sum(1 for r in repos if r["private"])))

        total_size = sum(r["size"] for r in repos)
        self.stat_cards["disk"].setText(format_size(total_size))

        # Language breakdown
        lang_data = {}
        for r in repos:
            lang = r["language"] or "Unknown"
            if lang not in lang_data:
                lang_data[lang] = {"count": 0, "size": 0}
            lang_data[lang]["count"] += 1
            lang_data[lang]["size"] += r["size"]

        sorted_langs = sorted(lang_data.items(), key=lambda x: -x[1]["count"])
        self.lang_table.setRowCount(len(sorted_langs))
        for i, (lang, data) in enumerate(sorted_langs):
            self.lang_table.setItem(i, 0, QTableWidgetItem(lang))
            ci = QTableWidgetItem(str(data["count"]))
            ci.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lang_table.setItem(i, 1, ci)
            si = QTableWidgetItem(format_size(data["size"]))
            si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.lang_table.setItem(i, 2, si)

        # Largest repos
        by_size = sorted(repos, key=lambda r: -r["size"])[:20]
        self.size_table.setRowCount(len(by_size))
        for i, r in enumerate(by_size):
            self.size_table.setItem(i, 0, QTableWidgetItem(r["name"]))
            si = QTableWidgetItem(format_size(r["size"]))
            si.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.size_table.setItem(i, 1, si)
            self.size_table.setItem(i, 2, QTableWidgetItem(r["language"]))

        # Recent activity
        by_push = sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)[:20]
        self.activity_table.setRowCount(len(by_push))
        for i, r in enumerate(by_push):
            self.activity_table.setItem(i, 0, QTableWidgetItem(r["name"]))
            self.activity_table.setItem(i, 1, QTableWidgetItem(
                r["pushed_at"][:10] if r.get("pushed_at") else ""))

        self.log(f"Insights generated for {len(repos)} repos")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: GITHUB API MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════
class APITab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        note = QLabel("Requires a Personal Access Token with 'repo' and 'delete_repo' scopes (Settings tab)")
        note.setProperty("class", "subtitle")
        layout.addWidget(note)

        # Repo table with editable properties
        self.table = make_table([
            ("", 40, "fixed"), ("Repository", 0, "stretch"), ("Visibility", 80, "fixed"),
            ("Description", 0, "stretch"), ("Archived", 70, "fixed"), ("Topics", 150, "fixed")
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        load_btn = QPushButton("Load Repos")
        load_btn.clicked.connect(self.load_repos)
        actions.addWidget(load_btn)

        sel_btn = QPushButton("Select All")
        sel_btn.setProperty("class", "secondary")
        sel_btn.setFixedWidth(90)
        sel_btn.clicked.connect(lambda: self._toggle(True))
        actions.addWidget(sel_btn)
        desel_btn = QPushButton("Deselect All")
        desel_btn.setProperty("class", "secondary")
        desel_btn.setFixedWidth(100)
        desel_btn.clicked.connect(lambda: self._toggle(False))
        actions.addWidget(desel_btn)
        actions.addStretch()

        # Bulk actions
        vis_label = QLabel("Set Visibility:")
        actions.addWidget(vis_label)
        self.vis_combo = QComboBox()
        self.vis_combo.addItems(["-- No Change --", "Public", "Private"])
        self.vis_combo.setFixedWidth(130)
        actions.addWidget(self.vis_combo)

        apply_btn = QPushButton("Apply Changes")
        apply_btn.setProperty("class", "success")
        apply_btn.clicked.connect(self.apply_changes)
        actions.addWidget(apply_btn)
        layout.addLayout(actions)

        # Dangerous actions
        danger = QHBoxLayout()
        danger.addStretch()

        archive_btn = QPushButton("Archive Selected")
        archive_btn.setProperty("class", "warning")
        archive_btn.clicked.connect(self.archive_selected)
        danger.addWidget(archive_btn)

        unarchive_btn = QPushButton("Unarchive Selected")
        unarchive_btn.setProperty("class", "secondary")
        unarchive_btn.clicked.connect(self.unarchive_selected)
        danger.addWidget(unarchive_btn)

        del_btn = QPushButton("DELETE Selected")
        del_btn.setProperty("class", "danger")
        del_btn.clicked.connect(self.delete_selected)
        danger.addWidget(del_btn)
        layout.addLayout(danger)

        # Create new repo
        create_group = QGroupBox("  Create New Repository")
        cg = QHBoxLayout(create_group)
        cg.addWidget(QLabel("Name:"))
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("my-new-repo")
        cg.addWidget(self.new_name, 1)
        cg.addWidget(QLabel("Description:"))
        self.new_desc = QLineEdit()
        self.new_desc.setPlaceholderText("Optional description")
        cg.addWidget(self.new_desc, 1)
        self.new_private = QCheckBox("Private")
        cg.addWidget(self.new_private)
        create_btn = QPushButton("Create")
        create_btn.setProperty("class", "success")
        create_btn.clicked.connect(self.create_repo)
        cg.addWidget(create_btn)
        layout.addWidget(create_group)

    def log(self, msg):
        self.log_signal.emit(msg)

    def load_repos(self):
        if not self.app.repos_cache:
            QMessageBox.information(self, "Fetch First", "Fetch repos from GitHub first (Clone tab).")
            return
        repos = self.app.repos_cache
        self.table.setRowCount(len(repos))
        for i, r in enumerate(repos):
            add_checkbox_to_table(self.table, i, 0, False)
            name_item = QTableWidgetItem(r["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, name_item)

            vis = QTableWidgetItem("Private" if r["private"] else "Public")
            vis.setFlags(vis.flags() & ~Qt.ItemFlag.ItemIsEditable)
            vis.setForeground(QColor("#f38ba8" if r["private"] else "#a6e3a1"))
            vis.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 2, vis)

            # Description is editable
            self.table.setItem(i, 3, QTableWidgetItem(r["description"]))

            arch = QTableWidgetItem("Yes" if r["archived"] else "No")
            arch.setFlags(arch.flags() & ~Qt.ItemFlag.ItemIsEditable)
            arch.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r["archived"]: arch.setForeground(QColor("#fab387"))
            self.table.setItem(i, 4, arch)

            self.table.setItem(i, 5, QTableWidgetItem(", ".join(r.get("topics", []))))

    def _toggle(self, state):
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk: chk.setChecked(state)

    def _get_selected_names(self):
        names = []
        repos = self.app.repos_cache or []
        for i in range(self.table.rowCount()):
            chk = get_table_checkbox(self.table, i, 0)
            if chk and chk.isChecked() and i < len(repos):
                names.append(repos[i]["full_name"])
        return names

    def _require_token(self):
        if not self.app.token:
            QMessageBox.warning(self, "Token Required", "Add a Personal Access Token in Settings.")
            return False
        return True

    def apply_changes(self):
        if not self._require_token(): return
        selected = self._get_selected_names()
        if not selected: return

        vis = self.vis_combo.currentText()
        repos = self.app.repos_cache or []

        api = GitHubAPI(self.app.username, self.app.token)

        def do_apply(progress_cb, log_cb):
            stats = {"ok": 0, "err": 0}
            total = len(selected)
            for i, full_name in enumerate(selected):
                progress_cb(i, total)
                data = {}
                if vis == "Public": data["private"] = False
                elif vis == "Private": data["private"] = True

                # Check for edited description
                for row in range(self.table.rowCount()):
                    if row < len(repos) and repos[row]["full_name"] == full_name:
                        new_desc = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
                        if new_desc != repos[row]["description"]:
                            data["description"] = new_desc

                        new_topics = self.table.item(row, 5).text() if self.table.item(row, 5) else ""
                        old_topics = ", ".join(repos[row].get("topics", []))
                        if new_topics != old_topics:
                            topic_list = [t.strip() for t in new_topics.split(",") if t.strip()]
                            # Topics use a different endpoint
                            requests.put(f"{api.BASE}/repos/{full_name}/topics",
                                        headers={**api.headers, "Accept": "application/vnd.github.mercy-preview+json"},
                                        json={"names": topic_list}, timeout=15)
                        break

                if data:
                    log_cb(f"Updating {full_name}: {data}")
                    resp = api.patch(f"/repos/{full_name}", data)
                    if resp.status_code == 200:
                        stats["ok"] += 1
                    else:
                        stats["err"] += 1
                        log_cb(f"  -> Error: {resp.status_code}")
                else:
                    stats["ok"] += 1
            progress_cb(total, total)
            return stats

        self.worker = GenericWorker(do_apply)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(lambda s: self.log(f"Apply complete: {s['ok']} ok, {s['err']} errors"))
        self.worker.error.connect(lambda e: self.log(f"ERROR: {e}"))
        self.worker.start()

    def archive_selected(self):
        if not self._require_token(): return
        selected = self._get_selected_names()
        if not selected: return
        if QMessageBox.question(self, "Confirm Archive",
                f"Archive {len(selected)} repos?") != QMessageBox.StandardButton.Yes:
            return
        api = GitHubAPI(self.app.username, self.app.token)
        for name in selected:
            self.log(f"Archiving {name}...")
            api.patch(f"/repos/{name}", {"archived": True})
        self.log("Archive complete. Reload to see changes.")

    def unarchive_selected(self):
        if not self._require_token(): return
        selected = self._get_selected_names()
        if not selected: return
        api = GitHubAPI(self.app.username, self.app.token)
        for name in selected:
            self.log(f"Unarchiving {name}...")
            api.patch(f"/repos/{name}", {"archived": False})
        self.log("Unarchive complete. Reload to see changes.")

    def delete_selected(self):
        if not self._require_token(): return
        selected = self._get_selected_names()
        if not selected: return
        confirm = QMessageBox.warning(self, "DANGER: Delete Repositories",
            f"This will PERMANENTLY DELETE {len(selected)} repositories from GitHub!\n\n"
            f"Repos:\n" + "\n".join(selected[:10]) +
            ("\n..." if len(selected) > 10 else "") +
            "\n\nThis cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Double confirm
        confirm2 = QMessageBox.critical(self, "FINAL WARNING",
            f"Type count: You are about to delete {len(selected)} repos.\n"
            "Are you absolutely sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm2 != QMessageBox.StandardButton.Yes:
            return

        api = GitHubAPI(self.app.username, self.app.token)
        for name in selected:
            self.log(f"DELETING {name}...")
            resp = api.delete(f"/repos/{name}")
            if resp.status_code == 204:
                self.log(f"  -> Deleted")
            else:
                self.log(f"  -> Error: {resp.status_code} {resp.text[:100]}")
        self.log("Deletion complete. Refresh repo list.")

    def create_repo(self):
        if not self._require_token(): return
        name = self.new_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Enter a repo name.")
            return
        api = GitHubAPI(self.app.username, self.app.token)
        data = {
            "name": name,
            "description": self.new_desc.text().strip(),
            "private": self.new_private.isChecked(),
            "auto_init": True
        }
        self.log(f"Creating repo: {name}...")
        resp = api.post("/user/repos", data)
        if resp.status_code == 201:
            self.log(f"Created: {resp.json().get('html_url', '')}")
            self.new_name.clear()
            self.new_desc.clear()
            QMessageBox.information(self, "Created", f"Repository '{name}' created successfully!")
        else:
            self.log(f"Error: {resp.status_code} - {resp.text[:200]}")
            QMessageBox.critical(self, "Error", f"Failed to create repo: {resp.text[:300]}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: DIFF VIEWER
# ═══════════════════════════════════════════════════════════════════════════════
class DiffTab(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self, app_state):
        super().__init__()
        self.app = app_state
        self.worker = None
        self.repo_data = {}  # {repo_name: {"path":..., "files": [...]}}
        self.current_repo = None
        self.current_file = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Top bar
        top = QHBoxLayout()
        self.scan_btn = QPushButton("Scan for Changes")
        self.scan_btn.clicked.connect(self.scan_all)
        top.addWidget(self.scan_btn)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Working Tree Changes (uncommitted)",
            "Staged Changes (ready to commit)",
            "Incoming Changes (remote vs local)",
            "Unpushed Commits (local vs remote)"
        ])
        self.mode_combo.setFixedWidth(320)
        self.mode_combo.currentIndexChanged.connect(self.scan_all)
        top.addWidget(self.mode_combo)

        top.addStretch()
        self.summary_label = QLabel("Scan your repos to see changes")
        self.summary_label.setProperty("class", "subtitle")
        self.summary_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        top.addWidget(self.summary_label)
        layout.addLayout(top)

        # Three-panel splitter: repos | files | diff
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Repo list
        repo_panel = QWidget()
        rp_layout = QVBoxLayout(repo_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)
        rp_layout.setSpacing(4)
        rp_header = QLabel("Repositories with Changes")
        rp_header.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px; padding: 4px;")
        rp_layout.addWidget(rp_header)
        self.repo_list = QTableWidget()
        self.repo_list.setColumnCount(3)
        self.repo_list.setHorizontalHeaderLabels(["Repository", "Files", "Type"])
        self.repo_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.repo_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.repo_list.setColumnWidth(1, 50)
        self.repo_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.repo_list.setColumnWidth(2, 70)
        self.repo_list.setAlternatingRowColors(True)
        self.repo_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.repo_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.repo_list.verticalHeader().setVisible(False)
        self.repo_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.repo_list.itemSelectionChanged.connect(self._on_repo_selected)
        rp_layout.addWidget(self.repo_list)
        self.splitter.addWidget(repo_panel)

        # Middle panel: File list
        file_panel = QWidget()
        fp_layout = QVBoxLayout(file_panel)
        fp_layout.setContentsMargins(0, 0, 0, 0)
        fp_layout.setSpacing(4)
        self.file_header = QLabel("Changed Files")
        self.file_header.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px; padding: 4px;")
        fp_layout.addWidget(self.file_header)
        self.file_list = QTableWidget()
        self.file_list.setColumnCount(3)
        self.file_list.setHorizontalHeaderLabels(["Status", "File", "Lines"])
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.file_list.setColumnWidth(0, 55)
        self.file_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.file_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.file_list.setColumnWidth(2, 60)
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_list.verticalHeader().setVisible(False)
        self.file_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        fp_layout.addWidget(self.file_list)

        # File action buttons
        factions = QHBoxLayout()
        self.stage_btn = QPushButton("Stage File")
        self.stage_btn.setProperty("class", "success")
        self.stage_btn.setFixedHeight(28)
        self.stage_btn.clicked.connect(self._stage_file)
        factions.addWidget(self.stage_btn)
        self.unstage_btn = QPushButton("Unstage")
        self.unstage_btn.setProperty("class", "secondary")
        self.unstage_btn.setFixedHeight(28)
        self.unstage_btn.clicked.connect(self._unstage_file)
        factions.addWidget(self.unstage_btn)
        self.discard_btn = QPushButton("Discard")
        self.discard_btn.setProperty("class", "danger")
        self.discard_btn.setFixedHeight(28)
        self.discard_btn.clicked.connect(self._discard_file)
        factions.addWidget(self.discard_btn)
        fp_layout.addLayout(factions)

        self.splitter.addWidget(file_panel)

        # Right panel: Diff viewer
        diff_panel = QWidget()
        dp_layout = QVBoxLayout(diff_panel)
        dp_layout.setContentsMargins(0, 0, 0, 0)
        dp_layout.setSpacing(4)
        self.diff_header = QLabel("Diff Output")
        self.diff_header.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px; padding: 4px;")
        dp_layout.addWidget(self.diff_header)
        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("Consolas", 9) if sys.platform == 'win32' else QFont("Monospace", 9))
        self.diff_view.setStyleSheet(
            "QTextEdit { background-color: #11111b; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; }"
        )
        dp_layout.addWidget(self.diff_view)

        # Commit controls
        commit_box = QHBoxLayout()
        self.commit_msg = QLineEdit()
        self.commit_msg.setPlaceholderText("Commit message...")
        commit_box.addWidget(self.commit_msg, 1)
        self.commit_btn = QPushButton("Commit")
        self.commit_btn.setProperty("class", "success")
        self.commit_btn.setFixedWidth(80)
        self.commit_btn.clicked.connect(self._do_commit)
        commit_box.addWidget(self.commit_btn)
        self.push_btn = QPushButton("Commit && Push")
        self.push_btn.setProperty("class", "warning")
        self.push_btn.setFixedWidth(120)
        self.push_btn.clicked.connect(self._do_commit_push)
        commit_box.addWidget(self.push_btn)
        dp_layout.addLayout(commit_box)

        self.splitter.addWidget(diff_panel)
        self.splitter.setSizes([220, 260, 520])

        layout.addWidget(self.splitter, 1)

    def log(self, msg):
        self.log_signal.emit(msg)

    def scan_all(self):
        src = self.app.repos_dir
        git = self.app.git_exe
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, "No Folder", "Set a valid repos folder in Settings.")
            return
        if not git:
            QMessageBox.critical(self, "No Git", "Git not found. Check Settings.")
            return

        mode_idx = self.mode_combo.currentIndex()
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.repo_list.setRowCount(0)
        self.file_list.setRowCount(0)
        self.diff_view.clear()
        self.repo_data = {}

        def do_scan(progress_cb, log_cb):
            entries = sorted([d for d in os.listdir(src)
                             if os.path.isdir(os.path.join(src, d, ".git"))])
            results = {}
            total = len(entries)

            for i, name in enumerate(entries):
                progress_cb(i, total)
                rpath = os.path.join(src, name)
                files = []

                try:
                    if mode_idx == 0:
                        # Working tree changes (unstaged)
                        r = subprocess.run([git, "-C", rpath, "diff", "--name-status"],
                                           capture_output=True, text=True, timeout=15)
                        if r.returncode == 0 and r.stdout.strip():
                            for line in r.stdout.strip().split("\n"):
                                parts = line.split("\t", 1)
                                if len(parts) == 2:
                                    files.append({"status": parts[0], "path": parts[1], "type": "unstaged"})
                        # Also show untracked files
                        r2 = subprocess.run([git, "-C", rpath, "ls-files", "--others", "--exclude-standard"],
                                            capture_output=True, text=True, timeout=15)
                        if r2.returncode == 0 and r2.stdout.strip():
                            for f in r2.stdout.strip().split("\n"):
                                if f.strip():
                                    files.append({"status": "?", "path": f.strip(), "type": "untracked"})

                    elif mode_idx == 1:
                        # Staged changes
                        r = subprocess.run([git, "-C", rpath, "diff", "--cached", "--name-status"],
                                           capture_output=True, text=True, timeout=15)
                        if r.returncode == 0 and r.stdout.strip():
                            for line in r.stdout.strip().split("\n"):
                                parts = line.split("\t", 1)
                                if len(parts) == 2:
                                    files.append({"status": parts[0], "path": parts[1], "type": "staged"})

                    elif mode_idx == 2:
                        # Incoming from remote (fetch first, then compare)
                        subprocess.run([git, "-C", rpath, "fetch", "--quiet"],
                                       capture_output=True, timeout=30)
                        r = subprocess.run([git, "-C", rpath, "diff", "--name-status", "HEAD..@{upstream}"],
                                           capture_output=True, text=True, timeout=15)
                        if r.returncode == 0 and r.stdout.strip():
                            for line in r.stdout.strip().split("\n"):
                                parts = line.split("\t", 1)
                                if len(parts) == 2:
                                    files.append({"status": parts[0], "path": parts[1], "type": "incoming"})

                    elif mode_idx == 3:
                        # Unpushed (local commits not on remote)
                        r = subprocess.run([git, "-C", rpath, "diff", "--name-status", "@{upstream}..HEAD"],
                                           capture_output=True, text=True, timeout=15)
                        if r.returncode == 0 and r.stdout.strip():
                            for line in r.stdout.strip().split("\n"):
                                parts = line.split("\t", 1)
                                if len(parts) == 2:
                                    files.append({"status": parts[0], "path": parts[1], "type": "unpushed"})

                except Exception as e:
                    log_cb(f"  {name}: {e}")

                if files:
                    results[name] = {"path": rpath, "files": files}

            progress_cb(total, total)
            return results

        self.worker = GenericWorker(do_scan)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._on_scan_done)
        self.worker.error.connect(lambda e: (
            self.log(f"ERROR: {e}"),
            self._reset_scan()
        ))
        self.worker.start()

    def _reset_scan(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan for Changes")

    def _on_scan_done(self, results):
        self._reset_scan()
        self.repo_data = results

        status_labels = {
            "M": ("Modified", "#fab387"),
            "A": ("Added", "#a6e3a1"),
            "D": ("Deleted", "#f38ba8"),
            "R": ("Renamed", "#89b4fa"),
            "C": ("Copied", "#89b4fa"),
            "T": ("Type", "#cba6f7"),
            "U": ("Unmerged", "#f38ba8"),
            "?": ("New", "#94e2d5"),
        }

        sorted_repos = sorted(results.keys(), key=str.lower)
        self.repo_list.setRowCount(len(sorted_repos))

        total_files = 0
        for i, name in enumerate(sorted_repos):
            data = results[name]
            file_count = len(data["files"])
            total_files += file_count

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            self.repo_list.setItem(i, 0, name_item)

            cnt = QTableWidgetItem(str(file_count))
            cnt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if file_count > 10:
                cnt.setForeground(QColor("#f38ba8"))
            elif file_count > 0:
                cnt.setForeground(QColor("#fab387"))
            self.repo_list.setItem(i, 1, cnt)

            # Dominant change type
            statuses = [f["status"][0] for f in data["files"]]
            dominant = max(set(statuses), key=statuses.count) if statuses else "?"
            label, color = status_labels.get(dominant, (dominant, "#cdd6f4"))
            type_item = QTableWidgetItem(label)
            type_item.setForeground(QColor(color))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.repo_list.setItem(i, 2, type_item)

        mode_names = ["uncommitted", "staged", "incoming", "unpushed"]
        mode_name = mode_names[self.mode_combo.currentIndex()]
        self.summary_label.setText(
            f"{len(sorted_repos)} repos with {total_files} {mode_name} changes"
        )
        self.log(f"Diff scan: {len(sorted_repos)} repos, {total_files} changed files ({mode_name})")

    def _on_repo_selected(self):
        rows = self.repo_list.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        name_item = self.repo_list.item(row, 0)
        if not name_item:
            return
        repo_name = name_item.data(Qt.ItemDataRole.UserRole)
        if repo_name not in self.repo_data:
            return

        self.current_repo = repo_name
        data = self.repo_data[repo_name]
        files = data["files"]
        self.file_header.setText(f"Changed Files - {repo_name}")
        self.diff_view.clear()

        status_info = {
            "M": ("Modified", "#fab387"),
            "A": ("Added", "#a6e3a1"),
            "D": ("Deleted", "#f38ba8"),
            "R": ("Renamed", "#89b4fa"),
            "C": ("Copied", "#89b4fa"),
            "?": ("New", "#94e2d5"),
        }

        self.file_list.setRowCount(len(files))
        for i, f in enumerate(files):
            st_char = f["status"][0]
            label, color = status_info.get(st_char, (f["status"], "#cdd6f4"))
            st_item = QTableWidgetItem(label)
            st_item.setForeground(QColor(color))
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.file_list.setItem(i, 0, st_item)

            path_item = QTableWidgetItem(f["path"])
            path_item.setData(Qt.ItemDataRole.UserRole, f)
            self.file_list.setItem(i, 1, path_item)

            # Lines changed placeholder (filled on diff)
            self.file_list.setItem(i, 2, QTableWidgetItem(""))

    def _on_file_selected(self):
        rows = self.file_list.selectionModel().selectedRows()
        if not rows or not self.current_repo:
            return
        row = rows[0].row()
        path_item = self.file_list.item(row, 1)
        if not path_item:
            return
        fdata = path_item.data(Qt.ItemDataRole.UserRole)
        if not fdata:
            return

        self.current_file = fdata
        repo_path = self.repo_data[self.current_repo]["path"]
        git = self.app.git_exe
        file_path = fdata["path"]
        ftype = fdata["type"]

        self.diff_header.setText(f"Diff - {self.current_repo}/{file_path}")

        try:
            if ftype == "untracked":
                # Show full file content for new untracked files
                full_path = os.path.join(repo_path, file_path)
                try:
                    with open(full_path, 'r', errors='replace') as fp:
                        content = fp.read(200000)  # Cap at ~200KB
                    self._render_new_file(file_path, content)
                except Exception as e:
                    self.diff_view.setPlainText(f"Cannot read file: {e}")
                return

            if ftype == "staged":
                cmd = [git, "-C", repo_path, "diff", "--cached", "--", file_path]
            elif ftype == "incoming":
                cmd = [git, "-C", repo_path, "diff", "HEAD..@{upstream}", "--", file_path]
            elif ftype == "unpushed":
                cmd = [git, "-C", repo_path, "diff", "@{upstream}..HEAD", "--", file_path]
            else:
                cmd = [git, "-C", repo_path, "diff", "--", file_path]

            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if r.returncode == 0 and r.stdout.strip():
                self._render_diff(r.stdout)
                # Update line count
                added = r.stdout.count("\n+") - r.stdout.count("\n+++")
                removed = r.stdout.count("\n-") - r.stdout.count("\n---")
                lines_item = self.file_list.item(row, 2)
                if lines_item:
                    lines_item.setText(f"+{added}/-{removed}")
                    lines_item.setForeground(QColor("#a6e3a1" if added > removed else "#f38ba8"))
            else:
                self.diff_view.setPlainText("No diff available (file may be binary or unchanged).")

        except Exception as e:
            self.diff_view.setPlainText(f"Error generating diff: {e}")

    def _render_diff(self, diff_text):
        """Render diff with colored lines in the diff viewer."""
        self.diff_view.clear()
        html_parts = ['<pre style="margin:0; font-family: Consolas, monospace; font-size: 9pt;">']

        for line in diff_text.split("\n"):
            escaped = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                          .replace(" ", "&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;"))

            if line.startswith("+++") or line.startswith("---"):
                html_parts.append(
                    f'<div style="color: #89b4fa; font-weight: bold;">{escaped}</div>')
            elif line.startswith("@@"):
                html_parts.append(
                    f'<div style="background-color: #1e1e3e; color: #cba6f7; padding: 2px 0;">{escaped}</div>')
            elif line.startswith("+"):
                html_parts.append(
                    f'<div style="background-color: #1a2e1a; color: #a6e3a1;">{escaped}</div>')
            elif line.startswith("-"):
                html_parts.append(
                    f'<div style="background-color: #2e1a1a; color: #f38ba8;">{escaped}</div>')
            elif line.startswith("diff "):
                html_parts.append(
                    f'<div style="color: #f9e2af; font-weight: bold; padding: 4px 0; '
                    f'border-top: 1px solid #45475a;">{escaped}</div>')
            else:
                html_parts.append(f'<div style="color: #6c7086;">{escaped}</div>')

        html_parts.append('</pre>')
        self.diff_view.setHtml("".join(html_parts))

    def _render_new_file(self, filename, content):
        """Render a new untracked file as all-green additions."""
        self.diff_view.clear()
        lines = content.split("\n")
        html_parts = [
            '<pre style="margin:0; font-family: Consolas, monospace; font-size: 9pt;">',
            f'<div style="color: #f9e2af; font-weight: bold; padding: 4px 0;">'
            f'New&nbsp;file:&nbsp;{filename}&nbsp;({len(lines)}&nbsp;lines)</div>',
        ]
        for line in lines[:2000]:
            escaped = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                          .replace(" ", "&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;"))
            html_parts.append(
                f'<div style="background-color: #1a2e1a; color: #a6e3a1;">+&nbsp;{escaped}</div>')
        if len(lines) > 2000:
            html_parts.append(
                '<div style="color: #fab387;">... truncated (file too large to display fully)</div>')
        html_parts.append('</pre>')
        self.diff_view.setHtml("".join(html_parts))

    def _get_current_context(self):
        """Get current repo path and file path, or None."""
        if not self.current_repo or self.current_repo not in self.repo_data:
            return None, None
        if not self.current_file:
            return self.repo_data[self.current_repo]["path"], None
        return self.repo_data[self.current_repo]["path"], self.current_file["path"]

    def _stage_file(self):
        repo_path, file_path = self._get_current_context()
        if not repo_path or not file_path:
            return
        git = self.app.git_exe
        r = subprocess.run([git, "-C", repo_path, "add", file_path],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            self.log(f"Staged: {self.current_repo}/{file_path}")
        else:
            self.log(f"Stage error: {r.stderr.strip()}")

    def _unstage_file(self):
        repo_path, file_path = self._get_current_context()
        if not repo_path or not file_path:
            return
        git = self.app.git_exe
        r = subprocess.run([git, "-C", repo_path, "restore", "--staged", file_path],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            self.log(f"Unstaged: {self.current_repo}/{file_path}")
        else:
            self.log(f"Unstage error: {r.stderr.strip()}")

    def _discard_file(self):
        repo_path, file_path = self._get_current_context()
        if not repo_path or not file_path:
            return
        confirm = QMessageBox.warning(self, "Discard Changes",
            f"Discard all changes to:\n{file_path}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        git = self.app.git_exe
        if self.current_file and self.current_file["type"] == "untracked":
            # Delete untracked file
            try:
                os.remove(os.path.join(repo_path, file_path))
                self.log(f"Deleted untracked: {self.current_repo}/{file_path}")
            except Exception as e:
                self.log(f"Delete error: {e}")
        else:
            r = subprocess.run([git, "-C", repo_path, "checkout", "--", file_path],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                self.log(f"Discarded: {self.current_repo}/{file_path}")
            else:
                self.log(f"Discard error: {r.stderr.strip()}")

    def _do_commit(self):
        self._commit(push=False)

    def _do_commit_push(self):
        self._commit(push=True)

    def _commit(self, push=False):
        if not self.current_repo or self.current_repo not in self.repo_data:
            QMessageBox.warning(self, "No Repo", "Select a repository first.")
            return
        msg = self.commit_msg.text().strip()
        if not msg:
            QMessageBox.warning(self, "No Message", "Enter a commit message.")
            return

        repo_path = self.repo_data[self.current_repo]["path"]
        git = self.app.git_exe

        # Check if there are staged changes
        r = subprocess.run([git, "-C", repo_path, "diff", "--cached", "--name-only"],
                           capture_output=True, text=True, timeout=10)
        if not r.stdout.strip():
            # Nothing staged, offer to stage all
            confirm = QMessageBox.question(self, "Nothing Staged",
                "No files are staged. Stage all changes and commit?")
            if confirm != QMessageBox.StandardButton.Yes:
                return
            subprocess.run([git, "-C", repo_path, "add", "-A"],
                           capture_output=True, timeout=10)

        r = subprocess.run([git, "-C", repo_path, "commit", "-m", msg],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            self.log(f"Committed to {self.current_repo}: {msg}")
            self.commit_msg.clear()
            if push:
                r2 = subprocess.run([git, "-C", repo_path, "push"],
                                    capture_output=True, text=True, timeout=60)
                if r2.returncode == 0:
                    self.log(f"Pushed {self.current_repo}")
                else:
                    self.log(f"Push error: {r2.stderr.strip()}")
                    QMessageBox.warning(self, "Push Failed", r2.stderr.strip()[:300])
        else:
            self.log(f"Commit error: {r.stderr.strip()}")
            QMessageBox.warning(self, "Commit Failed", r.stderr.strip()[:300])


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════
class AppState:
    """Shared state across all tabs."""
    def __init__(self):
        self.config = load_config()
        self.git_exe = find_git()
        self.repos_cache = []

    @property
    def username(self):
        return self.config.get("username", "")

    @property
    def token(self):
        return self.config.get("token", "")

    @property
    def repos_dir(self):
        return self.config.get("repos_dir", "")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.setWindowTitle(f"GitForge - GitHub Repository Manager")
        self.setMinimumSize(1050, 750)
        self.resize(1150, 820)
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 6)
        layout.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("GitForge")
        title.setProperty("class", "title")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #89b4fa;")
        header.addWidget(title)
        ver = QLabel("v2.1")
        ver.setProperty("class", "subtitle")
        ver.setStyleSheet("color: #6c7086; font-size: 11px; padding-top: 8px;")
        header.addWidget(ver)
        header.addStretch()
        self.git_label = QLabel()
        header.addWidget(self.git_label)
        layout.addLayout(header)

        # ── Main splitter: tabs + log ──
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Tabs
        self.tabs = QTabWidget()

        # Settings tab (integrated into the first tab)
        settings = self._build_settings_tab()
        self.tabs.addTab(settings, "Settings")

        self.clone_tab = CloneTab(self.state)
        self.clone_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.clone_tab, "Clone")

        self.sync_tab = SyncTab(self.state)
        self.sync_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.sync_tab, "Sync Status")

        self.diff_tab = DiffTab(self.state)
        self.diff_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.diff_tab, "Diff Viewer")

        self.backup_tab = BackupTab(self.state)
        self.backup_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.backup_tab, "Backup & Export")

        self.search_tab = SearchTab(self.state)
        self.search_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.search_tab, "Search")

        self.insights_tab = InsightsTab(self.state)
        self.insights_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.insights_tab, "Insights")

        self.api_tab = APITab(self.state)
        self.api_tab.log_signal.connect(self.log)
        self.tabs.addTab(self.api_tab, "GitHub API")

        splitter.addWidget(self.tabs)

        # Log panel
        log_container = QWidget()
        ll = QVBoxLayout(log_container)
        ll.setContentsMargins(0, 4, 0, 0)
        log_header = QHBoxLayout()
        log_lbl = QLabel("Activity Log")
        log_lbl.setProperty("class", "subtitle")
        log_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        log_header.addWidget(log_lbl)
        log_header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("class", "secondary")
        clear_btn.setProperty("class", "small")
        clear_btn.setFixedHeight(24)
        clear_btn.setFixedWidth(60)
        clear_btn.setStyleSheet("background-color: #45475a; color: #cdd6f4; padding: 2px 8px; font-size: 11px; border-radius: 4px;")
        clear_btn.clicked.connect(lambda: self.log_output.clear())
        log_header.addWidget(clear_btn)
        ll.addLayout(log_header)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 9) if sys.platform == 'win32' else QFont("Monospace", 9))
        self.log_output.setMaximumHeight(150)
        ll.addWidget(self.log_output)
        splitter.addWidget(log_container)

        splitter.setSizes([600, 150])
        layout.addWidget(splitter, 1)

        # Status bar
        self.statusBar().showMessage("Ready")

        # Init
        self._update_git_label()
        self._restore_settings()
        self.log("GitForge started")

    def _build_settings_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        # Connection
        conn = QGroupBox("  GitHub Connection")
        cl = QVBoxLayout(conn)
        row = QHBoxLayout()
        row.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("e.g. SysAdminDoc")
        self.username_input.textChanged.connect(self._save_settings)
        row.addWidget(self.username_input, 1)
        row.addSpacing(16)
        row.addWidget(QLabel("Personal Access Token:"))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("ghp_... (needed for private repos & API management)")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.textChanged.connect(self._save_settings)
        row.addWidget(self.token_input, 1)
        cl.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Local Repos Folder:"))
        self.repos_dir_input = QLineEdit()
        self.repos_dir_input.setPlaceholderText("Where your repos live locally...")
        self.repos_dir_input.textChanged.connect(self._save_settings)
        row2.addWidget(self.repos_dir_input, 1)
        browse = QPushButton("Browse")
        browse.setProperty("class", "secondary")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse_repos_dir)
        row2.addWidget(browse)
        cl.addLayout(row2)
        layout.addWidget(conn)

        # Git config
        git = QGroupBox("  Git Configuration")
        gl = QHBoxLayout(git)
        gl.addWidget(QLabel("user.name:"))
        self.git_name = QLineEdit()
        gl.addWidget(self.git_name, 1)
        gl.addSpacing(16)
        gl.addWidget(QLabel("user.email:"))
        self.git_email = QLineEdit()
        gl.addWidget(self.git_email, 1)
        gl.addSpacing(16)
        save_git = QPushButton("Save Git Config")
        save_git.setProperty("class", "secondary")
        save_git.clicked.connect(self._save_git_config)
        gl.addWidget(save_git)
        layout.addWidget(git)

        # Git info
        info = QGroupBox("  Git Status")
        il = QVBoxLayout(info)
        self.git_info_label = QLabel()
        self.git_info_label.setWordWrap(True)
        il.addWidget(self.git_info_label)
        layout.addWidget(info)

        layout.addStretch()
        return w

    def _restore_settings(self):
        cfg = self.state.config
        self.username_input.setText(cfg.get("username", ""))
        self.token_input.setText(cfg.get("token", ""))
        self.repos_dir_input.setText(cfg.get("repos_dir", ""))

        # Git config
        if self.state.git_exe:
            try:
                n = subprocess.run([self.state.git_exe, "config", "--global", "user.name"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
                e = subprocess.run([self.state.git_exe, "config", "--global", "user.email"],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
                self.git_name.setText(n)
                self.git_email.setText(e)
            except: pass

        # Git info
        if self.state.git_exe:
            try:
                ver = subprocess.run([self.state.git_exe, "--version"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                self.git_info_label.setText(f"{ver}\nPath: {self.state.git_exe}")
                self.git_info_label.setStyleSheet("color: #a6e3a1;")
            except:
                self.git_info_label.setText("Git found but not responding")
                self.git_info_label.setStyleSheet("color: #f38ba8;")
        else:
            self.git_info_label.setText(
                "Git NOT FOUND. Install Git for Windows from https://git-scm.com/download/win\n"
                "or ensure GitHub Desktop is installed.")
            self.git_info_label.setStyleSheet("color: #f38ba8;")

    def _save_settings(self):
        self.state.config["username"] = self.username_input.text().strip()
        self.state.config["token"] = self.token_input.text().strip()
        self.state.config["repos_dir"] = self.repos_dir_input.text().strip()
        save_config(self.state.config)

    def _browse_repos_dir(self):
        f = QFileDialog.getExistingDirectory(self, "Select Repos Folder")
        if f:
            self.repos_dir_input.setText(f)

    def _save_git_config(self):
        git = self.state.git_exe
        if not git:
            self.log("Git not found - cannot save config.")
            return
        name = self.git_name.text().strip()
        email = self.git_email.text().strip()
        msgs = []
        try:
            if name:
                subprocess.run([git, "config", "--global", "user.name", name], check=True, timeout=10)
                msgs.append(f"user.name={name}")
            if email:
                subprocess.run([git, "config", "--global", "user.email", email], check=True, timeout=10)
                msgs.append(f"user.email={email}")
            self.log(f"Git config saved: {', '.join(msgs)}" if msgs else "Nothing to save.")
        except Exception as e:
            self.log(f"Error saving git config: {e}")

    def _update_git_label(self):
        if self.state.git_exe:
            try:
                ver = subprocess.run([self.state.git_exe, "--version"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                self.git_label.setText(f"  {ver}")
                self.git_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            except:
                self.git_label.setText("  git error")
                self.git_label.setStyleSheet("color: #f38ba8;")
        else:
            self.git_label.setText("  git not found")
            self.git_label.setStyleSheet("color: #f38ba8; font-weight: bold;")

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {msg}")
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum())


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    branding_icon = QIcon(str(_branding_icon_path()))
    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLE)
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.setWindowIcon(branding_icon)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
