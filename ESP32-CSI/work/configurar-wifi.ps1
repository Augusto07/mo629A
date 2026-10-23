Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Wi-Fi do ESP32 - teste CSI'
$form.ClientSize = New-Object System.Drawing.Size(440,245)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$text = New-Object System.Windows.Forms.Label
$text.Text = 'Informe uma rede de 2,4 GHz. Os dados ficam apenas nesta pasta local e no firmware do ESP32.'
$text.SetBounds(20,15,400,45)
$form.Controls.Add($text)
$ssidLabel = New-Object System.Windows.Forms.Label
$ssidLabel.Text = 'Nome da rede (SSID)'
$ssidLabel.SetBounds(20,65,180,20)
$form.Controls.Add($ssidLabel)
$ssid = New-Object System.Windows.Forms.TextBox
$ssid.SetBounds(20,88,400,24)
$form.Controls.Add($ssid)
$passwordLabel = New-Object System.Windows.Forms.Label
$passwordLabel.Text = 'Senha'
$passwordLabel.SetBounds(20,122,180,20)
$form.Controls.Add($passwordLabel)
$password = New-Object System.Windows.Forms.TextBox
$password.UseSystemPasswordChar = $true
$password.SetBounds(20,145,400,24)
$form.Controls.Add($password)
$save = New-Object System.Windows.Forms.Button
$save.Text = 'Salvar Wi-Fi'
$save.SetBounds(290,193,130,32)
$save.Add_Click({
    if ([string]::IsNullOrWhiteSpace($ssid.Text) -or [Text.Encoding]::UTF8.GetByteCount($ssid.Text) -gt 32 -or [Text.Encoding]::UTF8.GetByteCount($password.Text) -gt 64) {
        [System.Windows.Forms.MessageBox]::Show('Confira o nome da rede (1 a 32 bytes) e a senha (ate 64 bytes).')
        return
    }
    $escapeSsid = $ssid.Text.Replace('\','\\').Replace('"','\"')
    $escapePassword = $password.Text.Replace('\','\\').Replace('"','\"')
    $config = "CONFIG_EXAMPLE_WIFI_SSID=`"$escapeSsid`"`nCONFIG_EXAMPLE_WIFI_PASSWORD=`"$escapePassword`"`n"
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'wifi.defaults'), $config, (New-Object Text.UTF8Encoding($false)))
    $password.Clear()
    $form.Close()
})
$form.Controls.Add($save)
$form.AcceptButton = $save
[void]$form.ShowDialog()
