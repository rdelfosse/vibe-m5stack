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
#include "protocol.h"
#include "serial_io.h"
#include <Arduino.h>

SerialProtocol::SerialProtocol()
    : lastMessageType(MessageType::INVALID), 
      lastRequestId(0),
      lastCreditPercent(0),
      creditInfoValid(false),
      newMessageAvailable(false),
      lastAgentState(AgentState::DONE),
      lastStatusSeq(0),
      statusValid(false),
      lastThinkingActivity(ThinkingActivity::REASONING),
      thinkingActivityValid(false) {
    lastTitle[0] = '\0';
    lastBody[0] = '\0';
    lastStatusDetail[0] = '\0';
}

void SerialProtocol::begin(uint32_t baud) {
    bridgeSerialBegin(baud);
}

bool SerialProtocol::receive() {
    if (!bridgeSerial.available()) {
        return false;
    }

    // Read JSON from serial
    DeserializationError error = deserializeJson(rxDoc, bridgeSerial);

    if (error) {
        // Clear buffer on error
        while (bridgeSerial.available()) bridgeSerial.read();
        return false;
    }
    
    // Parse message type
    const char* typeStr = rxDoc["type"];
    if (!typeStr) return false;
    
    if (strcmp(typeStr, "approval") == 0) {
        lastMessageType = MessageType::APPROVAL_REQUEST;
        lastRequestId = rxDoc["id"] | 0;
        
        strlcpy(lastTitle, rxDoc["title"] | "", sizeof(lastTitle));
        strlcpy(lastBody, rxDoc["body"] | "", sizeof(lastBody));
        
        newMessageAvailable = true;
        return true;
    }
    else if (strcmp(typeStr, "ping") == 0) {
        lastMessageType = MessageType::PING;
        return true;
    }
    else if (strcmp(typeStr, "ack") == 0) {
        lastMessageType = MessageType::ACK;
        return true;
    }
    else if (strcmp(typeStr, "credit_info") == 0) {
        lastMessageType = MessageType::CREDIT_INFO;
        lastCreditPercent = rxDoc["percent"] | 0;
        // Clamp to 0-100
        if (lastCreditPercent > 100) lastCreditPercent = 100;
        creditInfoValid = true;
        return true;
    }
    else if (strcmp(typeStr, "status") == 0) {
        lastMessageType = MessageType::STATUS;
        
        // Parse state
        const char* stateStr = rxDoc["state"];
        if (strcmp(stateStr, "thinking") == 0) {
            lastAgentState = AgentState::THINKING;
        } else if (strcmp(stateStr, "waiting") == 0) {
            lastAgentState = AgentState::WAITING;
        } else if (strcmp(stateStr, "done") == 0) {
            lastAgentState = AgentState::DONE;
        } else if (strcmp(stateStr, "error") == 0) {
            lastAgentState = AgentState::ERROR;
        } else if (strcmp(stateStr, "dead") == 0) {
            lastAgentState = AgentState::DEAD;
        } else if (strcmp(stateStr, "stuck") == 0) {
            lastAgentState = AgentState::STUCK;
        } else {
            lastAgentState = AgentState::DONE;
        }
        
        // Parse detail (optional, max 40 chars)
        const char* detail = rxDoc["detail"] | "";
        strlcpy(lastStatusDetail, detail, sizeof(lastStatusDetail));
        
        // Parse seq
        lastStatusSeq = rxDoc["seq"] | 0;
        statusValid = true;
        
        // Parse activity (only valid when state == thinking)
        const char* activityStr = rxDoc["activity"] | "";
        if (lastAgentState == AgentState::THINKING) {
            if (strcmp(activityStr, "reasoning") == 0) {
                lastThinkingActivity = ThinkingActivity::REASONING;
            } else if (strcmp(activityStr, "tool_exec") == 0) {
                lastThinkingActivity = ThinkingActivity::TOOL_EXEC;
            } else if (strcmp(activityStr, "reading") == 0) {
                lastThinkingActivity = ThinkingActivity::READING;
            } else if (strcmp(activityStr, "streaming") == 0) {
                lastThinkingActivity = ThinkingActivity::STREAMING;
            } else {
                // Default to REASONING if unknown or missing
                lastThinkingActivity = ThinkingActivity::REASONING;
            }
            thinkingActivityValid = true;
        } else {
            thinkingActivityValid = false;
        }
        
        return true;
    }
    
    return false;
}

void SerialProtocol::sendResponse(uint32_t requestId, ApprovalResponse response) {
    txDoc.clear();
    txDoc["type"] = "response";
    txDoc["id"] = requestId;
    
    switch (response) {
        case ApprovalResponse::APPROVED:
            txDoc["approved"] = true;
            break;
        case ApprovalResponse::REJECTED:
            txDoc["approved"] = false;
            break;
        case ApprovalResponse::CANCELLED:
        default:
            txDoc["approved"] = false;
            txDoc["cancelled"] = true;
            break;
    }
    
    serializeJson(txDoc, bridgeSerial);
    bridgeSerial.println();
}

void SerialProtocol::sendAck(uint32_t requestId) {
    txDoc.clear();
    txDoc["type"] = "ack";
    txDoc["id"] = requestId;
    serializeJson(txDoc, bridgeSerial);
    bridgeSerial.println();
}

MessageType SerialProtocol::getMessageType() const {
    return lastMessageType;
}

const char* SerialProtocol::getRequestTitle() const {
    return lastTitle;
}

const char* SerialProtocol::getRequestBody() const {
    return lastBody;
}

uint32_t SerialProtocol::getRequestId() const {
    return lastRequestId;
}

bool SerialProtocol::hasMessage() const {
    return newMessageAvailable;
}

uint8_t SerialProtocol::getCreditPercent() const {
    return lastCreditPercent;
}

bool SerialProtocol::hasCreditInfo() const {
    return creditInfoValid;
}

AgentState SerialProtocol::getAgentState() const {
    return lastAgentState;
}

const char* SerialProtocol::getStatusDetail() const {
    return lastStatusDetail;
}

uint32_t SerialProtocol::getStatusSeq() const {
    return lastStatusSeq;
}

bool SerialProtocol::hasStatus() const {
    return statusValid;
}

ThinkingActivity SerialProtocol::getThinkingActivity() const {
    return lastThinkingActivity;
}

bool SerialProtocol::hasThinkingActivity() const {
    return thinkingActivityValid;
}
