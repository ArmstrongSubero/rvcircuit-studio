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

import ast
import json
import os
import re
import shutil

PREFIX          = "ide_debug_"
STATE_FILENAME  = "ide_debug_state.py"

DEBUG_SIGNAL_S  = "[S]"
DEBUG_SIGNAL_CO = "[CO]"
DEBUG_SIGNAL_CW = "[CW]"
DEBUG_START     = "==== Start Debugging ===="
DEBUG_END       = "==== End Debugging ===="
DEBUG_OUT_START = "\x1b[?1049hD"
DEBUG_OUT_END   = "D\x1b[?1049l"

_TARGET_TYPES = {
    ast.Expr,               # expression_statement
    ast.Assign,             # assignment
    ast.AugAssign,
    ast.AnnAssign,
    ast.Return,             # return_statement
    ast.If,                 # if_statement
    ast.For,                # for_statement
    ast.While,              # while_statement
    ast.Try,                # try_statement
    ast.With,               # with_statement
    ast.FunctionDef,        # function_definition
    ast.AsyncFunctionDef,
    ast.ClassDef,           # class_definition
    ast.Break,              # break_statement
    ast.Continue,           # continue_statement
    ast.Pass,               # pass_statement
    ast.Match,              # match_statement (Python 3.10+, safe to include)
    ast.Import,
    ast.ImportFrom,
    ast.Raise,
    ast.Delete,
    ast.Global,
    ast.Nonlocal,
}

_EXCLUSION_TYPES = {
    ast.If,
    ast.Try,
    ast.For,
    ast.While,
    ast.With,
}

_SKIP_SELF = (
    ast.Module, ast.Interactive, ast.Expression,
)

def _is_docstring(node: ast.AST) -> bool:
    """Return True if this Expr node is a bare string literal (docstring)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )

def _is_elif(node: ast.AST, parent: ast.AST) -> bool:
    """
    True when *node* is the `elif` clause of *parent*.

    Python has no Elif node: `elif` is an If sitting alone in the parent If's
    orelse. The discriminator against a real `else:` containing a nested if is
    indentation, since an elif shares its parent's column.
    """
    return (
        isinstance(node, ast.If)
        and isinstance(parent, ast.If)
        and len(parent.orelse) == 1
        and parent.orelse[0] is node
        and node.col_offset == parent.col_offset
    )


def _walk_steppable(node: ast.AST, rows: set, parent=None):
    """Recursive DFS collecting steppable line numbers (0-based)."""
    if isinstance(node, _SKIP_SELF):
        for child in ast.iter_child_nodes(node):
            _walk_steppable(child, rows, node)
        return

    add_self = False

    if type(node) in _TARGET_TYPES:
        if _is_docstring(node):
            pass
        elif _is_elif(node, parent):
            # Instrumenting an elif inserts a statement between the if body and
            # the elif, which reattaches the elif to the injected block and
            # changes what the program does. Its body is still walked below.
            pass
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.decorator_list:
                pass
            else:
                add_self = True
        else:
            add_self = True

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if node.decorator_list:
            first_deco = node.decorator_list[0]
            rows.add(first_deco.lineno - 1)  # convert to 0-based

    if add_self and hasattr(node, "lineno"):
        rows.add(node.lineno - 1)  # convert to 0-based

    for child in ast.iter_child_nodes(node):
        _walk_steppable(child, rows, node)

def identify_steppable_lines(code: str) -> set:
    """
    Return a set of 0-based line numbers that are "steppable" in *code*.
    Returns an empty set if the code has a syntax error.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        # SyntaxError: incomplete/invalid code. ValueError: source with null
        # bytes. RecursionError: pathologically nested code. Any of these just
        # means "can't instrument", not a crash.
        return set()
    rows = set()
    _walk_steppable(tree, rows)
    return rows

def check_parseable(code: str, filename: str = "<code>"):
    """
    Return None if *code* compiles, otherwise a short human readable reason.

    Uses compile() rather than ast.parse(): errors like "name used prior to
    global declaration" are raised by the symbol table pass, not the parser,
    and ast.parse accepts them silently.
    """
    try:
        compile(code, filename, "exec")
        return None
    except SyntaxError as exc:
        where = f"line {exc.lineno}" if exc.lineno else "unknown line"
        return f"{where}: {exc.msg}"
    except (ValueError, RecursionError) as exc:
        return str(exc)


def _get_indent(line: str) -> str:
    """Return the leading whitespace of a line."""
    return re.match(r"^(\s*)", line).group(1)

def _is_breakpoint_line(line: str) -> bool:
    """Return True if the line contains a breakpoint comment # ●."""
    parts = line.split("#")
    if len(parts) > 1:
        comment = parts[-1].strip().lower()
        return comment == "●"
    return False

