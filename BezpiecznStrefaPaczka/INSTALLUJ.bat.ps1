
$ErrorActionPreference="Stop"
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$mc=Join-Path $env:APPDATA ".minecraft"
$mods=Join-Path $mc "mods"
$shaders=Join-Path $mc "shaderpacks"
$config=Join-Path $mc "config"
New-Item -ItemType Directory -Force -Path $mods,$shaders,$config|Out-Null

function GetFile($id){
  $v=Invoke-RestMethod "https://api.modrinth.com/v2/version/$id" -Headers @{"User-Agent"="BezpiecznaStrefaPaczka/1.0"}
  $f=$v.files|?{$_.primary -eq $true}|select -First 1
  if(!$f){$f=$v.files|select -First 1}
  if(!$f){throw "Brak pliku dla wersji $id"}
  return $f
}
function DL($f,$dest){
  Write-Host "Pobieram $($f.filename)..."
  Invoke-WebRequest $f.url -OutFile $dest -UseBasicParsing -Headers @{"User-Agent"="BezpiecznaStrefaPaczka/1.0"}
}

Write-Host "Bezpieczna Strefa - instalacja grafiki 1.21.11" -ForegroundColor Green

# Usuń tylko zarządzane konflikty.
Get-ChildItem $mods -File -ErrorAction SilentlyContinue|?{
 $_.Name.ToLower() -match '^(iris|sodium|fabric-api|hand-shaker).*\.jar$'
}|Remove-Item -Force -ErrorAction SilentlyContinue

$pins=@(
 @{id="fDpuVzVr"; name="Iris 1.10.7"},
 @{id="UddlN6L4"; name="Sodium 0.8.7"},
 @{id="DdVHbeR1"; name="Fabric API 0.141.1"},
 @{id="r5q5dcGl"; name="Hand Shaker Client 5.1.1"}
)
foreach($p in $pins){
  $f=GetFile $p.id
  DL $f (Join-Path $mods $f.filename)
}

# Complementary Unbound r5.7.1
$sf=GetFile "d8rcvDTp"
Get-ChildItem $shaders -File -ErrorAction SilentlyContinue|?{$_.Name -match '^ComplementaryUnbound_.*\.zip$'}|Remove-Item -Force -ErrorAction SilentlyContinue
DL $sf (Join-Path $shaders $sf.filename)

@"
enableShaders=true
shaderPack=$($sf.filename)
"@|Set-Content (Join-Path $config "iris.properties") -Encoding UTF8

Write-Host ""
Write-Host "GOTOWE." -ForegroundColor Green
Write-Host "W TLauncher/Crystal/innym launcherze wybierz Fabric 1.21.11 i uruchom gre."
Write-Host "Serwer: bezpiecznastrefa.6mc.pl"
Read-Host "ENTER aby zamknac"
