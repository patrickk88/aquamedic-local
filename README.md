# Aqua Medic Local (unofficial)

Local control of Aqua Medic app-controlled pumps in Home Assistant - no cloud, no account.

> **Unofficial community project. Not affiliated with, endorsed by or supported by Aqua Medic.**
> "Aqua Medic", "EcoDrift", "SmartDrift" and "DC Runner" are the manufacturer's product names and
> are used only to describe which devices this integration works with.

The Wi-Fi module in these pumps runs Gizwits firmware. Besides the cloud the official app uses,
it speaks a small LAN protocol (UDP 12414 for discovery, TCP 12416 for control) - the same one
the app uses when your phone is at home. This integration talks to that port only. The app and
the pump's own cloud connection keep working; several clients can be logged in at once.

## Supported devices (v0.1)

| Device | Read | Control | Tested firmware |
|---|---|---|---|
| EcoDrift x.3 / SmartDrift x.1 (Gizwits product `63632f49…`) | on/off, wave mode, wave form, flow, frequency, feed pause and its duration, timer on/off, current timer mode with its flow/frequency, timer slots, linkage, seven fault flags | pump on/off, wave mode (classic / sine / random / constant), wave form (pulse / tide), flow %, frequency %, feed pause, feed pause duration, timer on/off, linkage | module 04020B25 (EcoDrift 4.3 and 8.3); writing tested with pump on/off, flow, frequency, feed pause and feed pause duration |
| DC Runner x.3 return / skimmer pump (`00276aa0…`) | on/off, control mode, speed, feed pause, timer, current timer mode, timer slots, pump clock, fault flags | pump on/off, speed, feed pause, feed pause duration, timer on/off | **untested** - decoded from the public datapoint schema, testers welcome |

Writing timer slots (the 48-slot schedule) is not offered yet; the slots are shown as attributes
of the *Timer* switch and the *Timer slots* sensor.

## Use at your own risk

This software is provided "as is", without warranty of any kind (see the MIT license). It controls
pumps that keep a tank alive. A bug, a wrong automation or a lost network connection can stop the
flow or run a pump dry. **You alone are responsible for your tank.** Watch the tank after installing
or updating, keep the pumps' own settings sensible, and do not let automations switch pumps off
without a limit you have checked. The authors are not liable for any damage to equipment, livestock
or property.

The protocol was taken from what the pumps send on the network and from the publicly readable
datapoint schema of each product; no firmware was decompiled and no manufacturer files or keys are
included. Using it may void your warranty.

## Installation

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=patrickk88&repository=aquamedic-local&category=integration)

**HACS:** the button adds this repository to HACS in your own Home Assistant (as a custom
repository, type *Integration*); then download *Aqua Medic Local* and restart Home Assistant.
Without the button: HACS -> menu -> *Custom repositories* -> `https://github.com/patrickk88/aquamedic-local`,
type *Integration*.

**Manual:** copy `custom_components/aquamedic_local` into your `config/custom_components/` and restart.

Then *Settings -> Devices & services -> Add integration -> Aqua Medic Local*, or:

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=aquamedic_local)

Pumps on your network
are listed; pick one. If none is found (different subnet, broadcast blocked), enter the IP address
of the pump's Wi-Fi module. The passcode the pump needs for login is fetched from the pump itself -
no app account, no cloud.

If the pump refuses to hand out its passcode ("not in binding mode"), power-cycle it or press its
Wi-Fi button briefly and try again within a few minutes. Once stored, the passcode stays valid.

Give each pump a fixed IP address in your router; the integration reconnects by address.

## Entities

- **Pump** (switch) - on/off.
- **Wave mode** (select) - classic, sine, random wave, constant.
- **Wave form** (select) - pulse or tide (used by the classic mode).
- **Flow**, **Frequency** (number, %) - the current manual setting.
- **Feed pause** (switch) with **Feed pause duration** (number, 1-60 min).
- **Timer** (switch) - run the pump's own 48-slot schedule instead of the manual setting; attributes
  show the slots. **Timer mode now** (sensor) shows what the schedule is doing right now.
- **Linkage** (select) - independent, master or slave (the pumps' own 2.4 GHz coupling).
- **Fault** (binary sensor) - any of: motor overcurrent, overvoltage, overtemperature, undervoltage,
  locked rotor, no load (dry run), module link. The seven flags are also available as individual
  diagnostic binary sensors (disabled by default).

State values are keys (`random`, `tide`, `independent` ...); the UI translates them (English, German).

## Known quirks

- The pump pushes a status only when something changes, so the entities are "available" as long as
  the heartbeat is answered, even if no value changed for hours.
- Anyone on your LAN can control the pump this way - the module hands out its passcode to whoever
  asks (manufacturer behaviour, same as the app). Keep IoT devices in a trusted network.
- Flow and frequency below the pump's own minimum are clamped by the pump.
- The schedule's "flow" byte holds the feed pause length in minutes when the slot mode is *feed*.
- Firmware 04020B25 ignores a write that changes *only* the flow; the integration therefore always
  sends the current frequency along with it (the app does the same from its screen).
- Changes are pushed by the pump as command `0x0093` carrying its device id (not `0x0091` as in other
  Gizwits devices); the integration decodes both, so changes made in the app show up immediately.

## Development

- `custom_components/aquamedic_local/protocol.py` - framing, the two datapoint schemas, decode/encode;
  no Home Assistant imports. `python3 tests/test_protocol.py` runs the tests with status blocks
  captured from real pumps.
- `client.py` - one TCP session per pump (passcode -> login -> read; heartbeat every 4 s, reconnect).
- Datapoint schemas of other Gizwits products can be fetched without an account:
  `https://euapi.gizwits.com/app/datapoint?product_key=<key>`. Adding a product means adding its
  attribute table to `protocol.py` and a decode mapping.

Protocol references: [jebao-doser](https://github.com/m0s4ik/jebao-doser) (Gizwits LAN client for
Jebao dosers), [node-ph803w](https://github.com/Apollon77/node-ph803w/blob/master/PROTOCOL.md)
(packet-level description), [ha-aquamedic-component](https://github.com/Elwinmage/ha-aquamedic-component)
(cloud-based alternative with the same datapoints).

## Support the project

If this saves you a cloud dependency, you can [buy me a coffee](https://buymeacoffee.com/patrical).

## License

MIT - see `LICENSE`. This repository contains only original code; the datapoint layout is the
product's public schema, re-expressed as a table.
