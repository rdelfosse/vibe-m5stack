#pragma once
#include <cstdint>
#include <ArduinoJson.h>

enum class AgentState { THINKING, WAITING, DONE, ERROR, DEAD, STUCK };

enum class ThinkingActivity { REASONING, TOOL_EXEC, READING, STREAMING };

enum class VoiceAction { START, STOP };

enum class VoiceMode { PROMPT, APPROVE, REJECT };

enum class VoiceAckState { TRANSCRIBING, DONE };

enum class MessageType {
    INVALID, APPROVAL_REQUEST, APPROVAL_RESPONSE, PING, ACK,
    CREDIT_INFO, STATUS, VOICE, VOICE_ACK
};

#define WATCHDOG_DEAD_MS   12000
#define WATCHDOG_STUCK_MS  90000
#define HEARTBEAT_MS       3000

enum class ApprovalResponse { NONE, APPROVED, REJECTED, CANCELLED };

#define JSON_RX_SIZE 512
#define JSON_TX_SIZE 256

class SerialProtocol {
public:
    SerialProtocol();
    void begin(uint32_t baud = 115200);
    bool receive();
    void sendResponse(uint32_t requestId, ApprovalResponse response);
    void sendAck(uint32_t requestId);
    // micDevice : true = l'audio sera capturé sur le device et uploadé
    // (messages "audio"/"audio_end"), false = le PC enregistre avec son micro.
    void sendVoiceEvent(VoiceAction action, VoiceMode mode, uint32_t sessionId,
                        uint32_t requestId, bool micDevice = false);
    void sendVoiceAck(VoiceAckState state, const char* text = nullptr);
    MessageType getMessageType() const;
    const char* getRequestTitle() const;
    const char* getRequestBody() const;
    uint32_t getRequestId() const;
    bool hasMessage() const;
    uint8_t getCreditPercent() const;
    bool hasCreditInfo() const;
    AgentState getAgentState() const;
    const char* getStatusDetail() const;
    uint32_t getStatusSeq() const;
    bool hasStatus() const;
    ThinkingActivity getThinkingActivity() const;
    bool hasThinkingActivity() const;
    VoiceAckState getVoiceAckState() const;
    const char* getVoiceAckText() const;
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
    AgentState lastAgentState;
    char lastStatusDetail[41];
    uint32_t lastStatusSeq;
    bool statusValid;
    ThinkingActivity lastThinkingActivity;
    bool thinkingActivityValid;
    VoiceAckState lastVoiceAckState;
    char lastVoiceAckText[61];
    bool voiceAckValid;
};
