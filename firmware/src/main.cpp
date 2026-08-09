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
#include "config/config.h"
#include "config/config_menu.h"
#include "display/anim.h"
#include "display/chaton_fat_draw.h"
#include "display/screen.h"
#include "display/welcome.h"
#include "inputs/buttons.h"
#include "inputs/leds.h"
#include "serial/protocol.h"
#include "serial/serial_io.h"

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

#define LONGPRESS_MS 500

// Application states
enum class AppState {
    WELCOME,
    IDLE,
    SHOWING_REQUEST,
    THINKING,
    WAITING_INPUT,
    DONE,
    ERROR_STATE,
    DEAD,
    STUCK,
    CONFIG_MENU,
    LISTENING,
    TRANSCRIBING
};

AppState currentState = AppState::WELCOME;
AppState prevState = AppState::WELCOME;
ChatAnimator animator;
ApprovalScreen approvalScreen;
ButtonManager buttonManager;
SerialProtocol serialProtocol;
ConfigManager configManager;
ConfigMenu configMenu(configManager);

uint32_t lastPingTime = 0;

// Watchdog tracking
uint32_t lastRxMs = 0;
uint32_t lastSeqChangeMs = 0;
uint32_t lastStatusSeq = 0;
bool statusInitialized = false;

// LED state tracking for transitions
bool ledFlourishDone = true;

// Configuration-based state
volatile bool forceRedraw = false;

// Thinking activity tracking
ThinkingActivity currentThinkingActivity = ThinkingActivity::REASONING;

// Voice state tracking
static uint32_t voiceSessionId = 0;
static VoiceMode voiceMode = VoiceMode::PROMPT;
static uint32_t voiceRequestId = 0;

// Button A long-press tracking for voice
static bool buttonATracking = false;
static uint32_t buttonAHoldStart = 0;
static bool buttonALongFired = false;

// Button B long-press tracking for voice
static bool buttonBTracking = false;
static uint32_t buttonBHoldStart = 0;
static bool buttonBLongFired = false;

// Transcribing timeout tracking
static uint32_t transcribingStartTime = 0;
static const uint32_t TRANSCRIBING_TIMEOUT_MS = 20000;

void setup() {
    M5.begin();

    // DIAG canary 1: red = M5.begin() returned, LCD reachable
    M5.Lcd.fillScreen(RED);
    ::delay(800);

    animator.begin();
    
    // Initialize configuration manager
    configManager.begin();
    configMenu.begin();

    // DIAG canary 2: green if sprite OK, blue if alloc failed
    uint16_t bg = animator.isReady() ? GREEN : BLUE;
    M5.Lcd.fillScreen(bg);
    M5.Lcd.setTextColor(WHITE, bg);
    M5.Lcd.setTextSize(2);
    M5.Lcd.setCursor(8, 20);
    M5.Lcd.printf("v%s", FW_VERSION);
    M5.Lcd.setCursor(8, 50);
    M5.Lcd.printf("sprite: %s", animator.isReady() ? "OK" : "FAIL");
    M5.Lcd.setCursor(8, 80);
    M5.Lcd.printf("need : %u B", animator.bytesNeeded());
    M5.Lcd.setCursor(8, 110);
    M5.Lcd.printf("psram: %u B", animator.psramFree());
    M5.Lcd.setCursor(8, 140);
    M5.Lcd.printf("dram : %u B", animator.dramFree());
    ::delay(5000);

    M5.Lcd.fillScreen(BLACK);

    led::begin();
    // Apply saved LED brightness
    led::setBrightness(configManager.get().ledBrightness);

    animator.reset();
    serialProtocol.begin(115200);
    buttonManager.update();
}

// Watchdog alarm function
void triggerWatchdogAlarm(AppState alarmState) {
    static bool alarmTriggered = false;
    
    if (alarmTriggered) return;
    alarmTriggered = true;
    
    // Vibrate once to alert user (respect quiet mode)
    if (!configManager.get().quietMode) {
        buttonManager.vibrate(200, 100);
    }
}

// Bandeau de statut en bas d'ecran
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
        default: return;
    }
    M5.Lcd.fillRect(0, 220, 320, 20, BLACK);
    M5.Lcd.setTextFont(2);
    M5.Lcd.setTextSize(1);
    M5.Lcd.setTextColor(color, BLACK);
    M5.Lcd.setCursor(10, 221);
    M5.Lcd.print(text);
}

