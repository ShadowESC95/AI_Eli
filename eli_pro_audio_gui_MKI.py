#!/usr/bin/env python3
"""
ELI - Entropic Logical Interpreter 
Professional Assistant Interface with Audio STT
"""

import sys
import os
import json
import threading
import time
from datetime import datetime
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import ELI modules
print("🚀 Initializing Entropic Logical Interpreter..." if "🚀 Initializing Entropic Logical Interpreter..." not in (None, "", "None") else "")
try:
    from eli_tools.router_enhanced import route
    from eli_tools.compat import execute
    from eli_tools import state as eli_state

    from eli_tools.audio_stt import start_audio_listening, stop_audio_listening, listen_for_command
    print("✅ Core systems engaged" if "✅ Core systems engaged" not in (None, "", "None") else "")
    print("✅ Neural routing matrix: ONLINE" if "✅ Neural routing matrix: ONLINE" not in (None, "", "None") else "")
    print("✅ Executor protocols: ACTIVE" if "✅ Executor protocols: ACTIVE" not in (None, "", "None") else "")
    print("✅ Audio STT subsystem: READY" if "✅ Audio STT subsystem: READY" not in (None, "", "None") else "")
except ImportError as e:
    print(f"❌ System initialization failed: {e}" if f"❌ System initialization failed: {e}" not in (None, "", "None") else "")
    sys.exit(1)

class ELIWorker(QThread):
    """Quantum execution thread for non-blocking operations"""
    execution_complete = pyqtSignal(dict)
    system_error = pyqtSignal(str)
    
    def __init__(self, action, args):
        super().__init__()
        self._threads = []  # keep QThread refs alive
        self.action = action
        self.args = args
        self.execution_id = f"EXEC-{int(time.time() * 1000)}"
    
    def run(self):
        try:
            print(f"[{self.execution_id}] Executing: {self.action}" if f"[{self.execution_id}] Executing: {self.action}" not in (None, "", "None") else "")
            print(f"[{self.execution_id}] Parameters: {self.args}" if f"[{self.execution_id}] Parameters: {self.args}" not in (None, "", "None") else "")
            
            # Execute command
            if self.action == 'CHAT':
                msg = (self.args or {}).get('message') or (self.args or {}).get('prompt') or self.text
                result = execute('CHAT', {'message': msg})
            else:
                result = execute(action=self.action, args=(self.args or {}))
            
            # Add execution metadata
            result['execution_id'] = self.execution_id
            result['timestamp'] = datetime.now().isoformat()
            
            self.execution_complete.emit(result)
            
        except Exception as e:
            error_data = {
                'ok': False,
                'error': str(e),
                'execution_id': self.execution_id,
                'timestamp': datetime.now().isoformat()
            }
            self.system_error.emit(json.dumps(error_data))

