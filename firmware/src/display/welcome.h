#pragma once
#include <M5Stack.h>
#include "qrcode.h"

#define WELCOME_QR_URL "https://www.romaindelfosse.fr/blog/m5stack-vibe-bouton-physique-agents-ia/"

void drawWelcomeScreen();
void renderQRCode(int16_t x, int16_t y, uint8_t scale);
