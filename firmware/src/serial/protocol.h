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
    CREDIT_INFO, STATUS, VOICE, VOICE_ACK,
    TTS_AUDIO, TTS_END, TTS_STOP
};

#define WATCHDOG_DEAD_MS   12000
#define WATCHDOG_STUCK_MS  90000
#define HEARTBEAT_MS       3000

enum class ApprovalResponse { NONE, APPROVED, REJECTED, CANCELLED };

// 4 Ko : doit contenir un chunk tts_audio (~1,4 Ko de base64) + les clés.
#define JSON_RX_SIZE 4096
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
    // TTS getters
    uint32_t getTtsSeq() const;
    uint32_t getTtsTotal() const;
    const uint8_t* getTtsData() const;
    size_t getTtsDataLen() const;
    bool hasTtsAudio() const;
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
    // TTS streaming state
    uint32_t lastTtsSeq;
    uint32_t lastTtsTotal;
    char lastTtsData[1025];  // base64 decoded data buffer (~1 Ko raw µ-law)
    size_t lastTtsDataLen;
    bool ttsAudioValid;
};

// Télémétrie de diagnostic TTS (définie dans protocol.cpp).
extern uint32_t g_ttsChunksOk;
extern uint32_t g_ttsBytesOk;
extern uint32_t g_ttsDecodeErrors;
extern uint32_t g_rxParseErrors;
extern uint32_t g_rxOversized;
