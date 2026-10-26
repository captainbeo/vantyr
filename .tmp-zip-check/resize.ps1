$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$files = @{
  'small_zip-mark.png' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/src/assets/vantyr-mark.png'
  'small_new-mark.png' = 'D:/worktrees/vantyr-main/web/src/assets/vantyr-mark.png'
  'small_brand-new.png' = 'D:/worktrees/vantyr-main/deploy/vantyr/static/brand/logo.png'
}
$outDir = 'D:/worktrees/commercial-mvp/.tmp-zip-check'
foreach ($entry in $files.GetEnumerator()) {
  $img = [System.Drawing.Image]::FromFile($entry.Value)
  $size = 220
  $w = $size
  $h = [int]([math]::Round($img.Height * $size / $img.Width))
  if ($h -gt $size) { $h = $size; $w = [int]([math]::Round($img.Width * $size / $img.Height)) }
  $bmp = New-Object System.Drawing.Bitmap([int]$w, [int]$h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($img, 0, 0, $w, $h)
  $out = Join-Path $outDir $entry.Key
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose(); $img.Dispose()
  Write-Output "saved $out ($w x $h)"
}
