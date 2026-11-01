Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' 0 означает скрытый режим (окно полностью скрыто)
WshShell.Run "pythonw.exe main.py", 0, False
Set WshShell = Nothing
