// Vibe M5Stack - M5Stack integration for Mistral Vibe CLI
// Copyright 2026 Romain Delfosse
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
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
    SHOWING_REQUEST, // Displaying an approval request
    THINKING,       // Agent is generating/executing
    WAITING_INPUT,  // Waiting for user input/approval
    DONE,           // Agent finished its turn
    ERROR_STATE,   // Exception occurred
    DEAD,           // Agent dead (watchdog timeout)
    STUCK           // Agent stuck (generating forever)
};

AppState currentState = AppState::IDLE;
AppState prevState = AppState::IDLE;
ChatAnimator animator;
ApprovalScreen approvalScreen;
ButtonManager buttonManager;
SerialProtocol serialProtocol;

uint32_t lastPingTime = 0;

// Watchdog tracking
uint32_t lastRxMs = 0;           // Last message received time
uint32_t lastSeqChangeMs = 0;    // Last seq increment time
uint32_t lastStatusSeq = 0;     // Last received seq value
bool statusInitialized = false; // Has first status been received?

// LED state tracking for transitions
bool ledFlourishDone = true;    // Has the DONE flourish been shown?

// Thinking activity tracking
ThinkingActivity currentThinkingActivity = ThinkingActivity::REASONING;

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

// Watchdog alarm function
void triggerWatchdogAlarm(AppState alarmState) {
    static bool alarmTriggered = false;
    
    if (alarmTriggered) return;
    alarmTriggered = true;
    
    // Vibrate once to alert user
    buttonManager.vibrate(200, 100);
}

// Reset watchdog alarm
void resetWatchdogAlarm() {
    // Any key press will reset the alarm state
    // This is handled in the state machine
}

// Bandeau de statut en bas d'écran : suit l'état de l'agent (et l'activité de
// thinking). Couleur assortie à l'animation LED. Doit être (re)dessiné PAR-DESSUS
// le sprite du chat, sinon celui-ci le recouvre.
void drawStatusBanner() {
    const char* text = "";
    uint16_t color = WHITE;
    switch (currentState) {
        case AppState::IDLE:  text = "Ready"; color = GREEN; break;
        case AppState::DONE:  text = "Ready"; color = GREEN; break;
        case AppState::WAITING_INPUT: text = "Waiting for you..."; color = 0xFDE0; break;
        case AppState::THINKING:
            color = CYAN;
            switch (currentThinkingActivity) {
                case ThinkingActivity::REASONING: text = "Thinking..."; break;
                case ThinkingActivity::TOOL_EXEC: text = "Running...";  break;
                case ThinkingActivity::READING:   text = "Reading...";  break;
                case ThinkingActivity::STREAMING: text = "Writing...";  break;
            }
            break;
        case AppState::ERROR_STATE: {
            const char* d = serialProtocol.getStatusDetail();
            text = (d && d[0]) ? d : "Error";
            color = RED;
            break;
        }
        default: return;  // DEAD / STUCK / SHOWING_REQUEST : gérés en plein écran
    }
    M5.Lcd.fillRect(0, 220, 320, 20, BLACK);
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(color, BLACK);
    M5.Lcd.setCursor(10, 221);
    M5.Lcd.print(text);
}

// Dessine le chat (throttlé ~8 fps) puis le bandeau par-dessus. `forced` redessine
// immédiatement (utilisé à l'entrée d'un état pour un bandeau réactif).
void drawCatBanner(uint32_t now, bool forced) {
    static uint32_t lastCat = 0;
    if (forced || now - lastCat > 120) {
        lastCat = now;
        animator.update();
        animator.draw();
        drawStatusBanner();
    }
}

