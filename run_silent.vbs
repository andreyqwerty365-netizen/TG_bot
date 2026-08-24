Set WshShell = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")
ScriptDir = FileSystem.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir
WshShell.Run chr(34) & ScriptDir & "\run.bat" & chr(34), 0
Set WshShell = Nothing
Set FileSystem = Nothing
