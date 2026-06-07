"""
htmldelegate --- QStyledItemDelegate delegate. Draws HTML
=========================================================
"""

from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, \
                            QStyleOptionViewItem
from PySide6.QtGui import QAbstractTextDocumentLayout, \
                        QTextDocument, QPalette
from PySide6.QtCore import QSize

_HTML_ESCAPE_TABLE = \
{
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;",
    ">": "&gt;",
    "<": "&lt;",
    " ": "&nbsp;",
    "\t": "&nbsp;&nbsp;&nbsp;&nbsp;",
}


def htmlEscape(text):
    """Replace special HTML symbols with escase sequences
    """
    return "".join(_HTML_ESCAPE_TABLE.get(c,c) for c in text)


class HTMLDelegate(QStyledItemDelegate):
    """QStyledItemDelegate implementation. Draws HTML

    http://stackoverflow.com/questions/1956542/how-to-make-item-view-render-rich-html-text-in-qt/1956781#1956781
    """
    def paint(self, painter, option, index):
        
        try:
            option.state &= ~QStyle.State_HasFocus  # never draw focus rect

            options = QStyleOptionViewItem(option)
            self.initStyleOption(options, index)

            style = QApplication.style() if options.widget is None else options.widget.style()

            # Read the HTML from the model, not from options.text which may
            # be empty in some PySide6 builds (Bug 28).
            html = index.data(0)  # Qt.ItemDataRole.DisplayRole == 0
            if not html:
                html = options.text or ""

            doc = QTextDocument()
            doc.setDocumentMargin(1)
            doc.setHtml(html)
            if options.widget is not None:
                doc.setDefaultFont(options.widget.font())

            options.text = ""
            style.drawControl(QStyle.CE_ItemViewItem, options, painter)

            ctx = QAbstractTextDocumentLayout.PaintContext()

            # Bug 29: on dark themes unselected rows were invisible because
            # only the selected row had its colour set. Paint an explicit
            # selection bar and set text colour for both states.
            if option.state & QStyle.State_Selected:
                ctx.palette.setColor(
                    QPalette.ColorRole.Text,
                    option.palette.color(QPalette.ColorGroup.Active,
                                         QPalette.ColorRole.HighlightedText))
            else:
                ctx.palette.setColor(
                    QPalette.ColorRole.Text,
                    option.palette.color(QPalette.ColorGroup.Active,
                                         QPalette.ColorRole.Text))

            textRect = style.subElementRect(QStyle.SE_ItemViewItemText, options)
            painter.save()
            painter.translate(textRect.topLeft())
            doc.documentLayout().draw(painter, ctx)

            painter.restore()
        except RuntimeError as e:
            print(f"Caught a RuntimeError in paint: {e}")

    def sizeHint(self, option, index):
        """QStyledItemDelegate.sizeHint implementation
     """
        options = QStyleOptionViewItem(option)
        self.initStyleOption(options,index)

        # Read from model, not options.text (Bug 28).
        html = index.data(0)
        if not html:
            html = options.text or ""

        doc = QTextDocument()
        doc.setDocumentMargin(1)
        #  bad long (multiline) strings processing doc.setTextWidth(options.rect.width())
        doc.setHtml(html)
        return QSize(int(doc.idealWidth()),
                     int(doc.size().height()))
