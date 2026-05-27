"""Kate syntax definition parser and representation

Do not use this module directly. Use 'syntax' module

Read http://kate-editor.org/2005/03/24/writing-a-syntax-highlighting-file/
if you want to understand something


'attribute' property of rules and contexts contains not an original string,
but value from itemDatas section (style name)

'context', 'lineBeginContext', 'lineEndContext', 'fallthroughContext' properties
contain not a text value, but ContextSwitcher object
"""

import re
import logging

_logger = logging.getLogger('qutepart')

_numSeqReplacer = re.compile(r'%\d+')


class ContextStack:
    def __init__(self, contexts, data):
        """Create default context stack for syntax
        Contains default context on the top
        """
        self._contexts = contexts
        self._data = data

    def pop(self, count):
        """Returns new context stack, which doesn't contain few levels
        """
        if len(self._contexts) - 1 < count:
            _logger.error("#pop value is too big %d", len(self._contexts))
            if len(self._contexts) > 1:
                return ContextStack(self._contexts[:1], self._data[:1])
            else:
                return self

        return ContextStack(self._contexts[:-count], self._data[:-count])

    def append(self, context, data):
        """Returns new context, which contains current stack and new frame
        """
        return ContextStack(self._contexts + [context], self._data + [data])

    def currentContext(self):
        """Get current context
        """
        return self._contexts[-1]

    def currentData(self):
        """Get current data
        """
        return self._data[-1]


class ContextSwitcher:
    """Class parses 'context', 'lineBeginContext', 'lineEndContext', 'fallthroughContext'
    and modifies context stack according to context operation
    """
    def __init__(self, popsCount, contextToSwitch, contextOperation):
        self._popsCount = popsCount
        self._contextToSwitch = contextToSwitch
        self._contextOperation = contextOperation

    def __str__(self):
        return self._contextOperation

    def getNextContextStack(self, contextStack, data=None):
        """Apply modification to the contextStack.
        This method never modifies input parameter list
        """
        if self._popsCount:
            contextStack = contextStack.pop(self._popsCount)

        if self._contextToSwitch is not None:
            if not self._contextToSwitch.dynamic:
                data = None
            contextStack = contextStack.append(self._contextToSwitch, data)

        return contextStack


class TextToMatchObject:
    """Peace of text, which shall be matched.
    Contains pre-calculated and pre-checked data for performance optimization
    """
    def __init__(self, currentColumnIndex, wholeLineText, deliminatorSet, contextData):
        self.currentColumnIndex = currentColumnIndex
        self.wholeLineText = wholeLineText
        self.text = wholeLineText[currentColumnIndex:]
        self.textLen = len(self.text)

        self.firstNonSpace = not bool(wholeLineText[:currentColumnIndex].strip())

        self.isWordStart = currentColumnIndex == 0 or \
                         wholeLineText[currentColumnIndex - 1].isspace() or \
                         wholeLineText[currentColumnIndex - 1] in deliminatorSet

        self.word = None
        if self.isWordStart:
            wordEndIndex = 0
            for index, char in enumerate(self.text):
                if char in deliminatorSet:
                    wordEndIndex = index
                    break
            else:
                wordEndIndex = len(wholeLineText)

            if wordEndIndex != 0:
                self.word = self.text[:wordEndIndex]

        self.contextData = contextData


class RuleTryMatchResult:
    def __init__(self, rule, length, data=None):
        self.rule = rule
        self.length = length
        self.data = data

        if rule.lookAhead:
            self.length = 0


class AbstractRuleParams:
    """Parameters, passed to the AbstractRule constructor
    """
    def __init__(self, parentContext, format, textType, attribute, context, lookAhead, firstNonSpace, dynamic, column):
        self.parentContext = parentContext
        self.format = format
        self.textType = textType
        self.attribute = attribute
        self.context = context
        self.lookAhead = lookAhead
        self.firstNonSpace = firstNonSpace
        self.dynamic = dynamic
        self.column = column


