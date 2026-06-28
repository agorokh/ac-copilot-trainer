# Capture + crop/upscale + native Windows.Media.Ocr of the Track Titan overlay.
# Emits ONLY a JSON object to stdout: {"full_lines":[...],"debrief_lines":[...]}.
# All PARSING is done in Python (tools/ai_sidecar/coaching_oracle.py); this helper is capture+OCR only.
# Windows-only (Windows.Media.Ocr + System.Drawing). No third-party deps (tesseract not required).
#
# Captures land in an app-owned, per-user dir (%LOCALAPPDATA%\ac-copilot-trainer\ocr) and are deleted
# in a finally block. Exits non-zero (no JSON) when the OCR engine is unavailable or BOTH OCR passes
# fail, so the Python caller returns None (oracle unavailable) rather than a misleading empty snapshot.
#   powershell -NoProfile -ExecutionPolicy Bypass -File tt_overlay_ocr.ps1 [-Png <existing.png>]
#       [-CropX f -CropY f -CropW f -CropH f -Scale n]
param(
  [string]$Png,
  [double]$CropX = 0.385, [double]$CropY = 0.020, [double]$CropW = 0.235, [double]$CropH = 0.175,
  [double]$Scale = 3.0
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing | Out-Null
Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

# WinRT async helper — 10s/op (each Ocr pass uses up to five awaits; two passes run sequentially).
$AwaitTimeoutMs = 10000
$ext = [System.WindowsRuntimeSystemExtensions]
$asTask = ($ext.GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) {
  $m = $asTask.MakeGenericMethod($t)
  $task = $m.Invoke($null, @($op))
  if (-not $task.Wait($AwaitTimeoutMs)) {
    try { $op.Cancel() } catch {}
    throw "WinRT async timed out after ${AwaitTimeoutMs}ms"
  }
  $task.Result
}
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Media, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
[void][Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

# Prefer an English engine (TT overlay text is English); fall back to the user-profile engine.
$eng = $null
try { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language -ArgumentList 'en-US')) } catch {}
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $eng) { [Console]::Error.WriteLine('OCR engine unavailable'); exit 1 }
$maxdim = try { [int][Windows.Media.Ocr.OcrEngine]::MaxImageDimension } catch { 10000 }

# App-owned per-user capture dir; created if absent.
$appdir = Join-Path $env:LOCALAPPDATA 'ac-copilot-trainer\ocr'
New-Item -ItemType Directory -Force -Path $appdir | Out-Null
# Defensive: delete stale captures left by a prior forced termination (older than 10 min).
$staleCutoff = (Get-Date).AddMinutes(-10)
Get-ChildItem -Path $appdir -Filter '*.png' -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -lt $staleCutoff } |
  ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
$temps = @()
function New-Temp { $p = Join-Path $appdir ([guid]::NewGuid().ToString() + '.png'); $script:temps += $p; $p }

function Ocr($p) {
  # WinRT StorageFile needs a normalized, absolute Windows path.
  $p = [System.IO.Path]::GetFullPath($p)
  $sf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
  $st = Await ($sf.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  try {
    $d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($st)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $sb = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
      $r = Await ($eng.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
      # FLAT string[] via a List (no unary-comma idiom — caller wraps with @()).
      $lines = New-Object System.Collections.Generic.List[string]
      foreach ($ln in $r.Lines) { $lines.Add([string]$ln.Text) }
      $lines.ToArray()
    }
    finally { try { $sb.Dispose() } catch {} }   # dispose even if RecognizeAsync throws
  }
  finally { try { $st.Dispose() } catch {} }       # release the file handle so finally can delete it
}

try {
  # 1) Capture the primary screen (full-desktop grab — per-window BitBlt returns black for AC) or load PNG.
  if (-not $Png) {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $Png = New-Temp
    $bmp.Save($Png, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
  }
  $src = [System.Drawing.Bitmap]::FromFile($Png); $W = $src.Width; $H = $src.Height

  # 2) Crop the debrief widget and upscale — but cap to the OCR engine's max image dimension so a
  #    high-res rig's upscaled crop does not exceed what Windows.Media.Ocr accepts.
  $cx = [int]($CropX * $W); $cy = [int]($CropY * $H); $cw = [int]($CropW * $W); $ch = [int]($CropH * $H)
  $scale = $Scale
  if ($cw -gt 0 -and ($cw * $scale) -gt $maxdim) { $scale = [Math]::Min($scale, $maxdim / $cw) }
  if ($ch -gt 0 -and ($ch * $scale) -gt $maxdim) { $scale = [Math]::Min($scale, $maxdim / $ch) }
  $dw = [Math]::Max(1, [int]($cw * $scale)); $dh = [Math]::Max(1, [int]($ch * $scale))
  $dst = New-Object System.Drawing.Bitmap $dw, $dh
  $g2 = [System.Drawing.Graphics]::FromImage($dst)
  $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g2.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $dw, $dh), (New-Object System.Drawing.Rectangle $cx, $cy, $cw, $ch), [System.Drawing.GraphicsUnit]::Pixel)
  $crop = New-Temp
  $dst.Save($crop, [System.Drawing.Imaging.ImageFormat]::Png); $g2.Dispose(); $dst.Dispose(); $src.Dispose()

  # 3) Independent per-image OCR: a failed full-screen frame still yields the debrief crop, and vice-versa.
  $full = @(); $fullOk = $false
  try { $full = @(Ocr $Png); $fullOk = $true } catch { [Console]::Error.WriteLine("full OCR failed: $_") }
  $deb = @(); $debOk = $false
  try { $deb = @(Ocr $crop); $debOk = $true } catch { [Console]::Error.WriteLine("crop OCR failed: $_") }
  if (-not $fullOk -and -not $debOk) { [Console]::Error.WriteLine('both OCR passes failed'); exit 1 }

  # 4) Emit JSON (stdout only).
  ([ordered]@{ full_lines = @($full); debrief_lines = @($deb) }) | ConvertTo-Json -Depth 4 -Compress
}
finally {
  foreach ($t in $temps) { Remove-Item $t -Force -ErrorAction SilentlyContinue }
}