def _generate_debug_block(
    indent: str,
    is_breakpoint: bool,
    filename: str,
    line_num: int,           # 1-based display number
    watch_exprs: dict,       # {scope: [expr, ...]}; scope "" = global
    cond_breakpoints: dict,  # {scope: [expr, ...]}
) -> str:
    """Generate the debug instrumentation block to insert before a steppable line."""
    global_watches = watch_exprs.get("", [])
    local_watches  = watch_exprs.get(filename, [])
    all_watches    = list(dict.fromkeys(global_watches + local_watches))  # unique, ordered

    global_cbp = cond_breakpoints.get("", [])
    local_cbp  = cond_breakpoints.get(filename, [])
    all_cbp    = list(dict.fromkeys(global_cbp + local_cbp))

    block = ""
    inner = indent  # indent for the body

    if not is_breakpoint:
        for expr in all_cbp:
            # Same raw-injection concern as watches: only allow clean
            # single-line expressions into the generated board code.
            if not expr or "\n" in expr or "\r" in expr:
                continue
            block += f"{indent}try:\n"
            block += f"{indent}    _ds.us({expr})\n"
            block += f"{indent}except:\n"
            block += f"{indent}    pass\n"
        block += f"{indent}if _ds.e():\n"
        inner = indent + "    "
    else:
        block += f"{indent}_ds.us(True)\n"

    block += f'{inner}_ds.sh("{filename}", {line_num})\n'

    for expr in all_watches:
        # A watch expression is injected raw into generated source. A newline
        # or stray backslash would corrupt the file that runs on the board, so
        # skip anything that isn't a clean single-line expression.
        if not expr or "\n" in expr or "\r" in expr:
            continue
        safe_key = expr.replace("\\", "\\\\").replace('"', '\\"')
        block += f"{inner}try:\n"
        block += f"{inner}    _ds.d[\"w\"][\"{safe_key}\"] = str({expr})\n"
        block += f"{inner}except Exception as _debug_e:\n"
        block += f"{inner}    _ds.d[\"w\"][\"{safe_key}\"] = str(_debug_e)\n"

    block += f"{inner}_ds.st()\n"

    return block

_IMP_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_IMP_ONE  = re.compile(
    rf"^({_IMP_NAME}(?:\.{_IMP_NAME})*)(?:\s+as\s+({_IMP_NAME}))?$"
)
_TRIPLE = re.compile(r'"""|\'\'\'')


def _rewrite_imports(lines: list, all_python_files: list) -> list:
    """
    Rewrite cross-file imports so they reference the ide_debug_ prefixed copies.

    Handles 'from foo import ...', 'import foo', 'import foo as f' and
    'import foo, bar'. Dotted forms such as 'import foo.util' are left alone:
    the debug copies are flat files on the drive root, so there is no package
    for a dotted name to resolve against.

    Lines inside triple quoted strings are skipped, since this is a line based
    rewrite and a bare import line inside a docstring is data, not code.
    """
    file_stems = {os.path.splitext(f)[0] for f in all_python_files}
    result = []
    in_triple = False

    for line in lines:
        was_in_triple = in_triple
        # Toggle once per delimiter on the line; odd count flips the state.
        if len(_TRIPLE.findall(line)) % 2:
            in_triple = not in_triple
        if was_in_triple:
            result.append(line)
            continue

        m = re.match(rf"^(\s*)from\s+({_IMP_NAME})\s+import", line)
        if m and m.group(2) in file_stems:
            mod = m.group(2)
            result.append(line.replace(f"from {mod}", f"from {PREFIX}{mod}", 1))
            continue

        m = re.match(r"^(\s*)import\s+(.+?)\s*$", line)
        if m:
            indent, body = m.group(1), m.group(2)
            # An import statement cannot contain a string, so a '#' is always
            # the start of a comment. Split it off and put it back afterwards.
            comment = ""
            if "#" in body:
                body, _, tail = body.partition("#")
                comment = "  #" + tail
                body = body.strip()
            if body.endswith("\\") or not body:
                result.append(line)
                continue
            parts = [p.strip() for p in body.split(",")]
            matches = [_IMP_ONE.match(p) for p in parts]
            if all(matches) and any(
                mm.group(1).split(".")[0] in file_stems for mm in matches
            ):
                out = []
                for mm in matches:
                    dotted, alias = mm.group(1), mm.group(2)
                    if "." not in dotted and dotted in file_stems:
                        out.append(f"{PREFIX}{dotted} as {alias or dotted}")
                    else:
                        out.append(mm.group(0))
                result.append(f"{indent}import " + ", ".join(out) + comment)
                continue

        result.append(line)
    return result

