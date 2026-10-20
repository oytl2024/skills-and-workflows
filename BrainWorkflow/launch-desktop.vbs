Option Explicit
Dim shell, fso, env, root, workspace, python, prefix, folder, name, candidate
Dim command, argument, result, errorNumber
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set env = shell.Environment("PROCESS")
root = fso.GetParentFolderName(WScript.ScriptFullName)
workspace = fso.GetParentFolderName(fso.GetParentFolderName(root))
shell.CurrentDirectory = root
env("SystemRoot") = fso.GetSpecialFolder(0).Path
env("windir") = env("SystemRoot")
python = env("BRAINWORKFLOW_PYTHON")
prefix = ""
If python <> "" Then
    If Not fso.FileExists(python) Then
        Fail "BRAINWORKFLOW_PYTHON must name an installed python.exe or pythonw.exe."
    End If
Else
    For Each folder In Array(root & "\.venv\Scripts", workspace & "\.venv\Scripts")
        For Each name In Array("pythonw.exe", "python.exe")
            candidate = fso.BuildPath(folder, name)
            If python = "" And fso.FileExists(candidate) Then python = candidate
        Next
    Next
    For Each folder In Split(env("PATH"), ";")
        folder = Replace(shell.ExpandEnvironmentStrings(folder), Chr(34), "")
        If folder <> "" Then
            For Each name In Array("pythonw.exe", "python.exe", "py.exe")
                candidate = fso.BuildPath(folder, name)
                If python = "" And fso.FileExists(candidate) Then
                    python = candidate
                    If name = "py.exe" Then prefix = " -3"
                End If
            Next
        End If
    Next
End If
If python = "" Then
    Fail "Python was not found. Install Python 3.10+ with the project's dependencies, or set BRAINWORKFLOW_PYTHON to its full executable path."
End If
command = QuoteArgument(python) & prefix & " -m wqb.desktop"
For Each argument In WScript.Arguments
    command = command & " " & QuoteArgument(argument)
Next
On Error Resume Next
result = shell.Run(command, 0, True)
errorNumber = Err.Number
On Error GoTo 0
If errorNumber <> 0 Then Fail "Could not start Python: " & python
If result <> 0 Then
    Fail "Desktop startup failed (exit " & result & "). Interpreter: " & python & vbCrLf & _
         "See runs\desktop\startup.log and backend.log under the workspace (or your --runs-root). " & _
         "For interpreter/import errors, run launch-desktop.cmd from a terminal after checking BRAINWORKFLOW_PYTHON."
End If
WScript.Quit 0

Sub Fail(message)
    ' Input: diagnostic string. Output: exit 1. Show errors under both WScript and console hosts.
    If LCase(fso.GetFileName(WScript.FullName)) = "cscript.exe" Then
        WScript.Echo message
    Else
        MsgBox message, vbCritical, "BrainWorkflow startup failed"
    End If
    WScript.Quit 1
End Sub

Function QuoteArgument(value)
    ' Input: string. Output: string. Escape one Windows argv element, including trailing backslashes.
    Dim i, character, slashes, quoted
    quoted = Chr(34)
    slashes = 0
    For i = 1 To Len(value)
        character = Mid(value, i, 1)
        If character = "\" Then
            slashes = slashes + 1
        Else
            If character = Chr(34) Then
                quoted = quoted & String(slashes * 2 + 1, "\") & character
            Else
                quoted = quoted & String(slashes, "\") & character
            End If
            slashes = 0
        End If
    Next
    QuoteArgument = quoted & String(slashes * 2, "\") & Chr(34)
End Function
