' ORC | Windowless launcher for the weekly kernel review.
'
' Same reasoning as reasoning_cycle_hidden.vbs: Task Scheduler under an
' interactive logon runs the action in the user's own desktop session, so a
' console window would appear over whatever is on screen.  intWindowStyle 0
' never creates it; bWaitOnReturn is True so the exit code still reaches the
' scheduler.
'
' The review reports and never edits.  A model that could patch the evaluators
' could also quietly change what a result means.

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot  = fso.GetParentFolderName(scriptDir)
pyScript  = fso.BuildPath(scriptDir, "kernel_review.py")
logDir    = fso.BuildPath(repoRoot, "logs")
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
logFile   = fso.BuildPath(logDir, "kernel_review.log")

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = repoRoot

' The findings are the point, so the run is logged rather than discarded: a
' weekly review whose output goes nowhere is a weekly review nobody reads.
cmd = "cmd /c python """ & pyScript & """ >> """ & logFile & """ 2>&1"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
