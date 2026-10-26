$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$files = @{
  'small_v2-logo.png' = 'D:/Downloads/vantyr-logo-3d-v2.png'
  'small_v2-icon.png' = 'D:/Downloads/vantyr-icon-3d.png'
  'small_zip-lockup.png' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/src/assets/valantyr-logo.png'
}
$outDir = 'D:/worktrees/commercial-mvp/.tmp-zip-check'
foreach ($entry in $files.GetEnumerator()) {
  $img = [System.Drawing.Image]::FromFile($entry.Value)
  $size = 420
  $w = [int]([math]::Min($size, $img.Width * $size / $img.Height))
  $h = [int]([math]::Round($img.Height * $w / $img.Width))
  $bmp = New-Object System.Drawing.Bitmap([int]$w, [int]$h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($img, 0, 0, $w, $h)
  $out = Join-Path $outDir $entry.Key
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose(); $img.Dispose()
  Write-Output "saved $out ($w x $h)"
}