class ELIEntropicGUI(QMainWindow):
    """Main ELI Interface - Entropic Logical Interpreter"""
    
    def __init__(self):
        super().__init__()
        self._threads = []  # keep QThread refs alive (prevent GC crash)
        self._workers = []  # optional: keep worker objs alive too

        self.setWindowTitle("ELI - Entropic Logical Interpreter v3")
        self.setGeometry(100, 100, 1200, 850)
        
        # System state
        self.conversation_log = []
        self.system_status = "INITIALIZING"
        self.active_workers = 0
        self.start_time = datetime.now()
        self.audio_listening = False
        
        # Initialize UI
        self.init_ui()
        
        # Apply quantum theme
        self.apply_entropic_theme()
        
        # System startup
        QTimer.singleShot(500, self.system_startup)
        
        # Focus management
        QTimer.singleShot(1000, self.input_field.setFocus)
    
    def init_ui(self):
        """Initialize the user interface"""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Left panel - System dashboard
        self.init_left_panel(main_layout)
        
        # Right panel - Main interface
        self.init_right_panel(main_layout)
        
        # Status bar
        self.init_status_bar()
    
    def init_left_panel(self, main_layout):
        """Initialize left system dashboard panel"""
        left_panel = QFrame()
        left_panel.setFixedWidth(280)
        left_panel.setObjectName("leftPanel")
        
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(15)
        
        # ELI Logo and Title
        title_frame = QFrame()
        title_frame.setObjectName("titleFrame")
        title_layout = QVBoxLayout(title_frame)
        
        eli_logo = QLabel("◈ ELI ◈")
        eli_logo.setObjectName("eliLogo")
        eli_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(eli_logo)
        
        eli_title = QLabel("Entropic Logical\nInterpreter v3")
        eli_title.setObjectName("eliTitle")
        eli_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(eli_title)
        
        left_layout.addWidget(title_frame)
        
        # System status
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QVBoxLayout(status_frame)
        
        status_label = QLabel("SYSTEM STATUS")
        status_label.setObjectName("sectionTitle")
        status_layout.addWidget(status_label)
        
        self.status_indicator = QLabel("● INITIALIZING")
        self.status_indicator.setObjectName("statusIndicator")
        status_layout.addWidget(self.status_indicator)
        
        # System metrics
        metrics = [
            ("Neural Network", "SYNCHRONIZED"),
            ("Memory Cache", "OPTIMAL"),
            ("I/O Bandwidth", "STABLE"),
            ("Security", "ENCRYPTED"),
            ("Audio Input", "READY"),
        ]
        
        for metric, value in metrics:
            metric_frame = QFrame()
            metric_layout = QHBoxLayout(metric_frame)
            metric_layout.setContentsMargins(0, 5, 0, 5)
            
            metric_label = QLabel(metric)
            metric_label.setObjectName("metricLabel")
            metric_layout.addWidget(metric_label)
            
            metric_value = QLabel(value)
            metric_value.setObjectName("metricValue")
            metric_layout.addWidget(metric_value)
            
            status_layout.addWidget(metric_frame)
        
        left_layout.addWidget(status_frame)
        
        # Audio Control Panel
        audio_frame = QFrame()
        audio_frame.setObjectName("audioFrame")
        audio_layout = QVBoxLayout(audio_frame)
        
        audio_label = QLabel("AUDIO CONTROL")
        audio_label.setObjectName("sectionTitle")
        audio_layout.addWidget(audio_label)
        
        # Audio toggle button
        audio_toggle_frame = QFrame()
        audio_toggle_layout = QHBoxLayout(audio_toggle_frame)
        
        self.audio_button = QPushButton("🎤 OFF")
        self.audio_button.setObjectName("audioButton")
        self.audio_button.setCheckable(True)
        self.audio_button.toggled.connect(self.toggle_audio_input)
        self.audio_button.setToolTip("Toggle continuous voice listening")
        audio_toggle_layout.addWidget(self.audio_button)
        
        self.audio_status = QLabel("Voice: DISABLED")
        self.audio_status.setObjectName("audioStatus")
        audio_toggle_layout.addWidget(self.audio_status)
        
        audio_layout.addWidget(audio_toggle_frame)
        
        # Single voice command button
        voice_btn = QPushButton("🎤 Voice Command")
        voice_btn.setObjectName("quickButton")
        voice_btn.setToolTip("Activate single voice command")
        voice_btn.clicked.connect(self.listen_once_command)
        audio_layout.addWidget(voice_btn)
        
        left_layout.addWidget(audio_frame)
        
        # Quick Access Panel
        access_frame = QFrame()
        access_frame.setObjectName("accessFrame")
        access_layout = QVBoxLayout(access_frame)
        
        access_label = QLabel("QUICK ACCESS")
        access_label.setObjectName("sectionTitle")
        access_layout.addWidget(access_label)
        
        # Quick action buttons
        quick_actions = [
            ("🌐", "Network Browser", self.quick_browser, "Launch quantum browser"),
            ("🎵", "Audio Interface", self.quick_spotify, "Access sonic database"),
            ("📧", "Communication Hub", self.quick_email, "Open message matrix"),
            ("📄", "Data Fabricator", self.quick_document, "Create new data construct"),
            ("📁", "File System", self.quick_files, "Access storage matrix"),
            ("🔍", "Information Scan", self.quick_search, "Initiate data probe"),
            ("⏰", "Temporal Node", self.quick_time, "Check chronal alignment"),
            ("💾", "Memory Recall", self.quick_memory, "Access neural archive"),
        ]
        
        for icon, text, callback, tooltip in quick_actions:
            btn = QPushButton(f"{icon} {text}")
            btn.setObjectName("quickButton")
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            access_layout.addWidget(btn)
        
        left_layout.addWidget(access_frame)
        
        # System time
        time_frame = QFrame()
        time_layout = QVBoxLayout(time_frame)
        
        self.system_time = QLabel("00:00:00")
        self.system_time.setObjectName("systemTime")
        self.system_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_layout.addWidget(self.system_time)
        
        self.system_date = QLabel("YYYY-MM-DD")
        self.system_date.setObjectName("systemDate")
        self.system_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_layout.addWidget(self.system_date)
        
        left_layout.addWidget(time_frame)
        left_layout.addStretch()
        
        main_layout.addWidget(left_panel)
    
    def init_right_panel(self, main_layout):
        """Initialize right main interface panel"""
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(15)
        
        # Conversation header
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        
        conversation_title = QLabel("NEURAL INTERFACE CONSOLE")
        conversation_title.setObjectName("consoleTitle")
        header_layout.addWidget(conversation_title)
        
        header_layout.addStretch()
        
        # Active processes indicator
        self.process_indicator = QLabel("◌ IDLE")
        self.process_indicator.setObjectName("processIndicator")
        header_layout.addWidget(self.process_indicator)
        
        right_layout.addWidget(header_frame)
        
        # Conversation display
        self.conversation_display = QTextEdit()
        self.conversation_display.setObjectName("conversationDisplay")
        self.conversation_display.setReadOnly(True)
        right_layout.addWidget(self.conversation_display, 1)
        
        # Input area
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_layout = QVBoxLayout(input_frame)
        
        input_label = QLabel("ENTROPIC INPUT STREAM")
        input_label.setObjectName("inputLabel")
        input_layout.addWidget(input_label)
        
        input_row = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Enter command stream... (e.g., 'access network browser', 'query meaning of existence', 'fabricate document')")
        self.input_field.returnPressed.connect(self.process_input_stream)
        input_row.addWidget(self.input_field, 1)
        
        self.execute_button = QPushButton("EXECUTE")
        self.execute_button.setObjectName("executeButton")
        self.execute_button.clicked.connect(self.process_input_stream)
        input_row.addWidget(self.execute_button)
        
        input_layout.addLayout(input_row)
        
        right_layout.addWidget(input_frame)
        
        # Command suggestions
        suggestions_frame = QFrame()
        suggestions_layout = QHBoxLayout(suggestions_frame)
        
        suggestion_label = QLabel("QUICK COMMANDS:")
        suggestion_label.setObjectName("suggestionLabel")
        suggestions_layout.addWidget(suggestion_label)
        
        suggestions = [
            ("access network", "access network browser"),
            ("initiate audio", "initiate audio interface"),
            ("fabricate document", "fabricate data construct"),
            ("scan information", "scan information database"),
            ("query existence", "what's the meaning of life?"),
            ("check chronal", "check chronal alignment"),
        ]
        
        for text, cmd in suggestions:
            btn = QPushButton(text)
            btn.setObjectName("suggestionButton")
            btn.clicked.connect(lambda checked, c=cmd: self.input_field.setText(c))
            suggestions_layout.addWidget(btn)
        
        suggestions_layout.addStretch()
        right_layout.addWidget(suggestions_frame)
        
        main_layout.addWidget(right_panel, 1)
    
    def init_status_bar(self):
        """Initialize status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # System info
        self.system_info = QLabel(f"ELI v2.2 | Quantum State: STABLE | Uptime: 00:00:00")
        self.status_bar.addWidget(self.system_info)
        
        # Memory usage
        self.memory_display = QLabel("Memory: --/-- MB")
        self.status_bar.addPermanentWidget(self.memory_display)
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_system_info)
        self.update_timer.start(1000)
    
    def apply_entropic_theme(self):
        """Apply the entropic quantum theme"""
        self.setStyleSheet("""
            /* Main window */
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e14, stop:1 #151b26);
            }
            
            /* Left panel */
            #leftPanel {
                background-color: rgba(10, 14, 20, 0.9);
                border-right: 1px solid #1e2532;
            }
            
            /* Title frame */
            #titleFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a5fb4, stop:1 #26a269);
                border-radius: 8px;
                padding: 15px;
            }
            
            /* ELI logo */
            #eliLogo {
                color: white;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            
            /* ELI title */
            #eliTitle {
                color: white;
                font-size: 14px;
                font-weight: bold;
                font-family: 'Arial';
            }
            
            /* Section titles */
            #sectionTitle {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 5px;
            }
            
            /* Status frame */
            #statusFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            
            /* Status indicator */
            #statusIndicator {
                color: #f6d32d;
                font-size: 13px;
                font-weight: bold;
                font-family: 'Monospace';
                margin-bottom: 15px;
            }
            
            /* Metric labels */
            #metricLabel {
                color: #88c0d0;
                font-size: 11px;
            }
            
            #metricValue {
                color: #a3be8c;
                font-size: 11px;
                font-weight: bold;
            }
            
            /* Audio frame */
            #audioFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            
            /* Audio button */
            #audioButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #d8dee9;
                border: 1px solid #4c566a;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                min-width: 80px;
            }
            
            #audioButton:checked {
                background-color: rgba(191, 97, 106, 0.8);
                color: white;
                border: 1px solid #bf616a;
            }
            
            #audioButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
            }
            
            /* Audio status */
            #audioStatus {
                color: #88c0d0;
                font-size: 10px;
                font-family: 'Monospace';
            }
            
            /* Access frame */
            #accessFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            
            /* Quick buttons */
            #quickButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #d8dee9;
                border: 1px solid #4c566a;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
                text-align: left;
                margin: 2px;
            }
            
            #quickButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
                border: 1px solid #5e81ac;
            }
            
            #quickButton:pressed {
                background-color: rgba(94, 129, 172, 0.8);
            }
            
            /* System time */
            #systemTime {
                color: #81a1c1;
                font-size: 18px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            
            #systemDate {
                color: #88c0d0;
                font-size: 12px;
                font-family: 'Monospace';
            }
            
            /* Console title */
            #consoleTitle {
                color: #5e81ac;
                font-size: 14px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            /* Process indicator */
            #processIndicator {
                color: #a3be8c;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            
            /* Conversation display */
            #conversationDisplay {
                background-color: rgba(10, 14, 20, 0.8);
                border: 1px solid #2d3748;
                border-radius: 6px;
                color: #d8dee9;
                font-family: 'Consolas', 'Monospace';
                font-size: 12px;
                padding: 15px;
                selection-background-color: #4c566a;
            }
            
            /* Input frame */
            #inputFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            
            /* Input label */
            #inputLabel {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
            }
            
            /* Input field */
            #inputField {
                background-color: rgba(10, 14, 20, 0.9);
                border: 2px solid #3b4252;
                border-radius: 4px;
                color: #e5e9f0;
                font-size: 13px;
                padding: 10px;
                font-family: 'Monospace';
            }
            
            #inputField:focus {
                border: 2px solid #5e81ac;
                background-color: rgba(10, 14, 20, 1);
            }
            
            /* Execute button */
            #executeButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a5fb4, stop:1 #26a269);
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            #executeButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2d7ad1, stop:1 #38b87c);
            }
            
            #executeButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #154d8c, stop:1 #1d8a5c);
            }
            
            /* Suggestion label */
            #suggestionLabel {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                margin-right: 10px;
            }
            
            /* Suggestion buttons */
            #suggestionButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #88c0d0;
                border: 1px solid #4c566a;
                border-radius: 3px;
                padding: 5px 10px;
                font-size: 10px;
                margin: 0 3px;
            }
            
            #suggestionButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
                color: #d8dee9;
            }
            
            /* Status bar */
            QStatusBar {
                background-color: rgba(10, 14, 20, 0.9);
                color: #88c0d0;
                font-size: 10px;
                border-top: 1px solid #1e2532;
            }
            
            QStatusBar QLabel {
                color: #88c0d0;
                font-size: 10px;
                font-family: 'Monospace';
            }
        """)
    
    def system_startup(self):
        """System startup sequence"""
        self.add_system_message("SYSTEM", "Entropic Logical Interpreter v3", "#5e81ac")
        self.add_system_message("SYSTEM", "Initializing quantum neural matrix...", "#88c0d0")
        
        # Simulate startup sequence
        QTimer.singleShot(800, lambda: self.add_system_message("BOOT", "✓ Core protocols loaded", "#a3be8c"))
        QTimer.singleShot(1200, lambda: self.add_system_message("BOOT", "✓ Memory cache initialized", "#a3be8c"))
        QTimer.singleShot(1600, lambda: self.add_system_message("BOOT", "✓ I/O channels established", "#a3be8c"))
        QTimer.singleShot(2000, lambda: self.add_system_message("BOOT", "✓ Security encryption active", "#a3be8c"))
        QTimer.singleShot(2400, lambda: self.add_system_message("BOOT", "✓ Audio STT subsystem ready", "#a3be8c"))
        
        QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
        QTimer.singleShot(3100, lambda: self.add_system_message("SYSTEM", "Ready for entropic input stream", "#5e81ac"))
        QTimer.singleShot(3200, lambda: self.add_system_message("AUDIO", "Voice commands available. Say 'ELI' followed by command.", "#88c0d0"))
    
    def set_system_status(self, status):
        """Update system status"""
        self.system_status = status
        colors = {
            "INITIALIZING": "#f6d32d",
            "OPERATIONAL": "#a3be8c",
            "PROCESSING": "#5e81ac",
            "ERROR": "#bf616a"
        }
        color = colors.get(status, "#d8dee9")
        self.status_indicator.setText(f"● {status}")
        self.status_indicator.setStyleSheet(f"color: {color};")
    
    def add_system_message(self, source, message, color="#d8dee9"):
        """Add system message to conversation"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        html = f"""
        <div style="margin: 8px 0;">
            <span style="color: {color}; font-weight: bold; font-family: 'Monospace';">[{timestamp}] {source}</span>
            <div style="color: {color}; margin-left: 20px; font-family: 'Monospace';">{message}</div>
        </div>
        """
        
        self.conversation_display.append(html)
        self.conversation_display.ensureCursorVisible()
        
        # Log conversation
        self.conversation_log.append({
            'timestamp': timestamp,
            'source': source,
            'message': message,
            'color': color
        })
    
    def update_system_info(self):
        """Update system information displays"""
        # Update time
        current_time = datetime.now()
        self.system_time.setText(current_time.strftime("%H:%M:%S"))
        self.system_date.setText(current_time.strftime("%Y-%m-%d"))
        
        # Update uptime
        uptime = current_time - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # Update status bar
        self.system_info.setText(f"ELI v2.2 | Quantum State: {self.system_status} | Uptime: {uptime_str}")
        
        # Simulate memory usage
        import random
        mem_used = random.randint(200, 400)
        mem_total = 1024
        self.memory_display.setText(f"Memory: {mem_used}/{mem_total} MB")
    
    def process_input_stream(self):
        """Process user input stream"""
        user_input = self.input_field.text().strip()
        if not user_input:
            return
        
        # Add user input to display
        self.add_system_message("USER", user_input, "#e5e9f0")
        self.input_field.clear()
        
        # Update system state
        self.set_system_status("PROCESSING")
        self.active_workers += 1
        self.process_indicator.setText(f"◉ PROCESSING ({self.active_workers})")
        self.execute_button.setEnabled(False)
        
        try:
            # Route the input
            print(f"[ELI] Processing: '{user_input}'" if f"[ELI] Processing: '{user_input}'" not in (None, "", "None") else "")
            routed = route(user_input)
            action = routed['action']
            args = routed.get('args', {})
            
            print(f"[ELI] Routed to: {action}" if f"[ELI] Routed to: {action}" not in (None, "", "None") else "")
            self.add_system_message("ROUTER", f"→ {action.upper()}", "#88c0d0")
            
            # Execute in worker thread
            self.worker = ELIWorker(action, args)
            self.worker.execution_complete.connect(self.handle_execution_result)
            self.worker.system_error.connect(self.handle_system_error)
            if not hasattr(self, "_threads"): self._threads = []
            self._threads.append(self.worker)
            try:
                self.worker.finished.connect(lambda w=self.worker: self._threads.remove(w) if w in self._threads else None)
            except Exception:
                pass
            self._threads.append(self.worker)
            self.worker.finished.connect(lambda: self._threads.remove(self.worker) if self.worker in self._threads else None)
            self.worker.start()
            self._threads.append(self.worker)
            self.worker.finished.connect(lambda: self._threads.remove(self.worker) if self.worker in self._threads else None)
        except Exception as e:
            self.handle_system_error(json.dumps({
                'ok': False,
                'error': f"Routing error: {str(e)}",
                'execution_id': f"ERR-{int(time.time() * 1000)}",
                'timestamp': datetime.now().isoformat()
            }))
    
    def handle_execution_result(self, result):
        """Handle execution result"""
        self.active_workers = max(0, self.active_workers - 1)
        self.execute_button.setEnabled(True)
        
        execution_id = result.get('execution_id', 'UNKNOWN')
        
        if result.get('ok', False):
            self.set_system_status("OPERATIONAL")
            self.process_indicator.setText(f"◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
            
            # Format and display result
            response = self.format_eli_response(result)
            self.add_system_message("ELI", response, "#a3be8c")
            
            # Log execution
        else:
            self.handle_system_error(json.dumps(result))
    
    def handle_system_error(self, error_json):
        """Handle system error"""
        self.active_workers = max(0, self.active_workers - 1)
        self.set_system_status("ERROR")
        self.process_indicator.setText(f"◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
        self.execute_button.setEnabled(True)
        
        try:
            error_data = json.loads(error_json)
            execution_id = error_data.get('execution_id', 'UNKNOWN')
            error_msg = (error_data.get('error') or error_data.get('response') or error_data.get('message') or 'Unknown error')
            
            self.add_system_message("ERROR", f"Execution {execution_id} failed: {error_msg}", "#bf616a")
            QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
            
        except:
            self.add_system_message("ERROR", f"System error: {error_json}", "#bf616a")
            QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
    
    def format_eli_response(self, result):
        """Format ELI response with professional styling"""
        if 'response' in result:
            return result['response']
        elif 'message' in result:
            return result['message']
        elif 'result' in result:
            return f"Result: {result['result']}"
        elif 'time' in result:
            return f"Chronal alignment: {result['time']}"
        elif 'date' in result:
            return f"Temporal coordinate: {result['date']}"
        elif 'files' in result:
            files = result['files'][:8]
            return f"Storage matrix contains {len(result['files'])} entities:\n" + "\n".join(f"  ├ {f}" for f in files) + "\n  └ ..." if len(result['files']) > 8 else ""
        else:
            pass
    
    def toggle_audio_input(self, checked):
        """Toggle audio input on/off."""
        if checked:
            # Start audio listening
            self.audio_button.setText("🎤 ON")
            self.audio_status.setText("Voice: LISTENING")
            self.audio_status.setStyleSheet("color: #a3be8c;")
            
            # Start audio listening with callback
            def audio_callback(transcript):
                # Add audio input to conversation
                self.add_system_message("VOICE", transcript, "#d08770")
                # Process the audio command
                self.input_field.setText(transcript)
                self.process_input_stream()
            
            start_audio_listening(audio_callback)
            self.audio_listening = True
            self.add_system_message("AUDIO", "Continuous voice input activated. Say 'ELI' followed by your command.", "#88c0d0")
        else:
            # Stop audio listening
            self.audio_button.setText("🎤 OFF")
            self.audio_status.setText("Voice: DISABLED")
            self.audio_status.setStyleSheet("color: #88c0d0;")
            
            stop_audio_listening()
            self.audio_listening = False
            self.add_system_message("AUDIO", "Continuous voice input deactivated", "#88c0d0")
    
    def listen_once_command(self):
        # --- safety: avoid microphone re-entry (continuous + one-shot) ---
        was_continuous = bool(getattr(self, 'audio_listening', False))
        if was_continuous:
            try:
                stop_audio_listening()
            except Exception:
                pass
            self.audio_listening = False
            try:
                self.audio_button.setChecked(False)
            except Exception:
                pass
        # -----------------------------------------------------------------
        """Listen for a single command."""
        self.add_system_message("AUDIO", "Listening for voice command...", "#88c0d0")
        
        # Disable audio button during listening
        self.audio_button.setEnabled(False)
        self.audio_button.setText("🎤 ...")
        self.audio_status.setText("Voice: ACTIVE")
        
        def listen_thread():
            transcript = listen_for_command(timeout=10)
            if transcript:
                # Process on main thread
                QTimer.singleShot(0, lambda: self.process_audio_transcript(transcript))
            else:
                QTimer.singleShot(0, self.audio_listen_failed)
        
        threading.Thread(target=listen_thread, daemon=True).start()
    
    def process_audio_transcript(self, transcript):
        """Process audio transcript."""
        self.audio_button.setEnabled(True)
        self.audio_button.setText("🎤 OFF")
        self.audio_button.setChecked(False)
        self.audio_status.setText("Voice: DISABLED")
        
        self.add_system_message("VOICE", transcript, "#d08770")
        self.input_field.setText(transcript)
        self.process_input_stream()
    
    def audio_listen_failed(self):
        """Handle failed audio listening."""
        self.audio_button.setEnabled(True)
        self.audio_button.setText("🎤 OFF")
        self.audio_button.setChecked(False)
        self.audio_status.setText("Voice: DISABLED")
        self.add_system_message("AUDIO", "Could not understand audio command", "#bf616a")
    
    # Quick action methods
    def quick_browser(self):
        self.input_field.setText("access network browser")
        self.process_input_stream()
    
    def quick_spotify(self):
        self.input_field.setText("initiate audio interface")
        self.process_input_stream()
    
    def quick_email(self):
        self.input_field.setText("access communication hub")
        self.process_input_stream()
    
    def quick_document(self):
        self.input_field.setText("fabricate data construct")
        self.process_input_stream()
    
    def quick_files(self):
        self.input_field.setText("access storage matrix")
        self.process_input_stream()
    
    def quick_search(self):
        text, ok = QInputDialog.getText(self, "Information Scan", "Enter search query:")
        if ok and text:
            self.input_field.setText(f"scan information database for {text}")
            self.process_input_stream()
    
    def quick_time(self):
        self.input_field.setText("check chronal alignment")
        self.process_input_stream()
    
    def quick_memory(self):
        self.input_field.setText("access neural archive")
        self.process_input_stream()
    
    def closeEvent(self, event):
        """Handle window close event."""
        if self.audio_listening:
            stop_audio_listening()
        
        # Save conversation log
        if self.conversation_log:
            log_file = f"eli_conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            try:
                with open(log_file, 'w') as f:
                    json.dump(self.conversation_log, f, indent=2)
                print(f"[ELI] Conversation log saved to {log_file}" if f"[ELI] Conversation log saved to {log_file}" not in (None, "", "None") else "")
            except:
                pass
        
        event.accept()

def main():
    """Main entry point."""
    print("\n" + "="*60 if "\n" + "="*60 not in (None, "", "None") else "")
    print("        ELI - Entropic Logical Interpreter v3" if "        ELI - Entropic Logical Interpreter v3" not in (None, "", "None") else "")
    print("        Professional Assistant with Audio STT" if "        Professional Assistant with Audio STT" not in (None, "", "None") else "")
    print("="*60 + "\n" if "="*60 + "\n" not in (None, "", "None") else "")
    
    # Check for required dependencies
    try:
        import PyQt6
    except ImportError:
        print("❌ PyQt6 is required. Install with: pip install PyQt6" if "❌ PyQt6 is required. Install with: pip install PyQt6" not in (None, "", "None") else "")
        sys.exit(1)
    
    # Initialize Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("ELI Entropic Interpreter")
    app.setOrganizationName("Entropic Labs")
    
    # Set font
    font = QFont("Consolas", 10)
    app.setFont(font)
    
    # Create and show main window
    window = ELIEntropicGUI()
    window.show()
    
    # Print startup info
    print("✅ Quantum interface initialized" if "✅ Quantum interface initialized" not in (None, "", "None") else "")
    print("✅ Audio STT subsystem engaged" if "✅ Audio STT subsystem engaged" not in (None, "", "None") else "")
    print("✅ Ready for entropic input stream\n" if "✅ Ready for entropic input stream\n" not in (None, "", "None") else "")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
