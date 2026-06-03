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


class SnippetManager:
    active_instance = None

    def __init__(self, parent_widget, editor_widget, snippet_filename=None):
        if snippet_filename is None:
            snippet_filename = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snippets.json")
        if SnippetManager.active_instance:
            prev_layout = SnippetManager.active_instance.container.layout()
            for i in reversed(range(prev_layout.count())):
                widget = prev_layout.itemAt(i).widget()
                widget.setParent(None)
                widget.deleteLater()

        self.container = parent_widget
        self.container.setLayout(QVBoxLayout())
        self.SNIPPET_FILENAME = snippet_filename

        self.tree_widget = QTreeWidget(self.container)
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.itemDoubleClicked.connect(self.insert_snippet)
        self.container.layout().addWidget(self.tree_widget)

        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_snippet_context_menu)

        self.update_snippet_tree(self.SNIPPET_FILENAME)

        SnippetManager.active_instance = self
        self.editor = editor_widget

    def insert_snippet(self, item):
        snippet_code = item.data(0, Qt.UserRole)
        if not snippet_code:
            return
        current_widget = self.editor.currentWidget()
        if current_widget is None or not hasattr(current_widget, "qpart"):
            return  # no editor tab open to insert into
        current_editor = current_widget.qpart
        cursor = current_editor.textCursor()

        block = cursor.block()
        line_text = block.text()
        indent = ""
        for ch in line_text:
            if ch in (' ', '\t'):
                indent += ch
            else:
                break

        lines = snippet_code.split('\n')
        if len(lines) > 1:
            indented = lines[0] + '\n' + '\n'.join(indent + l if l.strip() else l for l in lines[1:])
        else:
            indented = lines[0]

        cursor.insertText(indented)

    def create_snippets_tree(self, snippet_file=None):
        snippet_file = snippet_file or self.SNIPPET_FILENAME
        self.tree_widget.clear()
        categories = self.load_snippets_from_file(snippet_file)
        if not categories:
            return
        for category, snippets in categories.items():
            category_item = QTreeWidgetItem(self.tree_widget, [category])
            for snippet_name, snippet_code in snippets.items():
                snippet_item = QTreeWidgetItem(category_item, [snippet_name])
                snippet_item.setData(0, Qt.UserRole, snippet_code)

    def update_snippet_tree(self, snippet_file=None):
        self.create_snippets_tree(snippet_file)

    def add_custom_snippet(self):
        name, ok = QInputDialog.getText(self.editor, "Save Snippet", "Enter Snippet Name:")
        if ok and name:
            code, ok = QInputDialog.getMultiLineText(self.editor, "Save Snippet", "Enter Snippet Code:")
            if ok and code:
                category_item = self.tree_widget.topLevelItem(0)
                new_snippet_item = QTreeWidgetItem(category_item, [name])
                new_snippet_item.setData(0, Qt.UserRole, code)
                self.save_snippets_to_file()

    def on_save_snippet(self):
        self.add_custom_snippet()

    def save_snippets_to_file(self):
        data = {}
        root_item = self.tree_widget.invisibleRootItem()
        for index in range(root_item.childCount()):
            category_item = root_item.child(index)
            category_name = category_item.text(0)
            snippets_data = {}
            for i in range(category_item.childCount()):
                snippet_item = category_item.child(i)
                snippet_name = snippet_item.text(0)
                snippet_code = snippet_item.data(0, Qt.UserRole)
                snippets_data[snippet_name] = snippet_code
            data[category_name] = snippets_data
        with open(self.SNIPPET_FILENAME, 'w') as f:
            json.dump(data, f)

    def load_snippets_from_file(self, snippet_file=None):
        snippet_file = snippet_file or self.SNIPPET_FILENAME
        if not os.path.exists(snippet_file):
            return None
        with open(snippet_file, 'r') as file:
            data = json.load(file)
        return data

    def show_snippet_context_menu(self, position):
        item = self.tree_widget.itemAt(position)
        if not item:
            return
        menu = QMenu()
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(lambda: self.delete_snippet(item))
        menu.exec_(self.tree_widget.viewport().mapToGlobal(position))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        clicked_item = self.tree_widget.itemAt(event.pos())
        delete_action = QAction("Delete", self)
        menu.addAction(delete_action)
        if clicked_item:
            def delete_snippet():
                clicked_item.parent().removeChild(clicked_item)
                self.save_snippets_to_file()
            delete_action.triggered.connect(delete_snippet)
        menu.exec_(event.globalPos())

    def delete_snippet(self, checked=False, _=None):
        clicked_item = self.tree_widget.currentItem()
        parent = clicked_item.parent()
        if parent:
            parent.removeChild(clicked_item)
        else:
            self.tree_widget.takeTopLevelItem(self.tree_widget.indexOfTopLevelItem(clicked_item))
        self.save_snippets_to_file()