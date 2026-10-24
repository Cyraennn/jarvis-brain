' CYRAEN Brain - sessiz baslatici (konsol penceresi acmaz)
' Masaustu kisayolu bu dosyayi cagirir.
Option Explicit

Dim fso, shell, here, projectDir, pyw, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Bu betigin bulundugu klasor -> ..\ = cyraen-brain kok dizini
here = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(here)

' pythonw.exe'yi bul: once bilinen kurulum, sonra PATH
pyw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pyw) Then
    pyw = "pythonw.exe"
End If

shell.CurrentDirectory = projectDir
cmd = """" & pyw & """ """ & projectDir & "\run_ui.py"""

' 0 = pencere gizli (PySide arayuzu kendi penceresini acar), False = bekleme
shell.Run cmd, 0, False
