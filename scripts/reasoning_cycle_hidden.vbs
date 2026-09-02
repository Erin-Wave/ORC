' ORC | Windowless launcher for the reasoning cycle.
'
' Task Scheduler under an interactive logon runs the action in the user's own
' desktop session, so powershell.exe flashes a console window over whatever is
' on screen - a game, a call, anything.  -WindowStyle Hidden does not prevent
' it; the window is created and then hidden.  Registering the task as S4U would
' put it in session 0 where no window can exist at all, but that requires
' elevation this account does not have.
'
' WScript.Shell.Run with intWindowStyle 0 never creates the window in the first
' place.  bWaitOnReturn is True so the PowerShell exit code propagates back to
' Task Scheduler, which is what drives its retry-on-failure setting.

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript  = fso.BuildPath(scriptDir, "reasoning_cycle.ps1")

cmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & psScript & """"

' Anything passed to the launcher goes through to the script, so the scheduled
' path itself can be exercised with -PromptFile pointing at a harmless prompt.
For Each a In WScript.Arguments
    If InStr(a, " ") > 0 Then cmd = cmd & " """ & a & """" Else cmd = cmd & " " & a
Next

Set sh = CreateObject("WScript.Shell")
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