def instrument_file(
    code: str,
    filename: str,
    watch_exprs: dict,
    cond_breakpoints: dict,
    all_python_files: list,
    is_entry_point: bool = False,
    breakpoint_lines=None,
) -> str:
    """
    Return the fully instrumented source for *filename*.

    Parameters
    ----------
    code              : original source text
    filename          : e.g. "code.py"
    watch_exprs       : {scope: [expr, ...]}  scope="" means global
    cond_breakpoints  : {scope: [expr, ...]}
    all_python_files  : list of all .py file names in the project (for import rewriting)
    is_entry_point    : True for code.py (or main.py when code.py absent) --
                        adds the DEBUG_START / DEBUG_END print wrappers
    breakpoint_lines  : iterable of 1-based line numbers marked as breakpoints
                        in the editor gutter. This is the primary source of
                        breakpoints; the legacy "# BULLET" comment is still
                        honoured so files written by older versions keep
                        working, but new breakpoints never touch user source.
    """
    bp_lines = set(breakpoint_lines or ())

    lines = code.splitlines()

    lines = _rewrite_imports(lines, all_python_files)

    steppable = identify_steppable_lines("\n".join(lines))
    sorted_rows = sorted(steppable)

    insertions = {}
    for row in sorted_rows:
        if row >= len(lines):
            continue
        line_content = lines[row]
        display_line = row + 1  # 1-based
        is_bp = (display_line in bp_lines) or _is_breakpoint_line(line_content)
        indent = _get_indent(line_content)
        block = _generate_debug_block(
            indent, is_bp, filename, display_line, watch_exprs, cond_breakpoints
        )
        insertions[row] = block

    out = []

    out.append("import ide_debug_state as _dbg\n")
    out.append("_ds = _dbg.DebugStates()\n")

    if is_entry_point:
        out.append(f"print('{DEBUG_START}')\n")

    for i, line in enumerate(lines):
        if i in insertions:
            out.append(insertions[i])
        out.append(line + "\n")

    if is_entry_point:
        out.append(f"print('{DEBUG_END}')\n")

    return "".join(out)

def generate_debug_state_module() -> str:
    """Return the content of ide_debug_state.py to be written to CIRCUITPY."""
    S, CO, CW = DEBUG_SIGNAL_S, DEBUG_SIGNAL_CO, DEBUG_SIGNAL_CW
    OS, OE    = DEBUG_OUT_START, DEBUG_OUT_END
    parts = []
    a = parts.append
    a('""" Util lib for debugging """'  )
    a("try:")
    a("    from time import monotonic as _time_now")
    a("    time_unit = 1000")
    a("except ImportError:")
    a("    from time import ticks_ms as _time_now")
    a("    time_unit = 1")
    a("import gc, json")
    a("from time import sleep")
    a("")
    a("def _time():")
    a("    return int(_time_now() * time_unit * 100) / 100")
    a("")
    a("def _memory():")
    a("    gc.collect()")
    a("    return gc.mem_free()")
    a("")
    a("class DebugStates:")
    a("    _instance = None")
    a("    _ready = False")
    a("    def __new__(cls, *av, **kw):")
    a("        if cls._instance is None: cls._instance = super().__new__(cls)")
    a("        return cls._instance")
    a("    def __init__(self):")
    a("        if self._ready: return")
    a("        self._ready = True")
    a("        self.t = _time()")
    a(f'        self.s = "{S}"')
    a('        self.d = {"t":_time(),"m":_memory(),"f":"","l":1,"w":{},"h":False}')
    a("    def sh(self, fn, ln):")
    a('        dur=_time()-self.t; self.d={"t":dur,"m":_memory(),"f":fn,"l":ln,"w":{},"h":False}')
    a("    def e(self):")
    a(f'        return not self.s == "{CO}"')
    a("    def us(self, c):")
    a(f'        if self.s=="{S}": return')
    a(f'        if c: self.s="{S}"')
    a("    def st(self):")
    a(f'        if self.s=="{CW}":')
    a('            self.d["h"]=False')
    a(f'            info="{OS}"+json.dumps(self.d)+"{OE}"')
    a('            print(info,end=""); sleep(len(info)*0.001)')
    a(f'        if self.s=="{S}":')
    a('            self.d["h"]=True')
    a(f'            info="{OS}"+json.dumps(self.d)+"{OE}"')
    a('            self.s=input(info)')
    a("        self.t=_time()")
    return "\n".join(parts) + "\n"

def cleanup_debug_files(drive_root: str):
    """Remove all ide_debug_* files and dirs from the root of drive_root."""
    try:
        for name in os.listdir(drive_root):
            if name.startswith(PREFIX):
                full = os.path.join(drive_root, name)
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    try:
                        os.remove(full)
                    except OSError:
                        pass
    except OSError:
        pass

