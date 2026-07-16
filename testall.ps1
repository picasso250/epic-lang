$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root
try {
    $tests = @(Get-ChildItem -File -Filter "test_*.py" | Sort-Object Name)
    $failed = @()

    foreach ($test in $tests) {
        Write-Host "=== $($test.Name) ==="
        python $test.Name
        if ($LASTEXITCODE -ne 0) {
            $failed += $test.Name
            Write-Host "FAILED $($test.Name) exit=$LASTEXITCODE"
        } else {
            Write-Host "PASSED $($test.Name)"
        }
    }

    Write-Host "=== runtests.py ==="
    python runtests.py --linker py
    if ($LASTEXITCODE -ne 0) {
        $failed += "runtests.py"
        Write-Host "FAILED runtests.py exit=$LASTEXITCODE"
    } else {
        Write-Host "PASSED runtests.py"
    }

    if ($failed.Count -gt 0) {
        Write-Host "Failed tests: $($failed -join ', ')"
        exit 1
    }

    Write-Host "All stage-0 tests passed."
} finally {
    Pop-Location
}