class AbstractRule:
    """Base class for rule classes
    Public attributes:
        parentContext
        format              May be None
        textType            May be None
        attribute           May be None
        context
        lookAhead
        firstNonSpace
        column          -1 if not set
        dynamic
    """

    _seqReplacer = re.compile(r'%\d+')

    def __init__(self, params):
        self.parentContext = params.parentContext
        self.format = params.format
        self.textType = params.textType
        self.attribute = params.attribute
        self.context = params.context
        self.lookAhead = params.lookAhead
        self.firstNonSpace = params.firstNonSpace
        self.dynamic = params.dynamic
        self.column = params.column

    def __str__(self):
        """Serialize.
        For debug logs
        """
        res = '\t\tRule %s\n' % self.shortId()
        res += '\t\t\tstyleName: %s\n' % (self.attribute or 'None')
        res += '\t\t\tcontext: %s\n' % self.context
        return res

    def shortId(self):
        """Get short ID string of the rule. Used for logs
        i.e. "DetectChar(x)"
        """
        raise NotImplementedError(str(self.__class__))

    def tryMatch(self, textToMatchObject):
        """Try to find themselves in the text.
        Returns (contextStack, count, matchedRule) or (contextStack, None, None) if doesn't match
        """
        try:
            # Skip if column doesn't match
            if self.column != -1 and \
               self.column != textToMatchObject.currentColumnIndex:
                return None

            if self.firstNonSpace and \
               (not textToMatchObject.firstNonSpace):
                return None

            return self._tryMatch(textToMatchObject)
        except Exception as e:
            _logger.error(f"Error encountered in {self.shortId()} while processing: {e}")
            return None


class DetectChar(AbstractRule):
    """Public attributes:
        char
    """
    def __init__(self, abstractRuleParams, char, index):
        AbstractRule.__init__(self, abstractRuleParams)
        self.char = char
        self.index = index

    def shortId(self):
        return 'DetectChar(%s, %d)' % (self.char, self.index)

    def _tryMatch(self, textToMatchObject):
        try:
            if self.char is None and self.index == 0:
                return None

            if self.dynamic:
                index = self.index - 1
                if index >= len(textToMatchObject.contextData):
                    _logger.error('Invalid DetectChar index %d', index)
                    return None

                if len(textToMatchObject.contextData[index]) != 1:
                    _logger.error('Too long DetectChar string %s', textToMatchObject.contextData[index])
                    return None

                string = textToMatchObject.contextData[index]
            else:
                string = self.char

            if textToMatchObject.text[0] == string:
                return RuleTryMatchResult(self, 1)
            return None

        except Exception as e:
            _logger.error(f"Error encountered in _tryMatch of {self.shortId()}: {e}")
            return None


class Detect2Chars(AbstractRule):
    """Public attributes
        string
    """
    def __init__(self, abstractRuleParams, string):
        AbstractRule.__init__(self, abstractRuleParams)
        self.string = string

    def shortId(self):
        return 'Detect2Chars(%s)' % self.string

    def _tryMatch(self, textToMatchObject):
        try:
            if self.string is None:
                return None

            if textToMatchObject.text.startswith(self.string):
                return RuleTryMatchResult(self, len(self.string))

            return None

        except Exception as e:
            _logger.error(f"Error encountered in _tryMatch of {self.shortId()}: {e}")
            return None


class AnyChar(AbstractRule):
    """Public attributes:
        string
    """
    def __init__(self, abstractRuleParams, string):
        AbstractRule.__init__(self, abstractRuleParams)
        self.string = string

    def shortId(self):
        return 'AnyChar(%s)' % self.string

    def _tryMatch(self, textToMatchObject):
        try:
            if textToMatchObject.text[0] in self.string:
                return RuleTryMatchResult(self, 1)

            return None

        except Exception as e:
            _logger.error(f"Error encountered in _tryMatch of {self.shortId()}: {e}")
            return None


