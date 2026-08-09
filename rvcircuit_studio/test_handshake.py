import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
app = QApplication([])
from patched.debugger_panel import DebuggerPanel
from patched.cp_debugger import DEBUG_START

# Silence modal dialogs so the event loop is never blocked in the harness.
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning     = staticmethod(lambda *a, **k: None)

class FakeREPL:
    def __init__(self, panel, ignore_n):
        self.panel, self.ignore_n = panel, ignore_n
        self.seen, self.log, self.is_connected = 0, [], True
    def _write_bytes(self, data):
        self.log.append(data)
        if data == b"\x03":
            self.seen += 1
            if self.seen > self.ignore_n:
                QTimer.singleShot(30, lambda: self.panel.feed_serial("\r\n>>> "))
        elif data.startswith(b"from ide_debug_"):
            QTimer.singleShot(50, lambda: self.panel.feed_serial(f"\r\n{DEBUG_START}\r\n"))

def run(ignore_n, label, bps=None, budget=25000):
    drive = tempfile.mkdtemp()
    open(os.path.join(drive, "code.py"), "w").write("x = 1\nprint(x)\nwhile True:\n    x += 1\n")
    p = DebuggerPanel()
    p.set_drive(drive)
    repl = FakeREPL(p, ignore_n)
    p.set_repl(repl)
    p.collect_breakpoints = lambda: (bps or {})
    res = {}
    of = p._start_failed
    p._start_failed = lambda t, d: (res.__setitem__("fail", t), app.quit())
    oo = p._on_session_started
    def w(ok):
        oo(ok); res["ok"] = ok; app.quit()
    p._on_session_started = w
    QTimer.singleShot(budget, app.quit)
    p._on_start_clicked()
    app.exec()
    imported = any(b.startswith(b"from ide_debug_") for b in repl.log)
    inst = os.path.exists(os.path.join(drive, "ide_debug_code.py"))
    body = open(os.path.join(drive, "ide_debug_code.py")).read() if inst else ""
    print(f"{label:46} started={res.get('ok')} ctrlC={repl.seen:2} "
          f"import={imported} bp_block={'_ds.us(True)' in body} fail={res.get('fail')}")
    shutil.rmtree(drive, ignore_errors=True)

run(0,  "responsive board")
run(4,  "swallows 4 Ctrl+C (slow display init)")
run(3,  "slow board, breakpoint on line 4", bps={"code.py": {4}})
run(99, "board never answers -> must fail cleanly", budget=20000)
