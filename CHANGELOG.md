# Changelog

## 0.2.0 - 2026-11-05
- Automatic discovery: after the first pump is set up, the network is searched every 10 minutes and when a
  pump goes offline; new pumps appear under "Discovered", known pumps follow a changed IP address by themselves.
- Reconfigure: change the address by hand (checked against the device id).
- Sensor "Feed pause ends" (timestamp) and attribute `feed_end` on the feed pause switch.
- Diagnostics download (passcode, MAC and device id redacted).
- Translations: Dutch, French, Spanish, Italian, Polish.

## 0.1.0 - 2026-11-05
- First version: EcoDrift x.3 / SmartDrift over the Gizwits LAN protocol (TCP 12416), no cloud.
  Pump on/off, wave mode, wave form, flow, frequency, feed pause and duration, timer on/off,
  linkage, current timer mode, timer slots (read), seven fault flags. Network discovery in the
  config flow; the passcode is fetched from the pump.
- DC Runner x.3 decoded from the public datapoint schema, not yet tested on hardware.
- Writes start from the last status block; a flow write always carries the frequency (firmware
  04020B25 ignores flow alone). Status pushes as `0x0093` with device id are decoded.