class StringDetect(AbstractRule):
    """Public attributes:
        string
    """
    def __init__(self, abstractRuleParams, string):
        AbstractRule.__init__(self, abstractRuleParams)
        self.string = string

    def shortId(self):
        return 'StringDetect(%s)' % self.string

    def _tryMatch(self, textToMatchObject):
        try:
            if self.string is None:
                return None

            if self.dynamic:
                string = self._makeDynamicSubsctitutions(self.string, textToMatchObject.contextData)
                if not string:
                    return None
            else:
                string = self.string

            if textToMatchObject.text.startswith(string):
                return RuleTryMatchResult(self, len(string))

            return None

        except Exception as e:
            _logger.error(f"Error encountered in _tryMatch of {self.shortId()}: {e}")
            return None

    @staticmethod
    def _makeDynamicSubsctitutions(string, contextData):
        """For dynamic rules, replace %d patterns with actual strings
        Python function, which is used by C extension.
        """
        def _replaceFunc(escapeMatchObject):
            stringIndex = escapeMatchObject.group(0)[1]
            index = int(stringIndex)
            if index < len(contextData):
                return contextData[index]
            else:
                return escapeMatchObject.group(0)  # no any replacements, return original value

        return _numSeqReplacer.sub(_replaceFunc, string)


class WordDetect(AbstractRule):
    """Public attributes:
        words
    """
    def __init__(self, abstractRuleParams, word, insensitive):
        AbstractRule.__init__(self, abstractRuleParams)
        self.word = word
        self.insensitive = insensitive

    def shortId(self):
        return 'WordDetect(%s, %d)' % (self.word, self.insensitive)

    def _tryMatch(self, textToMatchObject):
        try:
            if textToMatchObject.word is None:
                return None

            if self.insensitive or \
               (not self.parentContext.parser.keywordsCaseSensitive):
                wordToCheck = textToMatchObject.word.lower()
            else:
                wordToCheck = textToMatchObject.word

            if wordToCheck == self.word:
                return RuleTryMatchResult(self, len(wordToCheck))
            else:
                return None
        except Exception as e:
            _logger.error(f"Error in _tryMatch for WordDetect: {e}")
            return None


class keyword(AbstractRule):
    """Public attributes:
        string
        words
    """
    def __init__(self, abstractRuleParams, words, insensitive):
        AbstractRule.__init__(self, abstractRuleParams)
        self.words = set(words)
        self.insensitive = insensitive

    def shortId(self):
        return 'keyword(%s, %d)' % (' '.join(list(self.words)), self.insensitive)

    def _tryMatch(self, textToMatchObject):
        try:
            if textToMatchObject.word is None:
                return None

            if self.insensitive or \
               (not self.parentContext.parser.keywordsCaseSensitive):
                wordToCheck = textToMatchObject.word.lower()
            else:
                wordToCheck = textToMatchObject.word

            if wordToCheck in self.words:
                return RuleTryMatchResult(self, len(wordToCheck))
            else:
                return None
        except Exception as e:
            _logger.error(f"Error in _tryMatch for keyword: {e}")
            return None


