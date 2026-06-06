// Vibe M5Stack
// Copyright 2026

#include "welcome.h"
// NE PAS inclure gif_frames.h ici : ce header DÉFINIT ~3 MB de données de frames
// et est réservé à gif_animator.cpp (l'inclure dans un 2e TU duplique le payload).
// gif_metadata.h expose GIF_WIDTH (constexpr) + all_frames (extern), sans les pixels.
#include "gif_metadata.h"

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

#include "qrcode.h"

void renderQRCode(int16_t x, int16_t y, uint8_t scale) {
    const uint8_t version = 5;
    QRCode qrcode;
    uint8_t qrcodeData[qrcode_getBufferSize(version)];
    qrcode_initText(&qrcode, qrcodeData, version, ECC_LOW, WELCOME_QR_URL);

    const uint8_t quiet = 2;
    int side = (qrcode.size + 2 * quiet) * scale;
    M5.Lcd.fillRect(x, y, side, side, WHITE);
    for (uint8_t qy = 0; qy < qrcode.size; qy++) {
        for (uint8_t qx = 0; qx < qrcode.size; qx++) {
            if (qrcode_getModule(&qrcode, qx, qy)) {
                M5.Lcd.fillRect(x + (quiet + qx) * scale,
                                y + (quiet + qy) * scale, scale, scale, BLACK);
            }
        }
    }
}

void drawWelcomeScreen() {
    M5.Lcd.fillScreen(BLACK);

    const uint16_t* src = all_frames[0];   // 1re frame, via le symbole externe (pas de copie)
    const int srcW = GIF_WIDTH;
    const int dstW = 120;
    const int dstH = 120;
    const int dstX = 0;
    const int dstY = (240 - dstH) / 2;

    for (int y = 0; y < dstH; y++) {
        for (int x = 0; x < dstW; x++) {
            uint16_t color = src[(y * 2) * srcW + (x * 2)];
            M5.Lcd.drawPixel(dstX + x, dstY + y, color);
        }
    }

    M5.Lcd.setTextColor(WHITE, BLACK);

    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setCursor(130, 10);
    M5.Lcd.print("vibe-m5stack");

    M5.Lcd.setTextSize(1);
    M5.Lcd.setCursor(130, 40);
    M5.Lcd.print("Romain Delfosse");
    M5.Lcd.setCursor(130, 55);
    M5.Lcd.print("romaindelfosse.fr");
    M5.Lcd.setCursor(130, 75);
    M5.Lcd.printf("v%s", FW_VERSION);
    M5.Lcd.setCursor(130, 95);
    M5.Lcd.print("AI agent button");
    M5.Lcd.setCursor(130, 110);
    M5.Lcd.print("lance vibe-m5stack");

    renderQRCode(200, 130, 2);
}
