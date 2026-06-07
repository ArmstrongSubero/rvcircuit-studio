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

class CustomFileSystemModel(QFileSystemModel):
    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole and section == 0 and orientation == Qt.Orientation.Horizontal:
            return "Project Explorer"
        return super().headerData(section, orientation, role)

class WorkspaceFilterProxy(QSortFilterProxyModel):
    """Proxy that hides system files and optionally restricts top-level to one folder."""

    _HIDDEN_NAMES = {
        ".fseventsd", ".metadata_never_index", ".Trash-1000", ".Trashes",
        ".Spotlight-V100", ".DocumentRevisions-V100", "System Volume Information",
        "$RECYCLE.BIN", "desktop.ini", "thumbs.db",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_parent = ""   # normalized path of the parent dir
        self._filter_name   = ""   # folder name to show at top level

    def set_root_filter(self, parent_dir: str, folder_name: str):
        """Show only `folder_name` at the top level of `parent_dir`."""
        self._filter_parent = os.path.normpath(parent_dir) if parent_dir else ""
        self._filter_name   = folder_name
        self.invalidateFilter()

    def clear_root_filter(self):
        self._filter_parent = ""
        self._filter_name   = ""
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        source_model = self.sourceModel()
        index = source_model.index(source_row, 0, source_parent)
        file_path = source_model.filePath(index)
        if not file_path:
            return True

        name = os.path.basename(file_path)

        if name.startswith(".") or name in self._HIDDEN_NAMES:
            return False

        if name.startswith("ide_debug_") and name.endswith(".py"):
            return False

        if self._filter_parent and self._filter_name:
            parent_path = os.path.normpath(os.path.dirname(file_path))
            if parent_path == self._filter_parent:
                return name == self._filter_name

        return True
