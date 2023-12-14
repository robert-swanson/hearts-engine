#pragma once

#include "../../types.h"
#include "../message.h"
#include "../../constants.h"

namespace Common::Server::Message
{

class ConnectionResponse : public Message {
public:
    explicit ConnectionResponse(std::string status):
        status(status)
    {}

    json toJson() override
    {
        return {
                {Tags::TYPE, ServerMsgTypes::CONNECTION_RESPONSE},
                {Tags::STATUS, status}
        };
    }

    void initializeFromJson(json json) override
    {
        ASRT_EQ(json[Tags::TYPE], ServerMsgTypes::CONNECTION_RESPONSE);
    }
private:
    std::string status;
};
}