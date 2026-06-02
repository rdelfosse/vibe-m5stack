#include "welcome.h" 
#include "mistral_logo.h" 
  
#ifndef FW_VERSION  
#define FW_VERSION "dev"  
#endif 
  
QRCode qrcode; 
  
void renderQRCode(int16_t x, int16_t y, uint8_t scale) { 
    uint8_t qrTemp[1000];  
    qrcode.clear();  
    qrcode.addData(WELCOME_QR_URL);  
    qrcode.create();  
    int qrWidth = qrcode.getWidth(); 
    for (int qrY = 0; qrY < qrWidth; qrY++) { 
        for (int qrX = 0; qrX < qrWidth; qrX++) { 
            if (qrcode.getModule(qrX, qrY)) { 
                M5.Lcd.fillRect(x + qrX * scale, y + qrY * scale, scale, scale, WHITE); 
            }  
        }  
    }  
} 
  
void drawWelcomeScreen() { 
    M5.Lcd.fillScreen(BLACK);  
    constexpr uint8_t LOGO_SCALE = 1;  
    for (int i = 0; i < MISTRAL_LOGO_RECT_COUNT; i++) { 
        const MistralLogoRect& r = mistral_logo_rects[i]; 
        M5.Lcd.fillRect(20 + r.x * LOGO_SCALE, 40 + r.y * LOGO_SCALE,  
                        r.w * LOGO_SCALE, r.h * LOGO_SCALE, r.color);  
    } 
    M5.Lcd.setTextSize(2);  
    M5.Lcd.setTextColor(WHITE, BLACK);  
    M5.Lcd.setCursor(20, 10);  
    M5.Lcd.print("vibe-m5stack"); 
    M5.Lcd.setTextSize(1);  
    M5.Lcd.setCursor(20, 180);  
    M5.Lcd.print("Romain Delfosse"); 
    M5.Lcd.setCursor(20, 195);  
    M5.Lcd.print("romaindelfosse.fr");  
    M5.Lcd.setCursor(20, 210);  
    M5.Lcd.printf("v%\\s", FW_VERSION); 
    M5.Lcd.setCursor(20, 130);  
    M5.Lcd.print("Approbation physique");  
    M5.Lcd.setCursor(20, 145);  
    M5.Lcd.print("pour agents IA"); 
    M5.Lcd.setCursor(20, 225);  
    M5.Lcd.print("En attente de session - lance vibe-m5stack");  
    renderQRCode(180, 60, 2);  
} 
