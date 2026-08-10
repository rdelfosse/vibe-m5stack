#include "protocol.h"
#include "serial_io.h"
#include <Arduino.h>
#include <mbedtls/base64.h>

SerialProtocol::SerialProtocol()
    : lastMessageType(MessageType::INVALID), lastRequestId(0),
      lastCreditPercent(0), creditInfoValid(false), newMessageAvailable(false),
      lastAgentState(AgentState::DONE), lastStatusSeq(0), statusValid(false),
      lastThinkingActivity(ThinkingActivity::REASONING), thinkingActivityValid(false),
      lastVoiceAckState(VoiceAckState::TRANSCRIBING), voiceAckValid(false),
      lastTtsSeq(0), lastTtsTotal(0), lastTtsDataLen(0), ttsAudioValid(false) {
    lastTitle[0] = '\0'; lastBody[0] = '\0';
    lastStatusDetail[0] = '\0'; lastVoiceAckText[0] = '\0';
    lastTtsData[0] = '\0';
}

void SerialProtocol::begin(uint32_t baud) { bridgeSerialBegin(baud); }

bool SerialProtocol::receive() {
    // ⚠️ La queue RX interne de BluetoothSerial ne fait que 512 OCTETS et le
    // callback SPP jette les octets quand elle est pleine. Une ligne
    // tts_audio (~700 o) ne survit que si on draine la queue PLUS VITE
    // qu'elle ne se remplit : on vide TOUT à chaque appel dans notre propre
    // accumulateur, puis on extrait une ligne par appel.
    static char acc[6144]; static size_t accLen = 0;
    static char lineBuf[2048];

    while (bridgeSerial.available() && accLen < sizeof(acc)) {
        acc[accLen++] = (char)bridgeSerial.read();
    }

    // Extraire la première ligne complète de l'accumulateur.
    size_t nl = 0;
    bool haveLine = false;
    for (; nl < accLen; nl++) {
        if (acc[nl] == '\n' || acc[nl] == '\r') { haveLine = true; break; }
    }
    if (!haveLine) {
        if (accLen >= sizeof(acc)) accLen = 0;  // ligne monstrueuse : purge
        return false;
    }

    size_t lineLen = (nl < sizeof(lineBuf) - 1) ? nl : 0;  // trop longue : jetée
    if (lineLen > 0) memcpy(lineBuf, acc, lineLen);
    lineBuf[lineLen] = '\0';
    // Consommer la ligne + le(s) délimiteur(s) qui suivent.
    size_t consume = nl + 1;
    while (consume < accLen && (acc[consume] == '\n' || acc[consume] == '\r')) consume++;
    memmove(acc, acc + consume, accLen - consume);
    accLen -= consume;
    if (lineLen == 0) return false;
    DeserializationError error = deserializeJson(rxDoc, lineBuf);
    if (error) return false;
    const char* typeStr = rxDoc["type"];
    if (!typeStr) return false;
    if (strcmp(typeStr, "approval") == 0) {
        lastMessageType = MessageType::APPROVAL_REQUEST;
        lastRequestId = rxDoc["id"] | 0;
        strlcpy(lastTitle, rxDoc["title"] | "", sizeof(lastTitle));
        strlcpy(lastBody, rxDoc["body"] | "", sizeof(lastBody));
        newMessageAvailable = true; return true;
    } else if (strcmp(typeStr, "ping") == 0) { lastMessageType = MessageType::PING; return true;
    } else if (strcmp(typeStr, "ack") == 0) { lastMessageType = MessageType::ACK; return true;
    } else if (strcmp(typeStr, "credit_info") == 0) {
        lastMessageType = MessageType::CREDIT_INFO;
        lastCreditPercent = rxDoc["percent"] | 0;
        if (lastCreditPercent > 100) lastCreditPercent = 100;
        creditInfoValid = true; return true;
    } else if (strcmp(typeStr, "status") == 0) {
        lastMessageType = MessageType::STATUS;
        const char* stateStr = rxDoc["state"];
        if (strcmp(stateStr, "thinking") == 0) lastAgentState = AgentState::THINKING;
        else if (strcmp(stateStr, "waiting") == 0) lastAgentState = AgentState::WAITING;
        else if (strcmp(stateStr, "done") == 0) lastAgentState = AgentState::DONE;
        else if (strcmp(stateStr, "error") == 0) lastAgentState = AgentState::ERROR;
        else if (strcmp(stateStr, "dead") == 0) lastAgentState = AgentState::DEAD;
        else if (strcmp(stateStr, "stuck") == 0) lastAgentState = AgentState::STUCK;
        else lastAgentState = AgentState::DONE;
        const char* detail = rxDoc["detail"] | "";
        strlcpy(lastStatusDetail, detail, sizeof(lastStatusDetail));
        lastStatusSeq = rxDoc["seq"] | 0; statusValid = true;
        const char* activityStr = rxDoc["activity"] | "";
        if (lastAgentState == AgentState::THINKING) {
            if (strcmp(activityStr, "reasoning") == 0) lastThinkingActivity = ThinkingActivity::REASONING;
            else if (strcmp(activityStr, "tool_exec") == 0) lastThinkingActivity = ThinkingActivity::TOOL_EXEC;
            else if (strcmp(activityStr, "reading") == 0) lastThinkingActivity = ThinkingActivity::READING;
            else if (strcmp(activityStr, "streaming") == 0) lastThinkingActivity = ThinkingActivity::STREAMING;
            else lastThinkingActivity = ThinkingActivity::REASONING;
            thinkingActivityValid = true;
        } else thinkingActivityValid = false;
        return true;
    } else if (strcmp(typeStr, "voice_ack") == 0) {
        lastMessageType = MessageType::VOICE_ACK;
        const char* stateStr = rxDoc["state"] | "";
        if (strcmp(stateStr, "transcribing") == 0) lastVoiceAckState = VoiceAckState::TRANSCRIBING;
        else if (strcmp(stateStr, "done") == 0) lastVoiceAckState = VoiceAckState::DONE;
        else lastVoiceAckState = VoiceAckState::TRANSCRIBING;
        const char* text = rxDoc["text"] | "";
        strlcpy(lastVoiceAckText, text, sizeof(lastVoiceAckText));
        voiceAckValid = true; return true;
    }
    // TTS streaming messages
    else if (strcmp(typeStr, "tts_audio") == 0) {
        lastMessageType = MessageType::TTS_AUDIO;
        lastTtsSeq = rxDoc["seq"] | 0;
        const char* dataStr = rxDoc["data"] | "";
        // Base64 decode the data
        size_t decodedLen = 0;
        int result = mbedtls_base64_decode((unsigned char*)lastTtsData, sizeof(lastTtsData) - 1,
                                         &decodedLen, (const unsigned char*)dataStr, strlen(dataStr));
        if (result == 0) {
            lastTtsDataLen = decodedLen;
            ttsAudioValid = true;
        } else {
            lastTtsDataLen = 0;
            ttsAudioValid = false;
        }
        return true;
    }
    else if (strcmp(typeStr, "tts_end") == 0) {
        lastMessageType = MessageType::TTS_END;
        lastTtsTotal = rxDoc["total"] | 0;
        return true;
    }
    else if (strcmp(typeStr, "tts_stop") == 0) {
        lastMessageType = MessageType::TTS_STOP;
        return true;
    }
    return false;
}

