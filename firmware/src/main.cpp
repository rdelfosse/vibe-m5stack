#include <M5Stack.h>
#include "display/anim.h"
#include "display/screen.h"
#include "inputs/buttons.h"
#include "inputs/leds.h"
#include "serial/protocol.h"
#include "serial/serial_io.h"

// Application states
enum class AppState {
    IDLE,           // Waiting for approval request (show dancing logo)
    SHOWING_REQUEST  // Displaying an approval request
};

AppState currentState = AppState::IDLE;
ChatAnimator animator;
ApprovalScreen approvalScreen;
ButtonManager buttonManager;
SerialProtocol serialProtocol;

uint32_t lastPingTime = 0;

void setup() {
    M5.begin();

    // DIAG canary 1: red = M5.begin() returned, LCD reachable
    M5.Lcd.fillScreen(RED);
    ::delay(800);

    animator.begin();

    // DIAG canary 2: green if sprite OK, blue if alloc failed
    uint16_t bg = animator.isReady() ? GREEN : BLUE;
    M5.Lcd.fillScreen(bg);
    M5.Lcd.setTextColor(WHITE, bg);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setCursor(8, 20);
    M5.Lcd.printf("sprite: %s", animator.isReady() ? "OK" : "FAIL");
    M5.Lcd.setCursor(8, 60);
    M5.Lcd.printf("need : %u B", animator.bytesNeeded());
    M5.Lcd.setCursor(8, 90);
    M5.Lcd.printf("psram: %u B", animator.psramFree());
    M5.Lcd.setCursor(8, 120);
    M5.Lcd.printf("dram : %u B", animator.dramFree());
    ::delay(5000);

    M5.Lcd.fillScreen(BLACK);

    led::begin();

    animator.reset();
    serialProtocol.begin(115200);
    buttonManager.update();
}

void loop() {
    M5.update();
    buttonManager.update();
    
    // Handle serial communication
    if (serialProtocol.receive()) {
        if (serialProtocol.getMessageType() == MessageType::APPROVAL_REQUEST) {
            currentState = AppState::SHOWING_REQUEST;
        }
        else if (serialProtocol.getMessageType() == MessageType::CREDIT_INFO) {
            // Update credit info for the animator
            if (currentState == AppState::IDLE) {
                animator.setCreditInfo(
                    serialProtocol.getCreditPercent(),
                    serialProtocol.hasCreditInfo()
                );
            }
        }
    }
    
    // State machine
    switch (currentState) {
        case AppState::IDLE: {
            animator.update();
            animator.draw();
            
            // Send periodic ping
            if (::millis() - lastPingTime > 5000) {
                bridgeSerial.println("{\"type\":\"ping\"}");
                lastPingTime = ::millis();
            }
            break;
        }
        
        case AppState::SHOWING_REQUEST: {
            const char* title = serialProtocol.getRequestTitle();
            const char* body = serialProtocol.getRequestBody();
            uint32_t requestId = serialProtocol.getRequestId();
            
            // Show request and wait for response
            bool gotResponse = approvalScreen.showRequest(title, body, requestId);
            
            // Send response back
            if (gotResponse) {
                int response = approvalScreen.getResponse();
                ApprovalResponse approxResponse;
                
                switch (response) {
                    case 1: approxResponse = ApprovalResponse::APPROVED; break;
                    case 2: approxResponse = ApprovalResponse::REJECTED; break;
                    default: approxResponse = ApprovalResponse::CANCELLED; break;
                }
                
                serialProtocol.sendResponse(requestId, approxResponse);
                buttonManager.vibrate(100, 50); // Short vibration feedback
            } else {
                // Timeout - send cancelled
                serialProtocol.sendResponse(requestId, ApprovalResponse::CANCELLED);
            }
            
            led::off();
            currentState = AppState::IDLE;
            animator.reset();
            // Re-set credit info when returning to idle
            if (serialProtocol.hasCreditInfo()) {
                animator.setCreditInfo(
                    serialProtocol.getCreditPercent(),
                    true
                );
            }
            break;
        }
    }
    
    ::delay(16); // ~60fps
}

