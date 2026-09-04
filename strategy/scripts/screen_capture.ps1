Add-Type -AssemblyName System.Windows.Forms,System.Drawing
New-Item -ItemType Directory -Force C:\Temp | Out-Null
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$b.Save('C:\Temp\pc2_screen.png')
$g.Dispose(); $b.Dispose()
Write-Output "saved $($bounds.Width)x$($bounds.Height)"