class RegExpr(AbstractRule):
    """Handles regular expression parsing.
    
    Attributes:
        regExp: Compiled regular expression.
        wordStart: Indicates if the pattern starts with \b.
        lineStart: Indicates if the pattern starts with ^.
    """

    def __init__(self, abstractRuleParams,
                 string, insensitive, minimal, wordStart, lineStart):
        super().__init__(abstractRuleParams)
        self.string = string
        self.insensitive = insensitive
        self.minimal = minimal
        self.wordStart = wordStart
        self.lineStart = lineStart

        self.regExp = None if self.dynamic else self._compileRegExp(string, insensitive, minimal)

    def shortId(self):
        return f'RegExpr( {self.string} )'

    def _tryMatch(self, textToMatchObject):
        """Tries to parse text. If matched - saves data for dynamic context."""
        try:
            if self.wordStart and not textToMatchObject.isWordStart:
                return None

            if self.lineStart and textToMatchObject.currentColumnIndex > 0:
                return None

            regExp = self.regExp
            if self.dynamic:
                string = self._makeDynamicSubsctitutions(self.string, textToMatchObject.contextData)
                regExp = self._compileRegExp(string, self.insensitive, self.minimal)

            if regExp is None:
                return None

            wholeMatch, groups = self._matchPattern(regExp, textToMatchObject.text)
            if wholeMatch:
                return RuleTryMatchResult(self, len(wholeMatch), groups)
            return None
        except Exception as e:
            _logger.error(f"Error in _tryMatch: {e}")
            return None

    @staticmethod
    def _makeDynamicSubsctitutions(string, contextData):
        """For dynamic rules, replace %d patterns with actual strings
        Escapes reg exp symbols in the pattern
        Python function, used by C code
        """
        def _replaceFunc(escapeMatchObject):
            stringIndex = escapeMatchObject.group(0)[1]
            index = int(stringIndex)
            if index < len(contextData):
                return re.escape(contextData[index])
            else:
                return escapeMatchObject.group(0)  # no any replacements, return original value

        return _numSeqReplacer.sub(_replaceFunc, string)

    @staticmethod
    def _compileRegExp(string, insensitive, minimal):
        """Compile regular expression."""
        flags = re.IGNORECASE if insensitive else 0

        replacements = {
            '[_[:alnum:]]': '[\\w\\d]',
            '[:digit:]': '\\d',
            '[:blank:]': '\\s',
            '[:ascii:]': '\\x00-\\x7F',
            '[:cntrl:]': '\\x00-\\x1F\\x7F',
        }
        for k, v in replacements.items():
            string = string.replace(k, v)

        try:
            return re.compile(string, flags)
        except (re.error, AssertionError) as ex:
            _logger.warning(f"Invalid pattern '{string}': {str(ex)}")
            return None

    @staticmethod
    def _matchPattern(regExp, string):
        """Try to match pattern. Returns tuple (whole match, groups) or (None, None)"""
        try:
            match = regExp.match(string)
            if match and match.group(0):
                return match.group(0), (match.group(0),) + match.groups()
            return None, None
        except Exception as e:
            _logger.error(f"An error occurred while trying to match pattern: {e}", exc_info=True)
            return None, None


class AbstractNumberRule(AbstractRule):
    """Base class for Int and Float rules.
    This rules can have child rules

    Public attributes:
        childRules
    """
    def __init__(self, abstractRuleParams, childRules):
        super().__init__(abstractRuleParams)  # More Pythonic way of calling parent init
        self.childRules = childRules if childRules is not None else []

    def _tryMatch(self, textToMatchObject):
        """Try to find themselves in the text.
        Returns (count, matchedRule) or (None, None) if doesn't match
        """
        try:
            if not getattr(textToMatchObject, 'isWordStart', False):
                return None

            index = self._tryMatchText(textToMatchObject.text)
            if index is None:
                return None

            if textToMatchObject.currentColumnIndex + index < len(getattr(textToMatchObject, 'wholeLineText', '')):
                newTextToMatchObject = TextToMatchObject(textToMatchObject.currentColumnIndex + index,
                                                         getattr(textToMatchObject, 'wholeLineText', ''),
                                                         self.parentContext.parser.deliminatorSet,
                                                         textToMatchObject.contextData)
                for rule in self.childRules:
                    ruleTryMatchResult = rule.tryMatch(newTextToMatchObject)
                    if ruleTryMatchResult is not None:
                        index += ruleTryMatchResult.length
                        break
                # child rule context and attribute ignored

            return RuleTryMatchResult(self, index)
        except Exception as e:
            _logger.error(f"Error in _tryMatch: {e}")
            return None

    def _countDigits(self, text):
        """Count digits at start of text using Python's built-in takewhile
        """
        from itertools import takewhile
        return len(list(takewhile(str.isdigit, text)))


class Int(AbstractNumberRule):
    def shortId(self):
        return 'Int()'

    def _tryMatchText(self, text):
        try:
            matchedLength = self._countDigits(text)
            if matchedLength:
                return matchedLength
            else:
                return None
        except Exception as e:
            _logger.error(f"An error occurred while trying to match text in Int rule: {e}", exc_info=True)
            # Depending on your needs, you might return None, raise the exception again, etc.
            return None


