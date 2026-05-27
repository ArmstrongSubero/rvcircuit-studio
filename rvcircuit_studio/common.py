# Copyright 2026 Armstrong Subero
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
import platform
import re
import shutil
import sys
import time

from PySide6.QtCore import (QDir, QEvent, QSortFilterProxyModel, QThread,
                             QTimer, QUrl, Qt, Signal, Slot, QSize)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon,
                            QKeyEvent, QKeySequence, QPalette, QPixmap,
                            QSyntaxHighlighter, QTextCharFormat, QTextCursor,
                            QAction, QShortcut)
from PySide6.QtWidgets import *

try:
    from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
    HAS_QSERIALPORT = True
except ImportError:
    HAS_QSERIALPORT = False

try:
    from qutepart import Qutepart
    from qutepart.sideareas import *
    from qutepart.sideareas import MarkArea
    from qutepart.syntax import SyntaxManager
except ImportError:
    from .qutepart import Qutepart
    from .qutepart.sideareas import *
    from .qutepart.sideareas import MarkArea
    from .qutepart.syntax import SyntaxManager

logging.basicConfig(level=logging.WARNING)
_logger = logging.getLogger('qutepart')
_logger.setLevel(logging.WARNING)

CS_BG_DEEP        = "#0D1117"
CS_BG_TOOLBAR     = "#161B22"
CS_SURFACE        = "#1C2128"
CS_PRIMARY        = "#238636"
CS_PRIMARY_HOVER  = "#2EA043"
CS_PRIMARY_PRESS  = "#196127"
CS_ACCENT         = "#58A6FF"
CS_ACCENT_SOFT    = "#30363D"
CS_TEXT           = "#C9D1D9"
CS_TEXT_BRIGHT    = "#FFFFFF"
CS_TEXT_MUTED     = "#8B949E"
CS_SUCCESS        = "#3FB950"
CS_WARNING        = "#D29922"
CS_DANGER         = "#F85149"

SCROLLBAR_STYLESHEET = f"""
QScrollBar:vertical {{
    border: none; background: {CS_BG_DEEP}; width: 20px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {CS_SURFACE}; min-height: 20px; border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {CS_ACCENT_SOFT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none; background: none;
}}
QScrollBar:horizontal {{
    border: none; background: {CS_BG_DEEP}; height: 10px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {CS_SURFACE}; min-width: 20px; border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{ background: {CS_ACCENT_SOFT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none; background: none;
}}
"""

GLOBAL_STYLE = f"""
QWidget {{
    background-color: {CS_BG_DEEP};
    font-family: 'JetBrains Mono';
    font-size: 10pt;
    color: {CS_TEXT};
}}
QLineEdit {{
    border: 1px solid {CS_ACCENT_SOFT}; padding: 5px;
    border-radius: 4px; background-color: {CS_SURFACE}; color: {CS_TEXT};
}}
QLineEdit:focus {{ border: 1px solid {CS_ACCENT}; }}
QPushButton {{
    background-color: {CS_PRIMARY}; border: none; color: {CS_TEXT_BRIGHT};
    padding: 6px 15px; border-radius: 4px; font-size: 10px;
}}
QPushButton:hover {{ background-color: {CS_PRIMARY_HOVER}; }}
QPushButton:pressed {{ background-color: {CS_PRIMARY_PRESS}; }}
QToolBar {{
    background-color: {CS_BG_TOOLBAR};
    border-bottom: 1px solid {CS_SURFACE};
    spacing: 2px; padding: 3px 8px;
}}
QToolBar::separator {{
    width: 1px;
    background: qlineargradient(y1:0, y2:1, stop:0 transparent,
                stop:0.5 {CS_ACCENT_SOFT}, stop:1 transparent);
    margin: 4px 6px;
}}
QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 5px; padding: 4px; margin: 1px;
}}
QToolButton:hover {{
    background: rgba(88,166,255,0.12); border: 1px solid rgba(88,166,255,0.2);
}}
QToolButton:pressed {{ background: rgba(88,166,255,0.22); }}
QToolButton:checked {{
    background: rgba(88,166,255,0.10); border: 1px solid rgba(88,166,255,0.25);
}}
QMenuBar {{
    background-color: {CS_BG_TOOLBAR}; border-bottom: 1px solid {CS_SURFACE};
}}
QMenuBar::item:selected {{
    background: rgba(88,166,255,0.15); border-radius: 3px;
}}
QMenu {{
    background-color: {CS_BG_TOOLBAR}; border: 1px solid {CS_SURFACE};
    border-radius: 4px; padding: 4px;
}}
QMenu::item:selected {{
    background: rgba(88,166,255,0.15); border-radius: 3px;
}}
QTabWidget::tab-bar {{ left: 5px; }}
QTabBar::tab {{
    padding: 5px 12px; border: 1px solid {CS_ACCENT_SOFT};
    border-radius: 4px; margin-left: 3px;
    background-color: {CS_SURFACE}; color: {CS_TEXT};
}}
QTabBar::tab:hover {{ background-color: rgba(88,166,255,0.10); }}
QTabBar::tab:selected {{
    background-color: {CS_ACCENT}; color: {CS_BG_DEEP};
    border-color: {CS_ACCENT}; font-weight: bold;
}}
QTextEdit, QTreeView {{
    border: 1px solid {CS_ACCENT_SOFT}; border-radius: 4px;
    background-color: {CS_SURFACE}; color: {CS_TEXT};
}}
QTextEdit:focus, QTreeView:focus {{ border: 1px solid {CS_ACCENT}; }}
QPlainTextEdit {{ background-color: {CS_BG_DEEP}; border: none; }}
QSplitter::handle {{ background: {CS_ACCENT_SOFT}; }}
QSplitter::handle:hover {{ background: {CS_ACCENT}; }}
QLabel {{ color: {CS_TEXT}; }}
QComboBox {{
    background-color: {CS_SURFACE}; border: 1px solid {CS_ACCENT_SOFT};
    border-radius: 4px; padding: 3px 8px; color: {CS_ACCENT}; min-height: 22px;
}}
QComboBox:hover {{ border-color: {CS_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {CS_TEXT_MUTED};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {CS_BG_TOOLBAR}; border: 1px solid {CS_SURFACE};
    selection-background-color: rgba(88,166,255,0.2);
    selection-color: {CS_ACCENT}; border-radius: 4px;
}}
QStatusBar {{
    background-color: {CS_BG_TOOLBAR}; color: {CS_TEXT_MUTED};
    font-size: 10px; border-top: 1px solid {CS_ACCENT_SOFT};
}}
QToolTip {{
    background-color: {CS_SURFACE}; border: 1px solid {CS_ACCENT_SOFT};
    color: {CS_TEXT}; border-radius: 4px; padding: 6px 10px; font-size: 12px;
}}
QDialog {{ background-color: {CS_BG_DEEP}; }}
QGroupBox {{
    border: 1px solid {CS_ACCENT_SOFT}; border-radius: 4px;
    margin-top: 12px; padding-top: 12px;
}}
QGroupBox::title {{
    color: {CS_ACCENT}; subcontrol-origin: margin; left: 10px; padding: 0 5px;
}}
"""

