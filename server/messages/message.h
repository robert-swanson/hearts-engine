#pragma once

#include "../types.h"

namespace Common::Server::Message
{



class Message {
public:
    virtual json toJson() = 0;
    virtual void initializeFromJson(json json) = 0;

    std::string toString()
    {
        return toJson().dump() + "\n";
    }

};

class AnyMessage : public Message
{
public:
    json value;

    json toJson() override
    {
        return value;
    }

    void initializeFromJson(json json) override
    {
        value = json;
    }
};

class AnySessionMessage : public AnyMessage
{
public:


};

}