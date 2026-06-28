# Capture + crop/upscale + native Windows.Media.Ocr of the Track Titan overlay.
# Emits ONLY a JSON object to stdout: {"full_lines":[...],"debrief_lines":[...]}.
# All PARSING is done in Python (tools/ai_sidecar/coaching_oracle.py); this helper is capture+OCR only.
# Windows-only (Windows.Media.Ocr + System.Drawing). No third-party deps (tesseract not required).
#
# Captures land in an app-owned, per-user dir (%LOCALAPPDATA%\ac-copilot-trainer\ocr) and are deleted
# in a finally block — a full-desktop screenshot never lingers in shared/process-wide temp.
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

# App-owned per-user capture dir (LOCALAPPDATA is ACL'd to the user); created if absent.
$appdir = Join-Path $env:LOCALAPPDATA 'ac-copilot-trainer\ocr'
New-Item -ItemType Directory -Force -Path $appdir | Out-Null
$temps = @()
function New-Temp { $p = Join-Path $appdir ([guid]::NewGuid().ToString() + '.png'); $script:temps += $p; $p }

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

  # 2) Crop the debrief widget and upscale (stylized text OCRs far better enlarged).
  $cx = [int]($CropX * $W); $cy = [int]($CropY * $H); $cw = [int]($CropW * $W); $ch = [int]($CropH * $H)
  $dst = New-Object System.Drawing.Bitmap ([int]($cw * $Scale)), ([int]($ch * $Scale))
  $g2 = [System.Drawing.Graphics]::FromImage($dst)
  $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g2.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $dst.Width, $dst.Height), (New-Object System.Drawing.Rectangle $cx, $cy, $cw, $ch), [System.Drawing.GraphicsUnit]::Pixel)
  $crop = New-Temp
  $dst.Save($crop, [System.Drawing.Imaging.ImageFormat]::Png); $g2.Dispose(); $dst.Dispose(); $src.Dispose()

  # 3) OCR via native Windows.Media.Ocr (async awaited).
  $ext = [System.WindowsRuntimeSystemExtensions]
  $asTask = ($ext.GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, $t) { $m = $asTask.MakeGenericMethod($t); $task = $m.Invoke($null, @($op)); [void]$task.Wait(-1); $task.Result }
  [void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  [void][Windows.Media.Ocr.OcrEngine, Windows.Media, ContentType = WindowsRuntime]
  [void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
  [void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
  $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if (-not $eng) { Write-Error 'OCR engine unavailable'; exit 1 }
  function Ocr($p) {
    # WinRT StorageFile needs a normalized, absolute Windows path (forward slashes / relative fail).
    $p = [System.IO.Path]::GetFullPath($p)
    $sf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
    $st = Await ($sf.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($st)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $sb = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $r = Await ($eng.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    # Return a FLAT string[] via a List (no unary-comma idiom — the caller wraps with @()).
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($ln in $r.Lines) { $lines.Add([string]$ln.Text) }
    $lines.ToArray()
  }
  # Independent per-image OCR: if the large full-screen frame fails, the debrief crop can still succeed.
  $full = @(); try { $full = @(Ocr $Png) } catch { [Console]::Error.WriteLine("full OCR failed: $_") }
  $deb = @(); try { $deb = @(Ocr $crop) } catch { [Console]::Error.WriteLine("crop OCR failed: $_") }

  # 4) Emit JSON (stdout only).
  ([ordered]@{ full_lines = @($full); debrief_lines = @($deb) }) | ConvertTo-Json -Depth 4 -Compress
}
finally {
  foreach ($t in $temps) { Remove-Item $t -Force -ErrorAction SilentlyContinue }
}
