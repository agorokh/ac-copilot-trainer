# Capture + crop/upscale + native Windows.Media.Ocr of the Track Titan overlay.
# Emits ONLY a JSON object to stdout: {"full_lines":[...],"debrief_lines":[...]}.
# All PARSING is done in Python (tools/ai_sidecar/coaching_oracle.py); this helper is capture+OCR only.
# Windows-only (Windows.Media.Ocr + System.Drawing). No third-party deps (tesseract not required).
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

# 1) Capture the primary screen (full-desktop grab — per-window BitBlt returns black for AC) or load PNG.
$temps = @()
if (-not $Png) {
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
  $Png = [System.IO.Path]::GetTempFileName() + '.png'; $temps += $Png
  $bmp.Save($Png, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
}
$src = [System.Drawing.Bitmap]::FromFile($Png); $W = $src.Width; $H = $src.Height

# 2) Crop the debrief widget and upscale (stylized text OCRs far better enlarged).
$cx = [int]($CropX * $W); $cy = [int]($CropY * $H); $cw = [int]($CropW * $W); $ch = [int]($CropH * $H)
$dst = New-Object System.Drawing.Bitmap ([int]($cw * $Scale)), ([int]($ch * $Scale))
$g2 = [System.Drawing.Graphics]::FromImage($dst)
$g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g2.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $dst.Width, $dst.Height), (New-Object System.Drawing.Rectangle $cx, $cy, $cw, $ch), [System.Drawing.GraphicsUnit]::Pixel)
$crop = [System.IO.Path]::GetTempFileName() + '.png'; $temps += $crop
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
  $sf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
  $st = Await ($sf.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($st)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $sb = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $r = Await ($eng.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
  , @($r.Lines | ForEach-Object { $_.Text })
}
$full = Ocr $Png
$deb = Ocr $crop
foreach ($t in $temps) { Remove-Item $t -ErrorAction SilentlyContinue }

# 4) Emit JSON (stdout only).
([ordered]@{ full_lines = @($full); debrief_lines = @($deb) }) | ConvertTo-Json -Depth 4 -Compress