// Dessine le chat (throttled) puis le bandeau par-dessus
void drawCatBanner(uint32_t now, bool forced) {
    static uint32_t lastCat = 0;
    static bool wasChatonFat = false;
    if (configManager.get().model == DeviceModel::CHATON_FAT) {
        if (forced) {
            animator.reset();
            drawChatonFat(56, 34, 4, BLACK, WHITE);
            M5.Lcd.fillRect(120, 0, 200, 50, BLACK);
            M5.Lcd.setTextFont(2);
            M5.Lcd.setTextSize(2);
            M5.Lcd.setTextColor(0xFC00, BLACK);
            M5.Lcd.setCursor(130, 10);
            M5.Lcd.print("Chaton Fat");
            M5.Lcd.setTextSize(1);
            M5.Lcd.setTextColor(WHITE, BLACK);
            M5.Lcd.setCursor(130, 35);
            M5.Lcd.print("le nouveau modele Mistral");
            drawStatusBanner();
            lastCat = now;
        } else if (now - lastCat > 120) {
            lastCat = now;
            drawStatusBanner();
        }
        wasChatonFat = true;
    } else {
        if (forced || now - lastCat > 120) {
            if (wasChatonFat) {
                animator.reset();
                wasChatonFat = false;
            }
            lastCat = now;
            animator.update();
            animator.draw();
            drawStatusBanner();
        }
    }
}

