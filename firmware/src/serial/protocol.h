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
#include <ArduinoJson.h>

// Agent states (for STATUS messages)
enum class AgentState {
    THINKING,      // Agent is generating/executing
    WAITING,       // Waiting for user input/approval
    DONE,          // Agent finished its turn
    ERROR,         // Exception occurred
    DEAD,          // Agent dead (watchdog timeout)
    STUCK          // Agent stuck (generating forever)
};

// Thinking activities (sub-states of THINKING)
enum class ThinkingActivity {
    REASONING,     // Model is reasoning, no active tool
    TOOL_EXEC,     // Tool execution in progress (bash, write, edit, etc.)
    READING,       // Reading/searching data (read, grep, fetch, etc.)
    STREAMING      // Model response being streamed
};

// Message types
enum class MessageType {
    INVALID,
    APPROVAL_REQUEST,  // PC -> M5Stack: Show approval request
    APPROVAL_RESPONSE, // M5Stack -> PC: User response
    PING,              // Keepalive
    ACK,               // Acknowledgement
    CREDIT_INFO,       // PC -> M5Stack: Credit usage percentage (0-100)
    STATUS            // PC -> M5Stack: Agent state + heartbeat
};

// Watchdog constants (milliseconds)
#define WATCHDOG_DEAD_MS   12000   // No message received -> DEAD
#define WATCHDOG_STUCK_MS  90000   // No seq progression in THINKING -> STUCK
#define HEARTBEAT_MS       3000    // PC heartbeat interval

// Approval response values
enum class ApprovalResponse {
    NONE,
    APPROVED,
    REJECTED,
    CANCELLED
};

// Max JSON document sizes
#define JSON_RX_SIZE 512   // Max size for incoming JSON
#define JSON_TX_SIZE 256   // Max size for outgoing JSON

class SerialProtocol {
public:
    SerialProtocol();
    
    // Initialize serial communication
    void begin(uint32_t baud = 115200);
    
    // Check if data is available and parse it
    // Returns true if a valid message was received
    bool receive();
    
    // Send an approval response
    void sendResponse(uint32_t requestId, ApprovalResponse response);
    
    // Send a simple ACK
    void sendAck(uint32_t requestId);
    
    // Get last received message type
    MessageType getMessageType() const;
    
    // Get approval request data
    const char* getRequestTitle() const;
    const char* getRequestBody() const;
    uint32_t getRequestId() const;
    
    // Check if new message available
    bool hasMessage() const;
    
    // Get credit info
    uint8_t getCreditPercent() const;
    bool hasCreditInfo() const;
    
    // Get status info
    AgentState getAgentState() const;
    const char* getStatusDetail() const;
    uint32_t getStatusSeq() const;
    bool hasStatus() const;

    // Get thinking activity info
    ThinkingActivity getThinkingActivity() const;
    bool hasThinkingActivity() const;
    
private:
    StaticJsonDocument<JSON_RX_SIZE> rxDoc;
    StaticJsonDocument<JSON_TX_SIZE> txDoc;
    
    MessageType lastMessageType;
    uint32_t lastRequestId;
    char lastTitle[128];
    char lastBody[256];
    uint8_t lastCreditPercent;
    bool creditInfoValid;
    bool newMessageAvailable;
    
    // Status fields
    AgentState lastAgentState;
    char lastStatusDetail[41];  // max 40 chars + null terminator
    uint32_t lastStatusSeq;
    bool statusValid;

    // Thinking activity field
    ThinkingActivity lastThinkingActivity;
    bool thinkingActivityValid;
};
