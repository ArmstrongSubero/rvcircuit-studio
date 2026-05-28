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

from .common import *

class FoldedSection:
    def __init__(self, start_line, end_line, content):
        self.start_line = start_line
        self.end_line = end_line
        self.content = content

class CodeEditorWindow(Qutepart):
    def __init__(self, *args):
        super(CodeEditorWindow, self).__init__(*args)

        palette = self.palette()
        self._currentLineColor = QColor(CS_SURFACE)
        palette.setColor(QPalette.ColorRole.Base, QColor(CS_BG_DEEP))
        palette.setColor(QPalette.ColorRole.Text, QColor(CS_TEXT))
        self.setPalette(palette)

        self._zoomFactor = 1

        try:
            import json as _j
            _p = os.path.join(os.path.dirname(__file__), "data", "circuit_studio_config.json")
            self.zoom_level = int(_j.load(open(_p)).get("editor", {}).get("font_size", 10)) if os.path.exists(_p) else 10
        except Exception:
            self.zoom_level = 10
        self.set_zoom_font()

        self.folded_sections = []

        self.installEventFilter(self)

        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.setShortcut(QKeySequence("Ctrl+="))
        self.zoom_in_action.triggered.connect(self.zoom_in)
        self.addAction(self.zoom_in_action)

        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.triggered.connect(self.zoom_out)
        self.addAction(self.zoom_out_action)

        self.ctrl_pressed = False
        

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Control:
                    self.ctrl_pressed = True
                elif self.ctrl_pressed and event.key() == Qt.Key.Key_F:
                    if hasattr(self, 'toggle_code_folding'):
                        self.toggle_code_folding()
                    return True
                elif self.ctrl_pressed and event.key() == Qt.Key.Key_R:
                    if hasattr(self, 'toggle_block_comment'):
                        self.toggle_block_comment()
                    return True
                elif self.ctrl_pressed and event.key() == Qt.Key.Key_Plus:
                    if hasattr(self, 'zoom_in'):
                        self.zoom_in()
                    return True
                elif self.ctrl_pressed and event.key() == Qt.Key.Key_Minus:
                    if hasattr(self, 'zoom_out'):
                        self.zoom_out()
                    return True
            elif event.type() == QEvent.Type.KeyRelease:
                if event.key() == Qt.Key.Key_Control:
                    self.ctrl_pressed = False
        except Exception as e:
            print(f"Error encountered in eventFilter: {e}")
        return super(CodeEditorWindow, self).eventFilter(obj, event)

    def set_zoom_font(self):
        font = self.font()
        font.setPointSize(self.zoom_level)
        self.setFont(font)

    def _save_font_size(self):
        try:
            import json as _j
            _p = os.path.join(os.path.dirname(__file__), "data", "circuit_studio_config.json")
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            cfg = _j.load(open(_p)) if os.path.exists(_p) else {}
            cfg.setdefault("editor", {})["font_size"] = self.zoom_level
            _j.dump(cfg, open(_p, "w"), indent=2)
        except Exception:
            pass

    def zoom_in(self):
        self.zoom_level += 1
        self._apply_zoom_globally()

    def zoom_out(self):
        self.zoom_level = max(1, self.zoom_level - 1)
        self._apply_zoom_globally()

    def _apply_zoom_globally(self):
        """Apply zoom_level to ALL open editor tabs, then save."""
        self._save_font_size()
        w = self.parent()
        while w is not None:
            if hasattr(w, 'apply_font_size_to_all_tabs'):
                w.apply_font_size_to_all_tabs(self.zoom_level)
                return
            w = w.parent()
        self.set_zoom_font()

    def fold_selected_text(self):
        cursor = self.textCursor()
        
        if cursor.hasSelection():
            start_pos = cursor.selectionStart()
            end_pos = cursor.selectionEnd()

            start_block = self.document().findBlock(start_pos)
            end_block = self.document().findBlock(end_pos)

            start_line = start_block.blockNumber()
            end_line = end_block.blockNumber()

            selected_text = cursor.selectedText()
            first_line = start_block.text().strip()

            cursor.removeSelectedText()
            cursor.insertText(f"// {first_line}\n... FOLDED ...")

            fold = FoldedSection(start_line, end_line, selected_text)
            self.folded_sections.append(fold)

    def toggle_code_folding(self):
        cursor = self.textCursor()
        current_block = cursor.block()
        current_line_text = current_block.text().strip()

        if "... FOLDED ..." in current_line_text:
            self.unfold_at_cursor()
        elif cursor.hasSelection():
            self.fold_selected_text()

    def unfold_at_cursor(self):
        cursor = self.textCursor()
        current_block = cursor.block()
        current_line = current_block.blockNumber()

        folded_section = next((fold for fold in self.folded_sections if fold.start_line <= current_line and fold.end_line >= current_line), None)

        if folded_section:
            cursor.setPosition(current_block.position())

            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)

            if cursor.selectedText() == "... FOLDED ...":
                cursor.removeSelectedText()

                cursor.movePosition(QTextCursor.MoveOperation.Up, QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()

                cursor.insertText(folded_section.content)

                self.folded_sections.remove(folded_section)

    def toggle_block_comment(self):
        cursor = self.textCursor()

        if not cursor.hasSelection():
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
            
        selected_text = cursor.selectedText()
        lines = selected_text.split('\u2029')

        all_commented = all(line.strip().startswith("//") for line in lines)

        if all_commented:
            uncommented_lines = [line[2:] if line.startswith("//") else line for line in lines]
            cursor.insertText('\n'.join(uncommented_lines))
        else:
            commented_lines = ["//"+line for line in lines]
            cursor.insertText('\n'.join(commented_lines))

class EditorWidget(QWidget):
    
    def __init__(self, parent=None):
        super(EditorWidget, self).__init__(parent)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(0)
        
        self.vimModeIndication = QLabel()
        self.vimModeIndication.setAutoFillBackground(True)
        self.layout.addWidget(self.vimModeIndication)
        
        self.qpart = CodeEditorWindow()
        self.qpart.vimModeEnabled = False
        self.layout.addWidget(self.qpart)

        self.qpart.vimModeIndicationChanged.connect(self.onVimModeChanged)
        self.qpart.textChanged.connect(self.on_content_changed)

        self._modified = False 
        self.current_file = None

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave) 
        self.autosave_interval = 300000
        self.autosave_timer.start(self.autosave_interval)

    def is_Modified(self):
        return self._modified 

    def on_content_changed(self):
        self._modified = True 

    def onVimModeChanged(self, color, text):
        if color is not None:
            palette = self.vimModeIndication.palette()
            palette.setColor(QPalette.Window, color)
            self.vimModeIndication.setPalette(palette)
            self.vimModeIndication.setText(text)

    def openFile(self, filepath):
        if os.path.isdir(filepath):
            return

        try:
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
            except UnicodeDecodeError:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as file:
                    content = file.read()

            self.qpart.setPlainText(content)

            try:
                firstLine = content.splitlines()[0] if content else None
                syntax_path = filepath
                if filepath.lower().endswith('.rova'):
                    syntax_path = filepath[:-5] + '.cpp'
                self.qpart.detectSyntax(sourceFilePath=syntax_path, firstLine=firstLine)
            except Exception:
                pass

            self.current_file = filepath
            self._modified = False

        except IOError as e:
            print(f"Error opening the file: {e}")
        except Exception as e:
            print(f"Error opening file '{filepath}': {e}")

    def on_save(self):
        self._modified = False

    def highlight_error_line(self, line_number: int):
        """Highlight a line red (1-based) using qutepart's setExtraSelections.
        qutepart expects (startAbsolutePosition, length) tuples and uses
        _userExtraSelectionFormat for the highlight colour."""
        from PySide6.QtGui import QColor, QTextCharFormat
        from PySide6.QtCore import Qt
        doc = self.qpart.document()
        block = doc.findBlockByLineNumber(line_number - 1)
        if not block.isValid():
            return
        start = block.position()
        length = max(block.length() - 1, 1)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3d1a1a"))
        fmt.setForeground(QColor("#ff7b72"))
        self.qpart._userExtraSelectionFormat = fmt
        self.qpart.setExtraSelections([(start, length)])
        cursor = self.qpart.textCursor()
        cursor.setPosition(start)
        self.qpart.setTextCursor(cursor)
        self.qpart.ensureCursorVisible()

    def clear_error_highlight(self):
        """Remove any error highlighting."""
        self.qpart.setExtraSelections([])

    def get_text(self):
        return self.qpart.toPlainText()

    def set_text(self, text):
        self.qpart.setPlainText(text)

    def autosave(self):
        if self.is_Modified() and self.current_file:
            self.saveFile()

    def saveFile(self):
        with open(self.current_file, 'w',  encoding='utf-8') as file:
            file.write(self.get_text())
        self._modified = False  # Reset the modified flag

class EditorTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super(EditorTabWidget, self).__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_tab_context_menu)

    def open_file_in_new_tab(self, filepath):
        editor_widget = EditorWidget()
        editor_widget.qpart.load_file(filepath)  # Assuming load_file method in EditorWidget for Qutepart
        filename = os.path.basename(filepath)
        index = self.addTab(editor_widget, filename)
        self.setCurrentIndex(index)

    def show_tab_context_menu(self, position):
        index = self.tabBar().tabAt(position)
        if index == -1:  # No tab under the cursor
            return

        context_menu = QMenu(self)
        rename_action = context_menu.addAction("Rename Tab")
        action = context_menu.exec_(self.tabBar().mapToGlobal(position))

        if action == rename_action:
            self.rename_tab(index)

    def rename_tab(self, index):
        new_name, ok = QInputDialog.getText(self, "Rename Tab", "New Name:")
        if ok and new_name:
            self.setTabText(index, new_name)