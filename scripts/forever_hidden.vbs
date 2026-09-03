' ORC | Windowless launcher for the supervisor.
'
' Same reason as reasoning_cycle_hidden.vbs: Task Scheduler under an
' interactive logon runs the action in the user's own desktop session, so
' powershell.exe or python.exe flashes a console window over whatever is on
' screen.  -WindowStyle Hidden does not prevent it; the window is created and
' then hidden.  Registering the task as S4U would put it in session 0 where no
' window can exist, but that needs elevation this account does not have.
'
' WScript.Shell.Run with intWindowStyle 0 never creates the window at all.
'
' The difference from the reasoning launcher is bWaitOnReturn.  This one waits
' too, because the supervisor is meant to be the long-lived process: Task
' Scheduler must see the task as still running so its MultipleInstances
' IgnoreNew setting keeps the hourly watchdog trigger from starting a second
' copy.  A launcher that returned immediately would make every hourly trigger
' look like a fresh start, and forever.py's heartbeat lock would then be the
' only thing standing between one supervisor and twenty-four of them.

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyScript  = fso.BuildPath(scriptDir, "forever.py")

' pythonw.exe would also avoid a console, but it is not always installed beside
' python.exe and a missing interpreter here would be a silent no-op forever.
' python.exe under intWindowStyle 0 is the combination that is always present.
cmd = "python -X utf8 """ & pyScript & """"

For Each a In WScript.Arguments
    If InStr(a, " ") > 0 Then cmd = cmd & " """ & a & """" Else cmd = cmd & " " & a
Next

Set sh = CreateObject("WScript.Shell")
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
