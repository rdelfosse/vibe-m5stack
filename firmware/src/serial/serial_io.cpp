#include "serial_io.h"
#include <Arduino.h>

#if USE_BT_SERIAL
BluetoothSerial bridgeSerial;

void bridgeSerialBegin(uint32_t /*baud*/) {
    bridgeSerial.begin("M5Stack-Vibe");
}
#else
void bridgeSerialBegin(uint32_t baud) {
    Serial.begin(baud);
    while (!Serial) {
        delay(10);
    }
}
#endif
