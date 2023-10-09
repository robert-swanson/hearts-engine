#pragma once

namespace Common::Game
{
    enum PassDirection {Left, Right, Across, Keeper};
    PassDirection NextPassDirection(PassDirection passDirection)
    {
        switch (passDirection) {
            case Left:
                return Right;
            case Right:
                return Across;
            case Across:
                return Keeper;
            case Keeper:
                return Left;
        }
    }
}


