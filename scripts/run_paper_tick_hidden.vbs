' XSP Killer paper tick — hidden.
' Task Scheduler Interactive must not flash a console every 15m.
' Imports TipDrop (UW/TipSeeker shadow) which used to dump DATA_DIR to a visible window.
' Arg 2 = 0  -> hidden window
' Arg 3 = True -> wait so the task gets a real exit code
Option Explicit
Dim sh, root, py, tick, cmd, rc
Set sh = CreateObject("WScript.Shell")
root = "C:\Users\Owner\OneDrive\Desktop\xsp-killer"
py = root & "\.venv\Scripts\python.exe"
tick = root & "\scripts\paper_tick.py"
cmd = """" & py & """ """ & tick & """"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
