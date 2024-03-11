#pragma once

namespace Common::Game
{
    enum PassDirection {Left, Right, Across, Keeper};
    std::string PassDirectionToString(PassDirection passDirection)
    {
        switch (passDirection) {
            case Keeper:
                return "Keeper";
            case Left:
                return "Left";
            case Right:
                return "Right";
            case Across:
                return "Across";
            default:
                return "Unknown";
        }
    }

    PassDirection NextPassDirection(PassDirection passDirection)
    {
        switch (passDirection) {
            case Keeper:
                return Left;
            case Left:
                return Right;
            case Right:
                return Across;
            default:
                return Keeper;
        }
    }
    using PlayerID = std::string;
}