class Float(AbstractNumberRule):

    def shortId(self):
        return 'Float()'

    def _tryMatchText(self, text):
        try:
            matchedLength = 0

            # Check for initial set of digits
            matchedLength += self._consumeDigits(text[matchedLength:])
            
            # Check for decimal point
            if self._canProceed(matchedLength, text) and text[matchedLength] == '.':
                matchedLength += 1
                matchedLength += self._consumeDigits(text[matchedLength:])
            
            # Check for scientific notation
            if self._canProceed(matchedLength, text) and text[matchedLength].lower() == 'e':
                matchedLength += 1
                
                # Check for sign
                if self._canProceed(matchedLength, text) and text[matchedLength] in '+-':
                    matchedLength += 1
                    
                digitsInExponent = self._consumeDigits(text[matchedLength:])
                if not digitsInExponent:
                    return None
                matchedLength += digitsInExponent
            
            # If only dot is encountered without any digits, it's not a valid float
            if matchedLength == 1 and text[0] == '.':
                return None
            
            return matchedLength if matchedLength else None
        
        except Exception as e:
            _logger.error(f"Error in _tryMatchText: {e}")
            return None

    def _consumeDigits(self, text):
        """Returns the number of digits at the start of the text."""
        try:
            return len(text) - len(text.lstrip('0123456789'))
        except Exception as e:
            _logger.error(f"Error in _consumeDigits: {e}")
            return 0
    
    def _canProceed(self, matchedLength, text):
        """Check if we can still proceed."""
        try:
            return len(text) > matchedLength
        except Exception as e:
            _logger.error(f"Error in _canProceed: {e}")
            return False


class HlCOct(AbstractRule):
    def shortId(self):
        return 'HlCOct'

    def _tryMatch(self, textToMatchObject):
        try:
            if not textToMatchObject.text or textToMatchObject.text[0] != '0':
                return None

            index = 1
            while index < len(textToMatchObject.text) and textToMatchObject.text[index] in '01234567':
                index += 1

            if index == 1:
                return None

            if index < len(textToMatchObject.text) and textToMatchObject.text[index].upper() in 'LU':
                index += 1

            return RuleTryMatchResult(self, index)
            
        except Exception as e:
            _logger.error(f"Error in _tryMatch: {e}")
            return None


class HlCHex(AbstractRule):
    def shortId(self):
        return 'HlCHex'

    def _tryMatch(self, textToMatchObject):
        try:
            if len(textToMatchObject.text) < 3:
                return None

            if textToMatchObject.text[:2].upper() != '0X':
                return None

            index = 2
            while index < len(textToMatchObject.text) and textToMatchObject.text[index].upper() in '0123456789ABCDEF':
                index += 1

            if index == 2:
                return None

            if index < len(textToMatchObject.text) and textToMatchObject.text[index].upper() in 'LU':
                index += 1

            return RuleTryMatchResult(self, index)
            
        except Exception as e:
            _logger.error(f"Error in _tryMatch: {e}")
            return None


def _checkEscapedChar(text):
    try:
        index = 0
        if len(text) > 1 and text[0] == '\\':
            index = 1

            if text[index] in "abefnrtv'\"?\\":
                index += 1
            elif text[index] == 'x':  # if it's like \xff, eat the x
                index += 1
                while index < len(text) and text[index].upper() in '0123456789ABCDEF':
                    index += 1
                if index == 2:  # no hex digits
                    return None
            elif text[index] in '01234567':
                while index < 4 and index < len(text) and text[index] in '01234567':
                    index += 1
            else:
                return None

            return index

        return None
        
    except Exception as e:
        print(f"Error in _checkEscapedChar: {e}")
        return None


class HlCStringChar(AbstractRule):
    def shortId(self):
        return 'HlCStringChar'

    def _tryMatch(self, textToMatchObject):
        res = _checkEscapedChar(textToMatchObject.text)
        if res is not None:
            return RuleTryMatchResult(self, res)
        else:
            return None


