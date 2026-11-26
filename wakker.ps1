# Houdt de pc wakker (ook het scherm) tot het opgegeven moment, bv.
#   powershell -WindowStyle Hidden -File wakker.ps1 "2026-11-27 10:20"
# Nodig omdat deze laptop moderne stand-by gebruikt: een geplande taak wekt hem daar niet uit (26/11/2026).
# Zonder scherm-aan-vraag gaat een moderne-stand-by-laptop toch slapen zodra het scherm uitgaat.
# Een dichtgeklapt deksel of 'Slaapstand' kiezen wint altijd.
param([Parameter(Mandatory = $true)][string]$Tot)
$einde = [datetime]::Parse($Tot)
Add-Type -Name P -Namespace Wakker -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
# ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
[Wakker.P]::SetThreadExecutionState(0x80000003) | Out-Null
while ((Get-Date) -lt $einde) { Start-Sleep -Seconds 60 }
[Wakker.P]::SetThreadExecutionState(0x80000000) | Out-Null