void loop() {
    M5.update();
    buttonManager.update();
    
    uint32_t now = ::millis();

    // Config menu trigger: long press on C button (1000ms) from IDLE/DONE
    static uint32_t buttonCHoldStart = 0;
    static bool buttonCTracking = false;
    static bool buttonCWaitRelease = false;

    if (currentState == AppState::IDLE || currentState == AppState::DONE) {
        if (buttonManager.isHeld(AppButton::C)) {
            if (!buttonCWaitRelease) {
                if (!buttonCTracking) {
                    buttonCTracking = true;
                    buttonCHoldStart = now;
                } else if (now - buttonCHoldStart >= 1000) {
                    prevState = currentState;
                    currentState = AppState::CONFIG_MENU;
                    configMenu.open();
                    forceRedraw = true;
                    if (!configManager.get().quietMode) {
                        buttonManager.vibrate(100, 50);
                    }
                    buttonCTracking = false;
                    buttonCWaitRelease = true;
                }
            }
        } else {
            buttonCTracking = false;
            buttonCWaitRelease = false;
        }
    } else {
        buttonCTracking = false;
        buttonCWaitRelease = buttonManager.isHeld(AppButton::C);
    }

    // Voice block: root level, after menu block
    bool inVoiceEligibleState = (currentState == AppState::IDLE ||
                                  currentState == AppState::WELCOME ||
                                  currentState == AppState::SHOWING_REQUEST ||
                                  currentState == AppState::LISTENING);

    if (inVoiceEligibleState) {
        // Button A tracking for long-press
        bool aEligible = (currentState == AppState::IDLE ||
                         currentState == AppState::WELCOME ||
                         currentState == AppState::SHOWING_REQUEST);
        // Une fois en LISTENING (long-press A parti), le bouton porteur doit
        // rester suivi jusqu'au relâchement — sinon la branche « release »
        // se déclenche à la frame suivante avec le bouton encore enfoncé et
        // la session vocale dure 16 ms.
        bool aHolding = (currentState == AppState::LISTENING && buttonALongFired);

        if ((aEligible || aHolding) && buttonManager.isHeld(AppButton::A)) {
            if (!buttonATracking) {
                buttonATracking = true;
                buttonAHoldStart = now;
                buttonALongFired = false;
            } else if (!buttonALongFired && now - buttonAHoldStart >= LONGPRESS_MS) {
                buttonALongFired = true;
                if (currentState == AppState::IDLE || currentState == AppState::WELCOME) {
                    voiceMode = VoiceMode::PROMPT;
                    voiceRequestId = 0;
                    prevState = currentState;
                    currentState = AppState::LISTENING;
                    forceRedraw = true;
                } else if (currentState == AppState::SHOWING_REQUEST) {
                    voiceMode = VoiceMode::APPROVE;
                    voiceRequestId = serialProtocol.getRequestId();
                    prevState = currentState;
                    currentState = AppState::LISTENING;
                    forceRedraw = true;
                }
                serialProtocol.sendVoiceEvent(VoiceAction::START, voiceMode, voiceSessionId, voiceRequestId);
                voiceSessionId++;
                buttonManager.wasPressed(AppButton::A);
            }
        } else if (buttonATracking) {
            buttonATracking = false;
            if (buttonALongFired) {
                buttonALongFired = false;
                serialProtocol.sendVoiceEvent(VoiceAction::STOP, voiceMode, voiceSessionId - 1, voiceRequestId);
                if (voiceMode == VoiceMode::APPROVE) {
                    serialProtocol.sendResponse(voiceRequestId, ApprovalResponse::APPROVED);
                    if (!configManager.get().quietMode) {
                        buttonManager.vibrate(100, 50);
                    }
                }
                currentState = prevState;
                forceRedraw = true;
            } else {
                if (currentState == AppState::SHOWING_REQUEST) {
                    uint32_t requestId = serialProtocol.getRequestId();
                    serialProtocol.sendResponse(requestId, ApprovalResponse::APPROVED);
                    if (!configManager.get().quietMode) {
                        buttonManager.vibrate(100, 50);
                    }
                    led::off();
                    currentState = prevState;
                    animator.reset();
                    if (serialProtocol.hasCreditInfo()) {
                        animator.setCreditInfo(serialProtocol.getCreditPercent(), true);
                    }
                    forceRedraw = true;
                }
            }
        }

        // Button B tracking for long-press
        bool bEligible = (currentState == AppState::SHOWING_REQUEST);
        // Même principe que aHolding : suivre B jusqu'au relâchement en LISTENING.
        bool bHolding = (currentState == AppState::LISTENING && buttonBLongFired);

        if ((bEligible || bHolding) && buttonManager.isHeld(AppButton::B)) {
            if (!buttonBTracking) {
                buttonBTracking = true;
                buttonBHoldStart = now;
                buttonBLongFired = false;
            } else if (!buttonBLongFired && now - buttonBHoldStart >= LONGPRESS_MS) {
                buttonBLongFired = true;
                voiceMode = VoiceMode::REJECT;
                voiceRequestId = serialProtocol.getRequestId();
                prevState = currentState;
                currentState = AppState::LISTENING;
                forceRedraw = true;
                serialProtocol.sendVoiceEvent(VoiceAction::START, voiceMode, voiceSessionId, voiceRequestId);
                voiceSessionId++;
                buttonManager.wasPressed(AppButton::B);
            }
        } else if (buttonBTracking) {
            buttonBTracking = false;
            if (buttonBLongFired) {
                buttonBLongFired = false;
                serialProtocol.sendVoiceEvent(VoiceAction::STOP, voiceMode, voiceSessionId - 1, voiceRequestId);
                currentState = AppState::TRANSCRIBING;
                transcribingStartTime = now;
                forceRedraw = true;
            } else {
                if (currentState == AppState::SHOWING_REQUEST) {
                    uint32_t requestId = serialProtocol.getRequestId();
                    serialProtocol.sendResponse(requestId, ApprovalResponse::REJECTED);
                    if (!configManager.get().quietMode) {
                        buttonManager.vibrate(100, 50);
                    }
                    led::off();
                    currentState = prevState;
                    animator.reset();
                    if (serialProtocol.hasCreditInfo()) {
                        animator.setCreditInfo(serialProtocol.getCreditPercent(), true);
                    }
                    forceRedraw = true;
                }
            }
        }

        // Button C short press in SHOWING_REQUEST = cancel
        if (currentState == AppState::SHOWING_REQUEST && buttonManager.wasPressed(AppButton::C)) {
            uint32_t requestId = serialProtocol.getRequestId();
            serialProtocol.sendResponse(requestId, ApprovalResponse::CANCELLED);
            if (!configManager.get().quietMode) {
                buttonManager.vibrate(100, 50);
            }
            led::off();
            currentState = prevState;
            animator.reset();
            if (serialProtocol.hasCreditInfo()) {
                animator.setCreditInfo(serialProtocol.getCreditPercent(), true);
            }
            forceRedraw = true;
        }
    } else {
        // Not in voice-eligible state: reset tracking
        buttonATracking = false;
        buttonALongFired = false;
        buttonBTracking = false;
        buttonBLongFired = false;
    }

    // Handle serial communication
    if (serialProtocol.receive()) {
        lastRxMs = now;
        MessageType msgType = serialProtocol.getMessageType();

        if (msgType == MessageType::VOICE_ACK) {
            VoiceAckState ackState = serialProtocol.getVoiceAckState();
            if (currentState == AppState::TRANSCRIBING && ackState == VoiceAckState::DONE) {
                currentState = prevState;
                forceRedraw = true;
            }
        }
        else if (msgType == MessageType::APPROVAL_REQUEST) {
            if (currentState == AppState::CONFIG_MENU) {
                configMenu.close();
            } else {
                prevState = currentState;
            }
            currentState = AppState::SHOWING_REQUEST;
            ledFlourishDone = true;
        }
        else if (msgType == MessageType::CREDIT_INFO) {
            if (currentState == AppState::IDLE || currentState == AppState::THINKING) {
                animator.setCreditInfo(serialProtocol.getCreditPercent(), serialProtocol.hasCreditInfo());
            }
        }
        else if (msgType == MessageType::STATUS) {
            AgentState agentState = serialProtocol.getAgentState();
            uint32_t newSeq = serialProtocol.getStatusSeq();

            if (!statusInitialized || newSeq != lastStatusSeq) {
                lastSeqChangeMs = now;
                lastStatusSeq = newSeq;
                statusInitialized = true;
            }

            if (serialProtocol.hasThinkingActivity()) {
                currentThinkingActivity = serialProtocol.getThinkingActivity();
            }

            if (currentState != AppState::SHOWING_REQUEST &&
                currentState != AppState::CONFIG_MENU &&
                currentState != AppState::LISTENING &&
                currentState != AppState::TRANSCRIBING) {
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
                        ledFlourishDone = false;
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

    // Watchdog checks
    if (currentState != AppState::SHOWING_REQUEST &&
        currentState != AppState::LISTENING &&
        currentState != AppState::TRANSCRIBING) {
        if (statusInitialized && now - lastRxMs > WATCHDOG_DEAD_MS) {
            if (currentState != AppState::DEAD && currentState != AppState::STUCK) {
                if (currentState == AppState::CONFIG_MENU) {
                    configMenu.close();
                } else {
                    prevState = currentState;
                }
                currentState = AppState::DEAD;
                triggerWatchdogAlarm(AppState::DEAD);
            }
        }

        if (currentState == AppState::THINKING &&
            statusInitialized &&
            now - lastSeqChangeMs > WATCHDOG_STUCK_MS) {
            prevState = currentState;
            currentState = AppState::STUCK;
            triggerWatchdogAlarm(AppState::STUCK);
        }
    }

    // Redraw the LCD only on state transitions
    static AppState renderedState = AppState::SHOWING_REQUEST;
    bool justEntered = (currentState != renderedState) || forceRedraw;
    if (forceRedraw) forceRedraw = false;
    AppState prevRendered = renderedState;
    renderedState = currentState;

    auto isFullScreen = [](AppState s) {
        return s == AppState::WELCOME || s == AppState::DEAD || s == AppState::STUCK
            || s == AppState::ERROR_STATE || s == AppState::SHOWING_REQUEST
            || s == AppState::CONFIG_MENU || s == AppState::LISTENING
            || s == AppState::TRANSCRIBING;
    };
    if (justEntered && isFullScreen(prevRendered) && !isFullScreen(currentState)) {
        animator.reset();
    }

    // State machine
    switch (currentState) {
        case AppState::WELCOME: {
            if (justEntered) {
                drawWelcomeScreen();
            }
            led::welcome();
            if (::millis() - lastPingTime > 5000) {
                bridgeSerial.printf("{\"type\":\"ping\",\"fw\":\"%s\"}\n", FW_VERSION);
                lastPingTime = ::millis();
            }
            break;
        }

        case AppState::IDLE: {
            drawCatBanner(now, justEntered);
            led::idle();
            if (::millis() - lastPingTime > 5000) {
                bridgeSerial.printf("{\"type\":\"ping\",\"fw\":\"%s\"}\n", FW_VERSION);
                lastPingTime = ::millis();
            }
            break;
        }

        case AppState::THINKING: {
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
            if (!ledFlourishDone) {
                led::setAgentState(AgentState::DONE, true);
                ledFlourishDone = true;
            } else {
                led::setAgentState(AgentState::DONE, false);
            }
            break;
        }

        case AppState::ERROR_STATE: {
            led::setAgentState(AgentState::ERROR);
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                drawStatusBanner();
            }
            break;
        }

        case AppState::DEAD: {
            led::setAgentState(AgentState::DEAD);
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
            led::setAgentState(AgentState::STUCK);
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

        case AppState::CONFIG_MENU: {
            static bool menuWaitCRelease = false;
            static uint32_t menuCHoldStart = 0;
            static bool menuCTracking = false;

            if (justEntered) {
                buttonManager.wasPressed(AppButton::A);
                buttonManager.wasPressed(AppButton::B);
                buttonManager.wasPressed(AppButton::C);
                menuWaitCRelease = buttonManager.isHeld(AppButton::C);
                menuCTracking = false;
                configMenu.draw(true);
            } else {
                configMenu.draw();
            }

            if (menuWaitCRelease) {
                buttonManager.wasPressed(AppButton::A);
                buttonManager.wasPressed(AppButton::B);
                buttonManager.wasPressed(AppButton::C);
                if (!buttonManager.isHeld(AppButton::C)) {
                    menuWaitCRelease = false;
                }
            } else {
                bool cLongExit = false;
                if (buttonManager.isHeld(AppButton::C)) {
                    if (!menuCTracking) {
                        menuCTracking = true;
                        menuCHoldStart = now;
                    } else if (now - menuCHoldStart >= 1000) {
                        cLongExit = true;
                        menuCTracking = false;
                        menuWaitCRelease = true;
                    }
                } else {
                    menuCTracking = false;
                }

                bool btnAPressed = buttonManager.wasPressed(AppButton::A);
                bool btnBPressed = buttonManager.wasPressed(AppButton::B);
                bool btnCPressed = buttonManager.wasPressed(AppButton::C);

                if (!configMenu.update(btnAPressed, btnBPressed, btnCPressed, cLongExit)) {
                    currentState = prevState;
                    forceRedraw = true;
                }
            }

            static uint8_t appliedBrightness = 0;
            uint8_t brightness = configManager.get().ledBrightness;
            if (brightness != appliedBrightness) {
                led::setBrightness(brightness);
                appliedBrightness = brightness;
            }

            led::idle();
            break;
        }

        case AppState::SHOWING_REQUEST: {
            const char* title = serialProtocol.getRequestTitle();
            const char* body = serialProtocol.getRequestBody();
            uint32_t requestId = serialProtocol.getRequestId();

            bool timeout = approvalScreen.showRequest(title, body, requestId, 50000);

            if (timeout) {
                serialProtocol.sendResponse(requestId, ApprovalResponse::CANCELLED);
                led::off();
                currentState = prevState;
                animator.reset();
                if (serialProtocol.hasCreditInfo()) {
                    animator.setCreditInfo(serialProtocol.getCreditPercent(), true);
                }
                forceRedraw = true;
            }

            led::updateApprovalAnimation();
            break;
        }

        case AppState::LISTENING: {
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                M5.Lcd.setTextFont(2);
                M5.Lcd.setTextSize(2);
                M5.Lcd.setTextColor(CYAN, BLACK);
                M5.Lcd.setCursor(10, 80);
                M5.Lcd.print("Listening...");
                M5.Lcd.setTextSize(1);
                M5.Lcd.setCursor(10, 120);
                M5.Lcd.print("Release to send");
            }

            led::listening();
            break;
        }

        case AppState::TRANSCRIBING: {
            if (justEntered) {
                M5.Lcd.fillScreen(BLACK);
                M5.Lcd.setTextFont(2);
                M5.Lcd.setTextSize(2);
                M5.Lcd.setTextColor(CYAN, BLACK);
                M5.Lcd.setCursor(10, 100);
                M5.Lcd.print("Transcribing...");
            }

            led::listening();

            if (now - transcribingStartTime > TRANSCRIBING_TIMEOUT_MS) {
                currentState = prevState;
                forceRedraw = true;
            }
            break;
        }
    }
    
    ::delay(16);
}
