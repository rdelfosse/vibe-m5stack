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
#pragma once

#include "../serial/protocol.h"
#include <FastLED.h>

// Public LED API. Implementation is fully isolated in leds.cpp so that
// FastLED's headers (which use `RED`/`BLACK` as enum identifiers) never
// collide with M5Stack/TFT_eSPI's `#define RED 0xF800` etc.

namespace led {

void begin();
void off();

// Call repeatedly while waiting for the user's button press.
// Throttles itself; safe to call every loop tick.
//  - side ring (10 LEDs, GPIO 15) : Mistral palette chase
//  - port B + port C matrices (5x5, GPIO 26 + GPIO 17) : Mistral "M" blink
void updateApprovalAnimation();

// Set LED state based on agent state
// flourish: for DONE state, if true show 1.5s green flourish, else steady green
// activity: sub-activity for THINKING state (default = REASONING)
void setAgentState(AgentState state, bool flourish = false, ThinkingActivity activity = ThinkingActivity::REASONING);

// Idle animation (no agent activity yet): gentle green breathing.
// Self-throttling; safe to call every loop tick.
void idle();

}  // namespace led
