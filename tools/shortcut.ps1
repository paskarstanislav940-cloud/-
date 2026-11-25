# Creates or removes a Windows shortcut (.lnk). Used by START.bat.
# Example: shortcut.ps1 -Folder Desktop -Name "fioritura" -Target "C:\path\START.bat" -Style 1
#   -Folder  Desktop | Startup   (special folder name)
#   -Style   1 = normal window, 7 = minimized
param(
    [Parameter(Mandatory = $true)][string]$Folder,
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Target = "",
    [int]$Style = 1,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
try {
    $dir = [Environment]::GetFolderPath($Folder)
    $lnk = Join-Path $dir ($Name + ".lnk")
    if ($Remove) {
        Remove-Item -LiteralPath $lnk -ErrorAction SilentlyContinue
        exit 0
    }
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $Target
    $s.WorkingDirectory = Split-Path -Parent $Target
    $s.WindowStyle = $Style
    $s.Save()
    exit 0
}
catch {
    Write-Host $_.Exception.Message
    exit 1
}
