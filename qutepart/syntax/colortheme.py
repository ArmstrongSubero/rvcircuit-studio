class ColorTheme:
    """Brightened Mariana Inspired Color Theme for Dark Mode.
    """
    def __init__(self, textFormatClass):
        self.format = {
            'dsNormal':         textFormatClass(color='#DEE5F2'),  # Soft white on dark grey-blue
            'dsKeyword':        textFormatClass(color='#8DBBE6', bold=True),  # Blue
            'dsFunction':       textFormatClass(color='#FF9D9A'),  # Soft red
            'dsVariable':       textFormatClass(color='#A3B8EF'),  # Soft blue
            'dsControlFlow':    textFormatClass(color='#FF6B81', bold=True),  # Brighter red
            'dsOperator':       textFormatClass(color='#9FB8D7'),  # Muted blue
            'dsBuiltIn':        textFormatClass(color='#89D1C2', bold=True),  # Teal
            'dsExtension':      textFormatClass(color='#8FB8E7', bold=True),  # Soft blue
            'dsPreprocessor':   textFormatClass(color='#FFB981'),  # Soft orange
            'dsAttribute':      textFormatClass(color='#FFD16C'),  # Yellow-orange

            'dsChar':           textFormatClass(color='#F69674'),  # Light red
            'dsSpecialChar':    textFormatClass(color='#82D1E3'),  # Soft cyan
            'dsString':         textFormatClass(color='#FFD863'),  # Yellow
            'dsVerbatimString': textFormatClass(color='#FFD863'),
            'dsSpecialString':  textFormatClass(color='#FF9D63'),  # Orange
            'dsImport':         textFormatClass(color='#A5BCE2'),  # Muted blue

            'dsDataType':       textFormatClass(color='#8ED0E1'),  # Cyan
            'dsDecVal':         textFormatClass(color='#FFEB83'),  # Bright yellow
            'dsBaseN':          textFormatClass(color='#FFEB83'),
            'dsFloat':          textFormatClass(color='#FFEB83'),

            'dsConstant':       textFormatClass(color='#9EDBE3', bold=True),  # Bright cyan

            'dsComment':        textFormatClass(color='#65737E'),  # Muted dark teal
            'dsDocumentation':  textFormatClass(color='#7C8F9E'),  # Greyish teal
            'dsAnnotation':     textFormatClass(color='#FF6889'),  # Bright pinkish-red
            'dsCommentVar':     textFormatClass(color='#E27878'),  # Muted red

            'dsRegionMarker':   textFormatClass(color='#A3BCEF', background='#31363F'),  # Soft blue on darker grey
            'dsInformation':    textFormatClass(color='#FFEB83'),  # Bright yellow
            'dsWarning':        textFormatClass(color='#FF6B81'),  # Brighter red
            'dsAlert':          textFormatClass(color='#FF6B81', background='#383C47', bold=True),  # Red on dark grey
            'dsOthers':         textFormatClass(color='#FFA781'),  # Orange
            'dsError':          textFormatClass(color='#FF6B81', underline=True),  # Brighter red
        }

    def getFormat(self, styleName):
        return self.format[styleName]