class HlCChar(AbstractRule):
    def shortId(self):
        return 'HlCChar'

    def _tryMatch(self, textToMatchObject):
        if len(textToMatchObject.text) > 2 and textToMatchObject.text[0] == "'" and textToMatchObject.text[1] != "'":
            result = _checkEscapedChar(textToMatchObject.text[1:])
            if result is not None:
                index = 1 + result
            else:  # 1 not escaped character
                index = 1 + 1

            if index < len(textToMatchObject.text) and textToMatchObject.text[index] == "'":
                return RuleTryMatchResult(self, index + 1)

        return None


class RangeDetect(AbstractRule):
    """Public attributes:
        char
        char1
    """
    def __init__(self, abstractRuleParams, char, char1):
        AbstractRule.__init__(self, abstractRuleParams)
        self.char = char
        self.char1 = char1

    def shortId(self):
        return 'RangeDetect(%s, %s)' % (self.char, self.char1)

    def _tryMatch(self, textToMatchObject):
        if textToMatchObject.text.startswith(self.char):
            end = textToMatchObject.text.find(self.char1, 1)
            if end > 0:
                return RuleTryMatchResult(self, end + 1)

        return None


class LineContinue(AbstractRule):
    def shortId(self):
        return 'LineContinue'

    def _tryMatch(self, textToMatchObject):
        try:
            if textToMatchObject.text == '\\':
                return RuleTryMatchResult(self, 1)
            return None
        except Exception as e:
            _logger.error(f"An error occurred in _tryMatch: {e}")
            return None


class IncludeRules(AbstractRule):
    def __init__(self, abstractRuleParams, context):
        AbstractRule.__init__(self, abstractRuleParams)
        self.context = context

    def __str__(self):
        """Serialize.
        For debug logs
        """
        res = '\t\tRule %s\n' % self.shortId()
        res += '\t\t\tstyleName: %s\n' % (self.attribute or 'None')
        return res

    def shortId(self):
        return "IncludeRules(%s)" % self.context.name

    def _tryMatch(self, textToMatchObject):
        """Try to find themselves in the text.
        Returns (count, matchedRule) or (None, None) if doesn't match
        """
        try:
            for rule in self.context.rules:
                ruleTryMatchResult = rule.tryMatch(textToMatchObject)
                if ruleTryMatchResult is not None:
                    _logger.debug('\tmatched rule %s at %d in included context %s/%s',
                                  rule.shortId(),
                                  textToMatchObject.currentColumnIndex,
                                  self.context.parser.syntax.name,
                                  self.context.name)
                    return ruleTryMatchResult
            else:
                return None
        except Exception as e:
            # Log or print the exception for debugging purposes
            _logger.error(f"Error in _tryMatch: {e}")
            return None


class DetectSpaces(AbstractRule):
    def shortId(self):
        return 'DetectSpaces()'

    def _tryMatch(self, textToMatchObject):
        try:
            if not textToMatchObject.text:
                return None
            
            spaceLen = len(textToMatchObject.text) - len(textToMatchObject.text.lstrip())
            if spaceLen:
                return RuleTryMatchResult(self, spaceLen)
            else:
                return None

        except Exception as e:
            print(f"Error in _tryMatch: {e}")
            return None


class DetectIdentifier(AbstractRule):
    _regExp = re.compile('[a-zA-Z][a-zA-Z0-9_]*')

    def shortId(self):
        return 'DetectIdentifier()'

    def _tryMatch(self, textToMatchObject):
        try:
            if not textToMatchObject.text:  # check if the text is None or empty
                return None

            match = DetectIdentifier._regExp.match(textToMatchObject.text)
            if match and match.group(0):  # ensure match is not None and matched string is not empty
                return RuleTryMatchResult(self, len(match.group(0)))

            return None

        except Exception as e:
            # Log or print the exception for debugging purposes
            _logger.error(f"Error in _tryMatch: {e}")
            return None


