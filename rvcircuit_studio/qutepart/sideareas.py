"""Line numbers and bookmarks areas
"""

from PySide6.QtCore import QPoint, Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QToolTip
from PySide6.QtGui import QPainter, QPalette, QPixmap, QTextBlock, QColor

import qutepart
from qutepart.bookmarks import Bookmarks
from qutepart.margins import MarginBase



# Dynamic mixin at runtime:
# http://stackoverflow.com/questions/8544983/dynamically-mixin-a-base-class-to-an-instance-in-python
def extend_instance(obj, cls):
    base_cls = obj.__class__
    base_cls_name = obj.__class__.__name__
    obj.__class__ = type(base_cls_name, (base_cls, cls), {})



class LineNumberArea(QWidget):
    """Line number area widget
    """
    _LEFT_MARGIN = 20
    _RIGHT_MARGIN = 20

    def __init__(self, parent):
        QWidget.__init__(self, parent)

        extend_instance(self, MarginBase)
        MarginBase.__init__(self, parent, "line_numbers", 0)

        self.__width = self.__calculateWidth()

        self._qpart.blockCountChanged.connect(self.__updateWidth)

    def __updateWidth(self, newBlockCount=None):
        newWidth = self.__calculateWidth()
        if newWidth != self.__width:
            self.__width = newWidth
            self._qpart.updateViewport()

    def paintEvent(self, event):
        """QWidget.paintEvent() implementation
        """
        painter = QPainter(self)
        painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.Window))
        # RGB: (96, 125, 139)
        customColor = QColor(96, 125, 139)
        painter.setPen(customColor)

        try:
            block = self._qpart.firstVisibleBlock()
            blockNumber = block.blockNumber()
            top = int(self._qpart.blockBoundingGeometry(block).translated(self._qpart.contentOffset()).top())
            bottom = top + int(self._qpart.blockBoundingRect(block).height())
            singleBlockHeight = self._qpart.cursorRect().height()

            boundingRect = self._qpart.blockBoundingRect(block)
            availableWidth = self.__width - self._RIGHT_MARGIN - self._LEFT_MARGIN
            availableHeight = self._qpart.fontMetrics().height()
            while block.isValid() and top <= event.rect().bottom():
                if block.isVisible() and bottom >= event.rect().top():
                    number = str(blockNumber + 1)
                    painter.drawText(self._LEFT_MARGIN, top,
                                     availableWidth, availableHeight,
                                     Qt.AlignmentFlag.AlignRight, number)
                    
                    if boundingRect.height() >= singleBlockHeight * 2:  # wrapped block
                        # Parameters for dots
                        dotSpacing = 5  # adjust this for space between dots
                        dotX = int(self.__width / 2)  # X-coordinate of the dots (middle of the margin)
                        startDotY = int(top + singleBlockHeight)  # Starting Y-coordinate for the dots
                        endDotY = int(top + boundingRect.height() - singleBlockHeight)  # Ending Y-coordinate
                        
                        # Draw dots
                        currentDotY = startDotY
                        while currentDotY < endDotY:
                            painter.drawPoint(dotX, currentDotY)
                            currentDotY += dotSpacing

                block = block.next()
                boundingRect = self._qpart.blockBoundingRect(block)
                top = bottom
                bottom = top + int(boundingRect.height())
                blockNumber += 1
        finally:
            painter.end()  # Deactivate the painter

    def __calculateWidth(self):
        digits = len(str(max(1, self._qpart.blockCount())))
        return self._LEFT_MARGIN + self._qpart.fontMetrics().horizontalAdvance('9') * digits + self._RIGHT_MARGIN

    def width(self):
        """Desired width. Includes text and margins
        """
        return self.__width

    def setFont(self, font):
        QWidget.setFont(self, font)
        self.__updateWidth()


from PySide6.QtCore import Qt

class MarkArea(QWidget):
    @property
    def yPos(self):
        return int(self._yPos)

    @property
    def xPos(self):
        return int(self._xPos)

    _MARGIN = 1

    def __init__(self, qpart):
        QWidget.__init__(self, qpart)

        extend_instance(self, MarginBase)
        MarginBase.__init__(self, qpart, "mark_area", 1)

        qpart.blockCountChanged.connect(self.update)

        self.setMouseTracking(True)

        self._bookmarkPixmap = self._loadIcon('bookmark.png')
        self._lintPixmaps = {qpart.LINT_ERROR: self._loadIcon('lint-error.png'),
                             qpart.LINT_WARNING: self._loadIcon('lint-warning.png'),
                             qpart.LINT_NOTE: self._loadIcon('lint-note.png')}

        self._bookmarks = Bookmarks(qpart, self)

    def _loadIcon(self, fileName):
        icon = qutepart.getIcon(fileName)
        size = self._qpart.cursorRect().height() - 1
        pixmap = icon.pixmap(size, size)  # This also works with Qt.AA_UseHighDpiPixmaps
        return pixmap

    def sizeHint(self):
        """QWidget.sizeHint() implementation
        """
        return QSize(self.width(), 0)

    def paintEvent(self, event):
        """QWidget.paintEvent() implementation
        Draw markers with transparent background
        """
        painter = QPainter(self)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)  # Make the background transparent

        block = self._qpart.firstVisibleBlock()
        blockBoundingGeometry = self._qpart.blockBoundingGeometry(block).translated(self._qpart.contentOffset())
        top = blockBoundingGeometry.top()
        bottom = top + blockBoundingGeometry.height()

        for block in qutepart.iterateBlocksFrom(block):
            height = self._qpart.blockBoundingGeometry(block).height()
            # A wrapped block is several rows tall. Centre marks in its first
            # row so they line up with the line number, not the middle of the
            # wrapped text.
            rowHeight = min(height, self._qpart.cursorRect().height() or height)
            if top > event.rect().bottom():
                break
            if block.isVisible() and \
               bottom >= event.rect().top():
                if block.blockNumber() in self._qpart.lintMarks:
                    msgType, msgText = self._qpart.lintMarks[block.blockNumber()]
                    pixMap = self._lintPixmaps[msgType]
                    yPos = top + ((rowHeight - pixMap.height()) / 2)
                    painter.drawPixmap(0, int(yPos), pixMap)

                if self.isBlockMarked(block):
                    yPos = top + ((rowHeight - self._bookmarkPixmap.height()) / 2)
                    painter.drawPixmap(0, int(yPos), self._bookmarkPixmap)

            top += height

    def width(self):
        """Desired width. Includes text and margins
        """
        return self._MARGIN + self._bookmarkPixmap.width() + self._MARGIN

    def mouseMoveEvent(self, event):
        blockNumber = self._qpart.cursorForPosition(event.pos()).blockNumber()
        if blockNumber in self._qpart._lintMarks:
            msgType, msgText = self._qpart._lintMarks[blockNumber]
            QToolTip.showText(event.globalPos(), msgText)
        else:
            QToolTip.hideText()

        return QWidget.mouseMoveEvent(self, event)

    def clearBookmarks(self, startBlock, endBlock):
        """Clears the bookmarks
        """
        self._bookmarks.clear(startBlock, endBlock)

    def clear(self):
        self._bookmarks.removeActions()
        MarginBase.clear(self)