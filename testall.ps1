$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root
try {
    Write-Host "=== bootstrap_fixed_point.py ==="
    python bootstrap_fixed_point.py
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

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
    python runtests.py
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

    Write-Host "All v1 tests passed."
} finally {
    Pop-Location
}
