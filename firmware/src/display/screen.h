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
#include <cstdint>

class ApprovalScreen {
public:
    ApprovalScreen();
    
    // Draw-only, non bloquant : dessine la requête (une fois par requestId)
    // et retourne true quand le timeout est écoulé (l'appelant envoie alors
    // CANCELLED). Les boutons sont gérés dans loop(), jamais ici.
    bool showRequest(const char* title, const char* body,
                     uint32_t requestId, uint32_t timeoutMs = 30000);

    // Get the request ID that was responded to
    uint32_t getResponseRequestId() const;

private:
    uint32_t responseRequestId;
    uint32_t displayStartTime;
    
    void drawRequestFrame(const char* title, const char* body);
};
