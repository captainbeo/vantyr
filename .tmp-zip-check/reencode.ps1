$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$files = @{
  'cmp_zip-mark.jpg' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/small_zip-mark.png'
  'cmp_new-mark.jpg' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/small_new-mark.png'
  'cmp_zip-lockup.jpg' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/small_zip-lockup.png'
  'cmp_v2-logo.jpg' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/small_v2-logo.png'
  'cmp_v2-icon.jpg' = 'D:/worktrees/commercial-mvp/.tmp-zip-check/small_v2-icon.png'
}
foreach ($entry in $files.GetEnumerator()) {
  $img = [System.Drawing.Image]::FromFile($entry.Value)
  $out = 'D:/worktrees/commercial-mvp/.tmp-zip-check/' + $entry.Key
  $img.Save($out, [System.Drawing.Imaging.ImageFormat]::Jpeg)
  $img.Dispose()
  Write-Output "saved $out"
}
