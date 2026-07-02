$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root
try {
    $tests = @(
        "test_examples_py.py",
        "test_lexer_dump_format.py",
        "test_mir.py",
        "test_x64_layers.py",
        "tests/run.py"
    )
    $failed = @()

    foreach ($test in $tests) {
        Write-Host "=== $test ==="
        python $test
        if ($LASTEXITCODE -ne 0) {
            $failed += $test
            Write-Host "FAILED $test exit=$LASTEXITCODE"
        } else {
            Write-Host "PASSED $test"
        }
    }

    if ($failed.Count -gt 0) {
        Write-Host "Failed tests: $($failed -join ', ')"
        exit 1
    }

    Write-Host "All $($tests.Count) tests passed."
} finally {
    Pop-Location
}
