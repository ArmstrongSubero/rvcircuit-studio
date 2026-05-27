from qutepart.indenter.base import IndentAlgBase
import logging

class IndentAlgRust(IndentAlgBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('qutepart.indenter.ruststyle')
        
    def _computeSmartIndent(self, block, column):
        """Compute smart indent for case when cursor is on (block, column)
        """
        self.logger.debug(f"Processing block '{block.text()}' at column {column}")

        # Ensure bounds check when slicing
        lineStripped = block.text()[:column].strip() if column <= len(block.text()) else block.text().strip()
        spaceLen = len(block.text()) - len(block.text().lstrip())

        if lineStripped and lineStripped[-1] in '}':
            self.logger.debug("Cursor is after a closed brace")
            try:
                foundBlock, foundColumn = self.findBracketBackward(block,
                                                                   min(spaceLen + len(lineStripped) - 1, len(block.text()) - 1),
                                                                   lineStripped[-1])
            except ValueError:
                self.logger.warning("Failed to find matching opening brace")
                pass
            else:
                return self._computeSmartIndent(foundBlock, foundColumn)

        # Indentation for match, if, else, loop, for, and while statements
        if lineStripped in ('match', 'if', 'else', 'loop', 'for', 'while') or \
           lineStripped.endswith('=>') or \
           lineStripped.endswith('{'):
            self.logger.debug("Indenting for match/if/else/loop/for/while/=>/{ statements")
            return self._increaseIndent(self._blockIndent(block))

        # Handle multi-line comments
        if lineStripped.startswith("/*") and not lineStripped.endswith("*/"):
            self.logger.debug("Indenting for multi-line comments (start)")
            return self._increaseIndent(self._blockIndent(block))
        if lineStripped.endswith("*/"):
            self.logger.debug("Un-indenting for multi-line comments (end)")
            return self._decreaseIndent(self._blockIndent(block))

        # Un-indenting after the '}' character
        if lineStripped == '}':
            try:
                foundBlock, _ = self.findBracketBackward(block,
                                                         min(spaceLen + len(lineStripped) - 1, len(block.text()) - 1),
                                                         '{')
                self.logger.debug("Un-indenting after '}' character, aligned with '{'")
                return self._blockIndent(foundBlock)
            except ValueError:
                self.logger.warning("Failed to find opening '{', falling back to default un-indenting")
                # If we couldn't find the opening '{', fall back to just decreasing the indentation from the current level.
                return self._decreaseIndent(self._blockIndent(block))

        self.logger.debug("Returning default block indent")
        return self._blockIndent(block)


    def computeSmartIndent(self, block, char):
        block = self._prevNonEmptyBlock(block)
        column = len(block.text())
        return self._computeSmartIndent(block, column)