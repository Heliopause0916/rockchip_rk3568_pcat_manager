# PCat Manager

PCat Manager is a power management and device control system for photonicat 1/2 devices.

## Building Dependencies

libglib2.0-dev libusb-1.0-0-dev libjson-c-dev libgpiod-dev

## Control Channel Modes (Kernel CTL / Serial)

PCat Manager supports two transport modes for talking to the PMU:

- **serial** mode: for the legacy kernel (v1, UART not taken over) the manager controls the PMU directly over a serial device (default `/dev/ttyS4` at 115200 baud). Temperature read back requires the `[PowerManager] TemperatureOffset` offset (default `-40`) to be applied.
- **ctl** (kernel) mode: for the new kernel (`photonicat-pm` serdev driver owns `uart4`) the manager communicates with the kernel misc character device `/dev/pcat-pm-ctl`. Telemetry and power on/off handling are done by the kernel side, and temperature is reported as real Celsius (converted by the kernel) — no offset is applied on the ctl path.

### Selecting a mode

The mode is chosen in this priority order:

1. CLI flag `--mode=kernel` / `--mode=serial` (highest priority; if both `--mode` and `--ctl` are given, `--mode` wins)
2. CLI flag `--ctl` (taken into account when `--mode` is not given)
3. Environment variable: `PCAT_MANAGER_MODE=kernel` / `PCAT_MANAGER_MODE=serial`
4. Auto-detection of `/dev/pcat-pm-ctl`

```
pcat-manager --mode=kernel
PCAT_MANAGER_MODE=serial pcat-manager
```

### Recommended setup

For the new kernel, the **ctl** mode is recommended (configure `ControlDevice=/dev/pcat-pm-ctl`). Once `uart4` is owned exclusively by the kernel serdev driver, user space must not open `/dev/ttyS4` anymore — opening it will fail, and concurrent UART writes corrupt frames and can trigger a watchdog reset. Heartbeat and watchdog frames are handled by the kernel in ctl mode and must not be sent by user space.

Battery/power state is read from the real `power_supply` subsystem (`/sys/class/power_supply/battery`, `/sys/class/power_supply/charger`), with user-space state summary published under `/run/state/namespaces/Battery/{ChargePercentage,Voltage,OnBattery}`.

### TemperatureOffset

`TemperatureOffset` applies **only** on the serial path (default `-40`). On the ctl path the kernel converts the temperature itself (`temp1_input`), so the value there is already real Celsius and the offset is not applied.

## Configuration

Configuration is read from `/etc/pcat-manager.conf` (see `conf/pcat-manager.conf.sample`).

### `[Hardware]` — modem GPIO lines

| Key | Purpose |
| --- | --- |
| `GPIOModemPowerChip` / `GPIOModemPowerLine` / `GPIOModemPowerActiveLow` | Modem power GPIO (chip, line, active-low polarity) |
| `GPIOModemRFKillChip` / `GPIOModemRFKillLine` / `GPIOModemRFKillActiveLow` | Modem RF-kill GPIO |
| `GPIOModemResetChip` / `GPIOModemResetLine` / `GPIOModemResetActiveLow` | Modem reset GPIO |

### `[PowerManager]` — power management behaviour

| Key | Purpose |
| --- | --- |
| `ControlDevice` | Kernel ctl channel device (default `/dev/pcat-pm-ctl`) |
| `SerialDevice` | Serial device for serial mode (example/recommended value `/dev/ttyS4`, from `conf/pcat-manager.conf.sample`; no code hard fallback — if unset, serial mode cannot open a device) |
| `SerialBaud` | Serial baud rate (default `115200`) |
| `TemperatureOffset` | Temperature offset applied on the serial path only (default `-40`) |
| `AutoShutdownVoltageGeneral` | Auto-shutdown voltage threshold, general use |
| `AutoShutdownVoltageLTE` | Auto-shutdown voltage threshold, LTE mode |
| `AutoShutdownVoltage5G` | Auto-shutdown voltage threshold, 5G mode (default `3600`) |
| `LEDHighVoltage` | High-voltage LED threshold |
| `LEDMediumVoltage` | Medium-voltage LED threshold |
| `LEDLowVoltage` | Low-voltage LED threshold |
| `LEDWorkLowVoltage` | Low-voltage working LED threshold |
| `StartupVoltage` | Startup voltage threshold |
| `ChargerLimitVoltage` | Charger limit voltage |
| `ChargerFastVoltage` | Fast-charge voltage |
| `BatteryFullThreshold` | Battery full threshold (default `4100`) |
| `BatteryDischargeTableNormal` | Battery discharge table, normal profile (voltage;semicolon-separated) |
| `BatteryDischargeTable5G` | Battery discharge table, 5G profile |
| `BatteryChargeTable` | Battery charge table |

## Interfaces

### Socket API Documentation

**Socket Type:** Unix Domain Socket  
**Socket Path:** `/tmp/pcat-manager.sock`  
**Protocol:** JSON over stream socket  
**Message Format:** JSON string terminated with null byte (`\0`)

#### Connection Example:
```python
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/tmp/pcat-manager.sock')
s.send(b"{'command':'pmu-status'}\0")
response = s.recv(1024)
```

#### Available Commands:

**Power Management Commands:**
- `pmu-status` - Get PMU status (battery voltage, charger voltage, battery percentage, board temperature)
- `pmu-fw-version-get` - Get PMU firmware version

**Power Scheduling Commands:**
- `schedule-power-event-set` - Set power schedule events
- `schedule-power-event-get` - Get power schedule events

**Charger Commands:**
- `charger-on-auto-start-set` - Configure charger auto-start
- `charger-on-auto-start-get` - Get charger auto-start configuration

**Modem Commands:**
- `modem-status-get` - Get modem status (mode, SIM state, signal strength, ISP info)
- `modem-rfkill-mode-set` - Set RF kill mode
- `modem-network-setup` - Configure modem network settings
- `modem-network-get` - Get modem network configuration

**System Commands:**
- `network-route-mode-get` - Get current network routing mode

#### Response Format:
All responses are JSON objects containing:
- `command` - Echo of the command sent
- `code` - Response code (0 = success)
- Additional fields specific to each command

#### Example:

**pmu-status**
Request:
```json
{
  "command": "pmu-status"
}
```

Response:
```json
{
  "command": "pmu-status",
  "code": 0,
  "battery-voltage": 4200,
  "charger-voltage": 5000,
  "on-battery": 0,
  "charge-percentage": 85,
  "board-temperature": 35
}
```

**modem-status-get**
Request:
```json
{
  "command": "modem-status-get"
}
```

Response:
```json
{
  "command": "modem-status-get", 
  "code": 0,
  "mode": "LTE",
  "sim-state": 2,
  "rfkill-state": 0,
  "signal-strength": -75,
  "isp-name": "Carrier",
  "isp-plmn": "12345"
}
```


