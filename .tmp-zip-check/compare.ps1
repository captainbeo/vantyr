$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$base = 'D:/worktrees/commercial-mvp/.tmp-zip-check'
$zip = [System.Drawing.Image]::FromFile("$base/small_zip-mark.png")
$new = [System.Drawing.Image]::FromFile("$base/small_new-mark.png")
$pad = 48; $labelH = 88; $imgH = 260
$zipW = [int][math]::Round($zip.Width * $imgH / $zip.Height)
$newW = [int][math]::Round($new.Width * $imgH / $new.Height)
$W = $pad * 3 + $zipW + $newW
$H = $labelH + $imgH + 20
$bmp = New-Object System.Drawing.Bitmap([int]$W, [int]$H)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::FromArgb(255, 10, 10, 13))
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias
$titleFont = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
$subFont = New-Object System.Drawing.Font('Segoe UI', 10)
$white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$orange = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 255, 138, 61))
$gray = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 150, 150, 160))
$g.DrawString('ORIGINAL - your Lovable zip', $titleFont, $white, $pad, 20)
$g.DrawString('3D intro design I deployed, pinned-next10', $subFont, $gray, $pad, 46)
$g.DrawImage($zip, $pad, $labelH, $zipW, $imgH)
$x2 = $pad * 2 + $zipW
$g.DrawString('CURRENT LIVE - v2 swap', $titleFont, $orange, $x2, 20)
$g.DrawString('pinned-next11, from the relay-review instruction', $subFont, $gray, $x2, 46)
$g.DrawImage($new, $x2, $labelH, $newW, $imgH)
$bmp.Save("$base/logo-compare.jpg", [System.Drawing.Imaging.ImageFormat]::Jpeg)
$g.Dispose(); $bmp.Dispose(); $zip.Dispose(); $new.Dispose()
Write-Output "saved logo-compare.jpg ($W x $H)"
