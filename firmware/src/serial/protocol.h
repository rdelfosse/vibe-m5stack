#pragma once
#include <cstdint>
#include <ArduinoJson.h>

// Message types
enum class MessageType {
    INVALID,
    APPROVAL_REQUEST,  // PC -> M5Stack: Show approval request
    APPROVAL_RESPONSE, // M5Stack -> PC: User response
    PING,              // Keepalive
    ACK,               // Acknowledgement
    CREDIT_INFO        // PC -> M5Stack: Credit usage percentage (0-100)
};

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
};