class Context:
    """Highlighting context

    Public attributes:
        attribute
        lineEndContext
        lineBeginContext
        fallthroughContext
        dynamic
        rules
        textType     ' ' : code, 'c' : comment
    """
    def __init__(self, parser, name):
        # Will be initialized later, after all context has been created
        self.parser = parser
        self.name = name

    def setValues(self, attribute, format, lineEndContext, lineBeginContext, lineEmptyContext, fallthroughContext, dynamic, textType):
        self.attribute = attribute
        self.format = format
        self.lineEndContext = lineEndContext
        self.lineBeginContext = lineBeginContext
        self.lineEmptyContext = lineEmptyContext
        self.fallthroughContext = fallthroughContext
        self.dynamic = dynamic
        self.textType = textType

    def setRules(self, rules):
        self.rules = rules

    def __str__(self):
        """Serialize.
        For debug logs
        """
        res = '\tContext %s\n' % self.name
        res += '\t\t%s: %s\n' % ('attribute', self.attribute)
        res += '\t\t%s: %s\n' % ('lineEndContext', self.lineEndContext)
        res += '\t\t%s: %s\n' % ('lineBeginContext', self.lineBeginContext)
        res += '\t\t%s: %s\n' % ('lineEmptyContext', self.lineEmptyContext)
        if self.fallthroughContext is not None:
            res += '\t\t%s: %s\n' % ('fallthroughContext', self.fallthroughContext)
        res += '\t\t%s: %s\n' % ('dynamic', self.dynamic)

        for rule in self.rules:
            res += str(rule)
        return res

    def parseBlock(self, contextStack, currentColumnIndex, text):
        """Parse block
        Exits, when reached end of the text, or when context is switched
        Returns (length, newContextStack, highlightedSegments, lineContinue)
        """
        startColumnIndex = currentColumnIndex
        countOfNotMatchedSymbols = 0
        highlightedSegments = []
        textTypeMap = []
        ruleTryMatchResult = None
        while currentColumnIndex < len(text):
            textToMatchObject = TextToMatchObject(currentColumnIndex,
                                                   text,
                                                   self.parser.deliminatorSet,
                                                   contextStack.currentData())
            for rule in self.rules:
                ruleTryMatchResult = rule.tryMatch(textToMatchObject)
                if ruleTryMatchResult is not None:  # if something matched
                    _logger.debug('\tmatched rule %s at %d',
                                  rule.shortId(),
                                  currentColumnIndex)
                    if countOfNotMatchedSymbols > 0:
                        highlightedSegments.append((countOfNotMatchedSymbols, self.format))
                        textTypeMap += [self.textType for i in range(countOfNotMatchedSymbols)]
                        countOfNotMatchedSymbols = 0

                    if ruleTryMatchResult.rule.context is not None:
                        newContextStack = ruleTryMatchResult.rule.context.getNextContextStack(contextStack,
                                                                                              ruleTryMatchResult.data)
                    else:
                        newContextStack = contextStack

                    format = ruleTryMatchResult.rule.format if ruleTryMatchResult.rule.attribute else newContextStack.currentContext().format
                    textType = ruleTryMatchResult.rule.textType or newContextStack.currentContext().textType

                    highlightedSegments.append((ruleTryMatchResult.length,
                                                format))
                    textTypeMap += textType * ruleTryMatchResult.length

                    currentColumnIndex += ruleTryMatchResult.length

                    if newContextStack != contextStack:
                        lineContinue = isinstance(ruleTryMatchResult.rule, LineContinue)

                        return currentColumnIndex - startColumnIndex, newContextStack, highlightedSegments, textTypeMap, lineContinue

                    break  # for loop
            else:  # no matched rules
                if self.fallthroughContext is not None:
                    newContextStack = self.fallthroughContext.getNextContextStack(contextStack)
                    if newContextStack != contextStack:
                        if countOfNotMatchedSymbols > 0:
                            highlightedSegments.append((countOfNotMatchedSymbols, self.format))
                            textTypeMap += [self.textType for i in range(countOfNotMatchedSymbols)]
                        return (currentColumnIndex - startColumnIndex, newContextStack, highlightedSegments, textTypeMap, False)

                currentColumnIndex += 1
                countOfNotMatchedSymbols += 1

        if countOfNotMatchedSymbols > 0:
            highlightedSegments.append((countOfNotMatchedSymbols, self.format))
            textTypeMap += [self.textType for i in range(countOfNotMatchedSymbols)]

        lineContinue = ruleTryMatchResult is not None and \
                       isinstance(ruleTryMatchResult.rule, LineContinue)

        return currentColumnIndex - startColumnIndex, contextStack, highlightedSegments, textTypeMap, lineContinue