def write_debug_files(
    drive_root: str,
    all_python_files: list,
    debug_files: list,
    watch_exprs: dict,
    cond_breakpoints: dict,
    breakpoints: dict = None,
):
    """
    Instrument *debug_files* (subset of *all_python_files*) and write:
      - ide_debug_state.py
      - ide_debug_<name>.py for every file in all_python_files (with import
        rewriting even for non-debug files so cross-imports resolve correctly)

    Parameters
    ----------
    drive_root        : path to the CIRCUITPY drive root
    all_python_files  : list of .py filenames present on the drive (root level)
    debug_files       : subset of all_python_files to actually instrument
    watch_exprs       : {scope: [expr, ...]}
    cond_breakpoints  : {scope: [expr, ...]}
    breakpoints       : {filename: set(1-based line numbers)} from the gutter

    Returns a report dict:
        {"steppable":   {filename: count},
         "unparseable":  {filename: reason},   # the user's own source
         "broken":       {filename: reason},   # the generated debug copy
         "breakpoints":  total_breakpoints_placed}
    """
    breakpoints = breakpoints or {}
    report = {"steppable": {}, "unparseable": {}, "broken": {}, "breakpoints": 0}

    cleanup_debug_files(drive_root)

    has_code_py = "code.py" in all_python_files
    entry_point = "code.py" if has_code_py else ("main.py" if "main.py" in all_python_files else None)

    state_path = os.path.join(drive_root, STATE_FILENAME)
    _safe_write(state_path, generate_debug_state_module())

    filtered_watches = {k: [e for e in v if e.strip()] for k, v in watch_exprs.items()}

    for filename in all_python_files:
        src_path = os.path.join(drive_root, filename)
        try:
            with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
                code = fh.read()
        except OSError:
            continue

        is_entry = filename == entry_point
        is_debug = filename in debug_files

        if is_debug:
            reason = check_parseable(code)
            if reason:
                report["unparseable"][filename] = reason

            file_bps = set(breakpoints.get(filename, ()))
            steppable = identify_steppable_lines(code)
            # Only count breakpoints that actually land on a steppable line;
            # anything else would never fire and the user should be told.
            effective = {b for b in file_bps if (b - 1) in steppable}
            report["steppable"][filename] = len(steppable)
            report["breakpoints"] += len(effective)

            instrumented = instrument_file(
                code, filename, filtered_watches, cond_breakpoints,
                all_python_files, is_entry_point=is_entry,
                breakpoint_lines=effective,
            )
        else:
            # Not instrumented, so nothing in this file references _ds. Do not
            # emit the header: constructing DebugStates here only creates a
            # chance to disturb the live session state.
            lines = _rewrite_imports(code.splitlines(), all_python_files)
            instrumented = "\n".join(lines) + "\n"

        # The instrumentation itself can produce code that does not compile,
        # from a malformed watch expression, a breakpoint on a line that will
        # not accept a statement before it, or a watch on a name that a
        # function later declares global. Checking the source only catches
        # errors the user could already see.
        broke = check_parseable(instrumented, PREFIX + filename)
        if broke:
            report["broken"][filename] = broke

        dst_name = PREFIX + filename
        dst_path = os.path.join(drive_root, dst_name)
        _safe_write(dst_path, instrumented)

    return report

def _safe_write(path: str, content: str):
    """Write text to path, creating directories as needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)

def get_all_python_files(drive_root: str) -> list:
    """
    Return a sorted list of .py filenames at the root of drive_root, excluding:
    - hidden files (leading dot)
    - boot.py
    - ide_debug_* files
    """
    result = []
    try:
        for name in os.listdir(drive_root):
            if name.startswith("."):
                continue
            if name.startswith(PREFIX):
                continue
            if name == "boot.py":
                continue
            if not name.endswith(".py"):
                continue
            full = os.path.join(drive_root, name)
            if os.path.isfile(full):
                result.append(name)
    except OSError:
        pass
    return sorted(result)

_DEBUG_BLOCK_RE = re.compile(
    re.escape(DEBUG_OUT_START) + r"(.*?)" + re.escape(DEBUG_OUT_END),
    re.DOTALL,
)

def parse_debug_output(serial_text: str) -> list:
    """
    Extract all debug state JSON objects from serial_text.

    The board emits each state wrapped in:
        \\x1b[?1049hD <json> D\\x1b[?1049l

    Returns a list of dicts.  Malformed JSON blocks are silently skipped.
    """
    states = []
    for match in _DEBUG_BLOCK_RE.finditer(serial_text):
        raw = match.group(1)
        try:
            obj = json.loads(raw)
            states.append(obj)
        except (json.JSONDecodeError, ValueError):
            pass
    return states