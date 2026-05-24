#pragma once
#include <cstdint>

class ApprovalScreen {
public:
    ApprovalScreen();
    
    // Display an approval request
    // Returns true if button was pressed (response available)
    // Timeout: return to idle after timeoutMs milliseconds
    bool showRequest(const char* title, const char* body, 
                     uint32_t requestId, uint32_t timeoutMs = 30000);
    
    // Get the user's response
    // Returns: 0 = timeout/cancel, 1 = approved, 2 = rejected
    int getResponse() const;
    
    // Get the request ID that was responded to
    uint32_t getResponseRequestId() const;
    
private:
    int response;        // -1 = none, 0 = cancel, 1 = approve, 2 = reject
    uint32_t responseRequestId;
    uint32_t displayStartTime;
    
    void drawRequestFrame(const char* title, const char* body);
};
