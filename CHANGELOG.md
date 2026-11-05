# Changelog

## 0.3.1 - 2026-11-05
- Wave form "tide" is shown as "Cross-flow" - the name the Aqua Medic app uses for alternating linked pumps.
- README: linking two pumps (master / slave), synchronous and cross-flow operation, both confirmed on an
  EcoDrift 8.3 with a 4.3.

## 0.3.0 - 2026-11-05
- DC Runner is now read only: no write is sent to it until its writes are confirmed on a real pump. Pump,
  feed pause and timer appear as binary sensors, speed and feed pause duration as sensors.
- EcoDrift: wave mode, wave form, timer on/off and linkage confirmed on a real EcoDrift 8.3 (the pump
  reported each new value); with pump on/off, flow, frequency, feed pause and its duration, every
  EcoDrift control is now confirmed. README lists this.
- README: timer note - turning the timer off keeps the flow the timer slot set.

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
