#pragma once

#include "../../types.h"
#include "../message.h"
#include "../../constants.h"

namespace Common::Server::Message
{

class AcceptConnection : public Message {
public:
    json toJson() override
    {
        json json;
        json[Tags::TYPE] = MsgTypes::SERVER_ACCEPT_CONNECTION;
        return json;
    }

    void initializeFromJson(json json)
    {
    }
};
}