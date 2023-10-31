#pragma once

#include <utility>

#include "../../types.h"
#include "../message.h"
#include "../../constants.h"

namespace Common::Server::Message
{

class ConnectionRequest : public Message {
public:
    explicit ConnectionRequest(std::string playerTag):
        playerTag(std::move(playerTag))
    {}

    ConnectionRequest() = default;


    json toJson() override
    {
        json json;
        json[Tags::TYPE] = ClientMsgTypes::CONNECTION_REQUEST;
        json[Tags::PLAYER_TAG] = playerTag;
        return json;
    }

    void initializeFromJson(json json) override
    {
        ASRT_EQ(json[Tags::TYPE], ClientMsgTypes::CONNECTION_REQUEST);
        playerTag = json[Tags::PLAYER_TAG];
    }

    [[nodiscard]] std::string getPlayerTag() const
    {
        return playerTag;
    }

private:
    std::string playerTag;
};
}