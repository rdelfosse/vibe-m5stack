#pragma once

// Transport switch: USB serial vs Bluetooth Classic (SPP).
//   USE_BT_SERIAL = 0 : standard USB serial (CDC over CP2104). Required for
//                       `pio device monitor` and PlatformIO upload-with-monitor.
//   USE_BT_SERIAL = 1 : Bluetooth Classic Serial Port Profile. M5Stack appears
//                       as "M5Stack-Vibe" in Windows pairing, exposes a COM
//                       virtuel that bridge.py reads exactly like USB serial.
//                       Bypasses the host USB stack entirely (cures the
//                       POWERON_RESET-on-port-open seen on some laptops).
#ifndef USE_BT_SERIAL
#define USE_BT_SERIAL 1
#endif

#if USE_BT_SERIAL
  #include <BluetoothSerial.h>
  extern BluetoothSerial bridgeSerial;
#else
  #include <Arduino.h>
  #define bridgeSerial Serial
#endif

void bridgeSerialBegin(uint32_t baud);
