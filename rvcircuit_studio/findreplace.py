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

class FindReplaceWidget(QWidget):
    def __init__(self, editor_widget):  # Pass a reference to the EditorWidget here
        super().__init__()
        self.editor_widget = editor_widget
        self.setWindowTitle("Find/Replace")
        self.init_ui()

    def init_ui(self):
        self.find_label = QLabel("Find:")
        self.find_input = QLineEdit()
        self.replace_label = QLabel("Replace:")
        self.replace_input = QLineEdit()
        self.find_button = QPushButton("Find Next")
        self.replace_button = QPushButton("Replace")
        self.replace_all_button = QPushButton("Replace All")
        self.text_browser = QTextBrowser()  # Optional, based on your needs

        self.find_button.clicked.connect(self.find_next)
        self.replace_button.clicked.connect(self.replace)
        self.replace_all_button.clicked.connect(self.replace_all)

        main_layout = QVBoxLayout()
        
        find_layout = QHBoxLayout()
        find_layout.addWidget(self.find_label)
        find_layout.addWidget(self.find_input)
        
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(self.replace_label)
        replace_layout.addWidget(self.replace_input)
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.find_button)
        button_layout.addWidget(self.replace_button)
        button_layout.addWidget(self.replace_all_button)
        
        main_layout.addLayout(find_layout)
        main_layout.addLayout(replace_layout)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.text_browser)  # Optional

        self.setLayout(main_layout)

    def find_next(self):
        find_text = self.find_input.text()
        if not find_text:
            return

        if self.editor_widget:
            cursor = self.editor_widget.qpart.textCursor()
            pos = cursor.position()

            if find_text in self.editor_widget.qpart.toPlainText()[pos:]:
                start = self.editor_widget.qpart.toPlainText().find(find_text, pos)
                cursor.setPosition(start)
                cursor.setPosition(start + len(find_text), QTextCursor.MoveMode.KeepAnchor)
                self.editor_widget.qpart.setTextCursor(cursor)
            else:
                self.editor_widget.qpart.moveCursor(QTextCursor.MoveOperation.Start)
                if find_text in self.editor_widget.qpart.toPlainText():
                    start = self.editor_widget.qpart.toPlainText().find(find_text)
                    cursor.setPosition(start)
                    cursor.setPosition(start + len(find_text), QTextCursor.MoveMode.KeepAnchor)
                    self.editor_widget.qpart.setTextCursor(cursor)

    def replace(self):
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not find_text:
            return

        if self.editor_widget:
            cursor = self.editor_widget.qpart.textCursor()
            if cursor.hasSelection() and cursor.selectedText() == find_text:
                cursor.insertText(replace_text)

            self.find_next()  # After replacing, find the next occurrence

    def replace_all(self):
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not find_text:
            return

        if self.editor_widget:
            # Operate on the text directly and advance past each replacement.
            # Searching from the start in a loop would hang forever whenever
            # replace_text contains find_text (e.g. replace "a" with "ba").
            text = self.editor_widget.qpart.toPlainText()
            if find_text not in text:
                return
            result = []
            i = 0
            n = len(find_text)
            while True:
                j = text.find(find_text, i)
                if j == -1:
                    result.append(text[i:])
                    break
                result.append(text[i:j])
                result.append(replace_text)
                i = j + n
            new_text = "".join(result)
            cursor = self.editor_widget.qpart.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(new_text)
            cursor.endEditBlock()