void loop() {
    M5.update();
    buttonManager.update();
    
    // Track last message time
    static uint32_t loopCount = 0;
    uint32_t now = ::millis();
    
    // Handle serial communication
    if (serialProtocol.receive()) {
        lastRxMs = now;
        MessageType msgType = serialProtocol.getMessageType();
        
        if (msgType == MessageType::APPROVAL_REQUEST) {
            // Approval has priority over status states
            prevState = currentState;
            currentState = AppState::SHOWING_REQUEST;
            ledFlourishDone = true; // Reset flourish flag
        }
        else if (msgType == MessageType::CREDIT_INFO) {
            // Update credit info for the animator in IDLE or THINKING states
            if (currentState == AppState::IDLE || currentState == AppState::THINKING) {
                animator.setCreditInfo(
                    serialProtocol.getCreditPercent(),
                    serialProtocol.hasCreditInfo()
                );
            }
        }
        else if (msgType == MessageType::STATUS) {
            AgentState agentState = serialProtocol.getAgentState();
            uint32_t newSeq = serialProtocol.getStatusSeq();
            
            // Update watchdog tracking
            if (!statusInitialized || newSeq != lastStatusSeq) {
                lastSeqChangeMs = now;
                lastStatusSeq = newSeq;
                statusInitialized = true;
            }
            
            // Update thinking activity when available
            if (serialProtocol.hasThinkingActivity()) {
                currentThinkingActivity = serialProtocol.getThinkingActivity();
            }
            
            // Map agent state to app state (unless approval is active)
            if (currentState != AppState::SHOWING_REQUEST) {
                prevState = currentState;
                
                switch (agentState) {
                    case AgentState::THINKING:
                        currentState = AppState::THINKING;
                        break;
                    case AgentState::WAITING:
                        currentState = AppState::WAITING_INPUT;
                        break;
                    case AgentState::DONE:
                        currentState = AppState::DONE;
                        ledFlourishDone = false; // Trigger flourish
                        break;
                    case AgentState::ERROR:
                        currentState = AppState::ERROR_STATE;
                        break;
                    case AgentState::DEAD:
                        currentState = AppState::DEAD;
                        break;
                    case AgentState::STUCK:
                        currentState = AppState::STUCK;
                        break;
                }
            }
        }
    }
    
    // Watchdog checks - only when not showing approval
    if (currentState != AppState::SHOWING_REQUEST) {
        // DEAD check: no message received for WATCHDOG_DEAD_MS
        if (statusInitialized && now - lastRxMs > WATCHDOG_DEAD_MS) {
            if (currentState != AppState::DEAD && currentState != AppState::STUCK) {
                prevState = currentState;
                currentState = AppState::DEAD;
                triggerWatchdogAlarm(AppState::DEAD);
            }
        }
        
        // STUCK check: in THINKING state with no seq progression for WATCHDOG_STUCK_MS
        if (currentState == AppState::THINKING && 
            statusInitialized && 
            now - lastSeqChangeMs > WATCHDOG_STUCK_MS) {
            prevState = currentState;
            currentState = AppState::STUCK;
            triggerWatchdogAlarm(AppState::STUCK);
        }
    }
    
    // Redraw the LCD only on state transitions. Per-frame full-screen redraws
    // (fillScreen / banners / sprite push over SPI) were saturating the bus and
    // making the LED animations stutter. The LEDs are refreshed every frame;
    // the screen only when the state actually changes.
    static AppState renderedState = AppState::SHOWING_REQUEST;
    bool justEntered = (currentState != renderedState);
    renderedState = currentState;

    // State machine
    switch (currentState) {
        case AppState::IDLE: {
            drawCatBanner(now, justEntered);
            led::idle();

            // Send periodic ping
            if (::millis() - lastPingTime > 5000) {
                bridgeSerial.println("{\"type\":\"ping\"}");
                lastPingTime = ::millis();
            }
            break;
        }
        
        case AppState::THINKING: {
            // Chat throttlé + bandeau (le bandeau suit l'activité de thinking).
            drawCatBanner(now, justEntered);
            led::setAgentState(AgentState::THINKING, false, currentThinkingActivity);
            break;
        }
        
        case AppState::WAITING_INPUT: {
            drawCatBanner(now, justEntered);
            led::setAgentState(AgentState::WAITING);
            break;
        }
        
        case AppState::DONE: {
            drawCatBanner(now, justEntered);
            // LED flourish une seule fois, puis vert fixe.
            if (!ledFlourishDone) {
                led::setAgentState(AgentState::DONE, true);  // flourish
                ledFlourishDone = true;
            } else {
                led::setAgentState(AgentState::DONE, false); // steady
            }
            break;
        }
        
        case AppState::ERROR_STATE: {
            led::setAgentState(AgentState::ERROR);   // scanner rouge, chaque frame
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                drawStatusBanner();                  // "detail" ou "Error" en rouge
            }
            break;
        }

        case AppState::DEAD: {
            led::setAgentState(AgentState::DEAD);    // scanner rouge, chaque frame
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                M5.Lcd.setTextFont(2);
                M5.Lcd.setTextSize(2);
                M5.Lcd.setTextColor(RED, BLACK);
                M5.Lcd.setCursor(10, 100);
                M5.Lcd.print("Agent DEAD!");
                M5.Lcd.setTextSize(1);
                M5.Lcd.setCursor(10, 140);
                M5.Lcd.print("PC disconnected?");
            }
            break;
        }

        case AppState::STUCK: {
            led::setAgentState(AgentState::STUCK);   // scanner rouge, chaque frame
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                M5.Lcd.setTextFont(2);
                M5.Lcd.setTextSize(2);
                M5.Lcd.setTextColor(RED, BLACK);
                M5.Lcd.setCursor(10, 100);
                M5.Lcd.print("Agent STUCK!");
                M5.Lcd.setTextSize(1);
                M5.Lcd.setCursor(10, 140);
                M5.Lcd.print("Generating forever?");
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
            // Return to previous state
            currentState = prevState;
            animator.reset();
            // Re-set credit info
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