class Parser:
    """Parser implementation.

    Attributes:
        syntax (Syntax): An instance of Syntax.
        attributeToFormatMap (dict): A mapping from "attribute" to TextFormat.
        deliminatorSet (set): A set of delimiter characters.
        lists (dict): Keyword lists as dictionary "list name" : "list value".
        keywordsCaseSensitive (bool): Indicates if keywords are case-sensitive.
        contexts (dict): Context list as dictionary "context name" : context.
        defaultContext: Default context object.
    """

    def __init__(self, syntax, deliminatorSetAsString, lists, keywordsCaseSensitive, debugOutputEnabled):
        self.syntax = syntax
        self.deliminatorSet = set(deliminatorSetAsString)
        self.lists = lists
        self.keywordsCaseSensitive = keywordsCaseSensitive

    def setContexts(self, contexts, defaultContext):
        self.contexts = contexts
        self.defaultContext = defaultContext
        self._defaultContextStack = ContextStack([self.defaultContext], [None])

    def __str__(self):
        """Serialize for debug logs."""
        res = 'Parser\n'
        for name, value in vars(self).items():
            if not name.startswith('_') and \
               name not in ('defaultContext', 'deliminatorSet', 'contexts', 'lists', 'syntax') and \
               value is not None:
                res += '\t%s: %s\n' % (name, value)

        res += '\tDefault context: %s\n' % self.defaultContext.name
        for listName, listValue in self.lists.items():
            res += '\tList %s: %s\n' % (listName, listValue)

        for context in self.contexts.values():
            res += str(context)
        return res

    def highlightBlock(self, text, prevContextStack):
        """Parse block and return ParseBlockFullResult."""
        try:
            if prevContextStack is not None:
                contextStack = prevContextStack
            else:
                contextStack = self._defaultContextStack

            highlightedSegments = []
            lineContinue = False
            currentColumnIndex = 0
            textTypeMap = []

            if text:
                while currentColumnIndex < len(text):
                    _logger.debug('In context %s', contextStack.currentContext().name)
                    length, newContextStack, segments, textTypeMapPart, lineContinue = \
                        contextStack.currentContext().parseBlock(contextStack, currentColumnIndex, text)

                    highlightedSegments += segments
                    contextStack = newContextStack
                    textTypeMap += textTypeMapPart
                    currentColumnIndex += length

                # Handling line continuation
                if not lineContinue:
                    while contextStack.currentContext().lineEndContext is not None:
                        oldStack = contextStack
                        contextStack = contextStack.currentContext().lineEndContext.getNextContextStack(contextStack)
                        if oldStack == contextStack:  # Avoid infinite loop if no switch
                            break

                    # This code is not tested, because lineBeginContext is not defined by any XML file
                    if contextStack.currentContext().lineBeginContext is not None:
                        contextStack = contextStack.currentContext().lineBeginContext.getNextContextStack(contextStack)
            elif contextStack.currentContext().lineEmptyContext is not None:
                contextStack = contextStack.currentContext().lineEmptyContext.getNextContextStack(contextStack)

            lineData = (contextStack, textTypeMap)
            return lineData, highlightedSegments

        except Exception as e:
            _logger.error(f"Error in highlightBlock: {e}")
            return None, []

    def parseBlock(self, text, prevContextStack):
        try:
            return self.highlightBlock(text, prevContextStack)[0]
        except Exception as e:
            _logger.error(f"Error in parseBlock: {e}")
            return None