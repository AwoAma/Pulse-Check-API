# Critical Infrastructure Monitoring - Dead Man's Switch API

This is a lightweight, stateful backend service built using Python and Flask to monitor remote devices (like solar farms and unmanned weather stations). It acts as a Dead Man's Switch, triggering alerts automatically if a device fails to send a heartbeat signal within its specified timeout window.

## Architectural Flow
- Registration: Devices register with a unique ID, a specific timeout duration, and an alert email.
- Stateful Countdown: The system spins up an independent background timer for each device.
- Heartbeat: Every incoming heartbeat resets the countdown timer back to its initial value.
- Failure State: If a timer hits zero without a heartbeat, the device status flips to down and a critical JSON alert is logged to the terminal.
- Pause State: Support personnel can pause a monitor during scheduled maintenance to prevent false alarms.

---

## API Documentation

### 1. Register a Monitor
- Endpoint: POST /monitors
- Request Body:
`json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com"
}
## System Architecture

```mermaid
graph TD
    Admin([Device Admin]) -->|POST /monitors| API[Pulse Check API]
    API -->|Starts Countdown Timer| Storage[(In-Memory State)]
    
    Device([Critical Device]) -->|POST /monitors/:id/heartbeat| API
    API -->|Resets Timer to Max| Storage
    
    Storage -->|Timer Expirations / Hits 0| Alert[Log JSON Alert to Console & Set Status to Down]
    '''