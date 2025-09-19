# How to Set Up Wi-Fi

1. **Enter Wi-Fi credentials**

   Use `wpa_passphrase` to append your network to the config:

   ```bash
   sudo sh -c "wpa_passphrase 'TestWifi' 'TestPassword' >> /etc/wpa_supplicant/wpa_supplicant.conf"
   ```

2. **Verify the network is saved**

   Open the configuration file:

   ```bash
   sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
   ```

3. **Set Wi-Fi priority**

   Inside your `network` block, add a priority (higher = preferred):

   ```text
   network={
       ssid="TestWifi"
       psk=XXXXXXXXXXXX
       priority=1
   }
   ```

4. **Save and reconfigure**

   Apply the changes without rebooting:

   ```bash
   sudo wpa_cli -i wlan0 reconfigure
   ```