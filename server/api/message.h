#pragma once

#include "server/util/constants.h"
#include "server/game/objects/types.h"
#include "server/util/types.h"

namespace Common::Server::Message
{

class Message {
public:
    Message(std::string msgType, json j): mMsgType(msgType), mJson(j)
    {
        mJson[Tags::TYPE] = msgType;
    };

    Message(json j): mMsgType(j[Tags::TYPE]), mJson(j) {};

    [[nodiscard]] std::string getMsgType() const
    {
        return mMsgType;
    }

    const json & getJson() const
    {
        return mJson;
    }

    template <typename T>
    const T getTag(const std::string &tag) const
    {
        return mJson[tag].get<T>();
    }

    const bool hasTag(const std::string &tag) const
    {
        return mJson.find(tag) != mJson.end();
    }

protected:
    std::string mMsgType;
    json mJson;

};

class SessionMessage : public Message
{
public:
    SessionMessage(Message message, PlayerGameSessionID sessionID, uint16_t seqNum):
        Message(message.getMsgType(), message.getJson()), mSessionID(sessionID), mSeqNum(seqNum)
    {
        mJson[Tags::SESSION_ID] = sessionID;
        mJson[Tags::SEQ_NUM] = seqNum;
    };

    SessionMessage(Message message): Message(message.getMsgType(), message.getJson())
    {
        mSessionID = mJson[Tags::SESSION_ID];
        mSeqNum = mJson[Tags::SEQ_NUM];
    }

    PlayerGameSessionID getSessionID() const
    {
        return mSessionID;
    }

    uint16_t getSeqNum() const
    {
        return mSeqNum;
    }

private:
    PlayerGameSessionID mSessionID;
    int16_t mSeqNum;
};

}