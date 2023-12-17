#pragma once

#include "types.h"

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

    const json & getJson()
    {
        return mJson;
    }

    template <typename T>
    const T getTag(const std::string &tag) const
    {
        return mJson[tag].get<T>();
    }

protected:
    std::string mMsgType;
    json mJson;

};

class SessionMessage : public Message
{
public:
    SessionMessage(Message message, PlayerGameSessionID sessionID):
        Message(message.getMsgType(), message.getJson()), mSessionID(sessionID)
    {
        mJson[Tags::SESSION_ID] = sessionID;
    };

    SessionMessage(Message message): Message(message.getMsgType(), message.getJson())
    {
        mSessionID = mJson[Tags::SESSION_ID];
    }

    PlayerGameSessionID getSessionID() const
    {
        return mSessionID;
    }

private:
    PlayerGameSessionID mSessionID;
};

}