void SerialProtocol::sendResponse(uint32_t requestId, ApprovalResponse response) {
    txDoc.clear(); txDoc["type"] = "response"; txDoc["id"] = requestId;
    switch (response) {
        case ApprovalResponse::APPROVED: txDoc["approved"] = true; break;
        case ApprovalResponse::REJECTED: txDoc["approved"] = false; break;
        case ApprovalResponse::CANCELLED: default: txDoc["approved"] = false; txDoc["cancelled"] = true; break;
    }
    serializeJson(txDoc, bridgeSerial); bridgeSerial.println();
}

void SerialProtocol::sendAck(uint32_t requestId) {
    txDoc.clear(); txDoc["type"] = "ack"; txDoc["id"] = requestId;
    serializeJson(txDoc, bridgeSerial); bridgeSerial.println();
}

void SerialProtocol::sendVoiceEvent(VoiceAction action, VoiceMode mode, uint32_t sessionId,
                                    uint32_t requestId, bool micDevice) {
    txDoc.clear(); txDoc["type"] = "voice";
    const char* actionStr = (action == VoiceAction::START) ? "start" : "stop";
    txDoc["action"] = actionStr;
    const char* modeStr;
    switch (mode) {
        case VoiceMode::PROMPT: modeStr = "prompt"; break;
        case VoiceMode::APPROVE: modeStr = "approve"; break;
        case VoiceMode::REJECT: modeStr = "reject"; break;
        default: modeStr = "prompt"; break;
    }
    txDoc["mode"] = modeStr; txDoc["id"] = requestId; txDoc["session"] = sessionId;
    txDoc["mic"] = micDevice ? "device" : "pc";
    serializeJson(txDoc, bridgeSerial); bridgeSerial.println();
}

void SerialProtocol::sendVoiceAck(VoiceAckState state, const char* text) {
    txDoc.clear(); txDoc["type"] = "voice_ack";
    const char* stateStr = (state == VoiceAckState::TRANSCRIBING) ? "transcribing" : "done";
    txDoc["state"] = stateStr;
    if (text && text[0]) {
        char truncated[61]; strlcpy(truncated, text, sizeof(truncated));
        txDoc["text"] = truncated;
    } else if (text) { txDoc["text"] = ""; }
    serializeJson(txDoc, bridgeSerial); bridgeSerial.println();
}

MessageType SerialProtocol::getMessageType() const { return lastMessageType; }
const char* SerialProtocol::getRequestTitle() const { return lastTitle; }
const char* SerialProtocol::getRequestBody() const { return lastBody; }
uint32_t SerialProtocol::getRequestId() const { return lastRequestId; }
bool SerialProtocol::hasMessage() const { return newMessageAvailable; }
uint8_t SerialProtocol::getCreditPercent() const { return lastCreditPercent; }
bool SerialProtocol::hasCreditInfo() const { return creditInfoValid; }
AgentState SerialProtocol::getAgentState() const { return lastAgentState; }
const char* SerialProtocol::getStatusDetail() const { return lastStatusDetail; }
uint32_t SerialProtocol::getStatusSeq() const { return lastStatusSeq; }
bool SerialProtocol::hasStatus() const { return statusValid; }
ThinkingActivity SerialProtocol::getThinkingActivity() const { return lastThinkingActivity; }
bool SerialProtocol::hasThinkingActivity() const { return thinkingActivityValid; }
VoiceAckState SerialProtocol::getVoiceAckState() const { return lastVoiceAckState; }
const char* SerialProtocol::getVoiceAckText() const { return lastVoiceAckText; }

// TTS getters
uint32_t SerialProtocol::getTtsSeq() const { return lastTtsSeq; }
uint32_t SerialProtocol::getTtsTotal() const { return lastTtsTotal; }
const uint8_t* SerialProtocol::getTtsData() const { return (const uint8_t*)lastTtsData; }
size_t SerialProtocol::getTtsDataLen() const { return lastTtsDataLen; }
bool SerialProtocol::hasTtsAudio() const { return ttsAudioValid; }
