#!/usr/bin/env python3
"""
ELI Pro Audio GUI (PyQt6)

This file is meant to be the *single* GUI surface that:
- Calls executor_enhanced.execute(action, args) reliably.
- Shows capabilities discovered from executor at runtime.
- Provides a Proactive panel with ON/OFF toggle and live feed (no more dumb text files).
- Provides a PDF drop zone to analyze PDFs via eli_tools.analyze_pdfs and store into memory DB.

It fails soft: if a module is missing, the GUI still runs and tells you what's missing.
"""

from __future__ import annotations

import os
import sys
import json
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFileDialog,
    QSplitter, QListWidget, QListWidgetItem, QTabWidget, QMessageBox,
    QCheckBox, QSpinBox, QGroupBox, QFormLayout
)

# --- Resolve project root (best effort) ---
HERE = Path(__file__).resolve()
DEFAULT_ROOT = Path(os.environ.get("ELI_ROOT", str(HERE.parent))).expanduser().resolve()

def _safe_import_executor():
    try:
        # Support both "eli_tools/" package layout and flat file runs.
        from eli_tools.executor_enhanced import execute  # type: ignore
        return execute, None
    except Exception as e:
        return None, f"executor import failed: {type(e).__name__}: {e}"

def _safe_import_memory():
    try:
        from eli_tools.memory_db import MemoryDB  # type: ignore
        return MemoryDB, None
    except Exception as e:
        return None, f"memory_db import failed: {type(e).__name__}: {e}"

def _safe_import_pdf():
    try:
        from eli_tools.analyze_pdfs import analyze, analyze_folder, store_analysis_to_memory  # type: ignore
        return (analyze, analyze_folder, store_analysis_to_memory), None
    except Exception as e:
        return None, f"analyze_pdfs import failed: {type(e).__name__}: {e}"

class LogSink(QObject):
    message = pyqtSignal(str)

class DropPDFWidget(QTextEdit):
    dropped_paths = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setReadOnly(True)
        self.setPlaceholderText("Drop PDFs or a folder here…")

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        paths = [Path(u.toLocalFile()).expanduser().resolve() for u in urls if u.isLocalFile()]
        if paths:
            self.dropped_paths.emit([str(p) for p in paths])
        e.acceptProposedAction()

class ELIWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ELI — Pro Audio GUI (PyQt6)")
        self.resize(1280, 780)

        self.root = DEFAULT_ROOT
        self.db_path = Path(os.environ.get("ELI_MEMORY_DB", str(self.root / "eli_memory.sqlite3"))).expanduser().resolve()

        self.execute, exec_err = _safe_import_executor()
        self.MemoryDB, mem_err = _safe_import_memory()
        pdf_import, pdf_err = _safe_import_pdf()
        self.pdf_analyze = None
        self.pdf_analyze_folder = None
        self.pdf_store = None
        if pdf_import:
            self.pdf_analyze, self.pdf_analyze_folder, self.pdf_store = pdf_import

        self._init_ui(exec_err, mem_err, pdf_err)
        self._refresh_capabilities()

        # Proactive poller reads DB for latest proactive entries
        self.proactive_enabled = False
        self.proactive_timer = QTimer(self)
        self.proactive_timer.setInterval(2000)
        self.proactive_timer.timeout.connect(self._refresh_proactive_feed)

    # ---------- UI ----------
    def _init_ui(self, exec_err: Optional[str], mem_err: Optional[str], pdf_err: Optional[str]):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.status_label = QLabel("Status: booting…")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.status_label, 1)

        self.btn_refresh = QPushButton("Refresh Capabilities")
        self.btn_refresh.clicked.connect(self._refresh_capabilities)
        top.addWidget(self.btn_refresh)

        self.btn_pick_root = QPushButton("Set ELI Root…")
        self.btn_pick_root.clicked.connect(self._pick_root)
        top.addWidget(self.btn_pick_root)

        layout.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)

        # Left: quick actions + capabilities list
        left = QWidget()
        left_l = QVBoxLayout(left)

        self.quick_box = QGroupBox("Quick Actions")
        ql = QVBoxLayout(self.quick_box)

        # Quick buttons call executor actions; they are *resolved* at runtime.
        self.quick_buttons: Dict[str, QPushButton] = {}
        for label, action, args in [
            ("Time", "TIME", {}),
            ("List Capabilities", "LIST_CAPABILITIES", {"format": "json"}),
            ("Memory Stats", "MEMORY_STATS", {}),
            ("Memory Recall", "MEMORY_RECALL", {"n": 12}),
            ("Open File System", "OPEN_FILE_SYSTEM", {}),
            ("Open Network Browser", "OPEN_NETWORK_BROWSER", {}),
            ("Init Audio", "INIT_AUDIO", {}),
            ("Communication Hub", "COMMUNICATION_HUB", {}),
        ]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, a=action, ar=args: self._run_action(a, ar))
            self.quick_buttons[action] = b
            ql.addWidget(b)

        left_l.addWidget(self.quick_box)

        self.cap_list = QListWidget()
        self.cap_list.itemDoubleClicked.connect(self._cap_double_click)
        left_l.addWidget(QLabel("Capabilities (double‑click to run with empty args):"))
        left_l.addWidget(self.cap_list, 1)

        split.addWidget(left)

        # Right: tabs (Console / Memory / Proactive / PDFs)
        right = QTabWidget()
        split.addWidget(right)
        split.setStretchFactor(1, 2)

        # Console tab
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        right.addTab(self.console, "Console")

        # Memory tab
        mem_tab = QWidget()
        mem_l = QVBoxLayout(mem_tab)
        self.mem_search = QLineEdit()
        self.mem_search.setPlaceholderText("Search memory (FTS if available)…")
        self.mem_search.returnPressed.connect(self._memory_search)
        mem_l.addWidget(self.mem_search)

        self.mem_results = QTextEdit()
        self.mem_results.setReadOnly(True)
        mem_l.addWidget(self.mem_results, 1)

        mem_btns = QHBoxLayout()
        b_recent = QPushButton("Show Recent (20)")
        b_recent.clicked.connect(self._memory_recent)
        mem_btns.addWidget(b_recent)
        b_stats = QPushButton("Stats")
        b_stats.clicked.connect(lambda: self._run_action("MEMORY_STATS", {}))
        mem_btns.addWidget(b_stats)
        mem_l.addLayout(mem_btns)

        right.addTab(mem_tab, "Memory")

        # Proactive tab
        pro_tab = QWidget()
        pro_l = QVBoxLayout(pro_tab)

        self.chk_proactive = QCheckBox("Enable Proactive Feed (reads DB kind=proactive*)")
        self.chk_proactive.stateChanged.connect(self._toggle_proactive)
        pro_l.addWidget(self.chk_proactive)

        self.pro_feed = QTextEdit()
        self.pro_feed.setReadOnly(True)
        self.pro_feed.setPlaceholderText("When enabled, this shows latest proactive suggestions stored in memory DB.")
        pro_l.addWidget(self.pro_feed, 1)

        right.addTab(pro_tab, "Proactive")

        # PDFs tab
        pdf_tab = QWidget()
        pdf_l = QVBoxLayout(pdf_tab)

        self.pdf_drop = DropPDFWidget()
        self.pdf_drop.dropped_paths.connect(self._pdf_dropped)
        pdf_l.addWidget(QLabel("PDF Analysis Drop Zone"))
        pdf_l.addWidget(self.pdf_drop, 1)

        opts = QGroupBox("Options")
        fl = QFormLayout(opts)
        self.sp_max_pages = QSpinBox()
        self.sp_max_pages.setRange(0, 5000)
        self.sp_max_pages.setValue(0)
        self.sp_max_pages.setToolTip("0 = no limit")
        fl.addRow("Max pages:", self.sp_max_pages)

        self.chk_store_pdf = QCheckBox("Store extracted text to memory DB")
        self.chk_store_pdf.setChecked(True)
        fl.addRow(self.chk_store_pdf)

        pdf_l.addWidget(opts)

        b_pick = QPushButton("Pick PDF / Folder…")
        b_pick.clicked.connect(self._pick_pdf)
        pdf_l.addWidget(b_pick)

        self.pdf_out = QTextEdit()
        self.pdf_out.setReadOnly(True)
        pdf_l.addWidget(self.pdf_out, 1)

        right.addTab(pdf_tab, "PDFs")

        # Menu
        m = self.menuBar()
        filem = m.addMenu("File")
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        filem.addAction(act_quit)

        helpm = m.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._about)
        helpm.addAction(act_about)

        # Status errors
        errs = [x for x in [exec_err, mem_err, pdf_err] if x]
        if errs:
            self._log("Startup warnings:\n" + "\n".join(errs))
            self.status_label.setText("Status: running (with warnings)")
        else:
            self.status_label.setText("Status: running")

        self._log(f"ELI root: {self.root}")
        self._log(f"Memory DB: {self.db_path}")

    # ---------- helpers ----------
    def _log(self, msg: str):
        self.console.append(msg)

    def _about(self):
        QMessageBox.information(self, "ELI GUI",
                                "ELI Pro Audio GUI (PyQt6)\n\n"
                                "This GUI discovers actions from executor_enhanced at runtime and calls them reliably.\n"
                                "Proactive feed reads from the SQLite memory DB (entries table).")

    def _pick_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select ELI Root", str(self.root))
        if d:
            self.root = Path(d).expanduser().resolve()
            self.db_path = Path(os.environ.get("ELI_MEMORY_DB", str(self.root / "eli_memory.sqlite3"))).expanduser().resolve()
            self._log(f"Root set to: {self.root}")
            self._log(f"DB set to: {self.db_path}")

    def _refresh_capabilities(self):
        self.cap_list.clear()
        caps = []
        if self.execute:
            try:
                r = self.execute("LIST_CAPABILITIES", {"format": "json"})
                # r may already contain list, or JSON in content
                if isinstance(r, dict) and r.get("ok") and r.get("capabilities"):
                    caps = r["capabilities"]
                else:
                    # try parse content
                    txt = (r.get("content") if isinstance(r, dict) else "") or ""
                    try:
                        parsed = json.loads(txt)
                        caps = parsed.get("capabilities") or parsed
                    except Exception:
                        caps = []
            except Exception as e:
                self._log(f"LIST_CAPABILITIES failed: {type(e).__name__}: {e}")
        if not caps:
            # fallback: show the built-in quick action names
            caps = [{"action": k} for k in sorted(self.quick_buttons.keys())]

        for c in caps:
            a = c.get("action") if isinstance(c, dict) else str(c)
            it = QListWidgetItem(a)
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.cap_list.addItem(it)

    def _cap_double_click(self, item: QListWidgetItem):
        a = item.text().strip()
        self._run_action(a, {})

    def _run_action(self, action: str, args: Dict[str, Any]):
        if not self.execute:
            self._log("Executor not available (import failed).")
            return
        try:
            r = self.execute(action, dict(args))
            self._log(f"> {action} {args}")
            self._log(self._fmt_result(r))
        except Exception as e:
            self._log(f"ERROR executing {action}: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    def _fmt_result(self, r: Any) -> str:
        if isinstance(r, dict):
            if "content" in r and isinstance(r["content"], str):
                return r["content"]
            return json.dumps(r, indent=2, ensure_ascii=False)
        return str(r)

    # ---------- memory ----------
    def _memory_recent(self):
        if not self.MemoryDB:
            self.mem_results.setPlainText("memory_db not available.")
            return
        db = self.MemoryDB(self.db_path)
        rows = db.recent(20)
        self.mem_results.setPlainText(json.dumps(rows, indent=2, ensure_ascii=False))

    def _memory_search(self):
        if not self.MemoryDB:
            self.mem_results.setPlainText("memory_db not available.")
            return
        q = self.mem_search.text().strip()
        db = self.MemoryDB(self.db_path)
        rows = db.search(q, 30)
        self.mem_results.setPlainText(json.dumps(rows, indent=2, ensure_ascii=False))

    # ---------- proactive ----------
    def _toggle_proactive(self, state: int):
        self.proactive_enabled = (state == Qt.CheckState.Checked.value)
        if self.proactive_enabled:
            self.proactive_timer.start()
            self._refresh_proactive_feed()
            self._log("Proactive feed ON.")
        else:
            self.proactive_timer.stop()
            self._log("Proactive feed OFF.")

    def _refresh_proactive_feed(self):
        if not (self.proactive_enabled and self.MemoryDB):
            return
        db = self.MemoryDB(self.db_path)
        rows = db.search("proactive", 15)  # crude but works
        # Filter to kinds that start with 'proactive'
        rows = [r for r in rows if str(r.get("kind","")).startswith("proactive")]
        self.pro_feed.setPlainText(json.dumps(rows[:10], indent=2, ensure_ascii=False))

    # ---------- PDFs ----------
    def _pick_pdf(self):
        # Choose file or folder
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Pick input")
        msg.setText("Pick a PDF file or a folder?")
        b_file = msg.addButton("PDF File", QMessageBox.ButtonRole.AcceptRole)
        b_folder = msg.addButton("Folder", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == b_file:
            p, _ = QFileDialog.getOpenFileName(self, "Select PDF", str(self.root), "PDF Files (*.pdf)")
            if p:
                self._pdf_handle_paths([p])
        elif clicked == b_folder:
            d = QFileDialog.getExistingDirectory(self, "Select Folder", str(self.root))
            if d:
                self._pdf_handle_paths([d])

    def _pdf_dropped(self, paths: list):
        self._pdf_handle_paths(paths)

    def _pdf_handle_paths(self, paths: List[str]):
        self.pdf_out.clear()
        if not self.pdf_analyze:
            self.pdf_out.setPlainText("PDF analyzer not available. Ensure eli_tools/analyze_pdfs.py exists and pypdf is installed.")
            return

        max_pages = self.sp_max_pages.value()
        max_pages = None if max_pages == 0 else int(max_pages)

        for p in paths:
            pp = Path(p).expanduser().resolve()
            try:
                if pp.is_dir():
                    res = self.pdf_analyze_folder(pp, recursive=True, limit=None, max_pages=max_pages)
                    self.pdf_out.append(json.dumps(res, indent=2, ensure_ascii=False))
                else:
                    a = self.pdf_analyze(pp, max_pages=max_pages)
                    self.pdf_out.append(json.dumps({
                        "doc": a.doc.__dict__,
                        "warnings": a.warnings,
                        "preview": a.preview,
                        "chunks": len(a.chunks)
                    }, indent=2, ensure_ascii=False))
                    if self.chk_store_pdf.isChecked() and self.pdf_store and self.MemoryDB:
                        self.pdf_store(self.db_path, a, tags=["gui"])
                        self.pdf_out.append("Stored to memory DB.")
            except Exception as e:
                self.pdf_out.append(f"ERROR: {pp}\n{type(e).__name__}: {e}\n{traceback.format_exc()}")

def main():
    app = QApplication(sys.argv)
    w = ELIWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
