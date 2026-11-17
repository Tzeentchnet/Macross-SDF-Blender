# Regenerate the standard verification set in E:\tests\macross_sdf
param(
    [string]$Iso = "F:\Recomp_GameSource\Chou Jikuu Yousai Macross (Japan).iso",
    [string]$Blender = "D:\Blender Foundation\Blender 5.2\blender.exe",
    [string]$Out = "E:\tests\macross_sdf"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$test = Join-Path $root "tools\blender_test_import.py"
New-Item -ItemType Directory -Force $Out | Out-Null

function Run([string[]]$extra) {
    & $Blender -b --factory-startup --python $test -- --iso $Iso --out $Out @extra 2>&1 |
        Select-String -Pattern "^RESULT" | ForEach-Object { $_.Line.Substring(0, [Math]::Min(160, $_.Line.Length)) }
}

# Player craft: rest views + key clips (fighter, gerwalk, battroid, transformations)
Run @("--views", "persp,front,side", "--max-models", "2", "--frames", "3", "--max-actions", "6",
      "--actions", "t00_transf,t01_transf,g01_fwd,b00_stdneutral,b01_stdfor,b25_stdattack",
      "BIN.CVM/VF1J_AC.CMP", "BIN.CVM/VF1S_AC.CMP", "BIN.CVM/VE1_AC.CMP", "BIN.CVM/VF4_AC.CMP", "BIN.CVM/VF1JAMD_AC.CMP")
# Livery variant
Run @("--frames", "0", "--max-actions", "0", "--max-models", "2", "--variant", "BIN.CVM/VF1J_COL_03.MRG", "BIN.CVM/VF1J_AC.CMP")
# Enemies
Run @("--frames", "3", "--max-actions", "2", "--max-models", "1",
      "BIN.CVM/ENM_GLG.CMP", "BIN.CVM/ENM_RGN.CMP", "BIN.CVM/ENM_NJD.CMP", "BIN.CVM/ENM_QDL.CMP", "BIN.CVM/ENM_POD.CMP", "BIN.CVM/ENM_THUVA.CMP")
# Stages
Run @("--frames", "0", "BIN.CVM/GD_00.CMP", "BIN.CVM/GD_01.CMP", "BIN.CVM/GD_03.CMP", "BIN.CVM/GD_08.CMP", "BIN.CVM/GD_13.CMP", "BIN.CVM/GD_27.CMP")
# Event scene + FX
Run @("--frames", "0", "--max-models", "3", "BIN.CVM/AUTH_M01P1N0.CMP", "BIN.CVM/FX.CMP")
