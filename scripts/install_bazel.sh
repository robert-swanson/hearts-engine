#!/bin/bash

set -e
set -o xtrace

REQUIRED_MAJOR=9

# Function to check if Bazel 9+ is installed
check_bazel_installed() {
    if ! command -v bazel &> /dev/null; then
        return 1
    fi
    local major
    major=$(bazel --version 2>/dev/null | grep -oE '[0-9]+' | head -1)
    if [ "${major:-0}" -lt "$REQUIRED_MAJOR" ]; then
        echo "Bazel ${major} is installed but version ${REQUIRED_MAJOR}+ is required."
        return 1
    fi
}

# Function to install Bazel using apt (Debian/Ubuntu)
install_bazel_apt() {
    sudo apt update
    sudo apt install -y bazel
}

# Function to install Bazel using yum (CentOS/RHEL)
install_bazel_yum() {
    sudo yum install -y bazel
}

# Function to install Bazel using Homebrew (macOS)
install_bazel_homebrew() {
    brew install bazel
}

# Function to install Bazel
install_bazel() {
    echo "Bazel is not installed. Attempting to install..."

    # Detect the package manager
    if command -v apt &> /dev/null; then
        install_bazel_apt
    elif command -v yum &> /dev/null; then
        install_bazel_yum
    elif command -v brew &> /dev/null; then
        install_bazel_homebrew
    else
        echo "Unable to determine package manager. Please install Bazel manually."
        exit 1
    fi
}

# Main function
main() {
    echo "Checking if Bazel is installed..."
    if check_bazel_installed; then
        echo "Bazel is already installed."
    else
        install_bazel
    fi
}

main "$@"
