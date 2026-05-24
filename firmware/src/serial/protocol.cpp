#include "protocol.h"
#include <Arduino.h>

SerialProtocol::SerialProtocol() 
    : lastMessageType(MessageType::INVALID), 
      lastRequestId(0),
      lastCreditPercent(0),
      creditInfoValid(false),
      newMessageAvailable(false) {
    lastTitle[0] = '\0';
    lastBody[0] = '\0';
}

void SerialProtocol::begin(uint32_t baud) {
    Serial.begin(baud);
    while (!Serial) {
        ::delay(10);
    }
}

bool SerialProtocol::receive() {
    if (!Serial.available()) {
        return false;
    }
    
    // Read JSON from serial
    DeserializationError error = deserializeJson(rxDoc, Serial);
    
    if (error) {
        // Clear buffer on error
        while (Serial.available()) Serial.read();
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
    
    serializeJson(txDoc, Serial);
    Serial.println();
}

void SerialProtocol::sendAck(uint32_t requestId) {
    txDoc.clear();
    txDoc["type"] = "ack";
    txDoc["id"] = requestId;
    serializeJson(txDoc, Serial);
    Serial.println();
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
