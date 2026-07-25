# PowerShell CLI Wrapper for IPAM Test Suite
param(
    [switch]$Install,
    [switch]$Quiet,
    [string]$Filter,
    [switch]$Report
)

$argsList = @()
if ($Install) { $argsList += "--install" }
if ($Quiet) { $argsList += "--quiet" }
if ($Filter) { $argsList += "--filter"; $argsList += $Filter }
if ($Report) { $argsList += "--report" }

python run_tests.py $argsList
exit $LASTEXITCODE
