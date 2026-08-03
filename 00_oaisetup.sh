#!/usr/bin/env bash

# Stop immediately when a command fails, an unset variable is used, or a
# command in a pipeline fails. This prevents false "success" messages.
set -Eeuo pipefail

# Present the supported installation targets.
echo "Please select an option:"
echo "1. OAI O-CU"
echo "2. OAI O-DU"
echo "3. OAI NR-UE"
echo "4. OAI CN-5G"
echo "5. FlexRIC"
echo "6. EXIT"

read -r choice

# Override these with a release tag or commit hash for reproducible builds.
OAI_REF="${OAI_REF:-develop}"
FLEXRIC_REF="${FLEXRIC_REF:-br-flexric}"

# Clone a missing repository or safely refresh an existing clean checkout.
prepare_repo() {
    local repository="$1"
    local directory="$2"
    local revision="$3"

    if [[ -e "$directory" && ! -d "$directory/.git" ]]; then
        echo "Error: ${directory} exists but is not a Git repository." >&2
        return 1
    fi

    if [[ -d "$directory/.git" ]]; then
        if [[ -n "$(git -C "$directory" status --porcelain)" ]]; then
            echo "Error: ${directory} contains uncommitted changes." >&2
            return 1
        fi
        git -C "$directory" fetch --tags origin
    else
        git clone "$repository" "$directory"
    fi

    git -C "$directory" checkout "$revision"
}

# O-CU and O-DU currently use the same OAI gNB build procedure. Keep the
# shared commands in one function so that both targets remain consistent.
build_oai_gnb() {
    local role="$1"

    echo "Starting setup for ${role}"
    prepare_repo https://gitlab.eurecom.fr/oai/openairinterface5g.git oai "$OAI_REF"
    cd oai
    set +u
    source oaienv
    set -u
    cd cmake_targets
    ./build_oai -c -I
    ./build_oai --gNB -c -C -w USRP --build-e2 --ninja
    echo "Successfully set up ${role}"
}

case "$choice" in
    1)
        # Build the OAI gNB components used by the central unit.
        build_oai_gnb "OAI O-CU"
        ;;
    2)
        # Build the OAI gNB components used by the distributed unit.
        build_oai_gnb "OAI O-DU"
        ;;
    3)
        # Build the USRP-enabled OAI NR UE target.
        echo "Starting setup for OAI NR-UE"
        prepare_repo https://gitlab.eurecom.fr/oai/openairinterface5g.git oai "$OAI_REF"
        cd oai
        set +u
        source oaienv
        set -u
        cd cmake_targets
        ./build_oai -c -I
        ./build_oai --nrUE -c -C -w USRP --build-e2 --ninja
        echo "Successfully set up OAI NR-UE"
        ;;
    4)
        # Download the upstream CN-5G Compose bundle and start its services.
        echo "Starting setup for OAI CN-5G"
        wget -O oai-cn5g.zip 'https://gitlab.eurecom.fr/oai/openairinterface5g/-/archive/develop/openairinterface5g-develop.zip?path=doc/tutorial_resources/oai-cn5g'
        unzip -q oai-cn5g.zip
        cp -rf openairinterface5g-develop-doc-tutorial_resources-oai-cn5g/doc/tutorial_resources/oai-cn5g ./oai-cn5g
        cd oai-cn5g
        sudo docker compose up -d
        echo "Successfully set up OAI CN-5G"
        ;;
    5)
        # Build the pinned SWIG release before compiling the FlexRIC branch.
        echo "Starting setup for FlexRIC"
        sudo apt update
        sudo apt install -y autotools-dev automake libpcre2-dev yacc build-essential git
        sudo apt install -y libsctp-dev python3 cmake-curses-gui python3-dev pkg-config libconfig-dev libconfig++-dev
        sudo apt install -y libmysqlclient-dev mysql-server
        prepare_repo https://github.com/swig/swig.git swig v4.1.1
        cd swig
        ./autogen.sh
        ./configure --prefix=/usr/
        make
        sudo make install
        cd ..
        prepare_repo https://gitlab.eurecom.fr/mosaic5g/flexric.git flexric "$FLEXRIC_REF"
        cd flexric
        mkdir -p build
        cd build
        cmake ..
        make -j
        sudo make install
        echo "Successfully set up FlexRIC"
        ;;
    6)
        # Exit without making any system changes.
        echo "Bye"
        exit 0
        ;;
    *)
        echo "Invalid option. Please run this script again and select a valid option." >&2
        exit 1
        ;;
esac
