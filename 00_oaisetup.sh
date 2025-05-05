#!/bin/bash

# Parameters

# Prompt user for choice
echo "Please select option："
echo "1. OAI O-CU"
echo "2. OAI O-DU"
echo "3. OAI O-RU"
echo "4. OAI CN-5G"
echo "5. Flexric"
echo "6. EXIT"

read choice

# Excute the commandos based on options
case $choice in
    1)
        echo "Starting set up OAI O-CU"
	echo "Wait a minute..."
	sleep 10
	git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git oai
	cd oai
	source oaienv
	cd cmake_targets
	./build_oai -c -I
	./build_oai --gNB -c -C -w USRP --build-e2 --ninja
	echo "Success set up OAI O-CU"
        ;;
    2)
        echo "Starting set up OAI O-DU"
	git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git oai
	cd oai
	source oaienv
	cd cmake_targets
	./build_oai -c -I
	./build_oai --gNB -c -C -w USRP --build-e2 --ninja
	echo "Success set up OAI O-DU"
        ;;
    3)
        echo "Starting set up OAI O-RU"
	git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git oai
	cd oai
	source oaienv
	cd cmake_targets
	./build_oai -c -I
	./build_oai --nrUE -c -C -w USRP --build-e2 --ninja
	echo "Success set up OAI O-RU"
        ;;
    4)
	echo "Starting set up OAI CN-5G"
	echo "Wait a minut..."
	sleep 10
	wget -O ~/oai-cn5g.zip https://gitlab.eurecom.fr/oai/openairinterface5g/-/archive/develop/openairinterface5g-develop.zip?path=doc/tutorial_resources/oai-cn5g
	unzip ~/oai-cn5g.zip
	cp -rf ~/openairinterface5g-develop-doc-tutorial_resources-oai-cn5g/doc/tutorial_resources/oai-cn5g ~/oai-cn5g
	cd ~/oai-cn5g
	sudo docker compose up -d
	echo "Success set up OAI CN-5G"
	;;
    5) 
	echo "Starting set up Flexric"
	echo "Wait a minute..."
	sleep 10
	sudo apt install autotools-dev automake libpcre2-dev yacc build-essential git
	sudo apt install libsctp-dev python3 cmake-curses-gui python3-dev pkg-config libconfig-dev libconfig++-dev
	sudo apt install libmysqlclient-dev mysql-server
	git clone https://github.com/swig/swig.git
	cd swig
	git checkout v4.1.1
	./autogen.sh
	./configure --prefix=/usr/
	make
	sudo make install
	cd ~
	git clone https://gitlab.eurecom.fr/mosaic5g/flexric.git
	cd flexric
	git checkout br-flexric
	mkdir build
	cd build
	cmake ..
	make -j
	sudo make install
	echo "Success set up Flexric"
	;;
    6)
        echo "Bye！"
        exit 0
        ;;
    *)
        echo "Invalid option，Please run this script again, and select valid option."
        exit 1
        ;;
esac

