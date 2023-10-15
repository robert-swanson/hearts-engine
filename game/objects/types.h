#pragma once

namespace Common::Game
{
    enum PassDirection {Left, Right, Across, Keeper};
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
}


